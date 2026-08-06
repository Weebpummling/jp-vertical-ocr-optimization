# Operating the transcription workstation

For the person doing the reading. [`README.md`](README.md) next door is the
developer's view of the same software; you do not need it.

**The one rule:** *you* read the page. The software's job is to put the right
cell in front of you and to record what you say about it — never to decide what
it says. Nothing you enter is treated as final, so an honest "I can't read this"
is always a better answer than a confident guess.

---

## 1. Before your first session

Someone sets the workstation up once (see [§7](#7-setting-it-up-once)) and gives
you an **id code** that looks like `JP-K7QP-3M2X-9WTD`. That code is how the
project knows the work is yours. It is not a password and there is nothing to
choose or remember — keep it where you keep useful things, and tell whoever runs
the project if it goes astray so they can issue a new one.

Two browser tabs' worth of software must be running (again, §7). When it is, open
**http://localhost:5173**.

## 2. Signing in

Type your id code and you are in. The browser remembers it, so you do this once
per machine, not once per session.

The top-right corner always says **recording as \<your name>**. If that is not
you — a shared machine, someone else's session — click **not you?** and enter
your own code. Work recorded under the wrong name is the one mistake here that
is genuinely tedious to unpick.

If the code is refused, it has probably been rotated; ask for a current one.

## 3. Loading a page

The top bar has **pid** and **frame**, then **load**.

- **pid** is the volume — the NDL identifier. `1449426` is the 昭和8年 (1933)
  seniority list, the volume the layout template was built from.
- **frame** is the scan number, the same number the NDL viewer shows.

**It reopens wherever you left off.** The browser remembers the last page that
loaded, so you can close it mid-volume and come back to the same frame. A machine
that has never been used starts at pid `1449426`, frame `100`.

Move between pages with <kbd>Alt</kbd>+<kbd>PgDn</kbd> and
<kbd>Alt</kbd>+<kbd>PgUp</kbd>, or the **‹ prev** / **next ›** buttons.

Once a page loads, the status line reads something like:

> `showa-teinen-meibo-A` · 24 officers · 0 recorded · 11/12 bands · skew 0.4°

- **24 officers** — vertical columns the page was divided into. Each is one
  officer, numbered from the **right**, the direction the page is read.
- **0 recorded** — how many have been saved, including by other people.
- **11/12 bands** — how many horizontal rulings were actually matched. One
  missing is normal; several missing usually shows up as **needs review**.
- **skew** — how tilted the scan is. Large values are worth mentioning.

Two messages mean *stop and tell someone* rather than work around them:

| What you see | What it means |
|---|---|
| "This page matches no template, so it has no officer grid" | Index pages, section dividers and badly damaged pages have no grid — this is correct behaviour, not a fault. Move to the next content page. |
| "…is not registered in the database, so nothing can be saved yet" | The volume was never registered. **Anything you type will be lost.** Stop and get the volume registered first. |

## 4. The three panes

| Pane | What it is for |
|---|---|
| **Left — the page** | The scan. It follows your cursor: as you move between fields it centres on the exact cell you are filling. |
| **Middle — the form** | The seven fields for the current officer. This is where you work. |
| **Right — the crop** | A close-up of just the cell you are in, for when the full page is too small to read. |

## 5. Entering an officer

Seven fields, in reading order:

| Field | Notes |
|---|---|
| **序列番号** seniority no. | The printed sequence number. It should climb steadily as you move left across the page — a break is worth a note. |
| **氏名** name | The name cell also carries the birth date; type the name. |
| **兵科** branch | **From the section header, not this officer's cell** — the same for every officer under that heading, so it is carried forward for you (see below). |
| **階級** rank | Also from the section header, and also carried forward. |
| **職名** post | The appointment. |
| **任官年月日** commissioning date | Type it **exactly as printed** — `明四三、一二、二六` is fine, and so is `明治43年12月26日`. The server converts it. Do not tidy it up. |
| **備考** remarks | Anything worth saying about this reading. |

### Keys — the whole officer without the mouse

| Key | Does |
|---|---|
| <kbd>Enter</kbd> | Next field. Off the **last** field: records the officer and opens the next one. |
| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | Record this officer now, without leaving the field. |
| <kbd>Alt</kbd>+<kbd>↓</kbd> *(or <kbd>→</kbd>)* | Record and go to the next officer. |
| <kbd>Alt</kbd>+<kbd>↑</kbd> *(or <kbd>←</kbd>)* | Record and go back to the previous officer. |
| <kbd>Alt</kbd>+<kbd>PgDn</kbd> / <kbd>PgUp</kbd> | Next / previous **page**. |
| <kbd>Alt</kbd>+<kbd>G</kbd> | Mark a character you cannot read (see §6). |
| <kbd>Esc</kbd> | Close the suggestion list. |

### 兵科 and 階級 carry forward

Both come from the section header, so once you have entered them for one officer
they appear already filled for the next. **Check them against the page anyway** —
they are a suggestion, not a reading, and they keep appearing until you change
them. When the section heading changes, type the new value once and it carries
from there.

Stepping past an officer you have not read records nothing: a carried 兵科 on its
own is not a reading, and nothing is recorded for an officer until you type
something of your own.

### An officer somebody has already read

Their reading is shown in the form, above it a line saying who recorded it.
Nothing you do overwrites it — readings are only ever added, so editing one
records a *new* reading alongside theirs rather than replacing it. Normally you
should move on; correct it only if it is actually wrong, and say why in 備考.

**Leaving an officer records them.** You cannot lose an officer by stepping away
from them. A blank officer is not recorded, and re-recording an unchanged one
does nothing — so stepping back through finished work is safe.

**While your IME is converting, <kbd>Enter</kbd> and <kbd>Esc</kbd> belong to the
IME.** Converting 步兵 will not jump you to the next field mid-word.

### 兵科 and 階級: the suggestion list

These two fields draw on the project's fixed vocabulary. Type a few characters
and pick from the list — or just press <kbd>Enter</kbd> to take the top
suggestion. Printed forms resolve to modern ones (步兵 → 歩兵 `hohei`), and a
green line confirms what it resolved to.

If what you typed is **not** in the vocabulary you will see *"not in the
controlled vocabulary — flag rather than force"*. **Do not bend it into
something that fits.** Leave it and add a remark in 備考. A branch we have not
seen before is a discovery about the corpus; a wrong branch typed to make the
warning go away is a silent error.

### Labels on the fields

| Tag | Meaning |
|---|---|
| **provisional label** | We are not certain this row means what its name says. Enter what is printed; the label may be corrected later. |
| **check crop** | An edge of this cell was inferred rather than seen. Glance at the right-hand pane — the crop may be cutting something off. |
| **no cell** | Not a cell on the page at all (兵科, 階級, 備考). |

## 6. When a character defeats you

Two different problems:

**You can see it but cannot type it.** The rosters use old forms — 齋, 澤, 邊,
步, 戰 — and your IME offers the modern one. Under the field you are in, the
toolkit shows the counterpart of each character you typed and swaps it in one
click, in either direction.

**You cannot read it at all** — damaged, sealed, inked over. Put the caret where
that character belongs and press <kbd>Alt</kbd>+<kbd>G</kbd> to insert **〓**.
Type everything you *can* read around it: `平岩〓一` is a good record, and far
more useful than a blank or a guess. The record saves, marked for someone to
re-check against the image later.

**Never guess a character to avoid the mark.** The mark is cheap; a plausible
wrong name is expensive and invisible.

## 7. After you press record

> recorded as a draft — confirmation is a separate act

That is the normal, successful outcome. *Draft* is not a warning: every reading
starts as a draft, and confirming is a separate deliberate step by design.

Sometimes you also get:

> Saved without these — the server would not read them for you:
> `commissioning_date` **明四三、一二、二六** — could not resolve

The officer **was** recorded; that one field was left empty and your raw reading
kept alongside it. Usually it means a typo, occasionally a genuinely odd date
format. Have a look — and if the page really says that, leave it and note it.

If you see **not recorded:** followed by an error, the officer did **not** save.
Try once more; if it persists, stop and report it rather than retyping the page.

## 8. Rough edges, and how to work around them

Known and being fixed. Until then:

- **Nothing tells you which pages of the volume are done.** The counter covers
  the page you are on, not the volume — so keep a list, or agree page ranges with
  whoever else is transcribing. This is the next thing being fixed.
- **A recorded 兵科 or 階級 comes back in its standard form.** Record 步兵 and it
  reappears as 歩兵: the database stores the branch, not the shape of the
  character. Both mean `hohei`, and nothing has been changed on the page.

## 9. Setting it up once

For whoever installs it, not for the reader. Windows shown; the same commands
work elsewhere.

```bash
pip install -r requirements.txt        # from the repository root
```

Point `JP_OCR_DATA` at the data home, then, once ever:

```bash
python -c "import sys; sys.path.insert(0,'app'); import db; db.create(db.db_path()).close()"
python scripts/load_vocab.py                       # 11 ranks, 14 branches, 28 variants
python ingestion/iiif_client.py register 1449426   # register the volume
python scripts/issue_access_code.py "Their Name"   # one code per person
python scripts/backfill_edition_dates.py --apply --user JP-XXXX-XXXX-XXXX
```

**Issue the first code before the backfill, and pass it.** Every write is
attributed, so the backfill needs an existing worker; on a fresh database it has
nobody to attribute to and stops with `no such app_user: 'system'`.

The pages an annotator will read must be **cached first** — the workstation
serves pixels from the local cache and never from NDL, so an uncached page
cannot be worked on:

```bash
python ingestion/iiif_client.py fetch 1449426 100   # ~1.5 s per page, resumable
```

Then, two terminals:

```bash
uvicorn app.api:app --reload --port 8000
npm --prefix app/ui run dev            # → http://localhost:5173
```

Check `http://localhost:8000/health` — it should answer
`{"status":"ok","templates":["showa-teinen-meibo-A"]}`.

**If this ever leaves `127.0.0.1`, put it behind TLS or a tunnel.** The id code
is a bearer token: anyone holding it can record work as its owner.
