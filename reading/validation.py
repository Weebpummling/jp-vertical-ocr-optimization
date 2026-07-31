"""Record validation: the roster's own redundancy, turned into a flag queue.

The corpus audits itself: seniority numbers ascend monotonically in source
reading order, rank/branch vocabularies are closed and dated, dates are bounded,
and independent engines either agree or they don't. This module runs those
checks over transcribed cells and emits flags — it never corrects anything.
A flag is a claim that *something* is wrong with a cell, pointing at the page
and the evidence; a human decides what.

Flag codes map onto roster_cell.audit_status where one applies
('sequence_break' / 'extra_row' / 'missing_row'); vocabulary, date, and
agreement findings become review tasks only, since the cell's geometry is not
in question. flags_to_sql() emits the queue in the repo's no-driver SQL-on-
stdout style: audit_status updates plus one open review_flag task per flagged
cell, deduplicated against tasks already open.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

VOCAB_DIR = Path(__file__).resolve().parent.parent / "data" / "vocab"

MEIJI_RESTORATION = date(1868, 1, 1)   # no career datum can precede it

AUDIT_STATUS_CODES = {"sequence_break", "extra_row", "missing_row"}


@dataclass(frozen=True)
class Cell:
    """One officer cell as transcribed, in source reading order."""

    cell_id: str
    page_ref: str                      # e.g. 'pid 1449474 frame 51'
    seniority_no: int | None = None
    branch_code: str | None = None
    rank_code: str | None = None
    commissioning_date: date | None = None
    as_of_date: date | None = None
    agree_status: str | None = None    # worst machine_reading status for the cell


@dataclass(frozen=True)
class Flag:
    cell_id: str
    page_ref: str
    code: str                          # sequence_break / missing_row / extra_row /
                                       # branch_out_of_period / rank_out_of_period /
                                       # date_out_of_bounds / engine_disagreement
    detail: str

    @property
    def audit_status(self) -> str | None:
        return self.code if self.code in AUDIT_STATUS_CODES else None


def load_vocab_dates(name: str, code_col: str, vocab_dir: Path | None = None
                     ) -> dict[str, tuple[date | None, date | None]]:
    """{code: (valid_from, valid_to)} from a vocab CSV; None = unbounded."""
    out: dict[str, tuple[date | None, date | None]] = {}
    with open((vocab_dir or VOCAB_DIR) / name, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            def d(v):
                return date.fromisoformat(v) if (v or "").strip() else None
            out[row[code_col]] = (d(row.get("valid_from")), d(row.get("valid_to")))
    return out


def check_sequence(cells: list[Cell], *, expected_rows: int | None = None) -> list[Flag]:
    """Seniority must strictly ascend in source order; count must match template.

    Gaps are normal (absent officers); regressions and duplicates are not. The
    page-55 failure case reads 110, 11, 112 — the 11 is almost certainly a
    cropped 111, but that is the repair module's suggestion to make and a
    human's to accept. Here it is simply a break.
    """
    flags: list[Flag] = []
    prev: tuple[int, Cell] | None = None
    for c in cells:
        if c.seniority_no is None:
            continue
        if prev is not None:
            p_no, _ = prev
            if c.seniority_no <= p_no:
                flags.append(Flag(
                    c.cell_id, c.page_ref, "sequence_break",
                    f"seniority {c.seniority_no} after {p_no} breaks the monotone sequence",
                ))
        prev = (c.seniority_no, c)
    if expected_rows is not None and cells:
        got = len(cells)
        if got < expected_rows:
            flags.append(Flag(
                cells[-1].cell_id, cells[-1].page_ref, "missing_row",
                f"template expects {expected_rows} rows, page has {got}",
            ))
        elif got > expected_rows:
            flags.append(Flag(
                cells[-1].cell_id, cells[-1].page_ref, "extra_row",
                f"template expects {expected_rows} rows, page has {got}",
            ))
    return flags


def check_vocab_dating(cells: list[Cell],
                       branch_dates: dict[str, tuple[date | None, date | None]],
                       rank_dates: dict[str, tuple[date | None, date | None]],
                       ) -> list[Flag]:
    """A code that was not in force on the volume's snapshot date is a misread.

    The canonical case is corpus-verified: 航空兵 (kokuhei) exists from
    1925-05-01, so a kokuhei reading on a 1923 page cannot be right.
    """
    flags: list[Flag] = []
    for c in cells:
        if c.as_of_date is None:
            continue
        for code, dates, kind in ((c.branch_code, branch_dates, "branch"),
                                  (c.rank_code, rank_dates, "rank")):
            if code is None or code not in dates:
                continue
            lo, hi = dates[code]
            if (lo is not None and c.as_of_date < lo) or \
               (hi is not None and c.as_of_date > hi):
                flags.append(Flag(
                    c.cell_id, c.page_ref, f"{kind}_out_of_period",
                    f"{kind} {code} not in force on {c.as_of_date.isoformat()}",
                ))
    return flags


def check_bounded_dates(cells: list[Cell]) -> list[Flag]:
    """Career dates are bounded by history on one side and the snapshot on the other."""
    flags: list[Flag] = []
    for c in cells:
        d = c.commissioning_date
        if d is None:
            continue
        if d < MEIJI_RESTORATION:
            flags.append(Flag(
                c.cell_id, c.page_ref, "date_out_of_bounds",
                f"commissioning {d.isoformat()} precedes {MEIJI_RESTORATION.isoformat()}",
            ))
        elif c.as_of_date is not None and d > c.as_of_date:
            flags.append(Flag(
                c.cell_id, c.page_ref, "date_out_of_bounds",
                f"commissioning {d.isoformat()} is after the volume snapshot "
                f"{c.as_of_date.isoformat()}",
            ))
    return flags


def check_agreement(cells: list[Cell]) -> list[Flag]:
    """Engines disagreeing about a cell is exactly what review time is for."""
    return [
        Flag(c.cell_id, c.page_ref, "engine_disagreement",
             "machine readings disagree; show candidates side by side")
        for c in cells if c.agree_status == "disagree"
    ]


def validate_page(cells: list[Cell], *,
                  expected_rows: int | None = None,
                  branch_dates: dict | None = None,
                  rank_dates: dict | None = None) -> list[Flag]:
    """All checks over one page's cells, in source order. Flags, never fixes."""
    bd = branch_dates if branch_dates is not None else load_vocab_dates("branch.csv", "branch_code")
    rd = rank_dates if rank_dates is not None else load_vocab_dates("rank.csv", "rank_code")
    flags: list[Flag] = []
    flags += check_sequence(cells, expected_rows=expected_rows)
    flags += check_vocab_dating(cells, bd, rd)
    flags += check_bounded_dates(cells)
    flags += check_agreement(cells)
    return flags


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def flags_to_sql(flags: list[Flag]) -> str:
    """The flag queue as SQL: audit_status where applicable, one open
    review_flag task per flagged cell. Idempotent — a cell with an open
    review_flag task is not queued twice. Audited like every other write.
    """
    lines = ["-- Generated by reading/validation.py. Do not edit by hand.",
             "BEGIN;"]
    for f in flags:
        if f.audit_status:
            lines.append(
                f"UPDATE roster_cell SET audit_status = {_q(f.audit_status)} "
                f"WHERE cell_id = {_q(f.cell_id)}::uuid;"
            )
        lines.append(
            "INSERT INTO task (task_type, subject_id, status)\n"
            f"SELECT 'review_flag', {_q(f.cell_id)}::uuid, 'open'\n"
            "WHERE NOT EXISTS (SELECT 1 FROM task WHERE task_type = 'review_flag' "
            f"AND subject_id = {_q(f.cell_id)}::uuid AND status = 'open');"
            f"  -- {f.code}: {f.detail.replace(chr(10), ' ')}"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"
