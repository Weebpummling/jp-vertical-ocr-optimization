# Spike A — Kanpō full-text coverage · ANSWERED (29 Jul 2026)

**Question:** does machine-readable full text cover the military 叙任及辞令 sections of
the *Kanpō* for 1920–1937, and how do we get it?

**Verdict: the text exists but is not exportable — the miner runs its own OCR, scoped
to section pages located via IIIF manifest TOCs.** This is the contingency the plan
anticipated ("weak years get scoped OCR"), except it applies to the whole corpus and is
offset by two strong mitigations found below.

## Findings (verified against live endpoints)

1. **Coverage is total and open.** The complete Kanpō run 1883-07-02 → 1952-04-30
   (~21,000 issues) is in NDL Digital Collections, all インターネット公開
   (internet-public), one PID per issue, Public Domain Mark. Verified by direct IIIF
   fetches, e.g. pid 2955038 = 1922-05-01, 2955928 = 1925-04-01 (42 canvases),
   2959225 = 1936-02-28. PIDs run roughly sequential by issue date.
2. **NDL did OCR the Kanpō** in the FY2020–21 mass-OCR program (Official Gazettes:
   ~21,000 items / 387,962 images per the project page) and the text feeds the
   dl.ndl.go.jp full-text search UI. **But there is no public API to that search or its
   text** — it is a UI feature only.
3. **The Next-Generation Digital Library does NOT include Kanpō** — verified:
   `lab.ndl.go.jp/dl/api/book/2955038` returns HTTP 500 (its scope is copyright-expired
   books/classics only). So the convenient `fulltext-json` route that works for the
   rosters (see Spike B) is unavailable for Kanpō.
4. **Mitigation 1 — the manifests carry per-issue TOCs.** IIIF manifest `structures`
   list each issue's sections with canvas pointers, including the personnel-orders
   section — labeled in **old kanji forms 敍任及辭令** (match both old and new forms).
   Verified on pid 2957025 (1928-11-10): range 「授爵・敍任及辭令 …」 starts at canvas 5.
   So the miner can locate exactly the pages it needs without OCR-ing whole issues.
   Caveat: not every issue has the section (verified absent in two sampled issues).
5. **Mitigation 2 — NDL's OCR stack is open-source** (github.com/ndl-lab; the
   modern-documents **NDLOCR-Lite** is the engine of choice for the typeset Kanpō —
   naming guide in `docs/ndl-prior-work.md`), i.e. we can produce comparable text
   ourselves, CPU-capable, on just the section pages.

## Consequence for Phase 4

The miner's retrieval stage becomes: enumerate issue PIDs by date (sequential PIDs +
`opensearch?title=官報 YYYY年MM月DD日` as resolver) → fetch manifest → filter
`structures[].label` for 敍任及辭令/叙任及辞令 → OCR only those canvases with NDLOCR →
regex/dictionary extraction as designed. Compute is modest: a few pages per issue ×
~250 issues/year × 18 years, embarrassingly parallel, CPU-friendly.

Print quality supports this: a sampled 1925 issue (pid 2955928, frame 5) is clean dense
typeset — well within NDLOCR's design envelope.

## Stage-0 survey results (kanpo/survey_sections.py, 29 Jul 2026)

Measured on four sample months (~97 issues). PID-walking resolution works: ~24–25
regular issues/month, and **100% of issues carry a `structures` TOC**. But the
personnel-section *label* appears in the TOC far less often than hoped, and the rate is
era-dependent:

| Month | Issues | TOC present | 敍任及辭令 itemized |
|---|---|---|---|
| 1922-04 | 24 | 24 | **0** |
| 1925-04 | 25 | 25 | 11 |
| 1930-04 | 24 | 24 | 5 |
| 1935-04 | 24 | 24 | 4 |

Additional facts: a manual probe of a 1922 issue found the section absent from its
expected position (issues run ~42 canvases, so blind full-issue OCR is expensive).
*Update (号外 question resolved by the deployment-sources probe,
`deployment/crosscheck-sources.md`):* 号外 are **bound into the same-day issue's PID as
trailing canvases** (labeled `号外/p1` in `structures`); only Sunday/holiday 号外 get
their own sequential PID. The sequential walk therefore covers them — but appendix
(附録) contents are invisible to TOCs and need first-page classification. Also verified:
in the mid-1930s window, pid = issue番号 + 2956479.

**Revised conclusion:** manifest TOCs are a useful *accelerator*, not a *locator*. The
miner's retrieval stage needs, in order: (1) TOC hit → go straight to the section;
(2) no TOC hit → cheap page-header scan (each Kanpō page carries a section header line;
OCR only a thin header strip per page to find 敍任及辭令 pages); (3) separate 号外
enumeration (open: where their PIDs live); (4) check whether NDL Search `dcndl` records
carry fuller TOCs than the IIIF manifests. Also open: whether low itemization months
reflect missing labels or genuinely less-frequent personnel publication — distinguishing
these needs the header-scan fallback in place.

## Residual risks

- Our own OCR quality on Kanpō ≠ NDL's search text; precision/recall must be measured
  against ground truth as planned (§20).
- 号外 coverage is unquantified until their PID scheme is found.
