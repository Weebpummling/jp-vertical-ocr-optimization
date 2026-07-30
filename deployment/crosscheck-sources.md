# Individual deployment cross-check — source research (29 Jul 2026)

**Question:** can we verify that a *specific officer* deployed to a theater (took his
company out), and bracket when he left and returned — rather than only inferring it
from his unit's location? Purpose: upgrade unit-level deployment inference to
individually confirmed service records where sources allow (Layer 7).

**Answer: yes, for a meaningful subset, from fully open digitized sources — via a
three-layer cross-check.** Individual exact dates exist only in restricted service
records (spot-validation, not bulk).

## The cross-check design

```
[1] Officer → unit timeline        stopnen rosters (annual) + Kanpō 補職/転任 (dated)
[2] Unit → theater round trip      出動/凱旋 dates: 満洲方面部隊略歴 (JACAR
                                   C12122501000 series), 聯隊史, 戦史叢書, rotation
                                   schedules → the Layer-7 reference table
[3] Officer-in-theater confirm     満洲事変論功行賞 roll (Kanpō, 1935) — named
                                   individual award for Incident service
─────────────────────────────────────────────────────────────────────────
[1]×[2] = presumed deployment window for the officer
   +[3] = CONFIRMED service, upgrading the presumption to evidence
```

Contact measure: two officers' windows overlapping in a theater = co-deployment tie;
same unit in theater = strong tie. [3] adds a per-officer `confirmed` flag that
distinguishes "his unit went" from "he demonstrably served."

## Layer [3] — the award roll, verified in the digitized Kanpō (live probe)

- The 満洲事変 merit awards (功labeled 金鵄勲章, 勲章 grades, 賜金 classes) were
  conferred 29 Apr 1934 but **gazetted a year later, serialized in issue appendices
  (附録) titled 「敍任及辭令二」, April–May 1935**. Verified instalments: 官報第2483号
  (1935-04-16) = pid 2958962, appendix canvases 18–34; 第2505号 (1935-05-13) =
  pid 2958984 (includes posthumous entries with death dates). Instalment span ≈ pids
  2958952–2959005.
- Format (image-verified): dense columnar name lists — decoration grade / 賜金 class
  headers, then rank + full name with 同 ditto marks. **No per-name unit column** —
  unit attribution comes from our own panel via record linkage (name + rank at 1934).
- **従軍記章 (campaign medal): no recipient roll was ever published** — only the
  ordinance (勅令225号, gazetted 1934-07-23, pid 2958743). Not minable; medal evidence
  lives only in individual service records.
- 留守名簿 (home-front rosters) postdate this era (system created 1944) — not usable.

### Miner implications (feeds Phase 4)

- 附録 contents are invisible to manifest TOCs (`structures` marks only `附録/p1`) —
  instalment pages must be classified by reading each appendix's first page
  (敍任及辭令二 vs 廣告二 ad-overflow).
- **PID arithmetic in this window: pid = issue番号 + 2956479** (verified at three
  issues) — issue-number ↔ PID resolution without search calls.
- **号外 are bound into the same-day issue's PID as trailing canvases** (labeled
  `号外/p1` in structures); only Sunday/holiday 号外 get their own sequential PID.
  This resolves Spike A's open question — the sequential walk *does* cover 号外.
- dl.ndl.go.jp's undocumented full-text `POST /api/item/search` rate-limits
  aggressively (429) — do not build on it.

## Layer [2] — unit round-trip sources (the Layer-7 curation worklist)

| Source | Gives | Access |
|---|---|---|
| 満洲方面部隊略歴 (postwar unit-history summaries) | Unit-by-unit theater chronology | JACAR ref C12122501000 series, free images |
| 聯隊史 / 師団史 | 動員下令 / 出動 / 凱旋 dates to the day; often 将校職員表 naming deployed officers | NDL Digital Collections (many in the library-transmission tier), prefectural libraries |
| 戦史叢書 (all 102 vols full-text) + NIDS catalogs | Operational assignments, order of battle | nids.mod.go.jp/military_history_search |
| 陣中日誌 / 戦闘詳報 survivors | Officers named in actions, daily locations | JACAR (NIDS 満洲-満洲事変 series); survival patchy for 1931–34 |
| Kwantung Army division rotation | Division-year location backbone | Documented rotation schedule + OOB references (rikukaigun.org, 帝国陸軍編制総覧) |

Bonus for [1]: regimental histories' 将校職員表 directly name officers who deployed —
a second individual-level confirmation source, unit by unit.

## Individual service records (exact personal dates) — restricted tier

兵籍簿/履歴書 carry the officer's own 従軍事項 entries (departure/return to the day),
but access is family-only at prefectures; the NAJ-transferred series (将校名簿(陸軍),
fonds 4181376, from the MHLW transfers completed 2024) are requestable under the
Public Records Act with personal-information screening (eased for long-deceased
subjects). Treat as **spot-validation for a sample of officers**, not a bulk source —
e.g., to measure how well [1]×[2]×[3] brackets true dates.

## No prior art to reuse

No open machine-readable IJA officer-career or deployment database exists (2025–26
search) — the Officer Index will be the first. Compiled OOB references (rikukaigun.org,
generals.dk, 秦郁彦's 総合事典) are useful curation aids, not data sources.

## Caveats

- Award-roll coverage is service-biased: decorations skew toward those in actions;
  quiet garrison service in-theater may go unrecorded in [3] while still real.
  [3] is a one-way confirmation, never an exclusion test.
- The roll's OCR is the hardest text yet (dense columns, ditto marks) — extraction
  quality must be measured against a hand-checked instalment page before use.
- 感状 (citations) were not systematically gazetted; survivors sit in JACAR 陸軍省大日記.
