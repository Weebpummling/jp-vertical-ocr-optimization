# Layer 6 — Kanpō event mining

The *Kanpō* (官報) is the **easiest** automation target in this project, not the hardest.
Unlike the roster tables, its 叙任及辞令 personnel actions are regular, templated *prose* —
and NDL already publishes full text.

| Event | Japanese | Captured |
|---|---|---|
| Commissioning | 任官 | name, branch, rank, date |
| Promotion | 進級 / 任〔higher rank〕 | name, old→new rank, date |
| Assignment | 補職 / 転任 | name, unit/post, date |
| Reserve transfer | 予備役編入 / 待命 | name, date |
| Death | 死去 / 戦死 | name, date |

Pipeline (revised per Spike A, `docs/spikes/spike-a-kanpo.md`): enumerate issue PIDs by
date (they run sequential; `opensearch?title=官報 YYYY年MM月DD日` resolves a date to its
PID) → fetch the IIIF manifest and filter `structures[].label` for the personnel section
(**old kanji 敍任及辭令** as well as 叙任及辞令) → OCR only those canvases with
**NDLOCR-Lite** (the modern-documents engine; NDL's mass-OCR text for Kanpō is
search-UI-only, no export API — see `docs/ndl-prior-work.md`) → regex +
rank/branch/unit dictionary extraction, with LLM assist for irregular phrasings →
normalization → identity resolution → validation.

**Every extracted event is a proposal.** A promotion must be rank-consistent with the person's
prior state, and events reconcile against roster snapshots: a promotion between two snapshots
should match the rank change observed across them. The Kanpō is voluminous and its older OCR
is imperfect — scope by date and section, and validate against roster continuity.