"""The officer record and the work log as plain CSV.

The queries behind `scripts/export_record.py`, kept here so the workstation can
write the same two files itself - a reader's kit sends them home beside the
database (app/kit.py), and they must be the files the lead already knows.

Both are UTF-8 with a BOM: the likeliest thing to happen to them is being
double-clicked into Excel on a Japanese Windows machine, and without the BOM
Excel reads UTF-8 as cp932 and turns every name into mojibake.
"""
from __future__ import annotations

import csv
from pathlib import Path

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


def write_record(out_dir: Path, cur) -> tuple[int, int]:
    """officer-record.csv and work-log.csv into `out_dir`; (officers, log entries)."""
    return (write_csv(out_dir / "officer-record.csv", cur, OFFICER_RECORD),
            write_csv(out_dir / "work-log.csv", cur, WORK_LOG))
