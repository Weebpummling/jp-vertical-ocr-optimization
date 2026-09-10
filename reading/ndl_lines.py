"""NDL's precomputed OCR, as boxed lines.

Every volume in the Next-Generation Digital Library carries the output of NDL's
FY2021 mass OCR, retrievable per volume as one JSON document. Each frame in it
holds a `coordjson` array: one entry per line NDL detected, with the line's text
and its bounding box in full-resolution scan pixels.

Those boxes are the whole point. NDL's *reading order* for vertical text is
unreliable and its lines fragment - 熊谷敬一 arrives as three separate boxes - so
the text stream is not a transcript and never will be. But the boxes are good,
and our geometry is top-down: `reading/registration.py` puts a template cell at a
known rectangle on the page, so the association between text and field is done by
overlap rather than by reading order. NDL supplies free readings; we supply the
structure.

This module is deliberately the only place `coordjson` is parsed. It was being
read three times across two repositories - twice in ndl-workbench (once for text,
once for geometry, each discarding what the other needed) and again in the
binning prototype here - and the blank-leaf rule below had been rediscovered once
already.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class BoxedLine:
    """One line NDL detected, with its box in full-resolution scan pixels."""

    text: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def thickness(self) -> float:
        """The short side: column width for vertical text, height for horizontal.

        Taking the short side classifies ruby against body, and small-type
        annotation against large-type names, without needing to know the page's
        orientation up front.
        """
        return min(self.width, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) / 2.0, (self.ymin + self.ymax) / 2.0)

    def overlap(self, bbox: tuple[float, float, float, float]) -> float:
        """Fraction of THIS line's area that falls inside (x, y, w, h).

        Asymmetric on purpose. A cell is far larger than a line, so intersection
        over union would score every correct binning as a near-miss; what decides
        the bin is how much of the *line* the cell contains.
        """
        x, y, w, h = bbox
        ix = max(0.0, min(self.xmax, x + w) - max(self.xmin, x))
        iy = max(0.0, min(self.ymax, y + h) - max(self.ymin, y))
        area = self.width * self.height
        return (ix * iy / area) if area > 0 else 0.0


class NoCoordinateData(LookupError):
    """The frame carries no `coordjson` at all - not the same as a blank page."""


def frame_lines(entry: dict[str, Any]) -> list[BoxedLine]:
    """Boxed lines of one frame entry.

    An empty coordinate array is a real answer - a blank leaf, an endpaper, a
    plate - and returns an empty list. Only a frame with no coordinate data at
    all raises, because "NDL read nothing here" and "there was nothing here to
    read" are different findings and collapsing them loses a page silently.

    **Exact duplicates are dropped.** NDL's `coordjson` repeats some entries
    verbatim - same text, same four coordinates, listed twice. It is common
    enough to matter: 2.7% of lines in pid 843085 across 97 frames, 4.5% in pid
    1457899 across 113. Anything that concatenates the lines doubles that text,
    which is where 平岩棟一 became 平平岩棟一 and a decoration column printed
    itself twice. Two boxes at identical coordinates cannot be two readings of
    two things, so this is deduplication of a serialization artefact, not a
    judgement about the text - a genuine repeat on the page has a different box.
    """
    coord = entry.get("coordjson")
    if coord is None or coord == "null" or coord == "":
        raise NoCoordinateData(entry.get("id") or "<unknown frame>")
    try:
        raw = json.loads(coord) if isinstance(coord, str) else coord
    except ValueError as exc:
        raise NoCoordinateData(entry.get("id") or "<unknown frame>") from exc
    lines = []
    seen: set[tuple] = set()
    for item in raw:
        text = str(item.get("contenttext", ""))
        try:
            box = (float(item["xmin"]), float(item["ymin"]),
                   float(item["xmax"]), float(item["ymax"]))
        except (KeyError, TypeError, ValueError):
            continue
        key = (text, *box)
        if key in seen:
            continue          # see dedupe note below
        seen.add(key)
        lines.append(BoxedLine(text, *box))
    return lines


def frames(fulltext: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (frame_number, entry) over a volume's fulltext document.

    Frame numbers are 1-based and positional: NDL's list is in frame order, and
    the per-entry identifiers are not consistently numeric across volumes.
    """
    for i, entry in enumerate(fulltext.get("list") or [], start=1):
        yield i, entry


def frame(fulltext: dict[str, Any], number: int) -> list[BoxedLine]:
    """Boxed lines of frame `number` (1-based) of a volume."""
    entries = fulltext.get("list") or []
    if not 1 <= number <= len(entries):
        raise IndexError(f"frame {number} outside 1..{len(entries)}")
    return frame_lines(entries[number - 1])
