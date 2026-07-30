# Layer 9 — QC, ground truth & the standing benchmark suite

**Benchmark scores gate any change to the reading pipeline.** A change that improves one
layout family and regresses another does not ship.

Two fixed benchmark sets:

- **Typed vertical-text OCR baseline** — vertical Japanese in *typed* glyphs. Establishes the
  practical upper bound of the OCR engine on clean text, calibrating expectations before the
  degraded rosters.
- **Hand-transcribed engineering tables** — engine datasheets and weight/limit tables from the
  secondary corpus, measuring structured-table extraction on a second layout family.

Ground-truth pages are **held out and re-served blind** to measure per-person and per-field
accuracy for humans *and* every automated component.

Live metrics: throughput · flag rate · inter-annotator agreement on gold · linkage yield ·
event-extraction precision/recall · **coverage-vs-worklist**, the guard against silent
incompleteness.

Benchmark *definitions and scores* are versioned here. Benchmark *data* is not (see `data/README.md`).