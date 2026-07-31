# Controlled vocabularies

These are the closed vocabularies the pipeline relies on. Their job is to make reads
**rejectable**: an out-of-set rank or branch value is auto-rejected rather than silently
accepted.

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
1920s renaming).

## Roster-side verification (31 Jul 2026)

Method: token counts over NDL's precomputed full text for three editions spanning the
window — 大正12 (1923, pid 930894), 大正15 (1926, pid 1908494), 昭和10 (1935,
pid 1449474). Machine text is used only to *inventory the labels that occur*; it decides
nothing about any officer.

| Verified | Result |
|---|---|
| Ranks | Complete. All tokens resolve, kyūjitai generals (少將/中將/大將) via variants. 准尉 in force throughout; 特務曹長 absent, consistent with the 1920 renaming. |
| Combat branches | 步兵・騎兵・砲兵・野砲兵・野戰砲兵・重砲兵・山砲兵・野戰重砲兵・工兵・輜重兵・憲兵 all present in every sampled edition and all resolve. Kyūjitai forms dominate (步兵 ~5,000/edition vs 歩兵 ~300–600). |
| 航空兵 | 0 (1923) → 468 (1926) → present (1935). `valid_from = 1925-05-01` set accordingly — confirmed by the corpus itself. |
| 要塞砲兵 | Zero occurrences 1923+, consistent with the 1919 merge into 重砲兵. The variant stays for the 1914/1917 anchor volumes. |
| Folds | 戰/聯/臺 added to `kanji_variant.csv` — the survey's dominant forms (野戰砲兵, 聯隊, 臺灣) fail to fold without them. |

**Freeze decisions (31 Jul 2026, lead):**

- **法務部 / 技術部: dropped.** Zero occurrences in all three sampled editions — they
  are not officer branches inside the window. If a later volume ever surfaces either,
  that is a vocabulary change with its own migration, not a reload.
- **The vocabularies are frozen as of this decision**: 11 ranks, 14 branches,
  28 kanji variants. Changes from here are logged, argued-for events.

One coverage observation, recorded for the worklist rather than the vocabulary:
軍醫 falls from ~2,100 (1923/1926) to 214 in the 1935 edition, 獸醫 similarly — the
Shōwa-era editions likely split 各部 coverage into separate publications.

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
