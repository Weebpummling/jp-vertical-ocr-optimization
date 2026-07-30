# Layer 8 — Record linkage

Resolve every observation and event to one `person`, and tie the corpus to the existing
academy dataset.

Three jobs:

- **Cross-year identity** — mostly propagation, with a probabilistic backstop across gaps.
- **Academy-dataset link** — name + commissioning date/cohort + branch are very strong
  blocking keys, so this is near-deterministic.
- **Event attachment** — Kanpō events by name + date + rank context, which also disambiguates
  same-name officers.

Method: blocking on cohort / commissioning-year / branch, then Fellegi–Sunter scoring (Splink)
with kanji variant comparators and era-date tolerance.

Thresholds are **trained on ground truth**, not guessed — the verified dataset supplies true
match/non-match pairs, so auto-link and auto-reject bands are calibrated on reality. The
ambiguous middle goes to an adjudication queue with both records and images side by side.

Name changes are handled with an explicit alias model, so a mid-career change neither fractures
one career nor merges two people.