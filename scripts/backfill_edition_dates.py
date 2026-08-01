"""Fill in source_volume.edition_date from the volume title.

Ingestion registers volumes from the IIIF manifest, whose label carries the 調
date in prose ("... 昭和8年9月1日調") but not as a date column. Observations need
it: `observation.as_of_date` is NOT NULL and is the snapshot every reading is
true as of.

Parsing goes through reading/eradate.py, so this refuses exactly what the
transcription path refuses - no separate, looser date rule for metadata.

    python scripts/backfill_edition_dates.py            # report only
    python scripts/backfill_edition_dates.py --apply    # write

Writes are attributed: pass --user <login> (default 'system').
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "reading"))

import db  # noqa: E402
import eradate  # noqa: E402

# The 調 date in a volume label, in either notation the corpus uses.
DATE_IN_TITLE = re.compile(
    r"((?:明治|大正|昭和)[0-9０-９〇一二三四五六七八九十百]+年"
    r"[0-9０-９〇一二三四五六七八九十]+月"
    r"[0-9０-９〇一二三四五六七八九十]+日)")


def edition_date_from_title(title: str):
    """(date, reason) - exactly one of the two is set."""
    match = DATE_IN_TITLE.search(title or "")
    if not match:
        return None, "no 年月日 date found in the title"
    parsed = eradate.parse(match.group(1))
    return parsed.value, parsed.reason


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the dates")
    ap.add_argument("--user", default="system", help="app_user login to attribute writes to")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with db.read_session() as cur:
        cur.execute("SELECT volume_id, pid, title, edition_date FROM source_volume "
                    "ORDER BY pid")
        volumes = cur.fetchall()

    actor = None
    if args.apply:
        user = db.find_user(args.user)
        if not user:
            print(f"no such app_user: {args.user!r}", file=sys.stderr)
            return 2
        actor = str(user["user_id"])

    changed = refused = 0
    for volume in volumes:
        if volume["edition_date"]:
            print(f"{volume['pid']:>9}  {volume['edition_date']}  (already set)")
            continue
        value, reason = edition_date_from_title(volume["title"])
        if value is None:
            refused += 1
            print(f"{volume['pid']:>9}  REFUSED   {reason}")
            continue
        changed += 1
        if args.apply:
            db.set_volume_edition_date(str(volume["volume_id"]), value, actor)
            print(f"{volume['pid']:>9}  {value}  written")
        else:
            print(f"{volume['pid']:>9}  {value}  (would write; pass --apply)")

    print(f"\n{changed} to write, {refused} refused, {len(volumes)} volumes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
