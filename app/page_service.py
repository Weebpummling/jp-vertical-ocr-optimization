"""Layer 3 - what the workstation needs to know about a page.

Turns a scan into placed officer records: for each officer strip on the page,
the rectangle of every field, as both pixel coordinates and a re-checkable IIIF
region URL. This is the contract the three-pane UI consumes - the zoomable pane
centres on a cell, the entry form binds to its fields, and the candidate panel
hangs machine proposals off the same cell ids.

No FastAPI here. The HTTP layer (`app/api.py`) is deliberately thin so this
logic can be tested without a server, a network, or a browser.

Two rules from the standing commitments shape the shape of the output:

- **Nothing here authors a value.** The service places rectangles and says how
  much it trusts their placement. Field *contents* are for a human to enter and
  for Layer 4 to propose against.
- **Uncertainty travels with the geometry.** A cell whose edge was inferred
  rather than seen carries `suspect`, and a page that will not register is
  refused outright rather than served with plausible-looking rectangles.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field as dc_field, replace
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reading"))
import registration as R  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class PageNotRegistrable(Exception):
    """The page does not fit any known template.

    Not an error condition so much as a routing decision: index pages, section
    dividers and badly degraded panels all land here, and the honest response is
    to send the page to a human rather than invent a grid for it.
    """


@dataclass(frozen=True)
class Cell:
    """One field of one officer."""

    field: str
    bbox: tuple[int, int, int, int]
    suspect: bool
    confirmed_label: bool
    crop_url: str | None = None

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "bbox": list(self.bbox),
            "suspect": self.suspect,
            "confirmed_label": self.confirmed_label,
            "crop_url": self.crop_url,
        }


@dataclass(frozen=True)
class Officer:
    """One officer record - a column strip plus its fields.

    `index` is the officer's position in the reading order of the whole scan,
    which is what `roster_cell.row_index` stores. `panel` and `column` say where
    that lands physically, for crops and for saying "third from the right on the
    left-hand leaf" to a human.
    """

    index: int
    bbox: tuple[int, int, int, int]
    cells: list[Cell]
    crop_url: str | None = None
    panel: int = 0
    column: int = 0

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "panel": self.panel,
            "column": self.column,
            "bbox": list(self.bbox),
            "crop_url": self.crop_url,
            "cells": [c.as_dict() for c in self.cells],
        }


@dataclass(frozen=True)
class RegisteredPage:
    """A page the workstation can serve."""

    pid: str
    frame: int
    panel: int
    template_id: str
    skew_deg: float
    bands_matched: int
    bands_total: int
    explained_frac: float
    officers: list[Officer] = dc_field(default_factory=list)
    panels_total: int = 1
    panels_registered: tuple[int, ...] = (0,)
    # Leaves that registered only on their second reading (registration.py,
    # "read a second time under a local threshold").
    panels_reread: tuple[int, ...] = ()

    @property
    def needs_review(self) -> bool:
        """True when any cell on the page had an edge inferred."""
        return any(c.suspect for o in self.officers for c in o.cells)

    @property
    def panels_missing(self) -> tuple[int, ...]:
        """Leaves of this scan that carry a table but matched no template.

        A reader must be told about these. A spread whose left leaf silently
        failed looks exactly like a spread that only ever had one leaf, and the
        page then reports itself complete at half its officers.
        """
        return tuple(i for i in range(self.panels_total)
                     if i not in self.panels_registered)

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "frame": self.frame,
            "panel": self.panel,
            "template_id": self.template_id,
            "skew_deg": self.skew_deg,
            "bands_matched": self.bands_matched,
            "bands_total": self.bands_total,
            "explained_frac": self.explained_frac,
            "needs_review": self.needs_review,
            "officer_count": len(self.officers),
            "panels_total": self.panels_total,
            "panels_registered": list(self.panels_registered),
            "panels_missing": list(self.panels_missing),
            "panels_reread": list(self.panels_reread),
            "officers": [o.as_dict() for o in self.officers],
        }


def _label_confirmation(templates: list[R.Template]) -> dict[str, dict[str, bool]]:
    """Which field labels are settled, per template, read from the artifacts.

    The UI shows an unconfirmed label differently: the rectangle is trustworthy
    but the name on it is still a reading decision (see
    docs/decision-roster-date-rows.md).
    """
    import json
    out: dict[str, dict[str, bool]] = {}
    for path in TEMPLATE_DIR.glob("*.json"):
        spec = json.loads(path.read_text(encoding="utf-8"))
        out[spec["template_id"]] = {
            f["name"]: bool(f.get("confirmed")) for f in spec.get("fields", [])
        }
    return out


def vocabularies(vocab_dir: Path | None = None) -> dict:
    """The frozen controlled vocabularies, shaped for autocomplete.

    Ranks carry `seniority_order` so the form can offer them in service order
    rather than alphabetically; `variants` are the printed forms that should
    resolve to the same code, which is what lets an annotator type what is on
    the page and get a normalized value. The variant table is deliberately
    *not* a fold-everything map - 齋/斉 stay distinct (see data/vocab/README.md).
    """
    import csv
    vocab_dir = vocab_dir or (Path(__file__).resolve().parent.parent / "data" / "vocab")

    def rows(name):
        path = vocab_dir / name
        if not path.exists():
            return []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def split_variants(value):
        # The vocab CSVs separate multiple printed forms with ';' (e.g.
        # 野戦砲兵 -> "野戦砲;野砲兵"). Accept '|' and whitespace too rather than
        # depend on one convention holding across future rows.
        import re
        return [v for v in re.split(r"[;|\s]+", value or "") if v]

    ranks = [
        {
            "code": r["rank_code"],
            "ja": r["label_ja"],
            "en": r["label_en"],
            "order": int(r["seniority_order"]) if r.get("seniority_order") else None,
            "variants": split_variants(r.get("variants")),
        }
        for r in rows("rank.csv")
    ]
    branches = [
        {
            "code": b["branch_code"],
            "ja": b["label_ja"],
            "en": b["label_en"],
            "category": b.get("category"),
            "variants": split_variants(b.get("variants")),
        }
        for b in rows("branch.csv")
    ]
    variants = [
        {"variant": v["variant_char"], "canonical": v["canonical_char"],
         "note": v.get("note")}
        for v in rows("kanji_variant.csv")
    ]
    ranks.sort(key=lambda r: (r["order"] is None, r["order"]))
    return {"ranks": ranks, "branches": branches, "kanji_variants": variants}


class Leaves:
    """The leaves of one scan, each read once - and a second time, under a local
    threshold, only if a leaf asks for it. Shared across the panels of a spread
    so the scan is not read again for each."""

    def __init__(self, image, scale: float = R.SCALE):
        self.image, self.scale = image, scale
        self.first = R.detect_leaves(image, scale=scale)
        self._second: list | None = None

    def second(self, panel: int):
        if self._second is None:
            self._second = R.detect_leaves(self.image, scale=self.scale, local=True)
        return self._second[panel] if panel < len(self._second) else None


def register_image(image, pid: str, frame: int, *, panel: int = 0,
                   templates: list[R.Template] | None = None,
                   scale: float = R.SCALE,
                   url_for=None, leaves: Leaves | None = None) -> RegisteredPage:
    """Register one panel of an already-loaded scan.

    `url_for(pid, frame, bbox)` builds the IIIF region URL; omit it to skip URL
    construction (which otherwise costs a manifest fetch per page).
    Raises `PageNotRegistrable` if the panel matches no template - after a film
    leaf has had its second reading (registration.py).
    """
    templates = templates if templates is not None else R.load_library(TEMPLATE_DIR)
    leaves = leaves or Leaves(image, scale)
    grids = leaves.first
    if panel >= len(grids):
        raise PageNotRegistrable(
            f"{pid} frame {frame}: panel {panel} not found ({len(grids)} detected)")

    grid = grids[panel]
    reg = R.classify(grid, templates) if grid is not None else None
    if reg is None:
        again = leaves.second(panel)
        if again is not None:
            reg = R.classify(again, templates)
            if reg is not None:
                grid = again
    if grid is None:
        raise PageNotRegistrable(
            f"{pid} frame {frame} panel {panel}: no ruling grid on this leaf")
    if reg is None:
        raise PageNotRegistrable(
            f"{pid} frame {frame} panel {panel}: matches no template "
            f"(officer columns={grid.n_officer_columns})")

    template = next(t for t in templates if t.template_id == reg.template_id)
    confirmed = _label_confirmation(templates).get(template.template_id, {})

    by_officer: dict[int, list[Cell]] = {}
    for column, name, bbox, suspect in R.cells(reg, template, scale=scale):
        by_officer.setdefault(column, []).append(Cell(
            field=name,
            bbox=bbox,
            suspect=suspect,
            confirmed_label=confirmed.get(name, False),
            crop_url=url_for(pid, frame, bbox) if url_for else None,
        ))

    officers = []
    for column in sorted(by_officer):
        strip = R.column_bbox(reg, column, scale=scale)
        officers.append(Officer(
            index=column,
            bbox=strip,
            cells=by_officer[column],
            crop_url=url_for(pid, frame, strip) if url_for else None,
            panel=panel,
            column=column,
        ))

    return RegisteredPage(
        pid=pid,
        frame=frame,
        panel=panel,
        template_id=reg.template_id,
        skew_deg=grid.skew_deg,
        bands_matched=reg.matched,
        bands_total=len(template.band_fracs),
        explained_frac=reg.explained_frac,
        officers=officers,
        panels_total=len(grids),
        panels_registered=(panel,),
        panels_reread=(panel,) if grid.local else (),
    )


def register_spread(image, pid: str, frame: int, **kwargs) -> RegisteredPage:
    """Register every panel of a scan as one continuous reading sequence.

    A roster scan is a two-page spread and both leaves carry officers, but the
    workstation only ever asked for panel 0. That was not merely a missing
    control: `roster_cell` is `UNIQUE (page_id, row_index)` and a page_id is a
    frame, so registering the second leaf under its own column numbers would
    have collided with the first leaf's rows and re-pointed live observations at
    the wrong geometry.

    Numbering the spread continuously avoids the collision without touching the
    frozen schema, and it is not a workaround - it is what the print does.
    Japanese reads right to left, so the right-hand leaf is read first and its
    last column is followed by the left-hand leaf's first. The seniority numbers
    confirm it: pid 1449426 frame 100 runs 915-930 on the right and 931-944 on
    the left, frame 300 runs 1605-1628 then 1629-1643. Ditto chains therefore
    resolve across the gutter, and the monotone-seniority audit spans the whole
    scan rather than restarting halfway.

    A panel that matches no template is skipped, not fatal: half a spread read is
    better than none, and `panels_total` against `panels_registered` is what says
    a leaf was left out - loudly, rather than by a page quietly looking finished.
    That count includes a leaf on which no grid was found at all (a blank page,
    or rulings that did not come through): it too is a leaf nobody read.
    """
    leaves = Leaves(image, kwargs.get("scale", R.SCALE))
    grids = leaves.first
    pages, officers, registered, reread = [], [], [], []
    for index in range(len(grids)):
        try:
            page = register_image(image, pid, frame, panel=index, leaves=leaves, **kwargs)
        except PageNotRegistrable:
            continue
        pages.append(page)
        registered.append(index)
        reread.extend(index for _ in page.panels_reread)
        for officer in page.officers:
            officers.append(replace(officer, index=len(officers)))
    if not pages:
        raise PageNotRegistrable(
            f"{pid} frame {frame}: no panel matches a template "
            f"({len(grids)} detected)")
    first = pages[0]
    return RegisteredPage(
        pid=pid,
        frame=frame,
        panel=first.panel,
        template_id=first.template_id,
        skew_deg=first.skew_deg,
        bands_matched=min(p.bands_matched for p in pages),
        bands_total=first.bands_total,
        explained_frac=min(p.explained_frac for p in pages),
        officers=officers,
        panels_total=len(grids),
        panels_registered=tuple(registered),
        panels_reread=tuple(reread),
    )


def read_image(path: str | Path, flags: int = cv2.IMREAD_GRAYSCALE):
    """`cv2.imread` for any path; None when the file cannot be read.

    On Windows OpenCV opens files through the ANSI code page, so a scan under
    C:\\Users\\田中\\... comes back as None although the file is there - and a
    reader's kit lands exactly in such a folder. Reading the bytes ourselves and
    decoding from memory has no such limit.
    """
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, flags) if data.size else None


def write_image(path: str | Path, image) -> bool:
    """`cv2.imwrite` for any path, for the same reason as `read_image`."""
    ok, data = cv2.imencode(Path(path).suffix or ".png", image)
    if ok:
        data.tofile(str(path))
    return bool(ok)


# --------------------------------------------------------------------------
# stored registrations - a page registered once, and read back everywhere else
# --------------------------------------------------------------------------
#
# Registration is arithmetic on pixels, and it is not stable across machines: on
# 97 sampled pages, three registered with a different number of officers under
# OpenCV 5 than under OpenCV 4.8, and three more once the scan had been
# recompressed. An observation is recorded against `row_index`, so a reader's
# copy that counts columns differently from the master would file a reading
# under the wrong officer - silently.
#
# So a reader's kit does not register anything. The lead's machine registers
# every page when the kit is built (app/kit_build.py) and ships the result; the
# kit reads it back. The geometry a reader records against is then the lead's
# own, whatever libraries or image quality the kit carries.

STORED_DIR = "registered"


def stored_path(pid: str, frame: int, home: str | Path | None = None) -> Path | None:
    home = home or os.environ.get("JP_OCR_DATA")
    if not home:
        return None
    return Path(home) / "cache" / pid / STORED_DIR / f"frame_{frame:04d}.json"


def page_from_dict(d: dict, url_for=None) -> RegisteredPage:
    """The inverse of `RegisteredPage.as_dict`. Derived keys in `d` are ignored."""
    pid, frame = d["pid"], d["frame"]
    officers = []
    for o in d["officers"]:
        cells = [Cell(field=c["field"], bbox=tuple(c["bbox"]), suspect=c["suspect"],
                      confirmed_label=c["confirmed_label"],
                      crop_url=url_for(pid, frame, tuple(c["bbox"])) if url_for else None)
                 for c in o["cells"]]
        officers.append(Officer(
            index=o["index"], bbox=tuple(o["bbox"]), cells=cells,
            crop_url=url_for(pid, frame, tuple(o["bbox"])) if url_for else None,
            panel=o["panel"], column=o["column"]))
    return RegisteredPage(
        pid=pid, frame=frame, panel=d["panel"], template_id=d["template_id"],
        skew_deg=d["skew_deg"], bands_matched=d["bands_matched"],
        bands_total=d["bands_total"], explained_frac=d["explained_frac"],
        officers=officers, panels_total=d["panels_total"],
        panels_registered=tuple(d["panels_registered"]),
        panels_reread=tuple(d.get("panels_reread", ())))


def store_registration(home: str | Path, pid: str, frame: int,
                       page: RegisteredPage | None, reason: str | None = None) -> Path:
    """Write one page's registration - or why it has none - under a data home."""
    path = stored_path(pid, frame, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = page.as_dict() if page is not None else {"not_registrable": reason or ""}
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def load_stored(pid: str, frame: int, url_for=None) -> RegisteredPage | None:
    """A stored registration, if this data home has one for the page.

    Raises PageNotRegistrable when what was stored is that the page has no
    officer grid. Where nothing may be fetched (a reader's kit, JPOCR_OFFLINE)
    a page with nothing stored is an error rather than a cue to register it
    here: computing it locally is exactly what a kit exists not to do.
    """
    path = stored_path(pid, frame)
    if path is not None and path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "not_registrable" in doc:
            raise PageNotRegistrable(doc["not_registrable"]
                                     or f"{pid} frame {frame}: no officer grid")
        return page_from_dict(doc, url_for)
    if os.environ.get("JPOCR_OFFLINE", "") not in ("", "0"):
        raise PageNotRegistrable(
            f"{pid} frame {frame}: this kit carries no registration for the page")
    return None


def register_file(path: str | Path, pid: str, frame: int, **kwargs) -> RegisteredPage:
    """Register a cached page image from disk.

    `panel=None` (the default) registers the whole spread; an explicit `panel`
    registers that leaf alone. A whole-spread registration already stored for
    this page (see above) is returned as it is, without looking at the image.
    """
    fresh = kwargs.pop("fresh", False)      # register from the scan, whatever is stored
    if not fresh and kwargs.get("panel") is None \
            and "templates" not in kwargs and "scale" not in kwargs:
        stored = load_stored(pid, frame, kwargs.get("url_for"))
        if stored is not None:
            return stored
    image = read_image(path)
    if image is None:
        raise FileNotFoundError(f"cannot read page image: {path}")
    if kwargs.get("panel") is None:
        kwargs.pop("panel", None)
        return register_spread(image, pid, frame, **kwargs)
    return register_image(image, pid, frame, **kwargs)
