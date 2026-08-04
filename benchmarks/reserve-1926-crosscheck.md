# Cross-check — 1926 reserve directory vs MA/Tokyo Report 2727 (2026-08-01)

**Status: aggregate-level check, one volume.** First execution of the
bidirectional cross-check recorded in
[`manuals/references/nara-2023-739-report-2727-reserve-officers.md`](../manuals/references/nara-2023-739-report-2727-reserve-officers.md):
the U.S. attaché's 1927 tabulation of the Japanese reserve officer corps
against the digitized directory it was compiled from — 陸軍予備役将校同相当官
服役停年名簿 大正15年4月1日調, NDL pid
[1908490](https://dl.ndl.go.jp/pid/1908490) (949 canvases, Next-Gen DL,
fulltext-json 29.3 MB).

## Method

One officer entry occupies one vertical text column in the directory. NDL's
OCR line boxes (coordjson) are clustered by x-center per frame (new column
when the gap between successive sorted centers exceeds 60 px; frames with
fewer than 5 lines skipped). Column totals then estimate total entries —
no reading of content, layout only. Reproduce with
[`count_roster_columns.ps1`](count_roster_columns.ps1).

## Result

| Quantity | Value |
|---|---:|
| Report 2727, First Reserve officers (1 Apr 1926) | **22,745** |
| Column estimate, pid 1908490 (939 content frames) | **22,768** |
| Difference | +23 (0.10%) |
| Mean columns per frame (two-page spread) | 24.2 (≈12 entries/printed page) |

Supporting scans: the per-officer district pattern `第N(…)` matches 18,107
times (undercount, OCR noise — consistent direction); branch tokens (步兵 213,
砲兵 81…) appear only at section-header rates, confirming branch is not
per-entry text.

## Reading

The American count and the Japanese volume's physical layout agree at the
0.1 % level. The +23 residual is the right order for front-matter and
section-header columns and for split/merged column errors; it is **not** a
per-officer discrepancy claim. Neither source is validated at the cell level
by this check.

## What this does not show

- **No rank × branch cells.** Branch/rank live in section headers, so the
  cell-level comparison against Report 2727's table needs section-boundary
  detection — Layer 2 registration work, queued, not attempted here.
- **Column ≠ verified officer.** Split or merged columns can cancel in the
  total; the estimate is a scale check, not a count of records.
- n=1 volume, one era's layout. The same check should run on an active-list
  volume whose total is independently known before the method is trusted
  generally.
