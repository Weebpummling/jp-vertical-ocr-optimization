"""Layer 2 - template registration for roster pages.

Field identity comes from geometry, not from cell contents (templates/README.md).
This module detects the ruling grid on a page panel, classifies the panel against
the template library, and resolves per-cell rectangles in **original scan pixels**
so they convert directly to re-checkable IIIF region URLs
(`ingestion.iiif_client.region_url`).

Productionized from `reading/spike_c/registration_experiment.py`, which answered
the design's load-bearing question (docs/spikes/spike-c-registration.md) but threw
away everything the workstation needs: it scored band *fractions* only, took its
template from whichever panel happened to come first, and never mapped a cell back
onto the page. Three things are new here:

1. **Templates are fixed committed artifacts** (`templates/*.json`), not values
   re-derived at run time. Standing commitment 3 forbids a per-page self-improving
   detector; a page that does not fit its template is *reported*, never fitted to.
2. **Registration, not just detection.** Each template band is matched to the
   ruling this page actually has, so cell edges follow the page's own geometry.
   Unmatched bands fall back to the template fraction and are flagged.
3. **Coordinates round-trip to the original scan**, through panel offset, detection
   downscale, and deskew rotation.

Deskew note: cells are axis-aligned rectangles in the deskewed frame, so mapping
back through the inverse rotation yields a rotated quad. We return its axis-aligned
bounding box, which over-crops by up to `long_side * sin(skew)` (~2% at the ±1.2 deg
skew Spike C observed). Over-cropping is the safe direction: a human reading the
crop sees a little neighbouring ink rather than a clipped character.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Detection scale. Spike C lesson 1: below ~0.5x the thin interior rulings alias
# away under Otsu and the field bands vanish entirely.
SCALE = 0.6
MIN_PANEL_AREA = 0.10  # of image area

# Vertical rulings outside this fraction of panel width are page/film borders,
# not table frame. Measured on the 1933 volume: real table frames sit at 5-92%
# of panel width, borders at 0.2-1% and 97-99%.
EDGE_LO, EDGE_HI = 0.03, 0.95
# Largest run of consecutive missing rulings we will interpolate across.
MAX_PITCH_MULTIPLE = 4
PITCH_TOL = 0.2


# --------------------------------------------------------------------------
# geometry containers
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Panel:
    """One page panel located inside a scan image, in original scan pixels.

    Roster scans are two-page spreads; `find_panels` returns the right-hand page
    first because that is the reading order.
    """

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Grid:
    """Ruling geometry detected on one panel.

    Coordinates are in the *deskewed panel* frame at detection scale; use
    `Registration` to obtain original-scan rectangles. `band_ys` and `column_xs`
    are ruling positions, so N bands bound N-1 row intervals and M columns bound
    M-1 officer columns.
    """

    panel: Panel
    skew_deg: float
    table: tuple[int, int, int, int]  # x0, y0, x1, y1
    band_ys: tuple[int, ...]
    column_xs: tuple[int, ...]
    interpolated_columns: tuple[int, ...] = ()

    @property
    def table_height(self) -> int:
        return self.table[3] - self.table[1]

    @property
    def band_fracs(self) -> tuple[float, ...]:
        """Band positions as fractions of table height - the scale-free signature."""
        top, height = self.table[1], self.table_height
        if height <= 0:
            return ()
        return tuple(round((y - top) / height, 4) for y in self.band_ys)

    @property
    def n_officer_columns(self) -> int:
        x0, x1 = self.table[0], self.table[2]
        interior = [x for x in self.column_xs if x0 < x < x1]
        return len(interior) + 1


@dataclass(frozen=True)
class Template:
    """A layout family's fixed grid: band fractions plus the fields between them.

    `fields` maps a field name to a pair of band *indices*; the field occupies the
    space between those two template bands. Indices (not raw fractions) are what
    registration resolves against the page, so a field's edges follow the ruling
    this page actually has.
    """

    template_id: str
    layout_family: str
    band_fracs: tuple[float, ...]
    fields: tuple[tuple[str, int, int], ...]
    tolerance_frac: float
    min_bands_matched: int
    min_explained_frac: float
    min_columns: int
    expected_columns: int
    provenance: dict

    @classmethod
    def from_dict(cls, d: dict) -> "Template":
        m = d.get("match", {})
        return cls(
            template_id=d["template_id"],
            layout_family=d["layout_family"],
            band_fracs=tuple(d["band_fracs"]),
            fields=tuple((f["name"], f["band"][0], f["band"][1]) for f in d.get("fields", [])),
            tolerance_frac=m.get("tolerance_frac", 0.015),
            min_bands_matched=m.get("min_bands_matched", len(d["band_fracs"]) - 1),
            min_explained_frac=m.get("min_explained_frac", 0.8),
            min_columns=m.get("min_columns", 2),
            expected_columns=d.get("columns", {}).get("expected", 0),
            provenance=d.get("provenance", {}),
        )


@dataclass(frozen=True)
class Registration:
    """The result of fitting one page panel to one template.

    `band_ys` is per *template* band: the y this page actually rules there, or the
    interpolated fallback when the ruling was not detected (its index then appears
    in `unmatched_bands`, and every cell touching it is suspect).
    """

    template_id: str
    grid: Grid
    band_ys: tuple[float, ...]
    unmatched_bands: tuple[int, ...]
    mean_residual_frac: float
    explained_frac: float

    @property
    def matched(self) -> int:
        return len(self.band_ys) - len(self.unmatched_bands)

    @property
    def is_clean(self) -> bool:
        return not self.unmatched_bands


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

def find_panels(gray: np.ndarray) -> list[Panel]:
    """Locate page panels (bright) on the dark film border, right-hand page first.

    The two pages of a spread usually touch, so contour splitting is unreliable
    (Spike C lesson 3); find the bright region, then cut it at the darkest column
    near the middle - the gutter shadow.
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
    if mid1 <= mid0:
        return [Panel(x, y, cw, ch)]
    gutter = mid0 + int(np.argmin(col_mean[mid0:mid1]))
    return [Panel(x + gutter, y, cw - gutter, ch), Panel(x, y, gutter, ch)]


def _ruling_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Long horizontal and vertical rulings.

    Spike C lesson 2: close along the line direction first, or 1-px breaks in the
    thin interior rulings survive into the long opening and the line is lost.
    """
    ph, pw = binary.shape
    h_healed = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    v_healed = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    horiz = cv2.morphologyEx(
        h_healed, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(pw // 14, 25), 1)))
    vert = cv2.morphologyEx(
        v_healed, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(ph // 14, 25))))
    return horiz, vert


def _deskew_angle(horiz: np.ndarray) -> float:
    """Dominant angle of the long horizontal rulings, in degrees."""
    lines = cv2.HoughLinesP(horiz, 1, np.pi / 720, threshold=200,
                            minLineLength=horiz.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        if x2 != x1:
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if abs(a) < 5:
                angles.append(a)
    return float(np.median(angles)) if angles else 0.0


def _profile_lines(mask: np.ndarray, axis: int, min_run_frac: float = 0.30,
                   gap: int = 4) -> list[int]:
    """Cluster projection-profile peaks into single line coordinates."""
    length = mask.shape[1 - axis]
    prof = (mask > 0).sum(axis=1 - axis)
    hits = np.where(prof > min_run_frac * length)[0]
    lines: list[int] = []
    run: list[int] = []
    for v in hits:
        if run and v - run[-1] > gap:
            lines.append(int(np.mean(run)))
            run = []
        run.append(int(v))
    if run:
        lines.append(int(np.mean(run)))
    return lines


def _table_columns(vlines: list[int], panel_w: int) -> tuple[list[int], list[int]]:
    """Officer-column rulings spanning the table, with missing ones filled in.

    The officer grid has a strongly regular pitch, and that regularity - not the
    frame - is what identifies the table. Page and film borders survive ruling
    extraction but sit at the panel's extreme edges and break the pitch, so they
    are dropped; the longest run of rulings on a consistent pitch is the table.

    Thin interior rulings drop out on degraded panels, leaving a gap of two or
    three pitches. Left alone that would merge three officers into one crop, so
    gaps at a near-integer multiple of the pitch are filled at even spacing.
    Interpolating a ruling whose position the fixed grid already determines is
    registration, not per-page adaptation (commitment 3); the filled positions
    are returned separately so their cells can be flagged.

    Returns (columns, interpolated) - both lists of x, `interpolated` a subset.
    """
    inner = [x for x in vlines if EDGE_LO * panel_w <= x <= EDGE_HI * panel_w]
    if len(inner) < 3:
        return inner, []

    gaps = np.diff(inner)
    rough = float(np.median(gaps))
    core = [g for g in gaps if 0.6 * rough <= g <= 1.4 * rough]
    pitch = float(np.median(core)) if core else rough
    if pitch <= 0:
        return inner, []

    regular = [
        1 <= round(g / pitch) <= MAX_PITCH_MULTIPLE
        and abs(g / pitch - round(g / pitch)) <= PITCH_TOL
        for g in gaps
    ]
    # longest consecutive run of regular gaps
    best_len = best_i = best_j = 0
    i = 0
    while i < len(regular):
        if regular[i]:
            j = i
            while j < len(regular) and regular[j]:
                j += 1
            if j - i > best_len:
                best_len, best_i, best_j = j - i, i, j
            i = j
        else:
            i += 1
    if not best_len:
        return inner, []
    run = inner[best_i:best_j + 1]

    columns: list[int] = [run[0]]
    interpolated: list[int] = []
    for a, b in zip(run, run[1:]):
        steps = max(int(round((b - a) / pitch)), 1)
        for k in range(1, steps):
            x = int(round(a + (b - a) * k / steps))
            columns.append(x)
            interpolated.append(x)
        columns.append(b)
    return columns, interpolated


def detect_grid(panel_gray: np.ndarray, panel: Panel) -> Grid | None:
    """Detect the ruling grid on one already-cropped panel.

    `panel_gray` is the panel at detection scale; `panel` describes where that
    panel sits in the original scan, so the result can be mapped back. Returns
    None when the panel has no table-like ruling structure at all.
    """
    _, binv = cv2.threshold(panel_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horiz, _ = _ruling_masks(binv)
    angle = _deskew_angle(horiz)
    if abs(angle) > 0.05:
        ph, pw = panel_gray.shape
        rot = cv2.getRotationMatrix2D((pw / 2, ph / 2), angle, 1.0)
        panel_gray = cv2.warpAffine(panel_gray, rot, (pw, ph),
                                    flags=cv2.INTER_LINEAR, borderValue=255)
        _, binv = cv2.threshold(panel_gray, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        horiz, _ = _ruling_masks(binv)
    _, vert = _ruling_masks(binv)

    hlines = _profile_lines(horiz, axis=0)
    vlines = _profile_lines(vert, axis=1)
    if len(hlines) < 2 or len(vlines) < 2:
        return None
    columns, interpolated = _table_columns(vlines, panel_gray.shape[1])
    if len(columns) < 2:
        return None
    return Grid(
        panel=panel,
        skew_deg=round(angle, 3),
        table=(columns[0], hlines[0], columns[-1], hlines[-1]),
        band_ys=tuple(hlines),
        column_xs=tuple(columns),
        interpolated_columns=tuple(interpolated),
    )


def detect_page(image: np.ndarray, scale: float = SCALE) -> list[Grid]:
    """Detect grids for every page panel in a full scan image (reading order)."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    grids = []
    for p in find_panels(small):
        g = detect_grid(small[p.y:p.y + p.h, p.x:p.x + p.w], p)
        if g is not None:
            grids.append(g)
    return grids


# --------------------------------------------------------------------------
# template library
# --------------------------------------------------------------------------

def load_template(path: str | Path) -> Template:
    return Template.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_library(directory: str | Path) -> list[Template]:
    """Load every template artifact in a directory, sorted by id for determinism."""
    return sorted((load_template(p) for p in Path(directory).glob("*.json")),
                  key=lambda t: t.template_id)


# --------------------------------------------------------------------------
# registration + classification
# --------------------------------------------------------------------------

def register(grid: Grid, template: Template) -> Registration:
    """Fit a detected grid to a template.

    Each template band takes the position of the nearest detected ruling within
    tolerance. Bands with no ruling in range keep their nominal fraction and are
    flagged - a page missing bands is reported, never re-fitted (commitment 3).
    """
    top, height = grid.table[1], grid.table_height
    detected = grid.band_fracs
    band_ys: list[float] = []
    unmatched: list[int] = []
    residuals: list[float] = []
    for i, t in enumerate(template.band_fracs):
        if detected:
            nearest = min(detected, key=lambda b: abs(b - t))
            if abs(nearest - t) <= template.tolerance_frac:
                band_ys.append(top + nearest * height)
                residuals.append(abs(nearest - t))
                continue
        unmatched.append(i)
        band_ys.append(top + t * height)

    # Reverse direction: how much of what this page actually rules does the
    # template account for? A degraded panel can carry so many spurious rulings
    # that one lands near every template band by chance and matches perfectly in
    # the forward direction alone. Observed on a real page (frame 700 panel 1:
    # 28 rulings, 12/12 forward matches, 1 officer column).
    explained = sum(
        1 for b in detected
        if min(abs(b - t) for t in template.band_fracs) <= template.tolerance_frac
    )
    return Registration(
        template_id=template.template_id,
        grid=grid,
        band_ys=tuple(band_ys),
        unmatched_bands=tuple(unmatched),
        mean_residual_frac=round(float(np.mean(residuals)), 5) if residuals else 1.0,
        explained_frac=round(explained / len(detected), 4) if detected else 0.0,
    )


def classify(grid: Grid, templates: list[Template]) -> Registration | None:
    """Pick the template this panel belongs to, or None if it belongs to none.

    Returning None is a feature: Spike C found index (索引) pages match only 6-9
    of 11 bands with the wrong signature, and that wide margin is exactly the
    page-classification signal. Non-roster pages must fall out here rather than
    being force-fitted to a roster grid.

    Three gates, all tunable per template artifact:
      - `min_bands_matched`  - the template's structure is present;
      - `min_explained_frac` - and the page has little structure the template
        does not account for (catches over-detected/degraded panels);
      - `min_columns`        - and officer strips can actually be cut. Without
        interior vertical rulings there is no per-officer geometry to give the
        workstation, so rejecting is the honest outcome.
    """
    best: Registration | None = None
    for t in templates:
        reg = register(grid, t)
        if reg.matched < t.min_bands_matched:
            continue
        if reg.explained_frac < t.min_explained_frac:
            continue
        if grid.n_officer_columns < t.min_columns:
            continue
        if best is None or (reg.matched, -reg.mean_residual_frac) > \
                (best.matched, -best.mean_residual_frac):
            best = reg
    return best


# --------------------------------------------------------------------------
# cell geometry - the workstation's actual product
# --------------------------------------------------------------------------

def _to_scan(grid: Grid, x: float, y: float, scale: float) -> tuple[float, float]:
    """Map a deskewed-panel point back to original scan pixels."""
    # undo deskew (rotation was about the panel centre, positive angle CCW in cv2)
    cx, cy = grid.panel.w / 2, grid.panel.h / 2
    a = math.radians(-grid.skew_deg)
    dx, dy = x - cx, y - cy
    rx = cx + dx * math.cos(a) - dy * math.sin(a)
    ry = cy + dx * math.sin(a) + dy * math.cos(a)
    # undo panel offset, then detection downscale
    return (grid.panel.x + rx) / scale, (grid.panel.y + ry) / scale


def _column_edges(reg: Registration) -> list[int]:
    """Officer-column boundaries, right to left (reading order)."""
    x0, x1 = reg.grid.table[0], reg.grid.table[2]
    interior = [x for x in reg.grid.column_xs if x0 < x < x1]
    return [x1] + sorted(interior, reverse=True) + [x0]


def _rect_to_scan(grid: Grid, x0: float, y0: float, x1: float, y1: float,
                  scale: float) -> tuple[int, int, int, int]:
    """Axis-aligned bound, in scan pixels, of a deskewed-frame rectangle."""
    corners = [_to_scan(grid, cx, cy, scale)
               for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    left, top = int(math.floor(min(xs))), int(math.floor(min(ys)))
    right, bottom = int(math.ceil(max(xs))), int(math.ceil(max(ys)))
    return left, top, right - left, bottom - top


def column_bbox(reg: Registration, column: int,
                scale: float = SCALE) -> tuple[int, int, int, int]:
    """Full-height strip for one officer, in original scan pixels.

    This is the whole record - the rectangle `roster_cell.crop_bbox` stores and
    `roster_cell.crop_url` points at. `column` is 0-based in reading order
    (0 = rightmost officer).
    """
    edges = _column_edges(reg)
    if not 0 <= column < len(edges) - 1:
        raise IndexError(f"column {column} out of range (0..{len(edges) - 2})")
    x1, x0 = edges[column], edges[column + 1]
    return _rect_to_scan(reg.grid, x0, reg.band_ys[0], x1, reg.band_ys[-1], scale)


def cell_bbox(reg: Registration, template: Template, field: str, column: int,
              scale: float = SCALE) -> tuple[int, int, int, int]:
    """Rectangle for one field of one officer column, in original scan pixels.

    `column` is 0-based in reading order (0 = rightmost officer). The returned
    (x, y, w, h) is ready for `iiif_client.region_url`. Because deskew is undone
    by rotating the corners back, the rectangle is the axis-aligned bound of a
    slightly rotated cell and over-crops marginally - see the module docstring.
    """
    spans = {name: (a, b) for name, a, b in template.fields}
    if field not in spans:
        raise KeyError(f"{field!r} not in template {template.template_id}")
    a, b = spans[field]
    y0, y1 = sorted((reg.band_ys[a], reg.band_ys[b]))
    edges = _column_edges(reg)
    if not 0 <= column < len(edges) - 1:
        raise IndexError(f"column {column} out of range (0..{len(edges) - 2})")
    x1, x0 = edges[column], edges[column + 1]
    return _rect_to_scan(reg.grid, x0, y0, x1, y1, scale)


def cells(reg: Registration, template: Template, scale: float = SCALE):
    """Yield (column, field, bbox, suspect) for every cell on the page.

    `suspect` is True when any edge of the cell was inferred rather than seen -
    either a bounding band failed to register, or a bounding column ruling was
    interpolated across a gap. The workstation marks these for mandatory human
    attention rather than presenting a confidently-wrong crop.
    """
    n_cols = reg.grid.n_officer_columns
    unmatched = set(reg.unmatched_bands)
    interpolated = set(reg.grid.interpolated_columns)
    edges = _column_edges(reg)
    for column in range(n_cols):
        shaky_col = (edges[column] in interpolated
                     or edges[column + 1] in interpolated)
        for name, a, b in template.fields:
            yield (column, name, cell_bbox(reg, template, name, column, scale),
                   shaky_col or a in unmatched or b in unmatched)
