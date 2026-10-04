# Volume kits — sending a reader everything in one zip

A **kit** is a zip a reader unzips and double-clicks. It holds the workstation, one
volume's page images and OCR, and a database with only that volume in it. Nothing is
installed, nothing is fetched, and nothing syncs: the lead decides who reads which volume
before the kit is built, and the work comes home as one small file.

Decided 3 Oct 2026. One reader per volume; Windows only; no network.

## For the lead

### 1. Prepare the volume (once)

```
python scripts/prepare_volume.py 1449426        # or --all
```

Registers every page of the volume from its original scan, on this machine, and stores
the result in the data home (`cache/<pid>/registered/`). From then on this workstation
and every kit read that same stored result - see "Why a kit never registers a page"
below. It also makes the smaller page images kits carry, and writes a **readiness
report** to `<data home>/kits/readiness/`: how many officers a reader can record, and
which pages hold officers they cannot (one leaf did not register; a roster page fits no
template; numbers sit outside the grid). About three minutes a volume.

A prepared volume stays as it is until you run it again with `--redo` - which is what
to do after the detector or a template changes. Before anything stored is replaced,
every page that already has readings is registered afresh and each recorded officer
looked for where it was; if any would move, nothing is written unless `--force`.

### 2. Build a kit

```
python scripts/build_volume_kit.py 1449426 --reader "Tanaka Hanako" ^
    --return-to "Email that file to lead@example.org."
```

Run both with the same Python the workstation runs on. The builder:

1. checks the volume is complete and prepared with the current detector and templates;
2. finds the reader in the master database, or adds them;
3. cuts a database holding only that volume, with every id intact;
4. copies the volume in with its stored registrations and page images - the smaller
   ones unless `--images original`;
5. starts the kit's own program and has it open pages as a reader will, with every
   proxy pointed at a dead port. A kit that fails this is not zipped;
6. zips it into `<data home>/kits/Roster-<pid>-<reader>.zip`.

A kit is a 1.5 GB zip for a Shōwa volume - 1.4 GB of page images and 0.2 GB of program;
with `--images original` the images alone are 3.4 GB. That is a download link, not an
email attachment.

The kit program itself (`build/kit-app/`) is built on first use by
`scripts/build_kit_app.py` in its own environment (`.venv-kit`), and reused. Pass
`--rebuild-app` after changing the workstation.

### 3. Send it

Send the zip. `README-FIRST.txt` inside tells the reader the three steps; the one thing
worth saying in your own message is that Windows will warn about an unrecognised program
the first time ("More info" → "Run anyway").

### 4. Merge what comes back

The reader presses **Send in my work**, which writes `roster-<pid>-….zip` into the kit's
`outbox` folder and opens that folder. They send you the file — a megabyte or so.

```
python scripts/merge_returned.py roster-1449426-ab12cd34-20261003-101500.zip
python scripts/merge_returned.py roster-1449426-ab12cd34-20261003-101500.zip --apply
```

The first form only looks and reports what merging would add. `--apply` adds it, in one
transaction. Each file holds everything the reader has done so far, so merging a later
file after an earlier one — or the same file twice — adds only what is new.

It refuses, and says why, when the file and the master disagree about something that
should be identical. The one you may meet: the master already holds readings on that
volume which the kit never saw, meaning two people worked the same volume.
`--allow-other-work` merges anyway once you have looked.

The return file also carries `officer-record.csv` and `work-log.csv`, so a reader's work
can be read without merging anything.

## Why a kit never registers a page

Registration — finding the officer columns and field rows on a scan — is arithmetic on
pixels, and it is not stable across machines. Measured on 97 pages across the four
volumes (3 Oct 2026):

- **3 pages** registered with a different number of officers under OpenCV 5.0 than under
  OpenCV 4.8;
- **3 more** once the scan had been recompressed (one went from 20 officers to 5);
- on the 1923 camera scans, cell positions moved by up to 372 px with the officer count
  unchanged.

A reading is recorded against an officer's position on the page. A kit that counted
columns differently from the master would file readings under the wrong officer, and
nothing would look wrong.

So the lead's machine registers every page when the volume is prepared, stores the result
(`cache/<pid>/registered/`), and every kit carries a copy and reads it back
(`app/page_service.py`, "stored registrations"). In a kit, a page with nothing stored is
an error, never a cue to compute. Two consequences:

- the kit's libraries and image quality cannot change what a reader records against, so
  the images can be shipped small;
- pages open at once in a kit: nothing is computed.

The same instability applies to the master itself: **changing the OpenCV version on the
lead's machine can move cells on pages that already have readings.** `requirements.txt`
does not pin it. The versions a kit was registered with are written into its
`assignment.json` (`registered_with`).

## What a kit contains

```
Roster-<pid>-<reader>/
  Start Transcription.exe      the launcher (kit/launcher.py)
  _internal/                   a private Python and the workstation; no installs
  README-FIRST.txt
  data/
    assignment.json            which volume, which reader, when built, with what
    officer-index.db           this volume only; the reader's own id; no one else's code
    cache/<pid>/
      frame_NNNN.jpg           every page
      registered/frame_NNNN.json   every page's registration, from the lead's machine
      survey.json              derived from those registrations
      ndl_fulltext_raw.json    NDL's OCR, for the machine readings
      manifest.json
    logs/kit.log               created on first run
  outbox/                      created by "Send in my work"
```

## What is different inside a kit

- **No id-code screen.** The kit belongs to one reader; work with no code offered is
  attributed to the reader the assignment names. Other people's readings on the volume
  come along so finished pages show as finished, but their id codes are replaced — a
  code is a bearer secret and a kit leaves the building.
- **Opens on the first page with officers still to read**, and "next unread page" skips
  front matter, index pages and finished pages.
- **No network.** Anything the kit would have to fetch is reported as missing.
- **No zoomed re-reading.** NDLOCR-Lite is not in the kit (it would add ~630 MB); NDL's
  own readings are offered as before.

## Limits

- **Windows only.**
- **The program is not signed**, so Windows SmartScreen warns on first run.
- **A reader's work lives only in their folder until they send it.** Nothing syncs. Ask
  for a file at intervals, not only at the end.
- **One reader per volume.** Two kits for the same volume can both be merged
  (`--allow-other-work`), but two people will have read the same officers.
- **Cloud-synced folders.** Documents and Desktop are often OneDrive folders. The kit
  works there, but a sync client copying the database while it is being written is a
  known way to end up with a conflicted copy. A plain local folder is safer if a reader
  has the choice.
- **Not run on a second machine.** The kit was verified extracted into a folder with
  spaces and Japanese in its path, with nothing of this machine's on the PATH and every
  proxy pointed at a dead port - but on this machine. A first run on a clean Windows PC
  is worth doing before sending many.
