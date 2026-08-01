"""Era-date normalizer: 明治/大正/昭和 readings → canonical dates.

Phase 1. Rosters print dates as era + kanji numerals in digit juxtaposition —
the page-51 cells read 明三三、八、二 (Meiji 33, month 8, day 2) and 九、一二、二一
(era inherited from context: year 9, month 12, day 21). This module parses that
notation and converts to proleptic Gregorian dates.

The rule is the project's standing one: **ambiguous parses are flagged, not
guessed.** parse() returns either a date or a reason string — never a best
guess. An era year past the era's end, a 32nd day, a reading with no era and no
context era: all refusals with the reason recorded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Era epochs: era year 1 == epoch + 1. Bounds are the historical era spans.
ERAS = {
    "明": (1867, date(1868, 1, 25), date(1912, 7, 30)),   # Meiji
    "大": (1911, date(1912, 7, 30), date(1926, 12, 25)),  # Taishō
    "昭": (1925, date(1926, 12, 25), date(1989, 1, 7)),   # Shōwa
}
ERA_NAMES = {"明治": "明", "大正": "大", "昭和": "昭"}

DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
# 年/月/日 are separators too, not content: the roster columns use the terse
# juxtaposed form (昭三三、八、二) but the same date is written out in full
# (昭和8年9月1日) in volume titles and the front matter, and both must parse to
# the same day. A trailing 日 just yields an empty final part, which is dropped.
SEPARATORS = "、,，. ・年月日"


@dataclass(frozen=True)
class Parsed:
    """Either value is set, never both. reason is the flag text for a refusal."""
    value: date | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


def kanji_int(s: str) -> int | None:
    """Kanji numeral → int. Handles digit juxtaposition (三四 = 34), the
    十-positional form (二十三 = 23), 元 (= 1), and ASCII digits. None on junk."""
    s = s.strip()
    if not s:
        return None
    if s == "元":
        return 1
    if s.isascii() and s.isdigit():
        return int(s)
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = 1 if head == "" else DIGITS.get(head)
        ones = 0 if tail == "" else DIGITS.get(tail)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    out = 0
    for ch in s:
        if ch not in DIGITS:
            return None
        out = out * 10 + DIGITS[ch]
    return out


def parse(text: str, *, context_era: str | None = None) -> Parsed:
    """Parse an era-date reading like 明三三、八、二 or 九、一二、二一.

    context_era supplies the era when the reading omits it (roster columns
    inherit the era from the preceding row). Without either, refuse.
    """
    s = (text or "").strip()
    for name, abbrev in ERA_NAMES.items():
        if s.startswith(name):
            s, era = s[len(name):], abbrev
            break
    else:
        if s[:1] in ERAS:
            era, s = s[0], s[1:]
        elif context_era in ERAS:
            era = context_era
        elif context_era:
            return Parsed(reason=f"unknown context era {context_era!r}")
        else:
            return Parsed(reason="no era marker and no context era")

    parts = [p for p in _split(s) if p]
    if len(parts) != 3:
        return Parsed(reason=f"expected year/month/day, got {len(parts)} part(s): {text!r}")
    y, m, d = (kanji_int(p) for p in parts)
    if y is None or m is None or d is None:
        return Parsed(reason=f"unreadable numeral in {text!r}")

    epoch, era_start, era_end = ERAS[era]
    if not 1 <= m <= 12:
        return Parsed(reason=f"month {m} out of range")
    try:
        value = date(epoch + y, m, d)
    except ValueError:
        return Parsed(reason=f"day {d} invalid for {epoch + y}-{m:02d}")
    if not era_start <= value <= era_end:
        return Parsed(reason=f"{value.isoformat()} falls outside the {era} era")
    return Parsed(value=value)


def _split(s: str) -> list[str]:
    parts, cur = [], ""
    for ch in s:
        if ch in SEPARATORS:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts]
