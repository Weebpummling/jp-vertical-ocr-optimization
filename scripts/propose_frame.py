"""Propose every field of every officer on a frame, from NDL's own OCR.

The zero-cost first pass: no OCR run, no network once the volume's fulltext is
cached, about a second a page. Output is proposals for a human to confirm at the
workstation - never values. See reading/binning.py.

Usage:
    python scripts/propose_frame.py <pid> <frame> [frame ...]
    python scripts/propose_frame.py <pid> --range 60 80
    python scripts/propose_frame.py <pid> 60 --json out.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reading"))

import binning  # noqa: E402
import ndl_lines  # noqa: E402
import registration as R  # noqa: E402

TEMPLATE_DIR = ROOT / "templates"
FIELD_ORDER = ["seniority_no", "name_raw", "cohort", "post",
               "commissioning_date", "rank_date", "prev_rank_date",
               "service_in_rank", "court_rank_decorations"]


def data_home() -> Path:
    home = os.environ.get("JP_OCR_DATA")
    if not home:
        raise SystemExit("JP_OCR_DATA is not set")
    return Path(home)


def load_fulltext(pid: str) -> dict:
    path = data_home() / "cache" / pid / "ndl_fulltext_raw.json"
    if not path.exists():
        raise SystemExit(
            f"no cached fulltext for pid {pid} at {path}\n"
            f"fetch it once with NDL Workbench's client, then re-run")
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def frame_image(pid: str, frame: int):
    path = data_home() / "cache" / pid / f"frame_{frame:04d}.jpg"
    if not path.exists():
        raise SystemExit(f"frame {frame} is not cached at {path}")
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise SystemExit(f"could not read {path}")
    return img


def propose_frame(pid: str, frame: int, fulltext: dict, templates: list) -> dict:
    """Register the frame, bin NDL's lines into it, and propose each field."""
    image = frame_image(pid, frame)
    grids = R.detect_page(image)
    if not grids:
        return {"frame": frame, "status": "no table detected"}
    lines = ndl_lines.frame(fulltext, frame)

    panels = []
    for grid in grids:
        reg = R.classify(grid, templates)
        if reg is None:
            panels.append({"status": "no template matched"})
            continue
        template = next(t for t in templates if t.template_id == reg.template_id)
        cells, unassigned = binning.bin_page(lines, R.cells(reg, template))
        fields = [name for name, _a, _b in template.fields]
        officers = binning.propose(cells, reg.grid.n_officer_columns, fields)
        panels.append({
            "status": "ok",
            "template": reg.template_id,
            "clean": reg.is_clean,
            "officers": [
                {"column": o.column,
                 "fields": {k: {"value": p.value, "raw": p.raw,
                                "method": p.method, "note": p.note,
                                "suspect": p.suspect}
                            for k, p in o.fields.items()}}
                for o in officers],
            "unassigned": [l.text for l in unassigned],
        })
    return {"frame": frame, "lines": len(lines), "panels": panels}


def summarise(result: dict) -> None:
    print(f"\n=== frame {result['frame']} "
          f"({result.get('lines', 0)} NDL lines) ===")
    for i, panel in enumerate(result.get("panels", [])):
        if panel.get("status") != "ok":
            print(f"  panel {i}: {panel.get('status')}")
            continue
        print(f"  panel {i}: {panel['template']} "
              f"({'clean' if panel['clean'] else 'INFERRED EDGES'}), "
              f"{len(panel['officers'])} officers, "
              f"{len(panel['unassigned'])} lines outside the table")
        for officer in panel["officers"]:
            f = officer["fields"]
            bits = []
            for name in FIELD_ORDER:
                p = f.get(name)
                if not p:
                    continue
                if p["value"]:
                    mark = "~" if p["method"] == "inherited" else " "
                    bits.append(f"{name}={mark}{p['value']}")
                elif p["method"] == "refused":
                    bits.append(f"{name}=!({p['raw']})")
            print(f"    [{officer['column']:2d}] " + "  ".join(bits))
        if panel["unassigned"]:
            print("    outside: " + " | ".join(panel["unassigned"][:8]))


def coverage(results: list[dict]) -> None:
    """How much of the page the machine filled, per field."""
    filled: dict[str, int] = {}
    refused: dict[str, int] = {}
    total = 0
    for result in results:
        for panel in result.get("panels", []):
            if panel.get("status") != "ok":
                continue
            for officer in panel["officers"]:
                total += 1
                for name, p in officer["fields"].items():
                    if p["value"]:
                        filled[name] = filled.get(name, 0) + 1
                    elif p["method"] == "refused":
                        refused[name] = refused.get(name, 0) + 1
    if not total:
        return
    print(f"\n=== proposal coverage over {total} officer columns ===")
    for name in FIELD_ORDER:
        got = filled.get(name, 0)
        no = refused.get(name, 0)
        print(f"  {name:24s} {got:4d}/{total:<4d} "
              f"({100.0 * got / total:5.1f}%)  refused {no}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pid")
    ap.add_argument("frames", nargs="*", type=int)
    ap.add_argument("--range", nargs=2, type=int, metavar=("FIRST", "LAST"))
    ap.add_argument("--json", type=Path)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    frames = list(args.frames)
    if args.range:
        frames += list(range(args.range[0], args.range[1] + 1))
    if not frames:
        ap.error("give at least one frame, or --range")

    fulltext = load_fulltext(args.pid)
    templates = R.load_library(TEMPLATE_DIR)
    results = []
    for frame in frames:
        try:
            result = propose_frame(args.pid, frame, fulltext, templates)
        except SystemExit as exc:
            print(f"frame {frame}: {exc}")
            continue
        results.append(result)
        if not args.quiet:
            summarise(result)
    coverage(results)
    if args.json:
        with io.open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
