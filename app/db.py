"""Database access for the workstation.

One rule governs this module: **every write is attributable.** The audit
triggers take their actor from `current_setting('app.user_id')` (db/schema.sql),
so a write that does not set it lands in `audit_log` with a NULL actor - an
unattributable change to the most expensive thing the project owns, human
transcription. `actor_session()` is therefore the only sanctioned way to write,
and it sets the actor inside the same transaction as the write.

Connection settings come from the environment so no credential is committed:

    JPOCR_DSN                       full libpq connection string, or
    POSTGRES_{DB,USER,PASSWORD}     the docker-compose variables, plus
    JPOCR_DB_HOST / JPOCR_DB_PORT   (default 127.0.0.1:5432)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


class NotConfigured(RuntimeError):
    """No database credentials in the environment."""


def dsn() -> str:
    explicit = os.environ.get("JPOCR_DSN")
    if explicit:
        return explicit
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise NotConfigured(
            "set JPOCR_DSN, or POSTGRES_PASSWORD as in .env (see docs/SETUP.md)")
    return (
        f"host={os.environ.get('JPOCR_DB_HOST', '127.0.0.1')} "
        f"port={os.environ.get('JPOCR_DB_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'jpocr')} "
        f"user={os.environ.get('POSTGRES_USER', 'jpocr')} "
        f"password={password}"
    )


def connect() -> psycopg.Connection:
    return psycopg.connect(dsn(), row_factory=dict_row)


@contextmanager
def read_session() -> Iterator[psycopg.Cursor]:
    """A read-only cursor. No actor needed: reads are not audited."""
    with connect() as conn, conn.cursor() as cur:
        yield cur


@contextmanager
def actor_session(user_id: str) -> Iterator[psycopg.Cursor]:
    """A transaction whose writes are attributed to `user_id`.

    The setting is transaction-scoped, so a pooled or reused connection cannot
    leak one annotator's identity into another's writes. The transaction commits
    on clean exit and rolls back on exception, which keeps the audit log and the
    data it describes in step.

    `set_config(..., is_local => true)` rather than `SET LOCAL`: the latter is
    utility syntax and takes no bind parameter, so passing a user id would mean
    interpolating it into SQL.
    """
    if not user_id:
        raise ValueError("actor_session requires a user_id; unattributed writes are not allowed")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
            yield cur


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find_user(login: str) -> dict | None:
    with read_session() as cur:
        cur.execute(
            "SELECT user_id, login, display_name, role FROM app_user WHERE login = %s",
            (login,))
        return cur.fetchone()


def find_page(pid: str, frame: int) -> dict | None:
    """Resolve pid+frame to the registered page, with the volume's snapshot date."""
    with read_session() as cur:
        cur.execute(
            """
            SELECT p.page_id, p.frame_no, v.volume_id, v.pid, v.title, v.edition_date
              FROM source_page p
              JOIN source_volume v USING (volume_id)
             WHERE v.pid = %s AND p.frame_no = %s
            """,
            (pid, frame))
        return cur.fetchone()


def ensure_template(spec: dict, user_id: str) -> str:
    """Upsert a template artifact into `layout_template`, returning its id.

    The JSON under `templates/` is the source of truth; this mirrors it into the
    database so `source_page.template_id` can reference a real row. Matched by
    name, because the artifact's own id is the stable human-facing handle.
    """
    with actor_session(user_id) as cur:
        cur.execute("SELECT template_id FROM layout_template WHERE name = %s",
                    (spec["template_id"],))
        row = cur.fetchone()
        column_spec = psycopg.types.json.Json({
            "band_fracs": spec["band_fracs"],
            "fields": spec.get("fields", []),
            "columns": spec.get("columns", {}),
        })
        row_spec = psycopg.types.json.Json(spec.get("match", {}))
        if row:
            cur.execute(
                "UPDATE layout_template SET column_spec = %s, row_spec = %s, "
                "era = %s, series = %s, notes = %s WHERE template_id = %s",
                (column_spec, row_spec, spec.get("era"), spec.get("series"),
                 spec.get("description"), row["template_id"]))
            return str(row["template_id"])
        cur.execute(
            "INSERT INTO layout_template (name, series, era, column_spec, row_spec, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING template_id",
            (spec["template_id"], spec.get("series"), spec.get("era"),
             column_spec, row_spec, spec.get("description")))
        return str(cur.fetchone()["template_id"])


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

def upsert_cells(page_id: str, officers: list[dict], user_id: str) -> list[dict]:
    """Materialize one `roster_cell` per officer strip on a page.

    Idempotent on (page_id, row_index): re-registering a page refreshes the
    geometry rather than duplicating officers. Only geometry is written here -
    `seniority_no` stays NULL until a human reads it.
    """
    saved = []
    with actor_session(user_id) as cur:
        for officer in officers:
            cur.execute(
                """
                INSERT INTO roster_cell (page_id, row_index, crop_bbox, crop_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (page_id, row_index)
                DO UPDATE SET crop_bbox = EXCLUDED.crop_bbox,
                              crop_url  = EXCLUDED.crop_url
                RETURNING cell_id, row_index, crop_bbox, audit_status
                """,
                (page_id, officer["index"], list(officer["bbox"]),
                 officer.get("crop_url")))
            saved.append(dict(cur.fetchone()))
    return saved


def create_observation(*, page_id: str, cell_id: str, as_of_date, user_id: str,
                       values: dict) -> dict:
    """Record one officer as read by a human.

    Always `status = 'draft'`: confirmation is a separate, deliberate act, and
    nothing machine-derived reaches this table at all. `author_user_id` is the
    person the API authenticated, never a value supplied by the caller.
    """
    with actor_session(user_id) as cur:
        cur.execute(
            """
            INSERT INTO observation
                (page_id, cell_id, name_raw, rank_code, branch_code, post,
                 seniority_no, commissioning_date, as_of_date,
                 field_confidence, author_user_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
            RETURNING obs_id, status, created_at
            """,
            (page_id, cell_id,
             values.get("name_raw"), values.get("rank_code"),
             values.get("branch_code"), values.get("post"),
             values.get("seniority_no"), values.get("commissioning_date"),
             as_of_date,
             psycopg.types.json.Json(values.get("field_confidence") or {}),
             user_id))
        return dict(cur.fetchone())


def observations_for_page(page_id: str) -> list[dict]:
    with read_session() as cur:
        cur.execute(
            """
            SELECT o.obs_id, o.cell_id, c.row_index, o.name_raw, o.rank_code,
                   o.branch_code, o.post, o.seniority_no, o.commissioning_date,
                   o.status, o.created_at, u.login AS author
              FROM observation o
              JOIN roster_cell c USING (cell_id)
         LEFT JOIN app_user u ON u.user_id = o.author_user_id
             WHERE o.page_id = %s
          ORDER BY c.row_index
            """,
            (page_id,))
        return [dict(r) for r in cur.fetchall()]


def set_volume_edition_date(volume_id: str, edition_date, user_id: str) -> None:
    with actor_session(user_id) as cur:
        cur.execute("UPDATE source_volume SET edition_date = %s WHERE volume_id = %s",
                    (edition_date, volume_id))
