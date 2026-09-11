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

# Scans come in two kinds, and a leaf has to be found differently on each.
# Microfilm-derived scans (the Shōwa volumes, pids 1449426 and 1449474) show
# bright pages on a black film border. Camera scans of the bound book (the
# Taishō volumes, pids 930894 and 1908494) show grey or tan paper on a light
# backdrop, with the cover, the edges of the page block and a black binding
# strip in frame - paper and backdrop are the same brightness, so there is no
# bright region to find. Measured at SCALE over every cached frame (10 Sep
# 2026): the largest bright region covers 0.34-0.73 of a film scan and 1.00 of
# every camera scan.
FILM, BACKDROP = "film", "backdrop"
BACKDROP_REGION_FRAC = 0.9
# Rulings on the camera scans are thin and grey, and the light falls unevenly
# across a curved page: one Otsu threshold per leaf dropped most interior
# rulings of pid 1908494 (1 of 8 officer columns found on frame 100). A local
# threshold keeps them - 8 of 8 on both leaves. Block and offset at SCALE.
ADAPTIVE_BLOCK, ADAPTIVE_C = 31, 10
# On a camera scan the two tables' frames nearly meet at the gutter (25-70 px
# apart at SCALE), so a cut at the gutter can slice a leaf's own frame off. Each
# leaf reaches this fraction of the scan width past the cut; the neighbour's
# frame that comes with it sits off the officer-column pitch and is not taken.
GUTTER_OVERLAP = 0.05
# Horizontal rulings further than this (of panel height) outside the vertical
# reach of the officer-column rulings are not table - see _within_column_rulings.
RULING_EXTENT_TOL = 0.015
# Half-width, px at SCALE, of the window a column ruling's extent is read in.
# Narrow on purpose: the 1923 tables sit ~5 px from the gutter shadow, and a
# 15-px window took that full-height dark strip for the frame's own extent and
# trimmed the frame off as a page edge (pid 930894 frame 100). The price is a
# leaf whose deskew came out a degree wrong (pid 930894 frame 24, right leaf):
# its rulings drift out of the window, and the leaf is reported as missing.
RULING_EXTENT_HALF = 3
# A ruling the deskew left tilted is detected twice, a few px apart, and enough
# doubles wreck the pitch estimate: pid 930894 frame 27's left leaf took three
# lines 45 px apart at the gutter for the officer grid. Vertical lines closer
# than this fraction of panel width are one ruling. The doubles sit 8-10 px
# apart on a 1215-px leaf; 0.02 was too coarse - it welded a table frame to the
# paper edge 24 px away and lost a 尉官 column whose pitch is only 60 px.
# Camera scans only; the film path is left as measured.
MIN_COLUMN_SEP = 0.01
# A camera scan's paper, cover and page-block edges are long vertical lines
# too, and one that lands on the pitch outside the table joins the officer
# grid as a phantom column (pid 930894 frame 150, one pitch out on both
# leaves; pid 1908494 frame 165 left leaf, four pitches out with three columns
# interpolated to reach it). Table columns share the table's vertical extent;
# a line at the leaf's outer end that overshoots it by more than this fraction
# of panel height, or spans less than SHORT_EDGE_FRAC of it, is not a column -
# see _trim_edge_columns.
COLUMN_EXTENT_TOL = 0.03
SHORT_EDGE_FRAC = 0.8
# The gutter-side frame of the 1923 tables stands ~5 px from the binding
# shadow and the local threshold loses it there; the officer strip beside the
# gutter then vanishes without a word (pid 930894 frames 51 and 328, the strip
# of 列次 403 / 1854). If the officer run stops a pitch short of a vertical
# line seen within this fraction of a pitch of where the frame would be, the
# frame is placed at the pitch and flagged as interpolated - an inferred edge
# the reader is told about, like any other interpolated column.
GUTTER_FRAME_TOL = 0.35
# ...and only where a frame can stand: past the gutter overlap the leaf was
# cut with, plus this fraction of a pitch. The binding shadow is itself a line
# on the pitch when the frame was found, and without the margin it put a
# ninth strip on eight-strip pages (pid 930894 frame 100; pid 1908494 frame
# 100, whose overlap is 177 px on a wider scan). The recovered 1923 frames
# sit 130 px in on a 115-px overlap.
GUTTER_FRAME_BUFFER = 0.15
# Rows a horizontal ruling is smeared over before profiling, camera scans only
# (see _table_rulings): 5 px covers ~0.25 deg over a 1250-px table.
TABLE_RULING_SMEAR = 5
TABLE_RULING_MIN_FRAC = 0.5
COLUMN_RULING_SMEAR = 5


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
    required_bands: tuple[int, ...] = ()
    # Band intervals (pairs of band indices) inside which a detected ruling is
    # not counted against the page: cells of dense small type whose rows read
    # as lines. Declared by the layout, never inferred from the page.
    text_intervals: tuple[tuple[int, int], ...] = ()

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
            required_bands=tuple(m.get("required_bands", ())),
            text_intervals=tuple((a, b) for a, b in m.get("text_intervals", ())),
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

def _bright_region(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """The largest bright region of a scan (x, y, w, h), or None."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    regions = [cv2.boundingRect(c) for c in contours]
    regions = [r for r in regions if r[2] * r[3] > MIN_PANEL_AREA * w * h]
    if not regions:
        return None
    return max(regions, key=lambda r: r[2] * r[3])


def scan_kind(gray: np.ndarray) -> str | None:
    """FILM (pages on a dark border), BACKDROP (a camera scan of the book), or
    None when the scan has no bright region at all."""
    region = _bright_region(gray)
    if region is None:
        return None
    h, w = gray.shape
    return BACKDROP if region[2] * region[3] >= BACKDROP_REGION_FRAC * w * h else FILM


def find_panels(gray: np.ndarray) -> list[Panel]:
    """Locate the page panels of a scan, right-hand page first.

    The two pages of a spread usually touch, so contour splitting is unreliable
    (Spike C lesson 3); find the bright region, then cut it at the darkest column
    near the middle - the gutter shadow, or on a camera scan the binding strip.

    On a camera scan the bright region is the whole image (BACKDROP_REGION_FRAC),
    so each leaf also carries backdrop, cover and page-block edges. Nothing about
    the paper separates it from the backdrop, so the leaf is not trimmed here:
    `detect_grid` keeps only rulings inside the table's own column rulings. What
    the cut does need is overlap (GUTTER_OVERLAP) - without it the frame ruling
    beside the gutter falls outside EDGE_HI and each leaf loses an officer.
    """
    region = _bright_region(gray)
    if region is None:
        return []
    h, w = gray.shape
    x, y, cw, ch = region
    col_mean = gray[y:y + ch, x:x + cw].mean(axis=0)
    mid0, mid1 = int(cw * 0.35), int(cw * 0.65)
    if mid1 <= mid0:
        return [Panel(x, y, cw, ch)]
    gutter = mid0 + int(np.argmin(col_mean[mid0:mid1]))
    if cw * ch < BACKDROP_REGION_FRAC * w * h:
        return [Panel(x + gutter, y, cw - gutter, ch), Panel(x, y, gutter, ch)]
    ext = int(GUTTER_OVERLAP * cw)
    return [Panel(x + gutter - ext, y, cw - gutter + ext, ch),
            Panel(x, y, gutter + ext, ch)]


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


def _skew_score(binary: np.ndarray, angle: float) -> tuple[float, float]:
    """How crisply the ink stacks into rows and into columns at this rotation.

    The row-sum profile of a correctly deskewed table is a comb: near-empty
    between the rulings, spiking on them. Summing the squared first difference
    of that profile rewards exactly that shape.

    Both axes are scored because both matter and they are not redundant. Scoring
    rows alone finds an angle that is right to a tenth of a degree for the bands
    and wrong enough for the officer rulings to lose one - which is how frame
    100 of pid 1449426 came back with nine officers on a page that has ten. A
    ruled table is a grid; the true angle sharpens the whole grid.
    """
    if angle:
        h, w = binary.shape
        rot = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        binary = cv2.warpAffine(binary, rot, (w, h),
                                flags=cv2.INTER_NEAREST, borderValue=0)
    ink = binary > 0
    rows = np.square(np.diff(ink.sum(axis=1).astype(np.float64))).sum()
    cols = np.square(np.diff(ink.sum(axis=0).astype(np.float64))).sum()
    return float(rows), float(cols)


def _combine(scores: list[tuple[float, float]]) -> list[float]:
    """Row and column scores are different sizes; judge each against its own best."""
    best_rows = max((s[0] for s in scores), default=0.0) or 1.0
    best_cols = max((s[1] for s in scores), default=0.0) or 1.0
    return [s[0] / best_rows + s[1] / best_cols for s in scores]


def _deskew_angle(binary: np.ndarray, *, limit: float = 2.5,
                  coarse: float = 0.25, fine: float = 0.05) -> float:
    """Skew of a panel in degrees, by projection-profile search.

    This used to be a Hough fit over the extracted horizontal rulings, and it
    had a circular dependency that cost half of every spread: extracting the
    rulings runs a long horizontal opening, which a tilted panel has already
    fragmented, so the fit was made against the wreckage of the thing it was
    supposed to straighten. It happened to converge on the right-hand page of
    pid 1449426 frame 60 (+0.4 deg, 11 bands found) and to fail on the left-hand
    page of the same scan, returning +0.24 deg against a true -1.0 deg and
    finding 4 bands out of 12. The two leaves of a bound volume tilt
    independently, so one panel registering says nothing about the other.

    Scoring candidate rotations of the *binary* image breaks the circularity:
    nothing has to be extracted before the angle is known. Coarse sweep, then a
    refinement pass around the winner.
    """
    h, w = binary.shape
    if w > 700:  # the profile is a coarse statistic; full resolution is waste
        binary = cv2.resize(binary, (700, max(1, int(h * 700 / w))),
                            interpolation=cv2.INTER_NEAREST)

    def best_of(angles):
        combined = _combine([_skew_score(binary, a) for a in angles])
        return angles[int(np.argmax(combined))]

    grid = [float(a) for a in np.arange(-limit, limit + coarse / 2, coarse)]
    around = best_of(grid)
    refined = [float(a) for a in
               np.arange(around - coarse, around + coarse + fine / 2, fine)]
    return round(best_of(refined), 3)


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


def _merge_close(lines: list[int], min_sep: float) -> list[int]:
    """Collapse lines nearer than `min_sep` into one at their mean."""
    merged: list[list[int]] = []
    for x in sorted(lines):
        if merged and x - merged[-1][-1] < min_sep:
            merged[-1].append(x)
        else:
            merged.append([x])
    return [int(round(sum(g) / len(g))) for g in merged]


def _column_extents(vert: np.ndarray, columns: list[int]) -> dict[int, tuple[int, int]]:
    """First and last row each column ruling occupies (RULING_EXTENT_HALF)."""
    half = RULING_EXTENT_HALF
    out = {}
    for x in columns:
        rows = np.flatnonzero(vert[:, max(0, x - half):x + half + 1].any(axis=1))
        if len(rows):
            out[x] = (int(rows[0]), int(rows[-1]))
    return out


def _agreed(values: list[int], tol: float, *, from_top: bool) -> float:
    """The outermost position at least two column rulings share (within tol).

    The median start of the column rulings put a table's top 70 px too low on
    a leaf whose interior rulings are faint near the top (pid 930894 frame 250,
    left leaf) - the true top rule was then discarded and the frame column
    trimmed as an edge. A lone outlier (a gutter-side frame whose window
    catches the binding strip, a page edge) never sets the extent either: two
    rulings must begin, or end, together. Falls back to the largest cluster.
    """
    ordered = sorted(values) if from_top else sorted(values, reverse=True)
    clusters: list[list[int]] = []
    for v in ordered:
        if clusters and abs(v - clusters[-1][-1]) <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    for c in clusters:
        if len(c) >= 2:
            return float(np.median(c))
    return float(np.median(max(clusters, key=len)))


def _table_extent(extents: dict[int, tuple[int, int]], tol: float) -> tuple[float, float]:
    firsts = [e[0] for e in extents.values()]
    lasts = [e[1] for e in extents.values()]
    return _agreed(firsts, tol, from_top=True), _agreed(lasts, tol, from_top=False)


def _trim_edge_columns(columns: list[int], interpolated: list[int],
                       vert: np.ndarray, outer: str) -> tuple[list[int], list[int]]:
    """Drop lines that joined the officer grid at the leaf's outer end.

    `outer` is "left" or "right": the side of the leaf away from the gutter,
    where the paper edge, the page block, the cover and the margin's own marks
    run as long vertical lines. Only that end is examined, and by two tests:

    - an extent that overshoots the table's at either end by more than
      COLUMN_EXTENT_TOL - the paper edge (pid 930894 frame 150: 128-1425
      against a table of 226-1364, one pitch outside the last strip; checked
      against the page, which has thirteen strips, not fourteen);
    - a line spanning well under the table's height (SHORT_EDGE_FRAC) - a
      crease, a margin mark. Interior rulings may be faint and short; the
      outer end is the only place a short line is dropped, and only until the
      first full-height one;
    - a column reached only across interpolated ones (below).

    The gutter side is never trimmed: its frame column reads over-long too,
    because the binding shadow sits within a few px of it on the 1923 volume.
    """
    extents = _column_extents(vert, [x for x in columns if x not in interpolated])
    if len(extents) < 3:
        return columns, interpolated
    tol = COLUMN_EXTENT_TOL * vert.shape[0]
    top, bottom = _table_extent(extents, RULING_EXTENT_TOL * vert.shape[0])
    height = bottom - top

    def is_edge(x: int) -> bool:
        if x in interpolated:
            return True
        first, last = extents.get(x, (None, None))
        if first is None:
            return False
        if first < top - tol or last > bottom + tol:
            return True
        return (last - first) < SHORT_EDGE_FRAC * height

    kept = list(columns)
    if outer == "left":
        while len(kept) > 2 and is_edge(kept[0]):
            kept.pop(0)
        # An end column reached only across interpolated ones lies a whole
        # pitch or more from the nearest ruling actually seen: a page edge that
        # happened to sit on the pitch (pid 1908494 frame 165, left leaf, three
        # columns interpolated to reach it), not a frame whose neighbours all
        # faded at once.
        while len(kept) > 2 and kept[1] in interpolated:
            kept.pop(0)
            while len(kept) > 2 and kept[0] in interpolated:
                kept.pop(0)
    else:
        while len(kept) > 2 and is_edge(kept[-1]):
            kept.pop()
        while len(kept) > 2 and kept[-2] in interpolated:
            kept.pop()
            while len(kept) > 2 and kept[-1] in interpolated:
                kept.pop()
    return kept, [x for x in interpolated if x in kept]


def _table_rulings(horiz: np.ndarray, columns: list[int]) -> list[int]:
    """Horizontal rulings measured across the table's own width.

    `_profile_lines` asks for 30% of the panel width in one pixel row. A film
    panel is the page, so that is a third of the table; a camera-scan panel is
    half the scan, and the 1926 table fills two thirds of it - a residual
    quarter-degree of tilt then spreads a 1-px band rule over several rows,
    none of which holds enough, and the leaf comes back with its frame and
    nothing between (pid 1908494 frame 66, left leaf; 55% of that volume's
    roster frames lost a leaf this way). Once the columns are known the rulings
    are read inside the table's x-range, smeared a few rows so a slight tilt
    still stacks, and must cross half the table (TABLE_RULING_MIN_FRAC).

    Half, and not more: a row of tightly set small type - the 明治/同 heads of
    the date lines, the 少尉/中尉 tags under them - is welded into a bar by the
    closing step and reaches 0.5-0.92 of the table width, where a printed ruling
    on the wide pages reaches 0.96-1.00; but the narrow pages' rulings read far
    fainter, and at 0.8 or above most of them fail (sample of 41 frames: 12
    with both leaves against 26 at 0.5). The text bars are left to the
    template's explained-fraction gate.
    """
    x0, x1 = columns[0], columns[-1]
    band = cv2.dilate(horiz[:, x0:x1 + 1],
                      cv2.getStructuringElement(cv2.MORPH_RECT, (1, TABLE_RULING_SMEAR)))
    return _profile_lines(band, axis=0, min_run_frac=TABLE_RULING_MIN_FRAC)


def _recover_gutter_frame(columns: list[int], interpolated: list[int],
                          vlines: list[int], outer: str, panel_w: int,
                          gutter_overlap: float) -> tuple[list[int], list[int]]:
    """Put back a gutter-side frame the run stopped short of (GUTTER_FRAME_TOL).

    Evidence, not invention: a vertical line must have been seen within the
    tolerance of the pitch position (the shadow-merged remnant of the frame),
    the position must lie clear of the gutter zone (`gutter_overlap` plus
    GUTTER_FRAME_BUFFER), and the column goes into `interpolated`, so every
    cell it bounds is suspect.
    """
    if len(columns) < 3:
        return columns, interpolated
    real = [x for x in columns if x not in interpolated]
    if len(real) < 2:
        return columns, interpolated
    pitch = float(np.median(np.diff(real)))
    margin = gutter_overlap + GUTTER_FRAME_BUFFER * pitch
    if outer == "right":                       # gutter is on the left
        want = columns[0] - pitch
        near = [v for v in vlines if v < columns[0] and abs(v - want) <= GUTTER_FRAME_TOL * pitch]
        if not near or want < margin:
            return columns, interpolated
        x = int(round(want))
        return [x] + columns, interpolated + [x]
    want = columns[-1] + pitch
    near = [v for v in vlines if v > columns[-1] and abs(v - want) <= GUTTER_FRAME_TOL * pitch]
    if not near or want > panel_w - margin:
        return columns, interpolated
    x = int(round(want))
    return columns + [x], interpolated + [x]


def _within_column_rulings(hlines: list[int], vert: np.ndarray, columns: list[int],
                           interpolated: list[int]) -> list[int]:
    """The horizontal rulings that lie within the officer-column rulings' reach.

    A camera-scan leaf carries more than its table: the page edge, the cover and
    the binding strip rule long horizontal lines above and below it, and the
    first and last detected line are taken as the table's top and bottom. The
    officer columns are ruled frame to frame, so their vertical extent is the
    table's, and a line outside it is not a band - 1 to 9 of them per leaf on the
    Taishō samples. Film scans never pass through here: their panels are the
    page alone, and the Shōwa templates were derived without this filter.
    """
    extents = _column_extents(vert, [x for x in columns if x not in interpolated])
    if not extents:
        return []
    tol = RULING_EXTENT_TOL * vert.shape[0]
    top, bottom = _table_extent(extents, tol)
    return [y for y in hlines if top - tol <= y <= bottom + tol]


def _binarize(gray: np.ndarray, kind: str) -> np.ndarray:
    """Ink as white. One Otsu threshold for film scans; a local threshold for
    camera scans, whose rulings are faint and unevenly lit (ADAPTIVE_BLOCK)."""
    if kind == BACKDROP:
        return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY_INV, ADAPTIVE_BLOCK, ADAPTIVE_C)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def detect_grid(panel_gray: np.ndarray, panel: Panel, *, kind: str = FILM,
                outer: str = "right", gutter_overlap: float = 0.0) -> Grid | None:
    """Detect the ruling grid on one already-cropped panel.

    `panel_gray` is the panel at detection scale; `panel` describes where that
    panel sits in the original scan, so the result can be mapped back; `kind` is
    the scan's `scan_kind`, and on a camera scan `outer` names the side of the
    leaf away from the gutter ("right" for the right-hand page) and
    `gutter_overlap` how far, in panel px, the leaf reaches past the gutter cut.
    Returns None when the panel has no table-like ruling structure at all.
    """
    binv = _binarize(panel_gray, kind)
    angle = _deskew_angle(binv)
    if abs(angle) > 0.05:
        ph, pw = panel_gray.shape
        rot = cv2.getRotationMatrix2D((pw / 2, ph / 2), angle, 1.0)
        panel_gray = cv2.warpAffine(panel_gray, rot, (pw, ph),
                                    flags=cv2.INTER_LINEAR, borderValue=255)
        binv = _binarize(panel_gray, kind)
    horiz, vert = _ruling_masks(binv)

    hlines = _profile_lines(horiz, axis=0)
    if kind == BACKDROP:
        # A column ruling a fraction of a degree off drifts across several
        # pixel columns over a camera-scan leaf and no single one holds 30% of
        # the panel height. Smear sideways before profiling; the doubles a
        # tilt makes are merged below. (Not a cure for a bowed page: pid
        # 1908494 frame 74's left leaf spreads each column over ~20 px near
        # the spine and is still lost - reported as a missing leaf.)
        smeared = cv2.dilate(vert, cv2.getStructuringElement(
            cv2.MORPH_RECT, (COLUMN_RULING_SMEAR, 1)))
        vlines = _merge_close(_profile_lines(smeared, axis=1),
                              MIN_COLUMN_SEP * panel_gray.shape[1])
    else:
        vlines = _profile_lines(vert, axis=1)
    if len(hlines) < 2 or len(vlines) < 2:
        return None
    columns, interpolated = _table_columns(vlines, panel_gray.shape[1])
    if len(columns) < 2:
        return None
    if kind == BACKDROP:
        columns, interpolated = _trim_edge_columns(columns, interpolated, vert, outer)
        if len(columns) < 2:
            return None
        columns, interpolated = _recover_gutter_frame(columns, interpolated, vlines, outer,
                                                      panel_gray.shape[1], gutter_overlap)
        hlines = _table_rulings(horiz, columns)
        hlines = _within_column_rulings(hlines, vert, columns, interpolated)
        if len(hlines) < 2:
            return None
    return Grid(
        panel=panel,
        skew_deg=round(angle, 3),
        table=(columns[0], hlines[0], columns[-1], hlines[-1]),
        band_ys=tuple(hlines),
        column_xs=tuple(columns),
        interpolated_columns=tuple(interpolated),
    )


def detect_leaves(image: np.ndarray, scale: float = SCALE) -> list[Grid | None]:
    """One entry per page panel of a scan, in reading order: its grid, or None
    when the leaf has no table-like ruling structure.

    The None matters. A leaf that yields no grid is still a leaf - a blank
    page at a section's end, or a page whose rulings did not come through -
    and dropping it from the list made the other leaf look like the whole
    scan: pid 1908494 frame 74 carries 16 officers and reported 8, complete.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    kind = scan_kind(small)
    overlap = GUTTER_OVERLAP * small.shape[1] if kind == BACKDROP else 0.0
    return [detect_grid(small[p.y:p.y + p.h, p.x:p.x + p.w], p, kind=kind,
                        outer="right" if i == 0 else "left", gutter_overlap=overlap)
            for i, p in enumerate(find_panels(small))]


def detect_page(image: np.ndarray, scale: float = SCALE) -> list[Grid]:
    """Detect grids for every page panel in a full scan image (reading order),
    leaves without a grid left out - see `detect_leaves` for the full picture."""
    return [g for g in detect_leaves(image, scale) if g is not None]


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
    #
    # A ruling inside a declared text interval is neither for nor against: the
    # Taishō appointment cell holds four lines of small type whose rows weld
    # into bars, and a 将官 leaf carried four of them - 7 of 7 bands matched,
    # 0.54 explained, refused (pid 930894 frames 14, 25, 71). The interval is
    # the template's statement about where its print is dense, so ignoring
    # what is found there is still top-down.
    def in_text(b: float) -> bool:
        tol = template.tolerance_frac
        return any(template.band_fracs[a] + tol < b < template.band_fracs[z] - tol
                   for a, z in template.text_intervals)

    considered = [b for b in detected if not in_text(b)]
    explained = sum(
        1 for b in considered
        if min(abs(b - t) for t in template.band_fracs) <= template.tolerance_frac
    )
    return Registration(
        template_id=template.template_id,
        grid=grid,
        band_ys=tuple(band_ys),
        unmatched_bands=tuple(unmatched),
        mean_residual_frac=round(float(np.mean(residuals)), 5) if residuals else 1.0,
        explained_frac=round(explained / len(considered), 4) if considered else 0.0,
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

    Plus one optional gate, `required_bands`: rulings whose absence means a
    different printed layout rather than a faint line. `min_bands_matched`
    forgives any one miss, and on the Taishō volumes that let a 各部 page - the
    same table with no 列次 row - match the combatant template 6 of 7 with
    everything explained, exactly like a real page that lost one thin ruling.
    Which band is missing is what tells them apart.
    """
    best: Registration | None = None
    for t in templates:
        reg = register(grid, t)
        if reg.matched < t.min_bands_matched:
            continue
        if any(b in reg.unmatched_bands for b in t.required_bands):
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
