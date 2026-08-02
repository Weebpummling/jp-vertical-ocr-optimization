# Setup — running the workstation on a local machine

There is no server, no container and no password. The database is a single
SQLite file; the workstation is a Python API and a browser page that read it.
Clone and go.

## Prerequisites

- **Python 3.11+** and **Git**.
- **Node 20+**, only if you want the transcription UI (`app/ui/`).

Nothing else. Postgres and Docker were removed on 2 Aug 2026 — see decision 9 in
`docs/PLAN.md`. The database has to be shareable and openable by other
researchers, and a file is; a server on one machine is not.

## First run

```bash
git clone https://github.com/Weebpummling/jp-vertical-ocr-optimization.git
cd jp-vertical-ocr-optimization
pip install -r requirements.txt
```

1. Copy `.env.example` to `.env` and point `JP_OCR_DATA` at the machine's
   private data home (create it per `docs/data-home.md`). The database lives
   there as `officer-index.db` unless `JPOCR_DB` says otherwise.
2. Create the database and load the controlled vocabularies:

```bash
python -c "import sys; sys.path.insert(0,'app'); import db; db.create(db.db_path()).close()"
python scripts/load_vocab.py
```

   Loading vocabularies is not optional: `observation.rank_code` and
   `.branch_code` are foreign keys into those tables, so with them empty no
   officer carrying a rank can be recorded at all.

3. Register a volume and give yourself an id code:

```bash
python ingestion/iiif_client.py register 1449426
python scripts/backfill_edition_dates.py --apply
python scripts/issue_access_code.py "Your Name"
```

4. Run it:

```bash
uvicorn app.api:app --port 8000      # terminal 1
npm --prefix app/ui run dev          # terminal 2 → http://localhost:5173
```

## Opening the database directly

The point of a file is that you do not need this repo to read it:

- **DB Browser for SQLite** — click around, run queries, export.
- **Python** — `pandas.read_sql("SELECT * FROM observation", sqlite3.connect(path))`
- **R** — `DBI::dbConnect(RSQLite::SQLite(), path)`
- **Excel** — run `python scripts/export_record.py` and open the CSVs.

Foreign keys are off by default in SQLite. Anything that writes to this file
must run `PRAGMA foreign_keys = ON` first, as `app/db.py` does on every
connection.

## Sharing and merging

Copy `officer-index.db` into the shared folder. Row ids are uuids precisely so
that two people can transcribe on two machines and have their work merged back
without colliding.

`python scripts/export_record.py --out <folder>` writes `officer-record.csv` and
`work-log.csv` beside it, for anyone who would rather not open a database at
all.

## Backups

None. Removed entirely by the lead's decision (2 Aug 2026) — decision 8 in
`docs/PLAN.md`. There is one copy of the data, in the data home. The sources are
online and the tools in this repo regenerate everything derived from them.

## What runs where

| Concern | Machine |
|---|---|
| Database file + API + workstation | Wherever the transcribing happens |
| Private data home (`JP_OCR_DATA`) master copy | Lead's machine |
| Repo development, NDL retrieval, experiments | Any — everything hits public NDL endpoints politely |
