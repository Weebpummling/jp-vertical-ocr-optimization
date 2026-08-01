# Decision needed — naming the four date rows of `showa-teinen-meibo-A`

**Status: RESOLVED 1 Aug 2026.** Raised and settled the same day: the lead
reviewed the evidence below and accepted all four proposed names. All nine
fields of `showa-teinen-meibo-A` are now `confirmed: true`.

One qualification is recorded in the artifact rather than dropped. Three of the
four are backed by documentary evidence from the volume itself and carry
`"evidence": "documentary"`. Band `[3,4]` (`prev_rank_date`) rests on structural
inference only — no printed legend defines it — and carries
`"evidence": "inferred"`. It is the field to revisit first if a contradicting
record appears; 補職年月日 remains a live alternative.

## What is already settled

Five of the nine fields were read directly off the page and are marked
`confirmed: true`: `seniority_no`, `post`, `court_rank_decorations`,
`name_raw`, `cohort`. Cell rectangles were verified against the scan (seniority
915/916, 平岩棟一/乾忠夫, cohort 25/22).

The four rows above the seniority number are all dates or date-like, they
register cleanly, and their rectangles are right. What they *mean* is the open
question.

## The evidence

Two sections behave very differently, which is what makes the structure legible.

| Band | 歩兵大佐 (frame 100) | 砲兵少尉, cohort 43 (frame 500) |
|---|---|---|
| `[1,2]` | `〇、一、一`, then 同 across the section | `一、一〇、七`, then 同 |
| `[2,3]` | `昭八、…`, then 同 | `昭六、一〇、二六`, then 同 |
| `[3,4]` | per-officer 昭和-era dates | **blank for every officer** |
| `[4,5]` | per-officer 明治/大正 dates | **blank for every officer** |

Three independent cross-checks, all from the volume itself:

1. **The front matter dates the cohorts.** Frame 9 prints the 士官候補生 class
   table: the 43rd class is 昭和6年10月26日. The 砲兵少尉 section is entirely
   cohort 43, and its band `[2,3]` reads exactly that date.
2. **Band `[1,2]` is the arithmetic of band `[2,3]`.** 昭和6年10月26日 to the
   volume's 昭和8年9月1日調 date is 1 year 10 months ~6 days; the cell prints
   `一、一〇、七`. For the 大佐 section, `〇、一、一` against an appointment about
   two months before the 調 date. This is 実役停年 — the quantity in the volume's
   own title — not a date.
3. **Band `[4,5]` tracks the cohort field.** In the 大佐 section, cohort 22 →
   明43.12.26 and cohort 23 → 明44.12.26, and officers sharing a cohort print 同.
   Consecutive cohorts, consecutive years, matching the class table's cadence.

## The four decisions

| # | Band | Name (accepted) | Reading | Basis |
|---|---|---|---|---|
| 1 | `[1,2]` | `service_in_rank` | 実役停年 — elapsed service in current rank, 年・月・日 | Documentary — arithmetic checks out on both sections |
| 2 | `[2,3]` | `rank_date` | 現階級任官年月日 — appointment to current rank | Documentary — matches the front-matter class date exactly |
| 3 | `[3,4]` | `prev_rank_date` | 前階級任官年月日 — appointment to previous rank | **Inferred** — structural only |
| 4 | `[4,5]` | `commissioning_date` | 少尉任官年月日 — first commissioning | Documentary — tracks cohort; the schema's 任官年月日 |

Item 3 was the weak one. The argument is only that the column is per-officer,
昭和-era, and empty for officers who have never been promoted — consistent with
a previous-rank column, but no printed legend defines it and the stacked digits
could not be resolved reliably enough to test against a known promotion. It
could equally be 補職年月日. Accepted on review; flagged in the artifact.

Two consequences that follow from the decision:

- **`service_in_rank` is not a date.** If confirmed, it should not be parsed by
  `reading/eradate.py`; it needs a duration parser instead.
- **Only `commissioning_date` has a home in the schema** (`observation.commissioning_date`).
  Items 1–3 have no column. If they are worth capturing, that is a deliberate
  migration against a frozen schema, not something to slip in.

## To apply a decision

In `templates/showa-teinen-meibo-A.json`, set the field's `confirmed` to `true`
and replace its `note` with the settled reading. Correct any name you disagree
with in the same edit. Then:

```bash
python -m unittest discover -s reading -p "test_*.py"
```
