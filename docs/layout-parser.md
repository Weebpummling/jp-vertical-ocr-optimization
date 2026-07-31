# Layout-Parser — verification use only · DECIDED (31 Jul 2026)

**Question:** can [Layout-Parser](https://github.com/Layout-Parser/layout-parser)
be integrated into this project?

**Verdict: not applicable to the reading path; usable for data verification only.**

Layout-Parser is a bottom-up per-page layout detector — exactly the approach this
project exists to invert (see "Why this repo exists" in the README). Putting it in
Layer 2 in place of template registration would re-adopt the failure mode that
killed the prior effort. It is therefore **not** part of the pipeline.

What survives review is a verification role, consistent with the human-primary
rule (machines corroborate and flag):

- Its model zoo includes three Detectron2 models trained on **HJDataset**
  (250k+ layout annotations over row-structured historical Japanese documents —
  biographical directories, structural cousins of the 停年名簿 grid). Categories:
  Page Frame / Row / Title Region / Text Region.
- Those row detections can run as an **independent audit signal**: where the
  detector's rows and the registered template disagree, flag the page for human
  attention. A Layer 9 / benchmarks role — never authoritative, never in the
  reading path.

Practical notes, if the audit role is ever built:

- Detectron2 has no Windows wheels — containerize (pinned CPU-inference image in
  the existing Docker Compose). A few seconds per page on CPU is fine offline.
- The library is in maintenance mode (last release v0.3.4, Apr 2024); pin it.
- Apache 2.0 — compatible. HJDataset *images* are request-gated, but that only
  matters for retraining; the pretrained models download freely.
- NDLkotenOCR's own layout stage (already planned in Layer 4) is trained on NDL
  scans and dominates for roster pages; Layout-Parser's only marginal value is
  the explicit Row category and a second, independent detector for agreement
  scoring.

Entry criterion, should it be picked up: a spike measuring HJDataset row-detection
agreement against template registration on the Spike C pages (pid 1449426, frames
60±). High agreement → optional QA container under `benchmarks/`; low → drop.
