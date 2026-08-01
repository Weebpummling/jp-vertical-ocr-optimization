# Layer 3 — Transcription workstation

The human-primary core. Three panes: zoomable page (cell auto-centered) · structured entry
form (氏名, 兵科, 階級, 職名, 任官年月日, seniority, notes) · candidate/verification panel
(OCR + VLM + propagation + prior-year values).

Requirements that are not negotiable:

- **Keyboard-first and IME-aware** — a whole officer enterable without the mouse.
- **Controlled-vocabulary autocomplete** for branch/rank/post → normalized in one or two keystrokes.
- **Date normalizer** parses 明治/大正/昭和 to canonical dates; ambiguous parses are **flagged,
  not guessed**.
- **Difficult-character toolkit** — variant palette (kyūjitai↔shinjitai), radical/IDS lookup, and
  attach-the-cropped-glyph when a character cannot be typed, so reading is never blocked.
- **Furigana and per-character uncertainty capture**; one-click seal/damage flag → alt-scan flip
  or expert queue.
- **Suggestions look visually distinct from confirmed values.** The reader transcribes; the
  machine offers. That independence is the entire statistical basis for treating machine
  agreement as corroboration.

Stack: React + OpenSeadragon/Mirador over the FastAPI core.

## What exists

The **read side of the API** — where every officer and every field sits on a
page. This is the contract the three panes consume: the viewer centres on a
cell, the entry form binds to its fields, the candidate panel hangs proposals
off the same ids.

| File | Role |
|---|---|
| [`page_service.py`](page_service.py) | All the logic; framework-free, so it tests without a server or a browser |
| [`api.py`](api.py) | Thin HTTP routing over it |
| [`test_page_service.py`](test_page_service.py) | Synthetic spreads for CI, plus a real-page check that skips when the cache is absent |

```bash
pip install -r requirements.txt
uvicorn app.api:app --reload          # from the repository root
python -m unittest discover -s app -p "test_*.py"
```

| Endpoint | Returns |
|---|---|
| `GET /health` | Service status and the loaded template ids |
| `GET /templates` | Field labels per template, each with `confirmed` and `evidence` so the UI can show a provisional label differently from a settled one |
| `GET /volumes/{pid}/pages/{frame}` | Officer strips and field rectangles. `?panel=` selects the page of the spread (0 = right-hand), `?crop_urls=true` adds IIIF region URLs |

Two behaviours worth knowing before building against it:

- **A page that registers against no template returns 422, not a guess.** Index
  pages, section dividers and badly degraded panels are human tasks; the API
  will not invent a grid for them.
- **`needs_review` and per-cell `suspect` mean an edge was inferred**, not seen —
  an interpolated column ruling or an unmatched band. Render those cells as
  needing attention rather than presenting a confident crop.

## Not built yet

The three panes themselves, and the whole write side. Creating observations
touches audited tables and no code path may author a value without a human
behind it, so those endpoints land together with authentication.