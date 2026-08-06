# Implementation plan

The working plan for the Officer Index: what lands, in what order, and *done when*.
The deliverable is the verified dataset itself — transcribed rosters, exact-dated
career events, resolved identities — with every value human-confirmed and provenanced.

---

## Standing commitments

These are architectural, not preferences. Changing one is a design change, not a
refactor.

1. **The person is the unit of work** — not the page, not the text line.
2. **Humans decide; machines corroborate.** No code path may write a machine value as
   final. OCR, VLM, and extractors propose, score, and flag.
3. **No bottom-up per-page table detection, ever.** Structure comes from top-down
   template registration. This is the specific failure mode that sank the prior effort;
   reintroducing a self-improving crop detector is a regression regardless of its metrics.
4. **Everything is provenanced and reversible.** Every value traces to a page image or a
   gazette reference and is independently re-checkable.
5. **Ground truth is a hold-out.** `ReferenceTruth` is registered separately, split
   train/hold-out before first use, and never merged into production tables.
6. **Accuracy is measured, not asserted.** Claims about pipeline quality cite a number
   against held-out truth.

---

## Calendar anchor and critical path

Week numbers below count from project kickoff. The external constraint is the
**April 2027 collection year**.

- **What must land before collection starts: Phase 1** (week 12). The workstation alone
  unblocks hand-capture of 1922+ volumes. Everything after Phase 1 raises throughput and
  quality; nothing after it gates starting.
- **Phases 1 → 2 → 3 are the productivity critical path.** With an August 2026 kickoff,
  Phase 3 exits ~week 24 (late January 2027) — comfortable margin before April.
- **Phase 4 (Kanpō miner) is off the critical path and starts early.** It depends only on
  Phase-0 ingestion and the NDL full text, not on the workstation. It spikes
  during Phase 0 and matures in parallel; the week-20–30 window is when it
  *finishes*, not when it starts.
- **Phases 5–6 trail into the collection year by design.** Linkage, deployment, QC
  hardening, and export run alongside collection without blocking it.

Dependency sketch:

```
Phase 0 ─┬─▶ Phase 1 ─▶ Phase 2 ─▶ Phase 3 ─┐
         │                                   ├─▶ Phase 5 ─▶ Phase 6 ─▶ Phase S
         └─▶ Phase 4 (spike → mature) ───────┘
```

---

## De-risking spikes (run inside Phase 0, before heavy build)

Three assumptions underpin the whole design. Each is testable in days; each, if false,
changes the architecture. Test them **before** committing build-weeks on top of them.

- [x] **Spike A — Kanpō full-text coverage.** *Answered — see
      `docs/spikes/spike-a-kanpo.md`.* NDL's Kanpō OCR text exists but has no export
      API; the miner runs its own OCR (open-source NDLOCR), scoped to section pages
      located via IIIF manifest TOCs (`structures` labels, old kanji 敍任及辭令).
      Phase 4 below reflects this.
- [x] **Spike B — IIIF access at working rates.** *Answered — see
      `docs/spikes/spike-b-ndl-access.md`.* Full 1922–1936 roster run is digitized,
      internet-public, IIIF-served (~1.5 s/image observed); PIDs enumerated. Bonus:
      NDL's own OCR text per roster volume is retrievable via
      `lab.ndl.go.jp/dl/api/book/fulltext-json/{PID}` — a free third reading engine
      for Layer 4.
- [x] **Spike C — template registration on real pages.** *Answered — see
      `docs/spikes/spike-c-registration.md`.* On 20 real page panels of the 1933 volume,
      the band template transfers with mean residual ≤0.5% of table height; index-section
      pages fail to match cleanly, which is the page-classification signal. Experiment
      code: `reading/spike_c/registration_experiment.py`.
- [x] **Spike D — academy dataset reconnaissance.** *Answered — see
      `docs/spikes/spike-d-academy-dataset.md`.* 15,029 × 69; blocking keys all present
      at 100% fill (fullname + cohort + branch), plus pre-normalized shinjitai names and
      alias columns. Dataset stays on the lead's machine per the data policy.

## Phase 0 — Foundations (weeks 1–4) · *current*

**Delivers:** schema, environment, identity, ingestion skeleton, worklist + NDL IIIF
retrieval, ground truth registered, spikes A–D answered.

**Exit criterion:** any page is zoomable and provenanced; ground truth is loaded with its
train/hold-out split fixed; all four spikes have written answers.

- [x] Schema frozen 31 Jul 2026 (`db/schema.sql`) — 18 tables, audit triggers,
      vocabularies loaded. Changes from here are deliberate migrations.
- [x] Verify controlled vocabularies — `branch.csv` reconciled against the academy
      dataset's 13 observed labels, and roster-side verified against the 1923, 1926,
      and 1935 editions via NDL full text (see `data/vocab/README.md`): ranks complete,
      all combat branches resolve, `kokuhei` dated 1925-05-01 from the corpus itself,
      folds 戰/聯/臺 added. 法務部/技術部 dropped by the lead's decision (zero
      in-window occurrences). **Vocabularies frozen 31 Jul 2026**: 11 ranks,
      14 branches, 28 variants.
- [x] Database running: originally Postgres 16 under Docker Compose, **replaced by a
      single SQLite file on 2 Aug 2026** (decision 9). No server, no container, no
      credentials — `<data home>\officer-index.db`, with 3,565 rows migrated across.
- [x] **Backups: removed entirely** (lead, 2 Aug 2026 — decision 8). Both scheduled
      tasks unregistered, both scripts deleted, all copies removed. One copy of the
      data lives in the data home.
- [x] Work is attributed. Originally Postgres audit triggers keeping full before/after
      row images; **replaced 2 Aug 2026 by `work_log`** — who recorded what, when, on
      which page — written by the application in the same transaction as the work.
      The provenance of a value still lives on the row: `observation` carries
      `author_user_id`, `created_at` and `status`. The before/after images were a
      compliance-grade guarantee nobody asked for; a readable work log is what was.
- [x] CI on every push: the schema builds a fresh database, vocabularies load, and both
      test suites run — with no service container, so CI does exactly what a laptop does
      (`.github/workflows/ci.yml`, `scripts/lint_vocab.py`).
- [~] Worklist registry: roster PIDs 1914–1936 seeded (`ingestion/worklist-roster.csv`).
      **Reserve lists done (3 Aug 2026)** — both series enumerated and access-checked
      across the window (予備役 and 後備役, 8 editions each, plus the 昭和7 追録);
      swept through *both* catalogues with `scripts/ndl_worklist_sweep.ps1`, so the
      residual gaps (昭和5, 昭和8, and a non-public 昭和10 追録) are findings, not
      search misses — see the addendum in `docs/spikes/spike-b-ndl-access.md`.
      **号外 enumeration still to add** (Phase 4 dependency).
- [x] IIIF client (`ingestion/iiif_client.py`): manifest fetch (cached), volume +
      page registration (audited, idempotent), polite cached full-page retrieval,
      and per-cell region crops as re-checkable IIIF URLs — verified on real
      officer cells of pid 1449474. Non-IIIF source stamping deferred until a
      non-IIIF source is actually ingested.
- [x] Ground truth registered and **split fixed** (29 Jul 2026): 15,029 records,
      10,595 train / 4,434 hold-out, hash-deterministic rule, manifest hash committed —
      see `docs/ground-truth-split.md`. The verified asset is person-level; page-level
      transcription truth accrues from Phase 1 under the same split (inherited flags).
- [x] Scope confirmed with the lead: primary window 1922–1936; pre-1920 as linkage
      anchors only.

### Ground-truth split — definition of done

This is the one irreversible decision in Phase 0, so it gets a spec:

- **Stratified**, not random: hold-out pages span every covered year and every layout
  template present in the truth set, so accuracy numbers generalize across the corpus
  rather than reflecting one easy volume.
- **Proportion:** target ~30% hold-out / ~70% train, adjusted so no covered year has zero
  hold-out pages. If truth is thin for some year, hold-out wins the tie — measurement
  outranks tuning.
- **Fixed by artifact:** the split is a committed manifest (page identifiers + use_flag),
  and its hash is recorded. Any later change to the split is a logged, argued-for event,
  not an edit.
- **Hold-out discipline:** hold-out pages are never used for VLM tuning, prompt
  iteration, threshold fitting, or error analysis during development. One person owns
  enforcement (see open decisions).

## Phase 1 — Transcription MVP (weeks 5–12)

**Delivers:** the structured workstation; controlled-vocabulary autocomplete;
difficult-character toolkit; template registration for the main Shōwa layout.

**Exit criterion:** an annotator captures a full 1922+ volume by hand — measured, with
the observed officers/hour recorded as the baseline all later phases are judged against.

- [x] Three-pane workstation: zoomable page (cell auto-centered) · structured entry form
      (氏名, 兵科, 階級, 職名, 任官年月日, seniority, notes) · candidate panel. Reads *and*
      writes: each committed officer becomes a draft `observation` attributed to the
      worker's id code (`app/ui/`, `app/api.py`). Verified in a browser against pid
      1449426 — refused values surface with their reason instead of saving clean.
- [x] Keyboard-first, IME-aware entry — a whole officer without touching the mouse.
      Leaving an officer records them, so work is never lost to a keystroke.
- [x] Identity: each worker types an issued id code, which is their identifier
      (`scripts/issue_access_code.py`). Decided 2 Aug 2026 —
      `docs/decision-workstation-auth.md`. **Roles are not enforced and will not be**;
      reviewer ≠ author is a human arrangement, not a system guarantee.
- [x] Era-date normalizer (`reading/eradate.py`): 明治/大正/昭和 + kanji numerals in
      the roster's digit-juxtaposition notation → canonical dates; era bounds
      enforced; every ambiguous parse refused with a recorded reason.
- [x] Difficult-character toolkit (`app/ui/src/components/DifficultCharacter.tsx`):
      kyūjitai↔shinjitai variant palette driven by the frozen variant table, offering
      only the swaps present in what was typed, in both directions; and 〓 (the geta
      mark, <kbd>Alt</kbd>+<kbd>G</kbd>) at the caret for a character that cannot be
      read at all. The record saves with everything the reader *could* see and carries
      the count of unread characters plus the IIIF crop they sit in, so it is
      re-checked against the image rather than re-transcribed. **Radical/IDS lookup is
      deliberately not built** — it needs an external character-decomposition dataset,
      and no reading has yet failed that the palette and the geta mark cannot get past.
- [x] Per-character uncertainty capture — an unread character is marked in place, so
      uncertainty is recorded at the character, not smeared over the whole field. A
      marked field is reported as `needs_recheck`, never as a refusal: it *was*
      recorded, and calling it "not recorded" would teach annotators to distrust the
      flag that matters.
- [ ] One-click seal/damage flag → alt-scan flip.
- [x] First Shōwa seniority-list template, productionized from Spike C's hand-built grid
      (`templates/showa-teinen-meibo-A.json` + `reading/registration.py`): 12-band grid
      derived from 7 panels of pid 1449426, page classification with three measured gates
      (index and degraded pages reject), officer strips and per-field rectangles emitted in
      original-scan pixels for `roster_cell.crop_bbox` / IIIF region URLs. Verified end to
      end against the scan — cells land on seniority 915/916, 平岩棟一/乾忠夫, cohorts 25/22.
      Five fields confirmed against the page; the four upper date rows are geometry-only and
      await the lead's naming.
- [ ] Suggestions rendered visually distinct from confirmed values — human independence is
      what makes machine agreement statistically meaningful.

## Phase 2 — Machine reading + structure audit (weeks 10–18)

**Delivers:** dual-engine proposals, ground-truth fine-tuning, agreement scoring,
seniority-anchor auditing, additional templates.

**Exit criterion:** easy cells auto-confirm; structural errors auto-flag; VLM accuracy
measured against held-out truth.

- [ ] Ingest NDL's precomputed roster OCR (`fulltext-json`, per-line pixel boxes) and
      bin it into template cells — the zero-cost first proposal engine
      (`docs/ndl-prior-work.md`).
- [ ] Our own NDL OCR engine: benchmark NDLOCR-Lite (modern typeset) vs
      NDLkotenOCR-Lite (classical) on ground truth; ship the winner. CPU-capable.
- [ ] VLM / OCR-free structured extractor returning fields for an officer cell.
- [ ] Fine-tune / calibrate the VLM on the **train** portion of ground truth — MLLMs read
      vertical Japanese worse than horizontal out of the box; this is the single largest
      accuracy lever short of human reading.
- [ ] Field-level agreement scoring with a variant equivalence table (齋/斎 is not a conflict).
- [ ] **Seniority-anchor row auditing** — monotone integer sequence locks row alignment and
      pinpoints dropped or spurious rows; reconcile row count per page.
- [ ] Closed-vocabulary rejection (out-of-set rank/branch) and bounded-date flagging.
- [ ] Overnight batch pre-run so suggestions are at the desk with zero latency.
- [ ] Benchmark gate goes live: from here on, pipeline changes ship only at-or-above the
      standing benchmark scores (see `benchmarks/README.md`).

## Phase 3 — Cross-year propagation (weeks 16–24)

**Delivers:** seed → propose → confirm across 1922–1936; disappearance → Kanpō tasks.

**Exit criterion:** later years are confirm-and-correct rather than fresh transcription,
at a measured multiple of the Phase-1 baseline officers/hour.

- [ ] Pre-fill year *Y+1* from confirmed year *Y*, positioned by expected seniority.
- [ ] Change detection as the task — promoted? transferred? gone?
- [ ] Disappearance handling opens a targeted task (reserve/後備 lists, Kanpō query) so
      exits are **explained, never silent gaps**.
- [ ] Bias guardrails: propagated values marked unconfirmed and requiring an affirmative
      keystroke; a blinded sample hides suggestions for QC calibration.

## Phase 4 — Kanpō event miner (spike in Phase 0; matures weeks 5–30)

**Delivers:** retrieval, templated extraction, normalization, and validation of
commissioning / promotion / assignment / reserve / death events.

**Exit criterion:** exact-dated transitions populate the event table with measured
precision and recall.

This is the project's **easiest** automation target, not its hardest — the 叙任及辞令
sections are regular templated *prose*, and NDL already publishes full text. It depends
only on ingestion, so it runs in parallel with Phases 1–3 rather than after them; §18's
week-20–30 window is its completion window.

- [ ] Targeted retrieval of military 辞令 sections, ~1920–1937. Stage-0 survey done
      (`kanpo/survey_sections.py`): PID-walk resolution works; TOC itemization of the
      section is era-dependent (0–44% by month sampled), so retrieval is tiered:
      TOC hit → direct; else OCR a thin page-header strip per page to locate the
      section; enumerate 号外 separately (their PIDs are not interleaved). See the
      survey addendum in `docs/spikes/spike-a-kanpo.md`.
- [ ] Regex + rank/branch/unit dictionary extraction; LLM assist for irregular phrasings
      and OCR noise.
- [ ] Normalize to canonical ranks, branches, units, dates.
- [ ] Rank-consistency validation — a promotion must follow from the person's prior state.
- [ ] Reconcile events against roster snapshots: a promotion between two snapshots should
      match the rank change observed across them. (Full reconciliation needs Phase-3
      output; early mining validates against whatever snapshots exist.)
- [ ] Treat every extracted event as a **proposal**, not truth. Kanpō OCR is imperfect and
      same-name collisions are real.

## Phase 5 — Linkage + deployment (weeks 26–36)

**Delivers:** Splink linkage to the academy dataset and to events; adjudication queue;
division-level deployment table; officer-year join.

**Exit criterion:** observations and events resolve to persons; deployment history is
derivable.

- [ ] Blocking on cohort / commissioning-year / branch (keys confirmed by Spike D), then
      Fellegi–Sunter scoring with kanji variant comparators and era-date tolerance.
- [ ] **Ground-truth-trained thresholds** — fit auto-link/auto-reject bands on true
      match/non-match pairs; the ambiguous middle goes to adjudication with both records
      and images side by side.
- [ ] Alias model for mid-career name changes — neither fracture one career nor merge two people.
- [ ] `UnitDeployment` table at **division granularity first** (well documented, high
      coverage), refined to regiment where sources allow. Start from the documented
      Kwantung Army rotation. Cite sources; grade confidence. (Curation can begin any
      time after Phase 0 — it is a research task, not a code dependency.)
- [ ] Join officer-year unit history × unit deployment → officer-year theater history.

## Phase 6 — QC hardening + export (weeks 34–42)

**Delivers:** gold/blind re-serves, metrics dashboards, and the data exports.

**Exit criterion:** accuracy is measured; the datasets generate on demand.

- [ ] Blind re-serve of held-out gold pages to measure human *and* machine accuracy.
- [ ] Targeted double-entry on names and other high-cost fields only.
- [ ] Live metrics: throughput, flag rate, inter-annotator agreement, linkage yield,
      event precision/recall, **coverage-vs-worklist** (the guard against silent
      incompleteness).
- [ ] Exports: officer-year panel · event table · deployment history · data dictionary.
- [ ] Versioned CSV/Parquet stamped with DB version and regenerable from the audit log.

## Phase S — Secondary track (after the main goal ships)

Begins only once the Officer Index is delivered **and** the personal-copy manuals are in
the project's private storage (scan contents are not committed to this public repo).
Reuses Layers 1–4 and 9 wholesale; adds only two new capabilities.

- [ ] Extend template registration to engineering datasheet and weight/limit layouts.
- [ ] **Chart digitization** for the fuel/air performance charts — these are plotted
      curves, not tables; reading them means recovering data points from a graph
      (human-guided, WebPlotDigitizer-style). A distinct capability, not table extraction.
- [ ] **Modernization export** — faithful transcription of a complex bracketed original,
      then a clean, translated, modern table.
- [ ] Benchmark everything against the hand-transcribed samples.

---

## Decisions record

Settled with the project lead, 29 July 2026; later decisions carry their own date.

| # | Decision | Answer | Consequences |
|---|---|---|---|
| 1 | **VLM choice** | Deferred pending analysis — see `docs/vlm-selection.md`; final call after a bake-off on Spike C pages | Lead's machine has **no discrete GPU** (integrated graphics, 16 GB RAM), so fine-tuning happens on a rented GPU; local inference means a small quantized model on CPU, or hosted inference |
| 2 | **Hosting** | Lead's personal machine; a small hosted VM is acceptable later if workflow needs it | Docker Compose targets the local machine. **Superseded twice:** the offsite-backup requirement was removed 31 Jul 2026, and backups entirely on 2 Aug 2026 (decision 8) |
| 3 | **Team** | Two people (lead + one contributor) while the structure is built; verifiers join for the labor phase once it's ready | The workstation must be built for later multi-user onboarding (per-user attribution) even though it starts with two accounts. Undergrad-facing UX simplicity becomes a Phase-1 design criterion, not a nice-to-have. **Amended 2 Aug 2026 by decision 7:** reviewer ≠ author is *not* enforced by the system |
| 7 | **Worker identity** (2 Aug 2026) | Each worker enters an issued **id code**, which is their unique identifier. No passwords, no SSO, **no roles** | Attribution, not access control — the requirement is that work is recorded to whoever did it. The code lives in `app_user.login`, so the frozen schema is untouched. The workstation may leave this machine (depends on the human-hours estimate for the remaining work), which is why codes are minted with ~57 bits of entropy and why TLS/a tunnel is a condition of that move. See `docs/decision-workstation-auth.md` |
| 4 | **Private data home** | Lead's personal machine, outside this repo's working tree | Fixed local path convention, documented in `docs/`; included in the local backup snapshot; never referenced by absolute path from committed code |
| 5 | **Academy dataset** | Lead provides it personally | Spike D reduces to a handoff: get the file, confirm the blocking keys (name + commissioning date/cohort + branch) |
| 6 | **NDL/JACAR bulk access** | Research use; special permission unlikely to be needed | Spike B still records observed rate behavior and terms so retrieval stays polite and defensible |
| 9 | **The database is a file** (2 Aug 2026) | **SQLite, not Postgres. Docker removed.** One `officer-index.db` you can copy | The deliverable is the officer record, and the requirements on it are that it be easily shared, easily interacted with, and easily accessible for further research. A server on one machine fails all three; a file is opened by DB Browser, pandas, R and Excel with nothing installed. It also makes the working pattern possible: someone transcribes on their machine and hands back a file to merge. Migrated with 3,565 rows on the day the decision was made, when the cost was near zero. `scripts/export_record.py` writes the record and work log as CSV alongside it |
| 8 | **Backups** (2 Aug 2026) | **Removed entirely.** No scheduled tasks, no scripts, no second copies anywhere | Every operational failure this project has hit came from the backup machinery, which was protecting ~112 MB of static files and a database holding two rows. The sources are online and the tools here regenerate what is derived from them; the workbook and scans have originals outside this machine. One copy of the data, in the data home. This supersedes the "database loss" mitigation in the risk table below |

Hold-out enforcement (from the ground-truth split spec) is owned by the lead.

**Panel scope (29 Jul 2026, lead):** the panel starts **1923**. The 1920 volume
(pid 930893) serves as a pre-window baseline anchor for linkage and careers; the
surviving 1922 index (pid 1152237) is ingested as an existence census for coverage
accounting and exit-dating between 1920 and 1923, not as a panel year. The missing
大正11 roster volume therefore costs the panel nothing. Kanpō 1921–22 exit lists are
still mined so attrition across the gap is explained, never silent.

## Success metrics

| Metric | Target |
|---|---|
| Coverage | ≥ 99% of officers per targeted 1922+ volume, vs. worklist/seniority counts |
| Name accuracy | ≥ 99% exact match on held-out ground truth after review |
| Event miner | Measured precision/recall for promotions and exits; rank-consistency validation passing |
| Linkage | High auto-link rate on strong keys; small adjudication queue |
| Throughput | Propagation years at a multiple of the recorded Phase-1 officers/hour baseline |
| Benchmark suite | At or above the typed-vertical OCR baseline; table-field accuracy vs. hand-transcribed truth |
| Reproducibility | Every figure regenerable from a versioned export and traceable to images/gazette refs |

## Top risks

| Risk | Mitigation |
|---|---|
| Silent incompleteness — officers missing from the panel without anyone noticing | Coverage-vs-worklist metric; seniority-anchor auditing; explained exits via Kanpō |
| Drift back to bottom-up detection / crop-tuning | Architectural commitment above; no per-page self-improving detector |
| VLM/OCR hallucination on vertical names — silent and plausible | Proposal-only role; dual-engine agreement; ground-truth fine-tuning and measurement |
| **Database loss destroys human labor** — transcription hours are the costliest asset and all live in one database | **Accepted, unmitigated** (lead, 2 Aug 2026 — decision 8). Backups are gone. The counterweight is that finished work leaves the machine as shared exports rather than sitting only in a local database |
| Template registration fails on degraded real pages (the design's load-bearing bet) | Spike C proves it on real scans, including damaged pages, before build-weeks are committed |
| Kanpō full text patchy for parts of 1922–1937 | Spike A measures coverage first; weak years get scoped OCR, planned rather than discovered |
| NDL/JACAR rate limits or terms constrain bulk retrieval | Spike B surfaces limits; local cache/mirror + politeness layer if needed |
| Kanpō OCR errors and same-name collisions | Rank-context validation; reconcile against roster continuity; linkage disambiguation |
| Ground truth contaminates evaluation | Wall off `ReferenceTruth`; split fixed by committed manifest; named enforcement owner |
| Name changes fracture or merge careers | Explicit alias model; adjudicated, ground-truth-trained linkage |
| Scope creep delays collection | Phase 1 is independently useful and is the only collection gate; miner/linkage/deployment trail into the collection year |

## Immediate next steps

1. Run the four de-risking spikes (A–D) — they are the cheapest information in the
   project and everything downstream is shaped by their answers. *(In progress: A/B
   reconnaissance and the VLM analysis under way; D is a handoff from the lead.)*
2. Register the ground truth and fix the train/hold-out split per the definition of done —
   this unlocks both measurement and VLM tuning and is the one irreversible Phase-0 call.
3. Define the private-data path convention on the lead's machine — one copy, one
   folder, no backups (decision 8).
4. Verify and freeze schema + vocabularies against real 1922+ pages.
5. Begin the division-level deployment reference table (theater by unit-year), starting
   from the documented Kwantung Army rotation — a research task that can run now.
