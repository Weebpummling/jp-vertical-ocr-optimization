# Private data home — path convention

Per the decisions record (`docs/PLAN.md`): all research data lives on the lead's
machine, outside this repository's working tree, at a fixed local path. Committed code
must reference it via the `JP_OCR_DATA` environment variable — never by absolute path.

```
%USERPROFILE%\jp-ocr-data\
├── academy\        the 15k academy dataset (cohorts_output.xlsx and successors)
├── groundtruth\    ReferenceTruth: split-manifest.csv, registration.json,
│                   and (from Phase 1) verified page-level transcriptions
├── manuals\        personal-copy technical manual scans (Phase S)
├── benchmarks\     benchmark sample images/transcriptions (typed vertical-text set,
│                   engineering tables)
└── (working)       image caches etc. may be added as siblings; same rules apply
```

Rules:

- Nothing in this tree is ever committed, uploaded, or published as a side effect.
  Public artifacts about it are limited to hashes and aggregate counts (see
  `docs/ground-truth-split.md`).
- Backup: none, by the lead's decision (2 Aug 2026 -- PLAN.md decision 8). This
  folder is the single copy. Do not add a second one.
- Integrity anchor: `academy\cohorts_output.xlsx` SHA-256
  `dccb9dff01009676fab7bd92bd004215583a5807855105b6dacfe2fa7355d7e5`.
