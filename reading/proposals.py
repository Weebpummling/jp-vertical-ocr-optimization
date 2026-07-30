"""Review-first proposal layer: engine candidates become classified suggestions.

This is the one durable result of the prior effort, ported forward. That effort's
*geometry* was a bottom-up self-improving crop detector and is deliberately NOT
carried over — see PLAN.md standing commitment 3. What survives is everything it
learned downstream of geometry, at a cost of 29 benchmark runs:

  - A lexicon hit is evidence, not transcription. It never overwrites a reading.
  - Classification needs the MARGIN over the runner-up, not just the best score.
    A 0.95 best with a 0.94 runner-up is a coin flip, not a match.
  - Every selected value carries the raw candidate that produced it, so a human
    can see what the machine actually saw.
  - Conservative repairs record their method and their original reading.
  - A field with no trustworthy reading stays empty. Blank beats plausible.

Nothing here can author a final value. `Suggestion` is frozen and has no
"accepted" field; `to_machine_reading()` emits a `machine_reading` row, which the
schema keeps strictly separate from `observation`, where human decisions live.

Thresholds below are PROVISIONAL. Per standing commitment 6 they must be
calibrated against the hold-out split before any number is claimed; `benchmarks/`
owns that calibration. They are starting points, not results.

Usage:
    from proposals import Lexicon, Candidate, classify, agreement

    lex = Lexicon.from_csv(Path(os.environ["JP_OCR_DATA"]) / "academy" / "names.csv")
    sug = lex.suggest("吉野榮一郎")
    if sug.status is Status.PROBABLE:
        ...  # still only a suggestion; a human must confirm
"""
from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

VOCAB_DIR = Path(__file__).resolve().parent.parent / "data" / "vocab"

# Provisional. Calibrate on the hold-out split before quoting any accuracy.
PROBABLE_MIN_SCORE = 0.90
PROBABLE_MIN_MARGIN = 0.15
AMBIGUOUS_MIN_SCORE = 0.60


class Status(str, Enum):
    """Outcome of matching a reading against a lexicon.

    PROBABLE is the strongest thing a machine may say. It is not "correct".
    """

    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


class Agreement(str, Enum):
    """Mirrors machine_reading.agree_status in db/schema.sql."""

    AGREE = "agree"
    DISAGREE = "disagree"
    VARIANT_EQUAL = "variant_equal"
    NO_HUMAN_VALUE = "no_human_value"


# --------------------------------------------------------------------------
# Variant folding
# --------------------------------------------------------------------------


def load_variant_map(vocab_dir: Path | None = None) -> dict[str, str]:
    """Load variant -> canonical single-character mappings.

    The table is deliberately conservative: 齋->斎 and 齊->斉 are separate rows
    because they are different characters that merely look alike. Folding is a
    lookup, never a similarity guess, so that distinction survives.
    """
    path = (vocab_dir or VOCAB_DIR) / "kanji_variant.csv"
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            variant = (row.get("variant_char") or "").strip()
            canonical = (row.get("canonical_char") or "").strip()
            if variant and canonical:
                mapping[variant] = canonical
    return mapping


def canonicalize(text: str, variant_map: dict[str, str]) -> str:
    """Fold a reading to comparison form: NFKC, strip whitespace, fold variants.

    Applied to both sides of every comparison. Never stored as a value — the
    original reading is what gets kept and shown.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).strip()
    return "".join(variant_map.get(ch, ch) for ch in folded)


def similarity(a: str, b: str, variant_map: dict[str, str]) -> float:
    """Character-level similarity of two readings after variant folding."""
    ca, cb = canonicalize(a, variant_map), canonicalize(b, variant_map)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    return SequenceMatcher(None, ca, cb).ratio()


# --------------------------------------------------------------------------
# Candidates and suggestions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One engine's reading of one field, with enough provenance to re-check it.

    `engine` is free text rather than an enum because the reading stack has three
    proposal sources (NDL precomputed fulltext, an NDL OCR engine run by us, and
    a VLM) while machine_reading.engine currently only permits two. Recording the
    true source here keeps provenance honest; see to_machine_reading().
    """

    value: str
    engine: str
    score: float | None = None
    raw_text: str | None = None          # pre-cleanup reading
    source_ref: str | None = None        # crop / line-box / config identifier

    def __post_init__(self) -> None:
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score out of range: {self.score}")


@dataclass(frozen=True)
class LexiconHit:
    """A ranked lexicon entry. Evidence about a reading, never a replacement."""

    value: str
    score: float
    row_ref: str | None = None
    cohort: str | None = None
    branch: str | None = None


@dataclass(frozen=True)
class Suggestion:
    """A classified lexicon suggestion for one reading.

    Deliberately has no `accepted` or `final` field. The reading stays in
    `reading`; the suggestion stays here; a human reconciles them.
    """

    reading: str
    status: Status
    best: LexiconHit | None = None
    runner_up: LexiconHit | None = None
    ranked: tuple[LexiconHit, ...] = ()

    @property
    def margin(self) -> float:
        """Best score minus runner-up score. 1.0 when nothing else is close."""
        if self.best is None:
            return 0.0
        if self.runner_up is None:
            return self.best.score
        return round(self.best.score - self.runner_up.score, 4)

    @property
    def needs_review(self) -> bool:
        """Everything needs review. Present so callers read as review-first."""
        return True

    def to_machine_reading(self, cell_id: str, field_name: str, engine: str) -> dict:
        """Shape a machine_reading row. Never an observation row.

        `engine` must satisfy machine_reading's CHECK constraint; the richer
        source is preserved in provenance rather than being silently coerced.
        """
        return {
            "cell_id": cell_id,
            "field": field_name,
            "engine": engine,
            "value": self.reading,
            "confidence": self.best.score if self.best else None,
            "provenance": {
                "suggestion_status": self.status.value,
                "suggestion_value": self.best.value if self.best else None,
                "suggestion_row_ref": self.best.row_ref if self.best else None,
                "runner_up_value": self.runner_up.value if self.runner_up else None,
                "runner_up_score": self.runner_up.score if self.runner_up else None,
                "margin": self.margin,
            },
        }


def classify(
    reading: str,
    hits: list[LexiconHit],
    *,
    min_score: float = PROBABLE_MIN_SCORE,
    min_margin: float = PROBABLE_MIN_MARGIN,
    ambiguous_min: float = AMBIGUOUS_MIN_SCORE,
) -> Suggestion:
    """Classify a reading against ranked lexicon hits.

    PROBABLE requires a high best score AND clear separation from the runner-up.
    Requiring both is the point: the prior effort's 9/10 exact suggestions on the
    page-56 benchmark came with zero auto-applied values, because a strong score
    against a crowded field is still a coin flip.
    """
    ranked = tuple(sorted(hits, key=lambda h: -h.score))
    if not ranked:
        return Suggestion(reading=reading, status=Status.NO_MATCH)

    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = best.score - (runner_up.score if runner_up else 0.0)

    if best.score >= min_score and margin >= min_margin:
        status = Status.PROBABLE
    elif best.score >= ambiguous_min:
        status = Status.AMBIGUOUS
    else:
        status = Status.NO_MATCH

    return Suggestion(
        reading=reading,
        status=status,
        best=best,
        runner_up=runner_up,
        ranked=ranked,
    )


def agreement(
    candidates: list[Candidate],
    human_value: str | None,
    variant_map: dict[str, str],
) -> Agreement:
    """Compare engine candidates against a confirmed human reading.

    VARIANT_EQUAL is a distinct outcome, not a flavour of AGREE: 榮 vs 栄 means
    the engine read the glyph correctly and the two forms are the same name, but
    which form the source actually prints is a real question for the roster.
    """
    if human_value is None or not human_value.strip():
        return Agreement.NO_HUMAN_VALUE

    values = [c.value for c in candidates if c.value and c.value.strip()]
    if not values:
        return Agreement.NO_HUMAN_VALUE

    if any(v == human_value for v in values):
        return Agreement.AGREE

    human_canonical = canonicalize(human_value, variant_map)
    if any(canonicalize(v, variant_map) == human_canonical for v in values):
        return Agreement.VARIANT_EQUAL

    return Agreement.DISAGREE


# --------------------------------------------------------------------------
# Conservative sequence repair
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SequenceRepair:
    """A recovered seniority number, with the evidence that justified it."""

    value: int
    original: str
    method: str

    @property
    def inferred(self) -> bool:
        return True


def recover_truncated_seniority(
    reading: str,
    *,
    previous: int | None,
    following: int | None,
) -> SequenceRepair | None:
    """Recover a seniority number whose leading digits were cropped away.

    Seniority runs monotonically down a page, so a reading of `12` bracketed by
    `113` and `111` is almost certainly `112` — the prefix was lost to the crop,
    not misread. The repair is accepted only when restoring a prefix produces a
    value that fits strictly between its neighbours, and exactly one prefix does.

    Returns None when the reading is already consistent, when no prefix fits, or
    when several do. Ambiguity is reported as no repair, never as a best guess.
    """
    digits = reading.strip()
    if not digits.isdigit():
        return None

    lo = min(previous, following) if previous is not None and following is not None else None
    hi = max(previous, following) if previous is not None and following is not None else None
    if lo is None or hi is None or hi - lo < 2:
        return None

    current = int(digits)
    if lo < current < hi:
        return None  # already consistent; nothing to repair

    fits = []
    for prefix in range(1, 100):
        restored = int(f"{prefix}{digits}")
        if lo < restored < hi:
            fits.append(restored)
        if restored > hi:
            break

    if len(fits) != 1:
        return None

    return SequenceRepair(
        value=fits[0],
        original=digits,
        method=f"monotone_prefix_recovery(prev={previous},next={following})",
    )


# --------------------------------------------------------------------------
# Lexicon
# --------------------------------------------------------------------------


@dataclass
class Lexicon:
    """A read-only name lexicon. Loaded copies are never written back.

    The academy dataset is the intended source. It stays on the lead's machine
    per the data policy, so construction takes a path under JP_OCR_DATA rather
    than anything committed to this repository.
    """

    entries: list[LexiconHit] = field(default_factory=list)
    variant_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_csv(
        cls,
        path: Path,
        *,
        name_column: str = "fullname",
        variant_map: dict[str, str] | None = None,
    ) -> Lexicon:
        vm = variant_map if variant_map is not None else load_variant_map()
        entries: list[LexiconHit] = []
        with Path(path).open(encoding="utf-8-sig", newline="") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=2):
                name = (row.get(name_column) or "").strip()
                if not name:
                    continue
                entries.append(
                    LexiconHit(
                        value=name,
                        score=0.0,
                        row_ref=str(i),
                        cohort=(row.get("cohort") or "").strip() or None,
                        branch=(row.get("branch") or "").strip() or None,
                    )
                )
        return cls(entries=entries, variant_map=vm)

    def suggest(self, reading: str, *, top_n: int = 5, **kwargs) -> Suggestion:
        """Score `reading` against every entry and classify the result."""
        if not reading or not reading.strip():
            return Suggestion(reading=reading, status=Status.NO_MATCH)

        scored = [
            LexiconHit(
                value=e.value,
                score=similarity(reading, e.value, self.variant_map),
                row_ref=e.row_ref,
                cohort=e.cohort,
                branch=e.branch,
            )
            for e in self.entries
        ]
        scored.sort(key=lambda h: -h.score)
        return classify(reading, scored[:top_n], **kwargs)
