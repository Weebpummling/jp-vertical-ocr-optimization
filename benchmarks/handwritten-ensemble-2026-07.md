# Experimental benchmark — OCR vs vision-LLM on Shōwa handwriting (2026-07-31)

**Status: experimental, n=1 document.** First measured comparison of the two
machine-reading engines on real handwritten material, run end-to-end on JACAR
ref **C14030562600** (髑髏隊ヲ語ル, 31 pages, pen 行書/kyūjitai, JBIG2 scans
rendered at 150 DPI). Both engines are *proposal* engines under the standing
commitments — nothing here is an accuracy claim against human truth, because
no human-verified transcription of this document exists yet. What is measured
is **cost, throughput, self-declared coverage, and cross-engine agreement**.

Reproduce with [`ensemble_agreement.py`](ensemble_agreement.py) (engine
outputs live in the private data home, not this repo).

## Engines

| | Engine A — NDLOCR-Lite | Engine B — vision-LLM reading |
|---|---|---|
| Version | v1.2.3, tegaki3 handwriting models (Apr 2026), CPU | Claude (Fable-5 class), 4 parallel agents, 7–8 pages each |
| Method | `ocr.py --sourcepdf`, default thresholds | Page PNGs read with iterative crop/zoom; instructed to mark uncertainty (〓 / 〔?〕) rather than guess; blind to Engine A's output |
| Wall time | **36.1 s** total (1.17 s/page) | ~63 min parallel (~2.3 h serial-equivalent) |
| Marginal cost | ~0 (local CPU) | **905,106 tokens** total ≈ 29.2K tokens/page ≈ $5–20/document at Jun 2026 API list prices (tier-dependent) |
| Output | Reading-order text, per-line boxes + confidence, text-layer PDF | Transcription with uncertainty marks, drawing/map/stamp descriptions, folio metadata |
| Usable as a reading text | No — heavily garbled on 行書 (e.g. title read 髑髏隊ヲ**認**ム for 髑髏隊ヲ**語**ル) | Yes — the deliverable transcription |

## Scores

**Engine B self-declared coverage:** 25,527 Japanese characters transcribed;
1,902 marked unreadable 〓 (**7.5%**); 592 low-confidence 〔?〕 marks.

**Cross-engine corroboration** — for each substantive Engine-A line (≥6 chars,
613 lines), the fraction of its characters found in order in Engine B's reading
of the same page (difflib matching blocks; marks and notes stripped):

| Engine A confidence | Lines | Mean corroboration |
|---|---:|---:|
| ≥ 0.90 | 4 | 0.80 |
| 0.80 – 0.90 | 338 | 0.72 |
| 0.70 – 0.80 | 178 | 0.65 |
| 0.50 – 0.70 | 68 | 0.60 |
| < 0.50 | 25 | 0.48 |

Agreement rises **monotonically** with Engine A's own confidence — the
confidence signal is informative, not noise, and can be used to weight
proposals and route review attention.

**Per-page agreement** (character-sequence similarity of full page texts,
boilerplate stripped): mean **0.55** across 31 pages; clean prose pages
0.75–0.84; near zero on the drawing/roster/calligraphy pages (images 1, 28,
29, 31 — all < 0.25), which correctly self-identify as needing human/
vision-only treatment. Full per-page table: run `ensemble_agreement.py`
against the engine outputs in the private data home.

## Findings

1. **On this material the LLM layer is the primary reader, not an
   enhancement.** Engine A's error rate on pen 行書 is past the usability
   threshold; the deliverable transcription cannot be recovered from it.
   Engine B also covers what OCR structurally cannot: context-driven character
   disambiguation, drawings/maps, translation.
2. **Engine A earns its place as a near-free error model of Engine B.** The
   failure modes are complementary — the LLM fails *fluently* (invisible),
   the OCR fails *visibly*. 36 seconds of CPU buys an independent
   hallucination check, a validated confidence signal, and line-aligned boxes
   that become fine-tuning ground truth once lines are human-verified.
3. **Main efficiency lever identified:** Engine B spent most tokens on layout
   rediscovery (iterative cropping; 36–101 tool calls per agent) — work Engine
   A already does in its JSON boxes. Feeding pre-segmented line crops to the
   vision engine should cut LLM cost substantially. Untested; candidate for
   the next run.
4. **Expected long-term rebalance** (per Spike E): verified lines fine-tune
   the PARSeq recognizer until the economical architecture inverts — OCR
   proposes everything, the LLM adjudicates disagreement spans only.

## Caveats

- **Agreement is not accuracy.** Both engines can err together; the true CER
  of each engine awaits blind human verification of this document (which will
  also convert this from an agreement benchmark into an accuracy benchmark).
- n=1 document, one hand, one scan quality. The 1935 companion document
  (C14030374300) and future JACAR pulls widen the sample.
- Engine B's token count includes agent tool-call overhead, not pure
  inference; the cost band converts total tokens at list prices without an
  input/output split.
