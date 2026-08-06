# Layer 3 — Transcription workstation

> **Doing the transcribing rather than building it? Read
> [`OPERATING.md`](OPERATING.md).** This file is the developer's view; that one
> is the reader's, and includes the once-only setup.

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
| `GET /volumes/{pid}/progress` | Which frames of the volume carry readings — the coverage question |

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
python scripts/issue_access_code.py "Your Name"    # your own code
python scripts/backfill_edition_dates.py --apply --user JP-XXXX-XXXX-XXXX
```

The very first code is a bootstrap — there is nobody to attribute the insert to,
so `audit_log` records a NULL actor by design. Pass `--issuer <your code>` for
every one after that.

**Issue that code before the backfill, not after.** The backfill attributes its
writes like every other path, and its `--user` default (`system`) is a
placeholder rather than a real account — so on a fresh database the documented
order used to stop dead at `no such app_user: 'system'`. The script now says
what to do about it; the order above is the fix.

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

## When a character cannot be typed, or cannot be read

Two different problems, both of which used to stop a reader dead.

**The character is on the page but the IME will not produce it.** Rosters are
printed in kyūjitai — 齋, 澤, 邊, 步, 戰 — and a modern IME offers the shinjitai.
The toolkit shows the counterpart of every character actually typed, in both
directions, and swaps it in one click. Only the pairs present in the field are
offered: all 28 at once would be a wall to read past on every officer.

**The character cannot be read at all** — damaged, sealed, or illegible. Then it
becomes **〓** (<kbd>Alt</kbd>+<kbd>G</kbd>), the geta mark, inserted at the
caret rather than appended so it marks *which* character was lost. The record
saves with everything the reader could see, and `field_confidence` carries the
count of unread characters and the IIIF crop they sit in.

That last part is why a marked field comes back as `needs_recheck` and not as
`flagged`. It was recorded; someone can re-read it from the image later. Calling
it a refusal would be false, and would teach annotators to ignore the flag that
does mean "this did not save".

Radical/IDS lookup is deliberately absent. It needs an external
character-decomposition dataset, and no reading has yet failed that the palette
and the geta mark cannot get past — it can be added the first time one does.

## Not built yet

The seal/damage flag → alt-scan flip, and furigana capture. The candidate pane
is a styled placeholder until Layer 4 produces proposals.

### Throughput gaps found writing the operator guide (3 Aug 2026)

None of these break anything; all of them cost the annotator time or attention,
which is the quantity Phase 1's exit criterion measures. Roughly in order of
what they cost, with the workaround the guide currently tells readers to use:

1. ~~**兵科 and 階級 are retyped for every officer.**~~ **Fixed 3 Aug 2026.** Both
   carry forward from the nearest earlier officer, as a suggestion the reader can
   type over. Blankness is judged on what the reader typed rather than on what
   was carried, so stepping through unread officers still records nothing — the
   first cut of this got that wrong and wrote an observation carrying only an
   inherited branch, which is what a live test caught.
2. ~~**No keyboard page advance, and no memory of where you were.**~~ **Fixed
   3 Aug 2026.** <kbd>Alt</kbd>+<kbd>PgDn</kbd>/<kbd>PgUp</kbd> (and prev/next
   buttons) move between frames, and the last page that loaded is remembered per
   browser, so a session reopens where it stopped instead of at a hard-coded
   frame 100.
3. ~~**No volume-level progress.**~~ **Fixed 3 Aug 2026.** `GET
   /volumes/{pid}/progress` rolls up which frames carry readings, and the UI
   shows pages-read, whether the current page has been worked, and a jump to the
   next unread frame. Frames with nothing recorded are omitted rather than
   returned as zeroes — unread is the default state across hundreds of pages.
   Counts distinguish `rows_read` from `observations` because readings are
   append-only, so a re-read row is two readings of one row, not two rows.
4. ~~**Finishing the last officer on a page is silent.**~~ **Fixed 3 Aug 2026.**
   The last officer says so and points at the page-advance key, and the status
   line marks a page whose officers are all recorded as complete.
5. ~~**An officer already recorded showed an empty form**~~ — found while testing
   pass 1, **fixed 3 Aug 2026.** The listing endpoint already returned every
   field; the UI kept only "saved" and the author. It now shows the reading with
   a line naming who recorded it, codes resolved back through the vocabulary.

6. ~~**A page in flight showed the previous page's numbers.**~~ **Fixed
   3 Aug 2026.** An uncached frame is fetched from NDL, so a load is not
   instant; the status line kept the old page's "N recorded" under a frame box
   already showing the new number, which reads as "this page is done". It now
   says `loading frame N…`. Found by being misled by it while testing (3).

Each fix was built and driven in a browser against a real page of pid 1449426
before landing, and `OPERATING.md` moves with the software rather than after it.

Roles are **not** outstanding work — `app_user.role` gates nothing by decision,
and reviewer ≠ author is arranged between people rather than enforced by the
software.