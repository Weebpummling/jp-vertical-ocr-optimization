"""Export a reading worksheet - a volume's officers as an Excel workbook.

    python scripts/export_worksheet.py 1449426 100
    python scripts/export_worksheet.py 1449426 95-110 --images
    python scripts/export_worksheet.py 1449426 surveyed
    python scripts/export_worksheet.py 1449426 95-110 --fetch     # fetch missing scans from NDL

One row per officer: what a person recorded, what NDL's OCR proposes where
nobody has yet, colour-coded by source, with links to the image and to the
workstation. Written to <data home>/exports/<pid>/ with a .csv beside it.
See app/worksheet.py for what each sheet holds, and scripts/import_worksheet.py
for sending corrections made in the sheet back to the record.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import worksheet  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pid")
    ap.add_argument("frames", help="100, 95-110, 60,95-110, or 'surveyed'")
    ap.add_argument("--images", action="store_true",
                    help="embed the name crop beside each officer")
    ap.add_argument("--fetch", action="store_true",
                    help="fetch page images not on this machine from NDL (slow, polite)")
    ap.add_argument("--out", help="directory to write into (default: data home exports)")
    ap.add_argument("--base-url", default=worksheet.DEFAULT_BASE_URL,
                    help="where the workstation runs, for the 'open' links")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        frames = worksheet.parse_frames(args.frames, args.pid)
    except ValueError as exc:
        print(exc)
        return 2
    if args.images and len(frames) > worksheet.MAX_IMAGE_FRAMES:
        print(f"--images is limited to {worksheet.MAX_IMAGE_FRAMES} frames "
              f"({len(frames)} asked for); export without it, or in parts")
        return 2

    result = worksheet.export(args.pid, frames, images=args.images, fetch=args.fetch,
                              out_dir=args.out, base_url=args.base_url, log=print)
    counts = Counter(p.status for p in result.pages)
    print(f"\n{result.officers} officers from {result.frames} frames: "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"workbook  {result.path}")
    print(f"csv       {result.csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
