# Controlled vocabularies

These are the closed vocabularies the design relies on. Their job is to make reads
**rejectable**: an out-of-set rank or branch value is auto-rejected rather than silently
accepted (design v2.1 §4.3, Lever 3).

| File | Covers |
|---|---|
| `rank.csv` | 階級 — commissioned ranks, with `seniority_order` for rank-consistency validation |
| `branch.csv` | 兵科 and 各部 services |
| `kanji_variant.csv` | Kyūjitai/shinjitai and orthographic equivalences (齋 ≡ 斎) |

## Status: draft, partially verified

`branch.csv` is now reconciled against the **academy dataset's observed labels**
(13 distinct values over 15,029 officers): 歩兵 9624 · 工兵 1092 · 野戦砲兵 1084 ·
騎兵 918 · 輜重兵 652 · 野砲兵 514 · 重砲兵 396 · 砲兵 335 · 野戦砲 119 · 要塞砲兵 113 ·
航空兵 103 · 要塞砲 53 · 野戦重砲兵 26. Era-variant artillery names are mapped as
`variants` of canonical codes (野戦砲/野砲兵 → 野戦砲兵; 要塞砲兵/要塞砲 → 重砲兵, the
1920s renaming). **The roster side still needs its own verification pass** against real
1922+ pages before freeze. Specifically unresolved:

- Whether the artillery variant→canonical mapping matches how each roster *edition*
  prints the branch (the mapping above reflects academy-era usage).
- Exact `valid_from`/`valid_to` dates — 航空兵 became a separate branch in 1925, and the
  兵科 system was reorganized in 1940 (outside the window; relevant to Phase S).
- Which service departments (各部) appear in the seniority lists at all, versus being
  listed separately.
- The full kyūjitai variant set. `variants` currently holds only obvious forms.

Anything read from a real volume that fails against these lists is a signal to **fix the
vocabulary**, not to force the read.

## Conventions

- `rank_code` / `branch_code` are stable ASCII identifiers — they are foreign keys in
  `db/schema.sql` and must not be renamed once data exists.
- `seniority_order` ascends. Rank-consistency validation of Kanpō promotions compares this
  value, so gaps are fine but order must be right.
- `variants` is a `;`-separated list of alternate glyph forms that must **not** count as a
  disagreement in field-level agreement scoring.
- Empty `valid_from`/`valid_to` means "in force throughout the 1922–1936 window."
