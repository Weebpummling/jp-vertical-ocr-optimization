"""Ditto marks: "same as the entry above".

The rosters use them everywhere, not just in the date columns - a run of
officers sharing a branch, a rank, a posting or a commissioning date is printed
once and dittoed down the column. A ditto is a reading, not a value: 同 says
where to look, and says nothing else.

Resolving one is reading the page as printed. It is allowed for exactly that
reason, under two rules that keep it reading rather than guessing:

* **The row directly above, and no further.** If that row has no value in the
  column, the ditto cannot be resolved and is refused. Reaching further up to
  find something to copy would attach a value the page does not claim - and
  would do it invisibly, which is the failure mode this project exists to avoid.
* **Recorded as inherited.** The observation keeps what was printed, the row the
  value came from, and the fact that it was not written out, so nothing later
  mistakes an inherited value for one the page stated.

A chain of dittos resolves without recursion: a resolved ditto is stored as the
concrete value it meant, so the next row down finds a real value above it.
"""
from __future__ import annotations

# 上 is the "above" of 同上; 〃 and the quote-like forms turn up in later
# printings and in hand-corrected copies.
DITTO_MARKS = frozenset("同仝〃〆″”")

# The observation columns a ditto may be resolved against. 備考 is absent because
# it is not a column - a reader's note rides in field_confidence - and there is
# no sensible "same as above" for free text.
DITTOABLE = ("seniority_no", "name_raw", "rank_code", "branch_code",
             "post", "commissioning_date")


def is_ditto(text: str | None) -> bool:
    """True when a cell says 'same as above' rather than stating a value."""
    stripped = (text or "").strip().rstrip("上")
    return bool(stripped) and all(char in DITTO_MARKS for char in stripped)
