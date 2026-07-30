"""End-to-end prototype: NDL precomputed OCR boxes -> template cells -> officer records.

Proves the zero-local-OCR reading path (docs/ndl-prior-work.md): Spike C's ruling
detection supplies the geometry (officer columns), NDL's fulltext-json supplies boxed
text lines, and binning + content classification assembles one structured record per
officer — with the monotone-seniority audit running per page.

No database, no OCR install, CPU only. Inputs:
  - page images in reading/spike_c/pages/ (for ruling detection)
  - the volume's fulltext-json (fetched to JP_OCR_DATA or scratchpad)

Usage:
    python prototype_cell_binning.py <fulltext.json> <pages_dir> <frame> [frame ...]

Output: per-frame officer table on stdout + prototype_output.json next to this file.
"""
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

# reuse Spike C's detection machinery
sys.path.insert(0, str(Path(__file__).parent / "spike_c"))
from registration_experiment import SCALE, analyze_panel, find_panels  # noqa: E402

ERA_RE = re.compile(r"^[明大昭]")
DIGITS_RE = re.compile(r"^\d{1,4}$")
POST_HINT = re.compile(r"[長官附員部隊課級校]")
HONOR_RE = re.compile(r"[從正勲功旭瑞]")
KATAKANA_RE = re.compile(r"^[ァ-ヶー・]+$")


def detect_columns_fullres(img_gray):
    """Run Spike C detection; return per-panel column x-edges and band y-lines in
    FULL-RESOLUTION spread coordinates (detection runs at SCALE on panel crops)."""
    small = cv2.resize(img_gray, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    panels = []
    for (x, y, w, h) in find_panels(small):
        pan = analyze_panel(small[y:y + h, x:x + w])
        if pan is None:
            continue
        # map panel-relative detected lines back to full-res spread coords.
        # deskew rotation is <1.3 deg (Spike C); we accept its small y-shift.
        vx = sorted({round((x + px) / SCALE) for px in pan["vlines"]})
        hy = sorted({round((y + py) / SCALE) for py in pan["hlines"]})
        panels.append({"vx": vx, "hy": hy,
                       "x0": round(x / SCALE), "x1": round((x + w) / SCALE)})
    panels.sort(key=lambda p: -p["x0"])  # right page first
    return panels


def classify(cell_lines, y_top, y_bot):
    """Assign field meanings to a column's text lines by content, relative position,
    and glyph size (name characters are printed roughly twice the height of other
    text; small katakana beside them is furigana)."""
    rec = {"seniority": None, "cohort": None, "name": None, "reading": None,
           "post": [], "dates": [], "birth": None, "honors": [], "other": []}
    h = y_bot - y_top
    # in vertical text, glyph WIDTH tracks font size; name type is ~2x body type
    med_w = float(np.median([ln["w"] for ln in cell_lines])) or 1.0
    name_parts = []
    for ln in cell_lines:
        t = ln["text"].strip().replace(" ", "")
        yfrac = (ln["ymid"] - y_top) / h if h else 0
        if not t:
            continue
        if DIGITS_RE.match(t):
            n = int(t)
            if yfrac > 0.8 and n < 60:
                rec["cohort"] = n
            elif rec["seniority"] is None and 0.3 < yfrac < 0.55:
                rec["seniority"] = n
            else:
                rec["other"].append(t)
        elif ERA_RE.match(t):
            if yfrac > 0.6:
                rec["birth"] = (rec["birth"] or "") + t
            else:
                rec["dates"].append(t)
        elif KATAKANA_RE.match(t) and yfrac > 0.55:
            rec["reading"] = (rec["reading"] or "") + t
        elif HONOR_RE.search(t) and 0.55 < yfrac < 0.82 and len(t) <= 8:
            rec["honors"].append(t)
        elif POST_HINT.search(t) and yfrac < 0.72:
            rec["post"].append(t)
        elif (yfrac > 0.6 and ln["w"] >= 1.35 * med_w
              and not t.startswith("同") and not re.search(r"[、。\d]", t)):
            name_parts.append(ln)
        else:
            rec["other"].append(t)
    name_parts.sort(key=lambda ln: ln["ymid"])
    rec["name"] = "".join(ln["text"].strip() for ln in name_parts) or None
    rec["post"] = "".join(rec["post"]) or None
    rec["honors"] = "".join(rec["honors"]) or None
    return rec


def bin_page(entry, panels):
    """Column segmentation is anchored on the seniority-number boxes themselves
    (design §4.3, Lever 3): each officer column carries exactly one small Arabic
    number in the seniority band, so those boxes define the column centers far more
    robustly than thin vertical rulings do. Detected rulings still supply the table's
    vertical extent."""
    lines = [{"text": c["contenttext"],
              "xmid": (c["xmin"] + c["xmax"]) / 2,
              "ymid": (c["ymin"] + c["ymax"]) / 2,
              "h": c["ymax"] - c["ymin"],
              "w": c["xmax"] - c["xmin"]}
             for c in json.loads(entry["coordjson"])]
    officers = []
    for panel in panels:
        hy = panel["hy"]
        if len(hy) < 2:
            continue
        y_top, y_bot = hy[0], hy[-1]
        height = y_bot - y_top
        in_panel = [ln for ln in lines
                    if panel["x0"] <= ln["xmid"] < panel["x1"]
                    and y_top <= ln["ymid"] <= y_bot]
        # anchors: digit-only boxes in the seniority band
        anchors = [ln for ln in in_panel
                   if DIGITS_RE.match(ln["text"].strip())
                   and 0.30 < (ln["ymid"] - y_top) / height < 0.55]
        anchors.sort(key=lambda ln: -ln["xmid"])
        if not anchors:
            continue
        centers = [a["xmid"] for a in anchors]
        pitches = [a - b for a, b in zip(centers, centers[1:])]
        pitch = float(np.median(pitches)) if pitches else (panel["x1"] - panel["x0"]) / 2
        for c in centers:
            cell = [ln for ln in in_panel if abs(ln["xmid"] - c) <= pitch / 2]
            if len(cell) < 3:
                continue
            rec = classify(cell, y_top, y_bot)
            if rec["seniority"] or rec["name"]:
                # adjacent anchor windows can overlap on a shared box; dedupe
                if not any(o["seniority"] == rec["seniority"]
                           and o["post"] == rec["post"] for o in officers):
                    officers.append(rec)
    return officers


def audit(officers):
    """Per-page seniority audit: monotone ascending in reading order, gaps allowed."""
    seq = [o["seniority"] for o in officers if o["seniority"] is not None]
    breaks = [(a, b) for a, b in zip(seq, seq[1:]) if b <= a]
    return {"n_officers": len(officers), "n_with_seniority": len(seq),
            "monotone_ok": not breaks, "breaks": breaks}


def main():
    ft_path, pages_dir, *frames = sys.argv[1:]
    ft = json.load(open(ft_path, encoding="utf-8"))
    by_page = {e["page"]: e for e in ft["list"]}
    out = {}
    for frame in frames:
        f = int(frame)
        img = cv2.imread(str(Path(pages_dir) / f"f{f:03d}.jpg"), cv2.IMREAD_GRAYSCALE)
        if img is None or f not in by_page:
            print(f"frame {f}: missing image or fulltext entry")
            continue
        officers = bin_page(by_page[f], detect_columns_fullres(img))
        a = audit(officers)
        out[f] = {"audit": a, "officers": officers}
        print(f"\n=== frame {f}: {a['n_officers']} officers, "
              f"seniority {a['n_with_seniority']}, monotone={a['monotone_ok']} "
              f"{'breaks=' + str(a['breaks']) if a['breaks'] else ''} ===")
        for o in officers:
            print(f"  #{str(o['seniority']):>5} {str(o['name'] or '?'):　<10}"
                  f" cohort={o['cohort']} post={str(o['post'])[:28]}")
    with open(Path(__file__).parent / "prototype_output.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
