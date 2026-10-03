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
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402

from record_export import write_record  # noqa: E402


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
        officers, logged = write_record(out, cur)

    print(f"officer-record.csv  {officers:>6} officers")
    print(f"work-log.csv        {logged:>6} entries")
    print(f"\nwritten to {out}")
    print(f"the database itself: {db.db_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
