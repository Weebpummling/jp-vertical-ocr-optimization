"""Load the controlled vocabularies from data/vocab/*.csv into the database.

`db/schema.sql` creates rank_vocab, branch_vocab and kanji_variant but never
populates them, and nothing else does either -- so on a fresh database all three
are empty. That is not cosmetic: observation.rank_code and observation.branch_code
are foreign keys into those tables, so with them empty **no observation carrying a
rank or branch can be inserted at all**. This script closes that gap.

    python scripts/load_vocab.py            # load
    python scripts/load_vocab.py --dry-run  # count what would be written

Writes directly rather than emitting SQL to be piped into a database client. The
old pipe existed because the database was a container; it is a local file now,
and piping Japanese through a Windows console was its own hazard - cp932 cannot
encode 步 (U+6B65), which appears in branch.csv.

Idempotent: every row is an upsert keyed on the primary key, so re-running after
a vocabulary edit updates in place. It does not delete rows removed from the
CSVs -- vocabularies are referenced by foreign keys, and silently dropping a code
that observations point at would fail loudly at best and orphan data at worst.
Removals are deliberate migrations, not a side effect of a reload.

These tables are not attributed to a worker: they are loaded from
version-controlled CSVs, so their provenance is the git history.

`variants` is `;`-separated in the CSVs (the convention scripts/lint_vocab.py
enforces) and a JSON array in the database.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402

VOCAB = ROOT / "data" / "vocab"


def variants(value: str | None) -> str:
    """A ';'-separated variant list as a JSON array."""
    return json.dumps([v.strip() for v in (value or "").split(";") if v.strip()],
                      ensure_ascii=False)


def blank_to_none(value: str | None) -> str | None:
    return value if value else None


def rows(name: str):
    with open(VOCAB / name, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


TABLES = {
    "rank_vocab": (
        "rank.csv", "rank_code",
        ["rank_code", "label_ja", "label_en", "seniority_order",
         "variants", "valid_from", "valid_to"],
        lambda r: (r["rank_code"], r["label_ja"], blank_to_none(r["label_en"]),
                   int(r["seniority_order"]), variants(r["variants"]),
                   blank_to_none(r["valid_from"]), blank_to_none(r["valid_to"])),
    ),
    "branch_vocab": (
        "branch.csv", "branch_code",
        ["branch_code", "label_ja", "label_en", "category",
         "variants", "valid_from", "valid_to"],
        lambda b: (b["branch_code"], b["label_ja"], blank_to_none(b["label_en"]),
                   blank_to_none(b.get("category")), variants(b["variants"]),
                   blank_to_none(b["valid_from"]), blank_to_none(b["valid_to"])),
    ),
    "kanji_variant": (
        "kanji_variant.csv", "variant_char",
        ["variant_char", "canonical_char", "note"],
        lambda k: (k["variant_char"], k["canonical_char"], blank_to_none(k.get("note"))),
    ),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="count without writing")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.dry_run:
        for table, (csv_name, _, _, _) in TABLES.items():
            print(f"{table:<15} {len(list(rows(csv_name))):>4} rows in {csv_name}")
        return 0

    with db.session() as conn:
        cur = conn.cursor()
        for table, (csv_name, key, cols, to_values) in TABLES.items():
            updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != key)
            sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
                   f"VALUES ({', '.join('?' for _ in cols)}) "
                   f"ON CONFLICT ({key}) DO UPDATE SET {updates}")
            written = 0
            for row in rows(csv_name):
                cur.execute(sql, to_values(row))
                written += 1
            print(f"{table:<15} {written:>4} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
