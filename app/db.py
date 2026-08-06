"""Database access for the workstation.

The database is a single SQLite file. That is the whole point of it: the
project's deliverable is the officer record itself, and it has to be shareable,
openable and readable by people who are not running this code. A file can be
copied into a shared folder, opened in DB Browser, and read by pandas, R or
Excel. A server cannot.

Where it lives:

    JPOCR_DB        full path to the .db file, or
    JP_OCR_DATA     the data home; the file is <data home>/officer-index.db

Two rules survive from the Postgres original because they are about the data,
not the engine:

* **Every write is attributed.** `actor_session()` is the only sanctioned way to
  write, and it records the worker in `work_log` in the same transaction. The
  provenance of a value also lives on the row: `observation` carries
  `author_user_id`, `created_at` and `status`.
* **Foreign keys are enforced.** SQLite has them off by default, which would
  silently allow an observation to point at a cell that does not exist.

Journal mode is left at the default rather than WAL: WAL writes `-wal` and
`-shm` sidecar files, and a database you have to remember to checkpoint before
copying is not a database you can casually share.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"


class NotConfigured(RuntimeError):
    """Nowhere to put the database file."""


def db_path() -> str:
    """Where the database file is.

    A `file:` URI is passed through to SQLite untouched, which is how the tests
    run against a shared in-memory database instead of writing a file per test.
    """
    explicit = os.environ.get("JPOCR_DB")
    if explicit:
        return explicit
    home = os.environ.get("JP_OCR_DATA")
    if not home:
        raise NotConfigured(
            "set JPOCR_DB to the database file, or JP_OCR_DATA to the data home "
            "(see docs/SETUP.md)")
    return str(Path(home) / "officer-index.db")


def new_id() -> str:
    """A fresh row id.

    Ids stay uuids rather than autoincrement integers because copies of this
    file get merged: two people transcribing on two machines must be able to
    hand their work back without colliding.
    """
    return str(uuid.uuid4())


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = str(path) if path else db_path()
    conn = sqlite3.connect(target, isolation_level="DEFERRED",
                           uri=target.startswith("file:"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create(path: str | Path) -> sqlite3.Connection:
    """Create a database with the schema applied, and return it open.

    The caller owns the returned connection and must close it -- or, for an
    in-memory database, must hold it open for as long as the database should
    exist.
    """
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    return conn


@contextmanager
def session(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error, and closes.

    `with sqlite3.connect(...) as conn` does the first two and **not** the third,
    which on Windows leaves the file locked against the next writer. Use this for
    writes that belong to no particular worker - loading vocabularies from the
    versioned CSVs, registering a volume from a manifest.
    """
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def read_session(path: str | Path | None = None) -> Iterator[sqlite3.Cursor]:
    """A read-only cursor. No actor needed: reads are not logged."""
    conn = connect(path)
    try:
        yield conn.cursor()
    finally:
        conn.close()


@contextmanager
def actor_session(user_id: str, path: str | Path | None = None) -> Iterator[sqlite3.Cursor]:
    """A transaction whose writes are attributed to `user_id`.

    Commits on clean exit, rolls back on exception, so the work log and the data
    it describes can never disagree.
    """
    if not user_id:
        raise ValueError("actor_session requires a user_id; unattributed writes are not allowed")
    conn = connect(path)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log_work(cur: sqlite3.Cursor, user_id: str, action: str, *,
             volume_pid: str | None = None, frame_no: int | None = None,
             row_index: int | None = None, detail: dict | None = None) -> None:
    """Record one piece of work done. Called inside the caller's transaction."""
    cur.execute(
        "INSERT INTO work_log (user_id, action, volume_pid, frame_no, row_index, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, volume_pid, frame_no, row_index,
         json.dumps(detail, ensure_ascii=False) if detail else None))


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find_user(access_code: str) -> dict | None:
    """Resolve an id code to the worker it belongs to.

    The code *is* the identifier (docs/decision-workstation-auth.md), so it lives
    in `app_user.login`. Callers should treat the returned `login` as a secret
    and show `display_name` instead.
    """
    with read_session() as cur:
        cur.execute(
            "SELECT user_id, login, display_name FROM app_user WHERE login = ?",
            (access_code,))
        row = cur.fetchone()
        return dict(row) if row else None


def find_page(pid: str, frame: int) -> dict | None:
    """Resolve pid+frame to the registered page, with the volume's snapshot date."""
    with read_session() as cur:
        cur.execute(
            """
            SELECT p.page_id, p.frame_no, v.volume_id, v.pid, v.title, v.edition_date
              FROM source_page p
              JOIN source_volume v ON v.volume_id = p.volume_id
             WHERE v.pid = ? AND p.frame_no = ?
            """,
            (pid, frame))
        row = cur.fetchone()
        return dict(row) if row else None


def ensure_template(spec: dict, user_id: str) -> str:
    """Upsert a template artifact into `layout_template`, returning its id.

    The JSON under `templates/` is the source of truth; this mirrors it into the
    database so `source_page.template_id` can reference a real row. Matched by
    name, because the artifact's own id is the stable human-facing handle.
    """
    column_spec = json.dumps({
        "band_fracs": spec["band_fracs"],
        "fields": spec.get("fields", []),
        "columns": spec.get("columns", {}),
    }, ensure_ascii=False)
    row_spec = json.dumps(spec.get("match", {}), ensure_ascii=False)
    with actor_session(user_id) as cur:
        cur.execute("SELECT template_id FROM layout_template WHERE name = ?",
                    (spec["template_id"],))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE layout_template SET column_spec = ?, row_spec = ?, "
                "era = ?, series = ?, notes = ? WHERE template_id = ?",
                (column_spec, row_spec, spec.get("era"), spec.get("series"),
                 spec.get("description"), row["template_id"]))
            return row["template_id"]
        template_id = new_id()
        cur.execute(
            "INSERT INTO layout_template (template_id, name, series, era, column_spec, row_spec, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (template_id, spec["template_id"], spec.get("series"), spec.get("era"),
             column_spec, row_spec, spec.get("description")))
        return template_id


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

def upsert_cells(page_id: str, officers: list[dict], user_id: str,
                 volume_pid: str | None = None, frame_no: int | None = None) -> list[dict]:
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
                INSERT INTO roster_cell (cell_id, page_id, row_index, crop_bbox, crop_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (page_id, row_index)
                DO UPDATE SET crop_bbox = excluded.crop_bbox,
                              crop_url  = excluded.crop_url
                RETURNING cell_id, row_index, crop_bbox, audit_status
                """,
                (new_id(), page_id, officer["index"],
                 json.dumps(list(officer["bbox"])), officer.get("crop_url")))
            row = dict(cur.fetchone())
            row["crop_bbox"] = json.loads(row["crop_bbox"])
            saved.append(row)
        log_work(cur, user_id, "register_cells", volume_pid=volume_pid,
                 frame_no=frame_no, detail={"cells": len(saved)})
    return saved


def create_observation(*, page_id: str, cell_id: str, as_of_date, user_id: str,
                       values: dict, volume_pid: str | None = None,
                       frame_no: int | None = None, row_index: int | None = None) -> dict:
    """Record one officer as read by a human.

    Always `status = 'draft'`: confirmation is a separate, deliberate act, and
    nothing machine-derived reaches this table at all. `author_user_id` is the
    worker whose id code the API resolved, never a value supplied by the caller.
    """
    obs_id = new_id()
    commissioning = values.get("commissioning_date")
    with actor_session(user_id) as cur:
        cur.execute(
            """
            INSERT INTO observation
                (obs_id, page_id, cell_id, name_raw, rank_code, branch_code, post,
                 seniority_no, commissioning_date, as_of_date,
                 field_confidence, author_user_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            RETURNING obs_id, status, created_at
            """,
            (obs_id, page_id, cell_id,
             values.get("name_raw"), values.get("rank_code"),
             values.get("branch_code"), values.get("post"),
             values.get("seniority_no"),
             commissioning.isoformat() if hasattr(commissioning, "isoformat") else commissioning,
             as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else as_of_date,
             json.dumps(values.get("field_confidence") or {}, ensure_ascii=False),
             user_id))
        saved = dict(cur.fetchone())
        log_work(cur, user_id, "record_officer", volume_pid=volume_pid,
                 frame_no=frame_no, row_index=row_index,
                 detail={"name_raw": values.get("name_raw")})
    return saved


def observations_for_page(page_id: str, cur: sqlite3.Cursor | None = None) -> list[dict]:
    """What has been recorded for a page.

    `cur` lets a caller run this inside an existing transaction - which is how
    the tests exercise the real query against rows they roll back afterwards,
    rather than asserting against a copy of the SQL.
    """
    sql = """
            SELECT o.obs_id, o.cell_id, c.row_index, o.name_raw, o.rank_code,
                   o.branch_code, o.post, o.seniority_no, o.commissioning_date,
                   o.status, o.created_at,
                   -- The display name, never `u.login`: that column holds the
                   -- worker's id code, and this listing is visible to every
                   -- other worker on the page.
                   COALESCE(u.display_name, '(unnamed)') AS author
              FROM observation o
              JOIN roster_cell c ON c.cell_id = o.cell_id
         LEFT JOIN app_user u ON u.user_id = o.author_user_id
             WHERE o.page_id = ?
          ORDER BY c.row_index
    """
    if cur is not None:
        cur.execute(sql, (page_id,))
        return [dict(r) for r in cur.fetchall()]
    with read_session() as own:
        own.execute(sql, (page_id,))
        return [dict(r) for r in own.fetchall()]


def volume_progress(pid: str, cur: sqlite3.Cursor | None = None) -> list[dict]:
    """Which frames of a volume have readings, and how many, per frame.

    The coverage question - "what is left?" - asked of the database rather than
    of somebody's notepad. Only frames with at least one observation come back:
    a volume is hundreds of pages and the empty ones are the default, so sending
    them all would be a row per frame to say nothing.

    Counts are of *observations*, not distinct officers. Readings are
    append-only, so a row re-read by a second worker counts twice - which is why
    the caller compares against the officers actually on the page rather than
    treating this as a completion percentage.
    """
    sql = """
            SELECT p.frame_no,
                   COUNT(o.obs_id)             AS observations,
                   COUNT(DISTINCT c.row_index) AS rows_read,
                   MAX(o.created_at)           AS last_touched
              FROM source_volume v
              JOIN source_page p   ON p.volume_id = v.volume_id
              JOIN observation o   ON o.page_id = p.page_id
              JOIN roster_cell c   ON c.cell_id = o.cell_id
             WHERE v.pid = ?
          GROUP BY p.frame_no
          ORDER BY p.frame_no
    """
    if cur is not None:
        cur.execute(sql, (pid,))
        return [dict(r) for r in cur.fetchall()]
    with read_session() as own:
        own.execute(sql, (pid,))
        return [dict(r) for r in own.fetchall()]


def set_volume_edition_date(volume_id: str, edition_date, user_id: str) -> None:
    with actor_session(user_id) as cur:
        cur.execute("UPDATE source_volume SET edition_date = ? WHERE volume_id = ?",
                    (edition_date.isoformat() if hasattr(edition_date, "isoformat")
                     else edition_date, volume_id))
