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

| `GET /volumes/{pid}/pages/{frame}/image` | The cached page scan, for the viewer |
| `GET /volumes/{pid}/pages/{frame}/region?x&y&w&h` | One rectangle of it, as JPEG — the cell crops |

**Pixels come from our cache, never from the institution.** An annotator
stepping cell to cell would otherwise fire a request at NDL per crop and a tile
storm per page — which is exactly what returned HTTP 429 during development.
Retrieval stays where the politeness lives (one cached fetch per page in
`ingestion/iiif_client.py`); everything the workstation renders is local, so
transcription keeps working with no network at all. A cell's `crop_url` still
points at the public IIIF copy: that is provenance, not the display path.

## The UI

`ui/` — React + OpenSeadragon over Vite, per the stack above.

```bash
uvicorn app.api:app --reload --port 8000   # terminal 1, from the repo root
npm --prefix app/ui run dev                # terminal 2 → http://localhost:5173
```

Vite proxies `/api` to the FastAPI core, so the browser stays same-origin and
there is no CORS configuration to get wrong.

What works: all three panes against a real volume, officer and field navigation
by keyboard, the viewer auto-centring on the current cell, controlled-vocabulary
autocomplete that resolves printed variants (步兵 → `hohei`), and provisional
labels and inferred-edge cells tagged distinctly.

Two behaviours worth keeping when this grows:

- **The IME owns Enter and Escape while it is composing.** Every key handler
  checks `isComposing` before acting; advancing a field mid-conversion is the
  classic way a Japanese entry form becomes unusable. Verified in a browser,
  not just in principle.
- **A near-miss on the vocabulary is flagged, never normalised.** Typing 歩 does
  not quietly become 歩兵.

## The write side

| Endpoint | Does |
|---|---|
| `GET /whoami` | Resolve the caller's id code to the worker it belongs to |
| `POST /volumes/{pid}/pages/{frame}/cells` | Persist the page's officer geometry as `roster_cell` rows (idempotent per `row_index`) |
| `POST /volumes/{pid}/pages/{frame}/observations` | Record one officer as a human read them |
| `GET /volumes/{pid}/pages/{frame}/observations` | What has been recorded for a page |

Three rules are enforced rather than documented:

- **Every write is attributed.** `app/db.py` only writes inside
  `actor_session()`, which sets `app.user_id` in the same transaction, because
  the audit triggers read the actor from there — a write that skips it lands in
  `audit_log` with a NULL actor. A test asserts both halves of that.
- **Observations are always `draft`.** Confirmation is a separate, deliberate
  act, and `author_user_id` comes from the authenticated user, never the body.
- **An unclear date is refused, not guessed.** `commissioning_date` is submitted
  as the reading exactly as printed (明四三、一二、二六 or 明治43年12月26日);
  the server normalizes with `reading/eradate.py`. If it cannot resolve the
  reading, the observation still saves with **no date** and the refusal reason
  recorded in `field_confidence`, so a bad value never enters the panel dressed
  as a good one.

## Who is writing

A worker is issued an **id code**; typing it is how they identify themselves,
and the code is their identifier on the project. No passwords, no accounts, and
**no roles** — decided 2 Aug 2026,
[docs/decision-workstation-auth.md](../docs/decision-workstation-auth.md).

```bash
python scripts/issue_access_code.py "Their Name"   # mints JP-K7QP-3M2X-9WTD
python scripts/issue_access_code.py --list         # who exists (never prints codes)
python scripts/issue_access_code.py --rotate <user_id>   # a code got shared
```

The code travels in `X-Annotator` and resolves against `app_user.login`, so the
frozen schema needed no credential column. Two properties are load-bearing and
have tests on them (`test_identity.py`):

- **Codes are minted, never chosen.** ~57 bits from `secrets`, in an alphabet
  with no `O`/`0` or `I`/`1`/`L`, because codes get read aloud and typed by
  someone not looking at the screen. Entropy is what would make exposing this on
  a network defensible; `verifier1` would not be.
- **The code never comes back out.** Not in a 401 body, not from `whoami`, and
  not in the observations listing — that one is visible to every other worker on
  the page, so it attributes work to `display_name`, never to `login`.

What this does not do is prove who is at the keyboard: anyone holding a code can
write as its owner. That is the accepted trade — the requirement is that work is
recorded to the person who did it, not that the software polices access. **If
this ever leaves `127.0.0.1`, serve it over TLS or a tunnel**, since the code is
a bearer secret.

Setup, once:

```bash
python -c "import sys; sys.path.insert(0,'app'); import db; db.create(db.db_path()).close()"
python scripts/load_vocab.py                       # rank/branch FKs; nothing saves without them
python ingestion/iiif_client.py register <pid>     # register a volume
python scripts/backfill_edition_dates.py --apply   # observations need as_of_date
python scripts/issue_access_code.py "Your Name"    # your own code
```

The very first code is a bootstrap — there is nobody to attribute the insert to,
so `audit_log` records a NULL actor by design. Pass `--issuer <your code>` for
every one after that.

## Recording an officer

The UI writes. An officer is recorded by <kbd>Ctrl</kbd>+<kbd>Enter</kbd>, by
<kbd>Enter</kbd> off the last field, or by leaving them with
<kbd>Alt</kbd>+<kbd>↓</kbd> — leaving an officer records them, because an
unsaved officer abandoned by a keystroke is transcription work quietly thrown
away. Three rules hold it together:

- **A blank officer is not a record**, and re-recording an unchanged one is a
  no-op, so stepping back through finished officers cannot post duplicate
  drafts. Editing one deliberately does post a new draft — observations are
  append-only readings, not a mutable form.
- **What the server refused is shown, not swallowed.** A branch outside the
  controlled vocabulary and a date `eradate` could not resolve both save with
  the field left NULL and the raw reading kept in `field_confidence`; the form
  lists them under the officer rather than reporting a clean success.
- **Whoever already read this page is visible.** Loading a page fetches its
  observations, so a second worker sees which officers are done and by whom
  instead of re-transcribing them.

備考 rides in `field_confidence.notes`: `observation` has no notes column and
the schema is frozen, so a reader's remark goes where notes about a reading
belong rather than being dropped.

## Not built yet

From the non-negotiables above: the difficult-character toolkit (variant
palette, radical/IDS lookup, attach-the-glyph), furigana and per-character
uncertainty capture, and the seal/damage flag. The candidate pane is a styled
placeholder until Layer 4 produces proposals.

Roles are **not** outstanding work — `app_user.role` gates nothing by decision,
and reviewer ≠ author is arranged between people rather than enforced by the
software.