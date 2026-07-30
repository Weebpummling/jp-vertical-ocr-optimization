# Spike D — academy dataset reconnaissance · ANSWERED (29 Jul 2026)

**Question:** do the blocking keys the linkage design assumes (name + commissioning
date/cohort + branch) actually exist in the 15k academy dataset with usable quality?

**Verdict: yes — and the dataset is better prepared for linkage than the design assumed.**

The dataset (an xlsx held by the lead; stays out of this repo per the data policy) holds
**15,029 officers × 69 columns**, one sheet. Findings relevant to Layer 8:

## Blocking keys — all present

| Design key | Dataset column(s) | Fill | Notes |
|---|---|---|---|
| Name | `fullname` (+ `surname`/`name`) | 100% | Kyūjitai forms as printed |
| Cohort / commissioning | `cohort` (陸士期 class number) | 100% | No commissioning *date*, but class number is the standard proxy and maps to commissioning year |
| Branch | `branch` | 100% | Japanese labels matching our vocab; variants present (要塞砲 / 要塞砲兵) — normalization map needed |

## Bonuses the design didn't count on

- **`fullname_simp`** — a shinjitai-normalized name column (100%) — the variant-
  equivalence problem is pre-solved on the dataset side; our kanji_variant table only
  has to cover the roster side.
- **Alias columns** (`surname_alt`/`name_alt`/`fullname_alt`, ~5.4% filled) — mid-career
  name changes are already recorded (e.g. adoption-name changes). This feeds the alias
  model in Layer 8 directly and supplies ready-made test cases.
- **`rank_tot`/`rank_branch`** — graduation seniority within cohort (100%). Roster
  seniority ordering within a rank cohort should correlate; a free cross-validation
  signal for linkage.
- **Sentinel to handle:** missing alt-names are the literal string `NANA` (concatenated
  NAs), not empty — parse accordingly.

## Additional columns present

Origin prefecture (+ coordinates, ~72%), `social_class` (commoner/samurai/peer, 72%),
cadet-school and staff-college flags, attaché service, and initial unit (name +
prefecture + coordinates, 100%). Further affiliation columns exist beyond the linkage
keys; they are not used by this pipeline.
The initial-unit column also gives Layer 8 a second unit anchor at career start.

## Consequences

- Splink blocking on `cohort` × `branch` with name comparators over
  `fullname`/`fullname_simp`/`fullname_alt` is viable exactly as designed.
- Add fortress-artillery and any other observed branch labels to `data/vocab/branch.csv`
  during vocabulary verification, with a dataset↔vocab normalization map.
- `Person.academy_dataset_id`: the dataset has **no explicit ID column** — the stable key
  is row identity. Assign a durable ID (e.g. row hash of cohort+fullname+branch) at
  import time and freeze it.
