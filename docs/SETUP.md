# Setup — running the stack on a local machine

The database stack runs wherever Docker can run. (The lead's work machine cannot run
Docker; the intended host is the lead's home machine.) Everything below is contained in
this repo — clone and go.

## Prerequisites

- **Docker Desktop** (Windows/macOS) or docker-engine + compose (Linux). On Windows,
  Docker Desktop needs WSL2 and hardware virtualization enabled in BIOS/UEFI — if the
  engine fails to start with a virtualization error, that's the switch to look for.
- **Git** and (optional, for the Python tools) **Python 3.12**.

## First run

```bash
git clone https://github.com/Weebpummling/jp-vertical-ocr-optimization.git
cd jp-vertical-ocr-optimization
```

1. Copy `.env.example` to `.env`; set a real `POSTGRES_PASSWORD` and point
   `JP_OCR_DATA` at the machine's private data home (create it per
   `docs/data-home.md` — the same layout as on the lead's machine, populated from the
   shared project copies).
2. Start the database:

```bash
docker compose up -d
```

   First start applies `db/schema.sql` automatically (only on a fresh volume — schema
   changes after that are manual until migrations land).
3. Verify:

```bash
docker exec jpocr-db psql -U jpocr -d jpocr -c "\dt"
```

   Expect the full table list (person, observation, roster_cell, kanpo_event, …).

## Backups

None. Removed entirely by the lead's decision (2 Aug 2026) — see the decisions
record in `docs/PLAN.md`. There is one copy of the data, in the data home. The
sources are online and the tools in this repo regenerate everything derived
from them.

## Python tools (optional on the DB host)

```bash
python -m venv .venv
.venv\Scripts\pip install openpyxl opencv-python-headless numpy requests
```

Used by: `benchmarks/register_reference_truth.py` (ground-truth registration),
`reading/spike_c/registration_experiment.py` (template experiments),
`kanpo/survey_sections.py` (Kanpō surveys). All read/write only the repo and
`JP_OCR_DATA` — no other machine state.

## What runs where (current division of labor)

| Concern | Machine |
|---|---|
| PostgreSQL + (Phase 1) API + workstation | Home machine (Docker) |
| Private data home (`JP_OCR_DATA`) master copy | Lead's machine; copies distributed via daily file-sharing |
| Repo development, NDL retrieval, experiments | Any — everything hits public NDL endpoints politely |
