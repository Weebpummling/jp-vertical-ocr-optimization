# VLM selection analysis

*Prepared July 2026 for decision #1 in `PLAN.md`. Recommendation: run the Phase-2
bake-off with the three shortlisted models below; do not commit to one on paper.*

## The constraint set

- **Role:** proposal/corroboration engine only (design §9) — reads a cropped officer
  cell, returns structured fields. Never authors a final value.
- **Corpus:** vertically written Japanese, kyūjitai forms, typeset but degraded 1920s–30s
  scans. (Spike C reconnaissance confirmed the rosters are *typeset*, not handwritten —
  materially easier than feared.)
- **Fine-tuning:** LoRA on a few thousand human-verified examples from the ground truth.
- **Hardware:** the project machine has integrated graphics only (no CUDA GPU, 16 GB
  RAM). Fine-tuning therefore happens on a **rented GPU**; local inference means a
  **small quantized model on CPU**, or hosted inference.
- **License:** must permit research use without friction; permissive preferred.

## What the research says (the load-bearing findings)

The field has a benchmark aimed exactly at our problem: *Evaluating MLLMs on Vertically
Written Japanese Text* (arXiv 2511.15059, LREC 2026; datasets JSSODa synthetic +
VJRODa real-world, from NDL web-archive pages). Four findings drive the shortlist:

1. **Every general-purpose VLM reads vertical Japanese far worse than horizontal.**
   Qwen2.5-VL-7B: 7.75% character error rate horizontal → **112% vertical** (it falls
   into repetition loops and reads columns left-to-right). This validates the design's
   §4.2 caveat quantitatively.
2. **Fine-tuning nearly erases the gap on clean text** — Qwen2.5-VL-7B went from 112% →
   **0.10% CER** after one epoch on 18k synthetic vertical images. The vertical deficit
   is a data problem, not an architectural one. Our LoRA plan is the right lever.
3. **Synthetic-only tuning does not fully transfer to real degraded pages** (best
   post-FT real-world CER was ~40%). The paper's conclusion: real-world vertical
   performance needs training on *real* scans — which is precisely what our
   human-verified ground truth is. This strengthens the case that the ground-truth
   train split is the project's most valuable ML asset.
4. **Small specialized OCR models beat giant generalists on real vertical text.**
   PaddleOCR-VL (0.9B params) scored CER 20.1 on the real-world set — better than
   GPT-5-class models. Specialization > scale for this task.

## Shortlist for the Phase-2 bake-off

### 1. Qwen3-VL 4B / 8B — primary candidate

Apache 2.0 at every size. The Qwen-VL architecture was the *largest beneficiary of
vertical fine-tuning* in the benchmark, and Qwen3-VL ships with official vertical-
Japanese OCR support. First-class LoRA tooling (LLaMA-Factory, ms-swift — our
few-thousand-example dataset drops straight in), the best JSON-adherence reputation
among open VLMs (we need structured fields, not prose), and a mature GGUF quantization
path for CPU inference (4B ≈ 5 GB, 8B ≈ 8 GB at Q4). Plan: LoRA-tune 8B on a rented
GPU; run quantized locally. Caveat: its vertical-JA ability has official claims but no
published number on the real-world benchmark — measure, don't trust.

### 2. Sarashina2.2-Vision-3B / -OCR (SB Intuitions) — Japanese-native contender

MIT license, ~3–4B params. The only open family *designed* for vertical Japanese: the
OCR variant reads vertical order correctly zero-shot with real-world CER 22.6
(self-reported — roughly 2× better than anything post-synthetic-FT in the paper). Its
Japanese typography prior may matter for kyūjitai, where Qwen starts from a
Chinese-centric character prior. Small enough that QLoRA fits in ~10–12 GB — the one
candidate tunable without renting big iron. Costs: custom architecture outside the
standard tuning frameworks (hand-written Transformers+PEFT loop), and the OCR variant
emits Markdown rather than JSON — either post-parse it or fine-tune the Vision-3B chat
variant for field extraction.

### 3. Gemma 3 12B — the zero-shot control

Strongest *un-tuned* generalist on vertical Japanese in the benchmark (its 27B sibling
beat GPT-4.1 on the real-world set). Include it to measure what our fine-tuning is
actually buying: if Gemma wins zero-shot but loses post-FT, the tuning pipeline is
working. Well supported in tuning frameworks; 12B-Q4 runs in ~9 GB. Downsides: smallest
fine-tuning gains in the paper (less headroom), and a use-policy license rather than
pure Apache/MIT.

### Plus: PaddleOCR-VL as a third corroboration engine (not a bake-off entrant)

Apache 2.0, 0.9B params, best published real-world vertical-Japanese CER (20.1). It is
not promptable and doesn't fit the "structured fields from a prompt" role, but as a
*third independent reading* next to NDLkotenOCR-Lite it would strengthen the agreement
signal at near-zero compute cost. Windows tooling (PaddlePaddle) is the friction point;
evaluate during Phase 2 rather than committing now.

## Rejected candidates (and why)

| Model | Reason |
|---|---|
| IBM Granite Vision | Document-extraction specialist but English-centric; no Japanese/vertical evidence. The design's "Granite-Vision-class" placeholder is superseded |
| DeepSeek-OCR | Fails vertical Japanese outright (CER 182 on the real-world benchmark) |
| GOT-OCR2 | Poor Japanese performance in independent bake-offs |
| PLaMo 2.1-VL | Model card explicitly says not optimized for OCR |
| Stockmark-2-VL-100B | Undeployable at our scale |
| InternVL3 | Mid-pack zero-shot, weak fine-tuning response in the benchmark; mixed licenses |
| Phi-4-multimodal | No Japanese-OCR evidence; thinner vision-tuning tooling |
| llm-jp-4-VL 9B | Beta, unproven on vertical OCR — re-check when it matures |

## Also actionable now

NDL updated its OCR stack since the design was written: **NDLOCR-Lite** (new
lightweight CPU-only engine for modern documents, runs on Windows 11) and
**ndlkotenocr_cli v1.2** (April 2026, improved handwritten-character recognition).
Use the newest releases when standing up Layer 4 — and note NDLOCR-Lite (modern
documents) may suit the typeset Shōwa rosters better than the classical-materials
model; test both.

## Bake-off protocol (Phase 2)

1. Assemble the evaluation set from Spike C pages + ground-truth hold-in examples
   (never the hold-out).
2. Score all three shortlisted models zero-shot on per-field exact match (with variant
   equivalence) over name / rank / branch / post / date fields.
3. LoRA-tune Qwen3-VL-8B and Sarashina2.2-Vision-3B on the ground-truth train split
   (real scans, not synthetic renders — per finding 3). Re-score.
4. Pick on: post-FT field accuracy > JSON adherence > inference cost. Record scores in
   `benchmarks/`.

## Sources

- arXiv 2511.15059 · github.com/llm-jp/eval_vertical_ja (benchmark paper + data)
- github.com/QwenLM/Qwen3-VL (Apache 2.0; sizes; OCR language claims)
- huggingface.co/sbintuitions/sarashina2.2-ocr · sarashina2.2-vision-3b (MIT; VJRODa self-report)
- huggingface.co/PaddlePaddle/PaddleOCR-VL (Apache 2.0; VJRODa 20.1)
- github.com/ndl-lab/ndlocr-lite · ndl-lab/ndlkotenocr-lite (2025–26 releases)
- huggingface.co/ibm-granite/granite-vision-3.3-2b (English-centric document VLM)
