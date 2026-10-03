"""Merge the work a reader sent back into the master database.

    python scripts/merge_returned.py roster-1449426-ab12cd34-20261003-101500.zip
    python scripts/merge_returned.py <file> --apply

Without --apply it only looks: it checks the file against the master database
and says what merging would add. With --apply it adds it, in one transaction.

Safe to run on the same file twice, and on a later file from the same reader -
each file holds everything they have done so far, and only what is new is added.

It refuses when the file and the master disagree about something that should be
identical - most importantly when the master already holds readings on this
volume that the reader's kit never saw, which means two people worked on the
same volume. --allow-other-work merges anyway, once you have looked.

The master database is the one the workstation uses (JPOCR_DB, or the data
home's officer-index.db).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402
import kit_merge  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", help="the file the reader sent (roster-<pid>-...zip)")
    ap.add_argument("--apply", action="store_true", help="merge it (default: only report)")
    ap.add_argument("--allow-other-work", action="store_true",
                    help="merge even though the master has readings this kit never saw")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    package = Path(args.package)
    if not package.exists():
        raise SystemExit(f"no such file: {package}")
    master = Path(db.db_path())
    try:
        report = kit_merge.merge(master, package, apply=args.apply,
                                 allow_other_work=args.allow_other_work)
    except kit_merge.MergeRefused as exc:
        print(f"NOT MERGED: {exc}")
        return 1

    print(f"master database  {master}")
    print(f"from             {report['reader_name']}  -  volume {report['pid']}")
    print(f"new readings     {report['observations_new']:>6}  on {report['pages_touched']} pages"
          f"   ({report['observations_already_merged']} already in the master)")
    print(f"new cells        {report['cells_new']:>6}   ({report['cells_changed']} existing "
          f"cells updated)")
    print(f"work log entries {report['work_log_new']:>6}")
    new = (report["observations_new"] + report["cells_new"] + report["cells_changed"]
           + report["work_log_new"])
    if not new:
        print("\nNothing new: everything in this file is already in the master.")
    elif report["applied"]:
        print("\nMerged.")
    else:
        print("\nNothing was changed. Run again with --apply to merge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
