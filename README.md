# jp-vertical-ocr-optimization

Person-centric transcription and career reconstruction of Imperial Japanese Army (IJA)
officers, 1922–1936 — a complete, human-verified officer-year panel with exact-dated
career transitions, every value provenanced to a page image or gazette reference.

The reading model is **human-primary**: people read, machines corroborate and flag.
Nothing a machine produces becomes a final value without human confirmation.

> **Status:** Phase 0 — foundations. Schema, vocabularies, and layout are landing;
> no pipeline code yet. See [docs/PLAN.md](docs/PLAN.md).

---

## Why this repo exists

The hard part of this corpus is *not* character recognition. A prior effort stalled trying
to make a bottom-up detector self-improve its table cropping across every page — the most
brittle possible approach, and the direct cause of its false detections.

This project inverts that. The seniority lists (*停年名簿*) are highly regular within each
series, so pages are **registered to a small library of layout templates**, fields are
assigned **by position rather than by guessing cell contents**, and the roster's own
internal redundancy (monotone seniority numbers, closed rank vocabularies, bounded dates)
is used to **auto-audit every page**.

The design goal is not perfect detection everywhere — that is unattainable. It is
**checkable** detection everywhere, so human attention lands only on constraint violations
and low-agreement cells.

## Scope

**Main goal — the Officer Index.** A complete officer-year panel for 1922–1936 built from
the 停年名簿 seniority lists, plus exact-dated career transitions (commissioning, promotion,
assignment, reserve transfer, death) mined from the *Kanpō* (官報, Official Gazette), all
resolved to single officer identities and linked to an existing academy dataset.
Pre-1920 snapshots are optional linkage anchors only.

**Secondary goal — technical-manual reading** (begins only after the main goal ships).
A curated set of wartime engineering documents — Sakae 21/12 engine handbooks, Zero
maintenance and operating manuals. Each is a deliverable in its own right (a clean,
modernized, translated table) and collectively they are a **table-reading testbed** that
hardens the extraction pipeline against a second family of layouts.

## Architecture

Nine layers over one relational core (PostgreSQL).

```
ROSTER READING (human-primary + structural automation)   EVENTS & CONTEXT (automatable)

 1 Ingest ──▶ 2 Template ──▶ 3 Transcription ◀──▶ 4 OCR+VLM     6 Kanpō event    7 Unit deployment
   & image     registration    workstation         proposal /     mining           & location
   (IIIF)      + anchors                           verify         (dated events)   (unit ──▶ place)
                                    │                                   │                │
                             5 Cross-year ──▶ 8 Record linkage ◀────────┴────────────────┘
                               propagation           │
                                                     ▼
                                       Data export — panel · events
                                       · deployment history
```

| Layer | Directory | What it does |
|---|---|---|
| 1 Ingestion | [`ingestion/`](ingestion/) | IIIF retrieval from NDL, page registry, provenance |
| 2 Structure | [`templates/`](templates/), [`reading/`](reading/) | Template registration, ruling-line alignment, seniority-anchor row auditing |
| 3 Workstation | [`app/`](app/) | Keyboard-first, IME-aware transcription UI |
| 4 Machine reading | [`reading/`](reading/) | NDLkotenOCR + VLM dual proposals, agreement scoring |
| 5 Propagation | [`reading/`](reading/) | Seed → propose → confirm across adjacent years |
| 6 Kanpō mining | [`kanpo/`](kanpo/) | Templated extraction of 叙任及辞令 personnel actions |
| 7 Deployment | [`deployment/`](deployment/) | Curated unit × interval → theater reference table |
| 8 Linkage | [`linkage/`](linkage/) | Splink / Fellegi–Sunter identity resolution |
| 9 QC | [`benchmarks/`](benchmarks/) | Ground-truth hold-out, flag queue, standing benchmark suite |

## Repository layout

```
design/       design document (authoritative; v2.1)
docs/         implementation plan, decisions, schema notes
db/           PostgreSQL schema and migrations
data/         controlled vocabularies only — no datasets (see data/README.md)
templates/    layout templates per roster series/era
ingestion/    IIIF retrieval + page registry
reading/      structure registration, OCR/VLM proposal + verification, propagation
kanpo/        Kanpō event miner
deployment/   unit → location/theater reference table
linkage/      record linkage to the academy dataset + events
app/          transcription workstation (web)
manuals/      secondary corpus — technical manuals (contents not committed)
benchmarks/   standing benchmark suite and accuracy reporting
```

## Data policy

**No research data lives in this repository.** This is deliberate, not incidental:

- **Ground truth is walled off.** The human-verified partial dataset is the project's
  accuracy yardstick and its VLM fine-tuning set. It only stays an honest hold-out if it
  is never mixed with production data and never published.
- **Source scans are not ours to redistribute.** NDL, JACAR, and personal-copy materials
  stay with their holding institutions; the repo stores stable references (PIDs, IIIF
  manifest URLs, JACAR refs), not images.
- **Officer datasets stay local.** Transcription output and the linked academy dataset are
  research assets released, if at all, on the project's own terms — not by side effect of
  a commit.

What *is* versioned: schema, controlled vocabularies, layout templates, extraction code,
benchmark definitions, and documentation.

## Technology

PostgreSQL · Python + FastAPI · React + OpenSeadragon/Mirador · IIIF ·
OpenCV (template registration) · NDLkotenOCR-Lite + a fine-tunable VLM ·
Splink (record linkage) · Docker Compose.

## Documents

- [`design/design-v2.1.html`](design/design-v2.1.html) — the authoritative design
  document. Open in a browser; **Ctrl/Cmd + P → Save as PDF** (margins: Default) renders
  Japanese text and tables correctly.
- [`docs/PLAN.md`](docs/PLAN.md) — implementation plan and phase breakdown.

Personal names and third-party social-media handles present in the working copy of the
design document have been replaced with role labels in this public copy.

## License

Code and documentation: [MIT](LICENSE). Source materials and research data are not covered
and are not redistributed here.
