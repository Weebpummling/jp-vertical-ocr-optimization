"""CI lint for controlled vocabularies (docs/PLAN.md, Phase 0).

Checks the invariants the pipeline relies on:
  - rank.csv:  unique rank_code, strictly increasing unique seniority_order
  - branch.csv: unique branch_code, unique label_ja, no variant duplicated
    across rows or colliding with a canonical label
  - kanji_variant.csv: unique variant_char, variant != canonical
Exit 1 on any violation.
"""
import csv
import sys
from pathlib import Path

VOCAB = Path(__file__).resolve().parent.parent / "data" / "vocab"
errors: list[str] = []


def rows(name: str):
    with open(VOCAB / name, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def unique(name, field, values):
    seen = set()
    for v in values:
        if v in seen:
            errors.append(f"{name}: duplicate {field}: {v!r}")
        seen.add(v)
    return seen


ranks = list(rows("rank.csv"))
unique("rank.csv", "rank_code", [r["rank_code"] for r in ranks])
orders = [int(r["seniority_order"]) for r in ranks]
if orders != sorted(orders) or len(set(orders)) != len(orders):
    errors.append("rank.csv: seniority_order must be strictly increasing and unique")

branches = list(rows("branch.csv"))
unique("branch.csv", "branch_code", [b["branch_code"] for b in branches])
canon = unique("branch.csv", "label_ja", [b["label_ja"] for b in branches])
seen_variants: set = set()
for b in branches:
    for v in filter(None, b["variants"].split(";")):
        v = v.strip()
        if v in seen_variants:
            errors.append(f"branch.csv: variant {v!r} appears under multiple codes")
        if v in canon:
            errors.append(f"branch.csv: variant {v!r} collides with a canonical label")
        seen_variants.add(v)

kv = list(rows("kanji_variant.csv"))
unique("kanji_variant.csv", "variant_char", [r["variant_char"] for r in kv])
for r in kv:
    if r["variant_char"] == r["canonical_char"]:
        errors.append(f"kanji_variant.csv: {r['variant_char']} maps to itself")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"vocab OK: {len(ranks)} ranks, {len(branches)} branches, {len(kv)} kanji variants")
