# data/

**No research datasets live here.** Only controlled vocabularies are versioned.

Everything else is deliberately excluded by `.gitignore`:

- **Ground truth** — the human-verified partial dataset is the project's accuracy yardstick
  and its VLM fine-tuning set. It only remains an honest hold-out if it is never published
  and never mixed with production data.
- **Transcription output** — officer-year panels and event tables. Released, if
  at all, on the project's terms.
- **Source scans** — NDL / JACAR / personal copies are not ours to redistribute. Store the
  stable reference (PID, IIIF manifest URL, JACAR ref) instead of the image.

## What is here

`vocab/` — rank (階級), branch (兵科), and unit (部隊) controlled vocabularies, with
kyūjitai/shinjitai variant equivalences. These are code-like: small, reviewable, and
essential for the closed-vocabulary rejection rule in Layer 2.