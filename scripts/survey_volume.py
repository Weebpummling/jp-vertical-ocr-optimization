"""Survey a volume: how many officers each page holds, and which leaves register.

Fills the completeness sidecar the page picker and the worksheet read,
<data home>/cache/<pid>/survey.json. The sidecar is derived data - rerun this to
regenerate it - and every page opened in the workstation refreshes its own entry.

Only page images already on this machine are surveyed unless --fetch is given.
A fetch runs at iiif_client's polite rate, one image at a time, 1.5 s apart, and
is resumable: stop it with Ctrl+C and run it again.

    python scripts/survey_volume.py 1449426                         # cached pages
    python scripts/survey_volume.py 1449426 --first 90 --last 130 --fetch
    python scripts/survey_volume.py 1449426 --redo                  # after a template change
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402
import volume_service as vs  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pid")
    ap.add_argument("--first", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--fetch", action="store_true",
                    help="fetch page images not on this machine from NDL (slow, polite)")
    ap.add_argument("--redo", action="store_true", help="resurvey pages already surveyed")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    frames = db.volume_frames(args.pid)
    if not frames:
        print(f"{args.pid} is not registered: python ingestion/iiif_client.py register {args.pid}")
        return 2
    frames = [f for f in frames
              if (args.first is None or f >= args.first)
              and (args.last is None or f <= args.last)]
    if not args.fetch:
        cached = vs.cached_frames(args.pid)
        skipped = len([f for f in frames if f not in cached])
        frames = [f for f in frames if f in cached]
        if skipped:
            print(f"{skipped} pages not on this machine are left out (add --fetch to include them)")
    if not args.redo:
        done = vs.load_survey(args.pid)
        frames = [f for f in frames if f not in done]

    counts: Counter = Counter()
    officers = 0
    try:
        for n, frame in enumerate(frames, start=1):
            entry = vs.survey_frame(args.pid, frame, fetch=args.fetch)
            counts[entry["status"]] += 1
            if entry["status"] == "roster":
                officers += entry["officers"]
                missing = " LEAF MISSING" if entry["panels_missing"] else ""
                print(f"[{n}/{len(frames)}] frame {frame}: {entry['officers']} officers{missing}")
            else:
                print(f"[{n}/{len(frames)}] frame {frame}: {entry['status']}")
    except KeyboardInterrupt:
        print("\nstopped - everything surveyed so far is saved; run again to continue")

    print(f"\nsurveyed {sum(counts.values())} pages: "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"officers found: {officers}")
    print(f"sidecar: {vs.survey_path(args.pid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
