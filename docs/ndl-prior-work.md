# What NDL has already done on our source documents

*Verified against live endpoints, 29 July 2026. This inventory exists so we never
rebuild something NDL already ships. Naming note: NDL's OCR family has three members —
**NDLOCR** (the heavy FY2021 mass-OCR pipeline that produced the text below),
**NDLOCR-Lite** (2025, lightweight CPU engine for modern typeset documents, runs on
Windows), and **NDLkotenOCR-Lite** (classical/handwritten materials). Project docs name
the specific member; "NDLOCR" unqualified means the family.*

## 1. Every roster volume already has machine text with coordinates

NDL's FY2021 mass OCR covered our seniority-list volumes, and because they are in the
Next-Generation Digital Library, the output is downloadable per volume:

```
GET https://lab.ndl.go.jp/dl/api/book/fulltext-json/{PID}
```

Verified on the 1933 volume (pid 1449426): one 34 MB JSON, **874 page entries, each
with full text and per-line bounding boxes in full-resolution pixels** (page 60 alone:
453 boxed lines). Quality on our known page:

- **Good:** Arabic seniority numbers (165…199 all present), posts (聯隊長 titles),
  era dates (明一九、七、八), court ranks (從五), cohort numbers — and names largely
  correct **including kyūjitai** (田邊松太郞, 中山保三郞 read perfectly).
- **Weak, as the design predicted:** vertical reading order is unreliable and lines
  fragment (熊谷敬一 came out as separate per-character boxes), so the *text stream*
  is not usable as a transcript.
- **The fix is our architecture:** template registration bins the boxes into officer
  cells geometrically — the geometry does the association, NDL's text supplies free
  readings. This makes NDL's OCR a **zero-cost third proposal engine** for Layer 4
  agreement scoring, available before we run any OCR of our own.

## 2. Every roster volume has a name→page search index

```
GET https://lab.ndl.go.jp/dl/api/page/search?f-book={PID}&q-contents={term}
```

Verified: searching 中山保三郞 in the 1933 volume returns exactly page 60. Uses:
cross-year propagation ("find officer X in year Y+1's volume" without scanning),
disappearance handling, and spot-checks during linkage adjudication. Subject to the
same OCR name errors as above — an accelerator, never an authority.

There is also a layout-aware variant (`/book/layouttext/{PID}`, added 2025) — evaluate
during Phase 2 template work.

## 3. Kanpō: text exists but is locked behind the search UI

The FY2021 project OCR'd ~21,000 gazette issues (387,962 images), and that text powers
dl.ndl.go.jp full-text search — but there is **no export API**, and Kanpō is *not* in
the Next-Gen DL (`/book/{kanpo-pid}` returns 500), so the endpoints above don't apply.
Consequence (Spike A): the miner runs **NDLOCR-Lite** itself on the section pages it
locates. NDL's contribution here is the open-source engine plus the IIIF manifests'
article-level TOCs (era-dependent — see the spike-A survey).

## 4. Collection metadata we should ingest rather than discover

- **IIIF manifests** per volume/issue: canvas inventory, high-res image service,
  Public Domain Mark licensing, and `structures` TOCs.
- **欠番 lists**: the Kanpō catalog record documents known missing issues by number and
  date (including specific 号外) — the worklist registry should import these so
  coverage accounting distinguishes "not digitized" from "never held."
- **NDL Search APIs** (OpenSearch / SRU / OAI-PMH) for worklist building — verified
  patterns in `docs/spikes/spike-b-ndl-access.md`.

## 5. Open-source tooling and training data

`github.com/ndl-lab`: the full NDLOCR pipeline, NDLOCR-Lite, NDLkotenOCR-Lite (+ cli,
v1.2 Apr 2026), and the OCR **training datasets** behind them (`lab.ndl.go.jp/data_set/ocr/`)
— relevant both for running engines locally (all CPU-capable) and as auxiliary training
data if VLM fine-tuning needs more vertical-Japanese examples beyond our ground truth.

## Prototype validation (29 Jul 2026)

`reading/prototype_cell_binning.py` runs the full zero-local-OCR path on real pages:
seniority-number boxes anchor column segmentation (more robust than thin vertical
rulings), NDL boxes bin into cells, content+geometry classify fields. On three spreads
of the 1933 volume (branch sections: infantry colonels, infantry captains, artillery):
**20/20 officers per spread, seniority sequences exact and monotone, posts near-perfect
(including 野戰重砲兵-class unit names), cohort numbers good on clean pages.** Names are
partial — duplicate boxes (NDL emits merged and per-char boxes for the same glyphs),
dropped characters, and 〓 unknown-glyph markers — exactly the field the design reserves
for human-primary reading with machine corroboration. Verdict: NDL's text is a real
proposal engine for every field, and for names it corroborates rather than authors —
precisely its designed role.

## Consequences by layer

| Layer | What NDL's prior work changes |
|---|---|
| 2 (structure) | NDL line boxes can bootstrap template building and cross-check our ruling detection |
| 4 (machine reading) | Batch pre-run for rosters starts with **zero local OCR**: NDL text (binned by template) + VLM are the first two engines; our own NDLOCR-Lite/NDLkotenOCR-Lite run is the benchmark-driven third |
| 5 (propagation) | `page/search` gives name→page jumps across volumes |
| 6 (Kanpō miner) | Engine = NDLOCR-Lite run by us; TOCs accelerate location; 欠番 list bounds coverage claims |
| 9 (QC) | Coverage accounting imports known-missing lists; benchmark suite decides which NDL engine reads rosters best |
