"""Export the officer record and the work log as plain files.

The project's deliverable is the database, and a database nobody can open is not
a deliverable. This writes the two things anyone should be able to read without
running any of this code:

    officer-record.csv   one row per recorded officer, with who read it and when
    work-log.csv         what was done, by whom, when

Both are UTF-8 with a BOM, because the single most likely thing to happen to
them is being double-clicked into Excel on a Japanese Windows machine, and
without the BOM Excel reads UTF-8 as cp932 and turns every name into mojibake.

    python scripts/export_record.py                     # into the data home
    python scripts/export_record.py --out "G:\\shared"   # into a shared folder

The database file itself is the other half of the deliverable: copy it beside
these, and anyone with DB Browser, pandas or R has the whole record.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402

# Everything a reader needs to interpret a row without joining anything by hand:
# the officer, where on which page they were read, and who recorded them.
OFFICER_RECORD = """
    SELECT v.pid                AS volume_pid,
           v.title              AS volume_title,
           v.edition_date       AS as_of_date,
           p.frame_no           AS frame,
           c.row_index          AS row_on_page,
           o.seniority_no       AS seniority_no,
           o.name_raw           AS name,
           o.rank_code          AS rank_code,
           r.label_ja           AS rank_ja,
           o.branch_code        AS branch_code,
           b.label_ja           AS branch_ja,
           o.post               AS post,
           o.commissioning_date AS commissioning_date,
           o.status             AS status,
           COALESCE(u.display_name, '(unnamed)') AS recorded_by,
           o.created_at         AS recorded_at,
           o.field_confidence   AS flags,
           c.crop_url           AS source_image
      FROM observation o
      JOIN roster_cell   c ON c.cell_id   = o.cell_id
      JOIN source_page   p ON p.page_id   = o.page_id
      JOIN source_volume v ON v.volume_id = p.volume_id
 LEFT JOIN rank_vocab    r ON r.rank_code   = o.rank_code
 LEFT JOIN branch_vocab  b ON b.branch_code = o.branch_code
 LEFT JOIN app_user      u ON u.user_id     = o.author_user_id
  ORDER BY v.pid, p.frame_no, c.row_index
"""

WORK_LOG = """
    SELECT w.at, COALESCE(u.display_name, '(unnamed)') AS who, w.action,
           w.volume_pid, w.frame_no, w.row_index, w.detail
      FROM work_log w
 LEFT JOIN app_user u ON u.user_id = w.user_id
  ORDER BY w.log_id
"""


def write_csv(path: Path, cur, sql: str) -> int:
    cur.execute(sql)
    rows = cur.fetchall()
    # utf-8-sig: the BOM is what stops Excel reading Japanese as cp932.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not rows:
            writer.writerow([d[0] for d in cur.description])
            return 0
        writer.writerow(rows[0].keys())
        writer.writerows([list(r) for r in rows])
    return len(rows)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="directory to write into (default: the data home)")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    out = Path(args.out) if args.out else Path(
        os.environ.get("JP_OCR_DATA") or Path.home() / "jp-ocr-data")
    out.mkdir(parents=True, exist_ok=True)

    with db.read_session() as cur:
        officers = write_csv(out / "officer-record.csv", cur, OFFICER_RECORD)
        logged = write_csv(out / "work-log.csv", cur, WORK_LOG)

    print(f"officer-record.csv  {officers:>6} officers")
    print(f"work-log.csv        {logged:>6} entries")
    print(f"\nwritten to {out}")
    print(f"the database itself: {db.db_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
