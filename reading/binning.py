"""Bin NDL's boxed OCR lines into registered template cells.

This is the zero-cost first proposal engine (PLAN.md Phase 2, first item). It
runs no OCR, needs no network once the volume's fulltext is cached, and costs
nothing per page: NDL has already read these volumes, and `registration.py`
already knows where every field of every officer sits in scan pixels. Putting
the two together is a rectangle intersection.

**What replaces what.** `prototype_cell_binning.py` proved this path but took its
geometry from Spike C's per-page ruling detection - bottom-up, and squarely the
thing standing commitment 3 forbids in production. Here the geometry comes from
the registered template, top-down, and the prototype's characteristic failures go
with it: text landed in two cells at once (the honours column printed twice), a
name doubled its first character, and date fragments that belonged to a band
scattered into an `other` bucket because the binner was guessing a fragment's
field from its *content*. A cell now owns a line or it does not.

**What this is not.** Nothing here authors a value. Every officer becomes a set
of proposals carrying the raw fragments that produced them, for a human to
confirm or overrule at the workstation - standing commitment 2. A field with no
trustworthy reading stays empty, because blank beats plausible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

import ditto
import eradate
from ndl_lines import BoxedLine

# How much of a line must fall inside a cell before that cell owns it. A line
# that straddles two cells belongs to whichever contains more of it; one that
# is mostly outside every cell belongs to none, and says so.
MIN_OVERLAP = 0.5

# Two lines are the same sub-column when their long dimensions overlap by this
# much of the narrower one - what separates a name from the birth date printed
# beside it, without needing to know which is which.
SAME_RUN = 0.5

# The elapsed-service band is 年-月-日 of service, not a date. The template says
# so; a date parser handed it would either refuse loudly or, worse, succeed.
DATE_FIELDS = ("rank_date", "prev_rank_date", "commissioning_date")
NUMERIC_FIELDS = ("seniority_no", "cohort")

# Furigana is printed beside a name in small kana, and NDL boxes each ruby column
# as a line of its own. Where one overlaps the name column it falls into the same
# run and welds itself into the reading: 上住良吉 came back as ウ上住た良吉.
RUBY_FIELDS = ("name_raw",)
KANA_ONLY = re.compile(r"^[ぁ-ゖァ-ヺー・]+$")
RUBY_MAX_THICKNESS = 0.6

# The date of posting is printed small at the foot of a post cell. NDL's reading
# welds it onto the post (步兵第七十聯隊附八、八); a zoomed re-reading returns it as
# a line of its own. Kept apart, the post is the post and both engines agree.
POSTING_DATE_FIELDS = ("post",)
POSTING_DATE = re.compile(r"^[〇一二三四五六七八九十、・，,]+$")

# The birth date printed small beside a name - an era marker and kanji numerals.
# Recognised by what it says, not by type size: NDLOCR-Lite boxes it as wide as
# the name, and "the largest type is the name" then chose the date for four
# officers of frame 101 (明二一、九、二〇 given as officer 12's name).
BIRTH_DATE_FIELDS = ("name_raw",)
BIRTH_DATE = re.compile(r"^[明大昭][〇一二三四五六七八九十、・，,]+$")


@dataclass(frozen=True)
class Run:
    """One sub-column of text inside a cell, in reading order."""

    text: str
    thickness: float
    lines: tuple[BoxedLine, ...]


@dataclass(frozen=True)
class Cell:
    """Every line the template says belongs to one field of one officer."""

    column: int
    field: str
    bbox: tuple[int, int, int, int]
    runs: tuple[Run, ...]
    suspect: bool
    # Furigana taken out of the reading - kept, not discarded, so the proposal
    # can say what was read beside the name.
    ruby: tuple[BoxedLine, ...] = ()
    # Small type set aside from the reading for the same reason - the posting
    # date at the foot of a post.
    aside: tuple[BoxedLine, ...] = ()

    @property
    def text(self) -> str:
        """All runs joined, right to left. The whole cell as NDL read it."""
        return "".join(r.text for r in self.runs)

    @property
    def primary(self) -> str:
        """The main run: the one set in the largest type.

        A name cell holds the name in large type and the birth date beside it in
        small; a post cell holds the assignment and, at its foot, the date of
        posting. Thickness separates them without reading the characters.
        """
        if not self.runs:
            return ""
        return max(self.runs, key=lambda r: r.thickness).text

    @property
    def secondary(self) -> str:
        """The remaining runs, in reading order - the small-type annotation."""
        if len(self.runs) < 2:
            return ""
        main = max(self.runs, key=lambda r: r.thickness)
        return "".join(r.text for r in self.runs if r is not main)


@dataclass
class Proposal:
    """One machine-proposed field value, with what produced it."""

    field: str
    value: str | None
    raw: str
    method: str
    note: str = ""
    suspect: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.value


@dataclass
class OfficerProposal:
    """Every proposed field for one officer column."""

    column: int
    fields: dict[str, Proposal] = dc_field(default_factory=dict)

    def value(self, name: str) -> str | None:
        p = self.fields.get(name)
        return p.value if p else None


def _x_overlap(a: BoxedLine, b: BoxedLine) -> float:
    lo = max(a.xmin, b.xmin)
    hi = min(a.xmax, b.xmax)
    narrower = min(a.width, b.width)
    return (hi - lo) / narrower if narrower > 0 and hi > lo else 0.0


def _runs(lines: list[BoxedLine]) -> tuple[Run, ...]:
    """Group a cell's lines into sub-columns, right to left, top to bottom.

    Vertical Japanese reads down a column and columns advance right to left, so
    a cell holding two things side by side - a name and a birth date - is two
    runs, and joining them into one string would weld the birth date onto the
    end of the name.
    """
    ordered = sorted(lines, key=lambda l: -l.xmin)
    groups: list[list[BoxedLine]] = []
    for line in ordered:
        for group in groups:
            if any(_x_overlap(line, other) >= SAME_RUN for other in group):
                group.append(line)
                break
        else:
            groups.append([line])
    out = []
    for group in groups:
        group.sort(key=lambda l: l.ymin)
        thickness = sum(l.thickness for l in group) / len(group)
        out.append(Run("".join(l.text for l in group), thickness, tuple(group)))
    return tuple(out)


def _split_ruby(lines: list[BoxedLine]) -> tuple[list[BoxedLine], tuple[BoxedLine, ...]]:
    """Separate furigana from a cell's lines: kana only, AND markedly thinner.

    Both conditions, because either alone is wrong. A name can itself be kana,
    and a thin line can be the small-type birth date beside it. Thinness is
    judged against the thickest line in the cell, which is the name.
    """
    if not lines:
        return lines, ()
    thickest = max(l.thickness for l in lines)
    ruby = tuple(l for l in lines
                 if KANA_ONLY.match("".join(l.text.split()))
                 and l.thickness < RUBY_MAX_THICKNESS * thickest)
    return [l for l in lines if l not in ruby], ruby


def _split_posting_date(lines: list[BoxedLine]) -> tuple[list[BoxedLine], tuple[BoxedLine, ...]]:
    """Separate the small posting date from a post cell's lines.

    A line of nothing but kanji numerals and separators is never part of a
    post's name; a post that contains numerals (步兵第四十三聯隊長) has words in
    the same line and is left alone. Type size is deliberately not a condition:
    NDLOCR-Lite boxes the small foot as wide as the post, and a size test kept it
    on three posts of frame 100. A cell of nothing but numerals is left as read.
    """
    if not lines:
        return lines, ()
    foot = tuple(l for l in lines if POSTING_DATE.match("".join(l.text.split())))
    if len(foot) == len(lines):
        return lines, ()
    return [l for l in lines if l not in foot], foot


def _split_birth_date(lines: list[BoxedLine]) -> tuple[list[BoxedLine], tuple[BoxedLine, ...]]:
    """Separate the birth date from a name cell's lines. A cell of nothing but a
    date is left as read, and refused as a name when proposed."""
    if not lines:
        return lines, ()
    birth = tuple(l for l in lines if BIRTH_DATE.match("".join(l.text.split())))
    if len(birth) == len(lines):
        return lines, ()
    return [l for l in lines if l not in birth], birth


def cell_from_lines(column: int, name: str, bbox, lines, suspect: bool = False) -> Cell:
    """One cell built from the lines that belong to it.

    What `bin_page` does per cell once lines are assigned - and what a second
    reading engine does for the lines it read inside one cell - so both go
    through the same run grouping and furigana handling.
    """
    lines = list(lines)
    ruby: tuple[BoxedLine, ...] = ()
    aside: tuple[BoxedLine, ...] = ()
    if name in RUBY_FIELDS:
        lines, ruby = _split_ruby(lines)
    if name in POSTING_DATE_FIELDS:
        lines, aside = _split_posting_date(lines)
    if name in BIRTH_DATE_FIELDS:
        lines, aside = _split_birth_date(lines)
    return Cell(column, name, bbox, _runs(lines), suspect, ruby, aside)


def bin_page(lines: list[BoxedLine], cells_iter,
             *, min_overlap: float = MIN_OVERLAP
             ) -> tuple[dict[tuple[int, str], Cell], list[BoxedLine]]:
    """Assign each boxed line to at most one template cell.

    `cells_iter` is `registration.cells(reg, template)` - (column, field, bbox,
    suspect) in original scan pixels, the same space NDL's boxes use.

    Returns the filled cells and the lines that belong to none of them. That
    second list is not waste: on a roster page it should hold the section
    headers and the running head, and little else. A page where it holds officer
    text is a page whose registration is wrong, and it is better to see that
    than to have the text quietly absorbed into a neighbouring cell.
    """
    spec = list(cells_iter)
    assigned: dict[tuple[int, str], list[BoxedLine]] = {}
    unassigned: list[BoxedLine] = []
    for line in lines:
        if not line.text.strip():
            continue
        best, best_score = None, 0.0
        for column, name, bbox, _suspect in spec:
            score = line.overlap(bbox)
            if score > best_score:
                best, best_score = (column, name), score
        if best is None or best_score < min_overlap:
            unassigned.append(line)
        else:
            assigned.setdefault(best, []).append(line)
    cells = {}
    for column, name, bbox, suspect in spec:
        cells[(column, name)] = cell_from_lines(column, name, bbox,
                                                assigned.get((column, name), []), suspect)
    return cells, unassigned


def propose(cells: dict[tuple[int, str], Cell], columns: int,
            fields: list[str]) -> list[OfficerProposal]:
    """Turn binned cells into per-officer proposals, resolving ditto marks.

    Ditto resolution follows `reading/ditto.py` exactly: the officer directly
    above - here, the previous column in reading order - and no further. A ditto
    whose neighbour has nothing to give is refused and left empty, carrying the
    reason, rather than reaching up the page for something to copy.
    """
    officers = [OfficerProposal(column=c) for c in range(columns)]
    for column in range(columns):
        for name in fields:
            cell = cells.get((column, name))
            if cell is None:
                continue
            officers[column].fields[name] = _propose_field(
                name, cell, officers[column - 1] if column else None)
    return officers


def propose_cell(name: str, cell: Cell,
                 above: OfficerProposal | None = None) -> Proposal:
    """Interpret one cell's lines exactly as a page's are interpreted.

    For a second reading engine: whatever produced the lines, the same date
    reassembly, ditto rules, digit checks and furigana handling decide what they
    mean, so two engines' proposals for a cell are directly comparable.
    """
    return _propose_field(name, cell, above)


def _date_text(cell: Cell) -> str:
    """Reassemble a date cell into the notation `eradate` expects.

    A roster date is one vertical line - era-year, then month, then day - but it
    is set with the era-year in slightly narrower type, so NDL boxes it as two or
    three stacked segments that are staggered by a few tens of pixels. Whether
    those segments cluster into one run is a coin flip on that stagger, which is
    why picking the largest run read half a date and dropped the rest: 明四四 with
    一二、二六 thrown away.

    So a date cell is not grouped into runs at all. Its segments are ordered top
    to bottom - the direction the line is read - and joined with the separator
    the notation already uses between year, month and day.

    Inserting that separator cannot manufacture a date. `eradate` refuses
    anything that does not resolve to exactly year/month/day within its era, so a
    wrong reassembly comes back as a refusal with its reason, never as a value.
    """
    lines = sorted((l for run in cell.runs for l in run.lines),
                   key=lambda l: l.ymin)
    parts = [l.text.strip() for l in lines if l.text.strip()]
    joined = "、".join(parts)
    while "、、" in joined:
        joined = joined.replace("、、", "、")
    return joined.strip("、")


def _propose_field(name: str, cell: Cell, above: OfficerProposal | None) -> Proposal:
    raw = cell.text.strip()
    if not raw:
        return Proposal(name, None, "", "blank", suspect=cell.suspect)

    # A ditto is sometimes boxed with the separator that follows it (同、). The
    # tolerance lives here rather than in ditto.py: what counts as a ditto mark
    # is a statement about the printed page and is shared with the workstation,
    # while stripping punctuation off a machine reading is a statement about NDL.
    if ditto.is_ditto(raw.strip("、。 ")):
        if name not in ditto.DITTOABLE_FIELDS:
            return Proposal(name, None, raw, "refused",
                            f"printed as a ditto mark, but {name} is not a column "
                            f"a ditto may be resolved against", cell.suspect)
        inherited = above.value(name) if above else None
        if not inherited:
            return Proposal(name, None, raw, "refused",
                            "printed as a ditto mark, but the officer directly "
                            "above has no value in this column", cell.suspect)
        return Proposal(name, inherited, raw, "inherited",
                        "printed as a ditto mark; same as the entry above",
                        cell.suspect)

    if name in DATE_FIELDS:
        text = _date_text(cell)
        parsed = eradate.parse(text)
        if parsed.ok:
            return Proposal(name, parsed.value.isoformat(), text, "eradate",
                            suspect=cell.suspect)
        return Proposal(name, None, text, "refused", parsed.reason, cell.suspect)

    if name in NUMERIC_FIELDS:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits and digits == raw.strip():
            return Proposal(name, digits, raw, "digits", suspect=cell.suspect)
        return Proposal(name, None, raw, "refused",
                        "expected digits only", cell.suspect)

    if name == "name_raw":
        primary = cell.primary.strip()
        if BIRTH_DATE.match("".join(primary.split())):
            return Proposal(name, None, raw, "refused",
                            "only the birth date was read, not the name", cell.suspect)
        notes = []
        birth = cell.secondary or "".join(
            l.text for l in sorted(cell.aside, key=lambda l: l.ymin))
        if birth:
            notes.append(f"birth date read alongside: {birth}")
        if cell.ruby:
            notes.append("furigana read beside it: "
                         + " ".join(l.text for l in sorted(cell.ruby, key=lambda l: l.ymin)))
        return Proposal(name, primary or None, raw, "ndl-ocr",
                        "; ".join(notes), cell.suspect)

    if name in POSTING_DATE_FIELDS and POSTING_DATE.match("".join(raw.split())):
        return Proposal(name, None, raw, "refused",
                        "only the posting date was read, not the post", cell.suspect)

    if name in POSTING_DATE_FIELDS and cell.aside:
        foot = "".join(l.text for l in sorted(cell.aside, key=lambda l: l.ymin))
        return Proposal(name, raw, raw, "ndl-ocr",
                        f"posting date read at the foot: {foot}", cell.suspect)

    return Proposal(name, raw, raw, "ndl-ocr", suspect=cell.suspect)
