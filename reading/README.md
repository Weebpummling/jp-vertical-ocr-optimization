# Layers 2, 4 & 5 — Structure, machine reading, propagation

**Structure registration** — deskew and align each page to its template using ruling lines as
anchors; assign fields by position; audit rows against the monotone seniority sequence.

**Machine reading (proposal only)** — independent engines with independent error modes
(see `docs/ndl-prior-work.md` for the NDL naming and what's precomputed):

1. **NDL's precomputed OCR text** — every roster volume has full text with per-line
   pixel boxes (`fulltext-json`); template registration bins the boxes into officer
   cells, making this a zero-cost first proposal engine.
2. **An NDL OCR engine run by us** — NDLOCR-Lite (modern typeset — likely fit, since
   Spike C showed the rosters are typeset) vs NDLkotenOCR-Lite (classical materials);
   the benchmark suite decides which. CPU-capable either way.
3. **VLM / OCR-free extractor** — reads an officer cell in context, returns structured fields.

Agreement between engines is strong corroboration. Disagreement raises a flag with
candidates side by side. **No engine may author a final value.**

`proposals.py` implements that rule as code, ported from the prior effort — the one part
of it worth keeping, earned over 29 benchmark runs. Its geometry is not carried forward
(standing commitment 3); its downstream semantics are:

| Concern | Rule |
|---|---|
| Lexicon hits | Evidence, never transcription. `Suggestion` has no `accepted` field and is frozen. |
| Classification | `probable` requires a high best score **and** a clear margin over the runner-up. A 0.95 best behind a 0.94 runner-up is a coin flip, so it grades `ambiguous`. |
| Variant forms | `variant_equal` is its own agreement status, not a flavour of `agree` — 榮 vs 栄 is the same name, but which form the page prints is a real question. Folding is a vocab lookup, so 齋/斉 stay distinct. |
| Repairs | Conservative and self-reporting. A seniority number cropped to `12` between 113 and 111 recovers to 112, recording the original reading and the inference method. Several candidate prefixes means no repair, not a best guess. |
| Empty fields | Blank beats plausible. A field with no trustworthy reading stays empty. |

Thresholds in that module are **provisional** and must be calibrated against the hold-out
split before any accuracy number is quoted (standing commitment 6); `benchmarks/` owns
that calibration.

```
python -m unittest discover -s reading -p "test_*.py" -v
```

MLLMs read vertical Japanese worse than horizontal out of the box, so the VLM is fine-tuned
on the project's ground truth — the largest accuracy lever short of human reading.

**Cross-year propagation** — a confirmed officer in year *Y* is pre-filled in *Y+1*,
positioned by expected seniority. Only changeable fields are re-verified. Change detection
*is* the task, and it produces career transitions as a by-product. Propagated values are
marked unconfirmed and require an affirmative keystroke.