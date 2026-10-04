"""Prepare a volume for transcription: register every page once, here.

    python scripts/prepare_volume.py 1449426
    python scripts/prepare_volume.py --all
    python scripts/prepare_volume.py 1449426 --redo      # after the detector or a template changed
    python scripts/prepare_volume.py 1449426 --report    # only rewrite the readiness report

Registers every page of the volume from its original scan on this machine and
stores the result in the data home (cache/<pid>/registered). From then on this
workstation and every reader's kit read that same stored result: they cannot
disagree about where an officer is, and nothing that changes later - a library
upgrade, a new template - moves a cell on a page already read, until the
volume is prepared again on purpose. Also makes the smaller page images kits
carry, and writes a readiness report: which pages hold officers a reader will
not be able to record (<data home>/kits/readiness).

Run it with the Python the workstation runs on. A volume already prepared with
the current detector and templates is left alone unless --redo. Before stored
registrations are replaced, every page that already has readings is checked:
if a recorded officer would sit somewhere else, nothing is written unless
--force.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _sub in ("app", "scripts", "ingestion", "reading"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))


def prepare(pid: str, args) -> int:
    import db
    import kit_build
    import volume_service as vs

    home = vs.data_home()
    master = Path(db.db_path())
    volume = kit_build.volume_row(master, pid)
    frames = volume["frames"]
    record = kit_build.prepared(home, pid)
    current = record is not None and record["registration"] == kit_build.registration_fingerprint()
    print(f"\n{pid}  {volume['title']}  ({len(frames)} pages)")

    if not args.report:
        if current and not args.redo:
            print(f"  already prepared {record['prepared_at']} with the current detector "
                  f"and templates; --redo prepares it again")
        else:
            moved = kit_build.moved_readings(home, master, pid)
            if moved and not args.force:
                print(f"  NOT PREPARED: {len(moved)} recorded officers would sit somewhere "
                      f"else under the current registration, e.g. frame {moved[0]['frame']} "
                      f"row {moved[0]['row_index'] + 1}. Look before replacing; --force "
                      f"prepares anyway.")
                return 1
            started = time.time()

            def progress(done: int, total: int) -> None:
                if done == total or done % 50 == 0:
                    print(f"\r  registering     {done}/{total}", end="", flush=True)

            record = kit_build.prepare_volume(home, pid, frames, workers=args.workers,
                                              progress=progress)
            print(f"\r  prepared in {time.time() - started:.0f} s: {record['roster']} roster "
                  f"pages, {record['officers']} officers, {record['leaves_reread']} leaves on "
                  f"the second reading, small images {record['small_bytes'] / 1e6:.0f} MB")
    elif record is None:
        print("  not prepared yet")
        return 1

    report = kit_build.readiness(home, pid, frames)
    md, table = kit_build.write_readiness(home / "kits" / "readiness", report, volume["title"])
    print(f"  a reader can record {report['officers']} officers on {report['roster']} pages; "
          f"about {report['out_of_reach']} ({report['out_of_reach_pct']}%) are out of reach:")
    print(f"    {report['leaf_missing']:4d} pages with one leaf not registered")
    print(f"    {report['not_registered']:4d} roster-looking pages that fit no template")
    print(f"    {report['cut_short']:4d} pages with numbers outside the grid")
    print(f"  report: {md}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pid", nargs="*")
    ap.add_argument("--all", action="store_true", help="every volume in the master database")
    ap.add_argument("--redo", action="store_true", help="prepare again, replacing what is stored")
    ap.add_argument("--force", action="store_true",
                    help="replace even if recorded officers would move")
    ap.add_argument("--report", action="store_true", help="only rewrite the readiness report")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import db

    pids = list(args.pid)
    if args.all:
        with db.read_session() as cur:
            cur.execute("SELECT pid FROM source_volume ORDER BY edition_date")
            pids = [r["pid"] for r in cur.fetchall()]
    if not pids:
        ap.error("name a volume, or --all")
    return max(prepare(pid, args) for pid in pids)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
