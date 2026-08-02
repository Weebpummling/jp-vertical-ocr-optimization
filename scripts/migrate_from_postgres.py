"""One-shot: copy the Postgres database into the SQLite file.

Run once, on 2 Aug 2026, to carry the existing rows across when the project
moved off Postgres (PLAN.md decision 9). Kept in the repo because the move
should be reproducible and auditable, not because it needs running again.

    python scripts/migrate_from_postgres.py --target %JP_OCR_DATA%\\officer-index.db

Needs the old stack up and POSTGRES_PASSWORD (or JPOCR_DSN) in the environment.
Refuses to write over an existing file: a migration that silently overwrote the
live database would be the exact accident this project cannot afford.

Type conversions, all of them lossless in this direction:

    uuid            -> str
    date/timestamp  -> ISO-8601 str
    text[] / int[]  -> JSON array
    jsonb           -> JSON text

`app_user.role` is dropped: roles gate nothing and the column is gone from the
new schema (decision 7). The Postgres `audit_log` is not carried over either -
it held before/after images of the same rows being copied here, and the new
`work_log` records work rather than row diffs. The old dump was inspected before
this ran; the audit history it contained was five rows describing the two
observations and their cells.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db as sqlite_db  # noqa: E402

# Copied in dependency order so foreign keys hold at every step.
TABLES = [
    "rank_vocab", "branch_vocab", "kanji_variant",
    "app_user",
    "source_volume", "layout_template", "source_page", "roster_cell",
    "person", "unit", "unit_deployment",
    "observation", "kanpo_event", "machine_reading",
    "reference_truth", "linkage_decision", "task",
]

# Columns that exist in Postgres but not in the SQLite schema.
DROPPED = {("app_user", "role")}


def convert(value):
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    return value


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="path of the SQLite file to create")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    target = Path(args.target)
    if target.exists():
        print(f"refusing to overwrite {target}", file=sys.stderr)
        return 2

    import os

    import psycopg
    from psycopg.rows import dict_row

    password = os.environ.get("POSTGRES_PASSWORD")
    dsn = os.environ.get("JPOCR_DSN") or (
        f"host=127.0.0.1 port=5432 dbname={os.environ.get('POSTGRES_DB','jpocr')} "
        f"user={os.environ.get('POSTGRES_USER','jpocr')} password={password}")

    target.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite_db.create(target)
    total = 0
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as pg:
            for table in TABLES:
                with pg.cursor() as cur:
                    cur.execute(f"SELECT * FROM {table}")
                    rows = cur.fetchall()
                if not rows:
                    print(f"{table:<18}    0")
                    continue
                cols = [c for c in rows[0].keys() if (table, c) not in DROPPED]
                sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
                       f"VALUES ({', '.join('?' for _ in cols)})")
                out.executemany(sql, [[convert(r[c]) for c in cols] for r in rows])
                total += len(rows)
                print(f"{table:<18} {len(rows):>4}")
        out.commit()
    finally:
        out.close()

    print(f"\n{total} rows -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
