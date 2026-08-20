"""How fast transcription actually goes.

Phase 1 exits on a measured number, not an impression: the officers/hour a human
achieves by hand, which every later phase is judged against (docs/PLAN.md). The
work log already carries a timestamp per officer recorded, so the number is a
query, not a stopwatch.

    python scripts/session_rate.py
    python scripts/session_rate.py --gap 30    # what counts as a break, minutes

Sessions are split on a gap: consecutive officers more than --gap minutes apart
are treated as separate sittings, so lunch does not get counted as transcription
time. A single officer on its own is reported but contributes no rate - one
timestamp cannot measure a duration.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gap", type=float, default=15.0,
                    help="minutes of inactivity that ends a sitting (default 15)")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with db.read_session() as cur:
        cur.execute("""
            SELECT w.at, COALESCE(u.display_name,'(unnamed)') AS who,
                   w.volume_pid, w.frame_no
              FROM work_log w
         LEFT JOIN app_user u ON u.user_id = w.user_id
             WHERE w.action = 'record_officer'
          ORDER BY w.at
        """)
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        print("No officers recorded yet.")
        return 0

    sittings: list[list[dict]] = [[rows[0]]]
    for previous, row in zip(rows, rows[1:]):
        minutes = (parse(row["at"]) - parse(previous["at"])).total_seconds() / 60
        if minutes > args.gap:
            sittings.append([])
        sittings[-1].append(row)

    total_officers = 0
    all_intervals: list[float] = []
    for sitting in sittings:
        start, end = parse(sitting[0]["at"]), parse(sitting[-1]["at"])
        minutes = (end - start).total_seconds() / 60
        intervals = [(parse(b["at"]) - parse(a["at"])).total_seconds()
                     for a, b in zip(sitting, sitting[1:])]
        all_intervals += intervals
        total_officers += len(sitting)
        who = ", ".join(sorted({r["who"] for r in sitting}))
        pages = ", ".join(sorted({f"{r['volume_pid']}/{r['frame_no']}" for r in sitting}))
        line = (f"{start:%Y-%m-%d %H:%M}  {len(sitting):>3} officers  "
                f"{minutes:>6.1f} min  {who}  [{pages}]")
        if intervals:
            # Rate from the gaps between officers, not from count/elapsed: the
            # first officer's own time is not in the log, and counting it as
            # free would flatter every short sitting.
            line += f"  {3600 / statistics.mean(intervals):>6.1f} officers/hour"
        print(line)

    print(f"\n{total_officers} officers across {len(sittings)} sitting(s)")
    if all_intervals:
        mean = statistics.mean(all_intervals)
        median = statistics.median(all_intervals)
        print(f"per officer: {mean:.0f}s mean, {median:.0f}s median")
        print(f"BASELINE:    {3600 / mean:.1f} officers/hour")
    else:
        print("Not enough officers yet to measure a rate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
