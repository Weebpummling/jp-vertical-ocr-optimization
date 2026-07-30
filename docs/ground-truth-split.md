# Ground-truth registration & split — record of the irreversible call

Registered **29 July 2026** by the lead. The human-verified academy dataset is the
project's `ReferenceTruth` asset. The data lives in the private data home on the lead's
machine (see `docs/data-home.md`) and never enters this repository; this page holds the
tamper-evidence.

## What was fixed

| Item | Value |
|---|---|
| Records registered | 15,029 |
| Split | 10,595 train / 4,434 hold-out (29.5%) |
| Split rule | `holdout ⇔ sha1(academy_id + "jp-vertical-ocr-v1") % 100 < 30` — hash-deterministic, order-independent, no seed to lose |
| Source file SHA-256 | `dccb9dff01009676fab7bd92bd004215583a5807855105b6dacfe2fa7355d7e5` |
| Manifest SHA-256 | `b6ae9c0dbad43eec68cdc4859fb238687018fb53ad984270b37699eb25d198c1` |
| Registration script | `benchmarks/register_reference_truth.py` (this repo) |
| Duplicate identity keys | 1 (two same-name officers in one cohort+branch; disambiguated by deterministic sequence suffix in `academy_id`) |

Any future change to the split must produce a new manifest hash recorded here with a
written rationale — a silent re-split is detectable by hash mismatch.

**Hold-out discipline** (owner: the lead): hold-out rows are never used for VLM
fine-tuning, prompt iteration, threshold fitting, or development-time error analysis.

## Coverage map (per academy cohort)

Every cohort 15–44 is represented in both halves; no stratum has zero hold-out.

| Cohort | Train | Hold-out | | Cohort | Train | Hold-out |
|---|---|---|---|---|---|---|
| 15 | 501 | 206 | | 30 | 441 | 189 |
| 16 | 371 | 178 | | 31 | 346 | 143 |
| 17 | 258 | 104 | | 32 | 297 | 131 |
| 18 | 660 | 260 | | 33 | 305 | 132 |
| 19 | 751 | 317 | | 34 | 240 | 103 |
| 20 | 206 | 69 | | 35 | 236 | 77 |
| 21 | 291 | 126 | | 36 | 226 | 104 |
| 22 | 506 | 210 | | 37 | 205 | 95 |
| 23 | 522 | 217 | | 38 | 248 | 92 |
| 24 | 524 | 210 | | 39 | 213 | 80 |
| 25 | 512 | 228 | | 40 | 162 | 62 |
| 26 | 508 | 229 | | 41 | 171 | 68 |
| 27 | 524 | 237 | | 42 | 151 | 66 |
| 28 | 466 | 180 | | 43 | 158 | 68 |
| 29 | 373 | 162 | | 44 | 223 | 91 |

## Nature of this ground truth

This is a **person-level** verified dataset (identities, cohorts, branches, aliases,
covariates, outcome flags) — the design's §3.2 asset. It anchors record linkage
(true-match training), identity resolution, and coverage accounting. It is *not*
page-level transcription truth: per-field transcription accuracy (names as printed on a
specific roster page) will additionally need verified page transcriptions, which accrue
from Phase 1 onward and join `ReferenceTruth` under the same split discipline —
an officer's page-level truth inherits their person-level `use_flag`, so the hold-out
never leaks through a different granularity.
