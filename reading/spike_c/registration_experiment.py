"""Spike C - template registration on real 1933 roster pages.

Question under test (docs/PLAN.md): does top-down template registration hold on real
scans? Concretely: after deskew, are the horizontal field-band boundaries of the
officer table stable enough across pages (as fractions of table height) that field
identity can be assigned by geometry alone?

Method
  1. Split each spread into its two page panels (bright regions on black film border).
  2. Deskew each panel from the dominant angle of its long horizontal rulings.
  3. Extract long horizontal/vertical rulings morphologically; cluster into line
     positions via projection profiles.
  4. Panel 1 of the reference page defines the template (band fractions of table
     height). Every other panel is scored against it: matched bands within tolerance,
     mean residual, and officer-column count.
  5. Emit overlay images for visual verification and a JSON summary.

Run:  python registration_experiment.py   (expects pages/ next to this file)
"""
import cv2
import json
import numpy as np
from pathlib import Path

HERE = Path(__file__).parent
PAGES = sorted((HERE / "pages").glob("f*.jpg"))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

SCALE = 0.6           # detection scale — below ~0.5 the thin interior rulings alias away
TOL_FRAC = 0.015      # band-match tolerance, fraction of table height
MIN_PANEL_AREA = 0.10 # of image


def find_panels(gray):
    """Bright page panels on dark film background -> list of (x,y,w,h), right first.

    The two pages of a spread often touch at the gutter, so contour splitting is
    unreliable; find the bright region, then split it at the darkest column near
    its middle (the gutter shadow).
    """
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    regions = [cv2.boundingRect(c) for c in contours]
    regions = [r for r in regions if r[2] * r[3] > MIN_PANEL_AREA * w * h]
    if not regions:
        return []
    x, y, cw, ch = max(regions, key=lambda r: r[2] * r[3])
    col_mean = gray[y:y + ch, x:x + cw].mean(axis=0)
    mid0, mid1 = int(cw * 0.35), int(cw * 0.65)
    gutter = mid0 + int(np.argmin(col_mean[mid0:mid1]))
    right = (x + gutter, y, cw - gutter, ch)   # right page first (reading order)
    left = (x, y, gutter, ch)
    return [right, left]


def ruling_masks(panel_bin):
    ph, pw = panel_bin.shape
    # heal 1-px breaks in thin rulings before the long opening
    h_healed = cv2.morphologyEx(panel_bin, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    v_healed = cv2.morphologyEx(panel_bin, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    horiz = cv2.morphologyEx(h_healed, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (max(pw // 14, 25), 1)))
    vert = cv2.morphologyEx(v_healed, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(ph // 14, 25))))
    return horiz, vert


def deskew_angle(horiz):
    """Dominant angle of long horizontal rulings, degrees."""
    lines = cv2.HoughLinesP(horiz, 1, np.pi / 720, threshold=200,
                            minLineLength=horiz.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        if x2 != x1:
            a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(a) < 5:
                angles.append(a)
    return float(np.median(angles)) if angles else 0.0


def profile_lines(mask, axis, min_run_frac=0.30, gap=4):
    """Cluster projection-profile peaks into line coordinates."""
    length = mask.shape[1 - axis]
    prof = (mask > 0).sum(axis=1 - axis)
    hits = np.where(prof > min_run_frac * length)[0]
    lines, run = [], []
    for v in hits:
        if run and v - run[-1] > gap:
            lines.append(int(np.mean(run)))
            run = []
        run.append(v)
    if run:
        lines.append(int(np.mean(run)))
    return lines


def analyze_panel(gray_panel):
    _, binv = cv2.threshold(gray_panel, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horiz, _ = ruling_masks(binv)
    ang = deskew_angle(horiz)
    if abs(ang) > 0.05:
        ph, pw = gray_panel.shape
        M = cv2.getRotationMatrix2D((pw / 2, ph / 2), ang, 1.0)
        gray_panel = cv2.warpAffine(gray_panel, M, (pw, ph),
                                    flags=cv2.INTER_LINEAR, borderValue=255)
        _, binv = cv2.threshold(gray_panel, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        horiz, _ = ruling_masks(binv)
    _, vert = ruling_masks(binv)

    hlines = profile_lines(horiz, axis=0)
    vlines = profile_lines(vert, axis=1)
    if len(hlines) < 2 or len(vlines) < 2:
        return None
    top, bot = hlines[0], hlines[-1]
    left, right = vlines[0], vlines[-1]
    height = bot - top
    bands = [(y - top) / height for y in hlines]
    # officer columns = interior vertical lines + 1
    cols = max(len([x for x in vlines if left < x < right]) + 1, 0)
    return {
        "angle_deg": round(ang, 3),
        "table_bbox": [int(left), int(top), int(right), int(bot)],
        "band_fracs": [round(b, 4) for b in bands],
        "n_columns": cols,
        "gray": gray_panel,
        "hlines": hlines,
        "vlines": vlines,
    }


def score_against(template, bands):
    matched, residuals = 0, []
    for t in template:
        d = min(abs(b - t) for b in bands)
        if d <= TOL_FRAC:
            matched += 1
            residuals.append(d)
    return matched, (float(np.mean(residuals)) if residuals else None)


def main():
    results, template = [], None
    for page in PAGES:
        img = cv2.imread(str(page), cv2.IMREAD_GRAYSCALE)
        small = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        panels = find_panels(small)
        for pi, (x, y, w, h) in enumerate(panels):
            pan = analyze_panel(small[y:y + h, x:x + w])
            tag = f"{page.stem}_p{pi}"
            if pan is None:
                results.append({"panel": tag, "status": "no_table"})
                continue
            if template is None:
                template = pan["band_fracs"]
                print(f"TEMPLATE from {tag}: {len(template)} bands -> {template}")
            matched, resid = score_against(template, pan["band_fracs"])
            rec = {
                "panel": tag, "status": "ok",
                "skew_deg": pan["angle_deg"],
                "bands_detected": len(pan["band_fracs"]),
                "bands_matched": f"{matched}/{len(template)}",
                "mean_residual_frac": round(resid, 4) if resid is not None else None,
                "n_columns": pan["n_columns"],
            }
            results.append(rec)
            vis = cv2.cvtColor(pan["gray"], cv2.COLOR_GRAY2BGR)
            for yy in pan["hlines"]:
                cv2.line(vis, (0, yy), (vis.shape[1], yy), (0, 0, 255), 2)
            for xx in pan["vlines"]:
                cv2.line(vis, (xx, 0), (xx, vis.shape[0]), (255, 0, 0), 1)
            cv2.imwrite(str(OUT / f"{tag}_overlay.jpg"), vis,
                        [cv2.IMWRITE_JPEG_QUALITY, 70])

    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
