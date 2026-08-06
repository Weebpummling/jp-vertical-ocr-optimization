# Spike B — NDL IIIF access & roster coverage · ANSWERED (29 Jul 2026)

**Question:** are the 1922–1936 seniority lists digitized and retrievable at working
rates, and under what terms?

**Verdict: yes on all counts — the full window is digitized, internet-public, IIIF-served,
and (bonus) NDL's own OCR text is retrievable per volume via a documented API.**

## Roster coverage (verified PIDs)

Every edition in the window is in NDL Digital Collections, internet-public, Public
Domain Mark. (An initial title-only search missed 1925–1932; the Next-Gen DL search
API surfaced them — catalog records vary, so worklists should be built from *both*
`ndlsearch` and the `lab.ndl.go.jp/dl` API.)

| Edition (調 date) | PID | Verified |
|---|---|---|
| 大正3–13 set incl. 大正11 (1922), 大正12 (1923), 大正13 (1924) | 930891–930895, 930897 (+ 索引 930896/930898–930900) | ✓ (individual 調 dates: resolve via `lab.ndl.go.jp/dl/api/book/{PID}`) |
| 大正14 (1925) | 1908495 | pub-year inference — confirm |
| 大正15年9月1日調 (1926) | 1908494 | ✓ API |
| 昭和2 (1927) | 1454434 | confirm |
| 昭和3年9月1日調 (1928) | 1454433 | ✓ API |
| 昭和4 (1929) | 1454435 | confirm |
| 昭和5 (1930) | 1454436 | confirm |
| 昭和6 (1931) | 1454438 | confirm |
| 昭和7 (1932) | 1454441 | confirm |
| 昭和8 (1933) 索引付 | 1449426 | ✓ manifest + page images fetched |
| 昭和9年9月1日調 (1934) | 1449429 / 1449461 / 1449981 | ✓ |
| 昭和10年9月1日調 (1935) | 1445522 / 1449474 | ✓ |
| 昭和11年9月1日調 (1936) | 1454447 | ✓ API (924 pp) |

Also present and internet-public: **reserve/後備役 lists** (予備役 942278–942279,
後備役 942280–942281 for 大正12/13; Meiji-era 843985–843986, 1939211) — needed by
Layer 5's disappearance handling. ~~Worklist task: enumerate reserve-list editions for
the Shōwa window the same way.~~ **Done — see the addendum below.**

## Addendum — reserve-list enumeration for the Shōwa window (1–3 Aug 2026)

Both reserve series were enumerated by exact-title SRU query
(`陸軍予備役将校同相当官服役停年名簿` / `陸軍後備役…`), each PID then confirmed
internet-public by fetching its IIIF manifest. Twelve editions added to
`ingestion/worklist-roster.csv`; the two series run in parallel, same 4月1日調
date, same publisher (偕行社).

| 調 year | 予備役 pid | 後備役 pid |
|---|---|---|
| 大正12 (1923) | 942278 | 942280 |
| 大正13 (1924) | 942279 | 942281 |
| 大正15 (1926) | 1908490 | 1908476 |
| 昭和2 (1927) | 1445528 | 1454449 |
| 昭和3 (1928) | 1454437 | 1454445 |
| 昭和4 (1929) | 1449978 | 1454450 |
| 昭和6 (1931) | 1444345 | 1452970 |
| 昭和9 (1934) | 1454448 | 1454463 |

**The apparent gaps are partly explained, not silent.** No full edition surfaces for
昭和5, 7, 8 or 10. For two of those years a **追録 (supplement)** exists instead,
and the supplements merge both series into one volume
(`予備役・後備役将校同相当官服役停年名簿追録`):

- **昭和7年 (1932)** — pid 1449401, 266 canvases, internet-public.
- **昭和10年 (1935)** — pid 1906893, **not** internet-public (IIIF 404;
  library-transmission only). Needs a 送信サービス/onsite route if that year matters.

**Both APIs were swept, per this spike's own lesson.** A second pass over
`lab.ndl.go.jp/dl/api/book/search?keyword=服役停年名簿` (123 records, both series,
active and reserve) returns exactly the reserve set above plus the Meiji anchors —
no edition that the SRU title query missed. The two independent catalogues agreeing
is what makes the remaining gaps a finding rather than a search failure:

- **昭和7 (1932)** — covered by the public 追録.
- **昭和5 (1930), 昭和8 (1933)** — no reserve edition of any kind in either API.
- **昭和10 (1935)** — 追録 exists but is not internet-public; note it does not appear
  in the lab API sweep at all, which is consistent with that index covering only
  public items. Absence there is therefore not evidence of absence generally.

No 大正14 (1925) reserve edition surfaced either. Whether these are non-publication
years or non-digitized volumes is a question for NDL's printed catalogue, not the
APIs.

Consequence for Layer 5: an officer's disappearance from the active list can be
checked against a reserve list in the same or the following year for every year of
the window **except 昭和5 and 昭和8**, where the check degrades to the neighbouring
edition plus Kanpō.

## Access patterns (verified live)

- Manifest: `https://dl.ndl.go.jp/api/iiif/{PID}/manifest.json` (also `www.dl.ndl.go.jp`)
- Region: `https://dl.ndl.go.jp/api/iiif/{PID}/R{frame:07d}/{region}/{size}/{rotation}/default.jpg`
- Source scans are high-res (5774×4067 for pid 1449426; server caps long side at 5000 px
  on delivery); 874 canvases for the 1933 volume.
- Observed latency ~1.5–1.7 s per image (1600px page or full-res region crop),
  single-threaded, from this machine. A full volume ≈ 20–25 min serial — fine with the
  planned local cache; politeness over parallelism.
- **Bonus — NDL OCR text per roster volume:** the rosters are in the Next-Gen Digital
  Library, so `GET https://lab.ndl.go.jp/dl/api/book/fulltext-json/{PID}` returns NDL's
  own OCR text **with coordinates** (verified on 1454447; >10 MB payload), and
  `GET /page/search?f-book={PID}&q-contents={term}` does within-volume search. This is
  a free third reading engine for Layer 4 and a bootstrap for template building —
  treat it like any machine proposal, never authoritative.
- NDL Search APIs for worklist building: OpenSearch
  (`ndlsearch.ndl.go.jp/api/opensearch?title=…`) and SRU
  (`/api/sru?operation=searchRetrieve&query={CQL}&recordSchema=dcndl`), both verified;
  OAI-PMH exists for bulk metadata.

## Terms / rate limits

No API keys. No published numeric rate limits; NDL states concurrent-request limits
exist (thresholds undisclosed) and *requests* notification for continuous automated
access; prior application required only for commercial use. Items here are Public
Domain Mark; attribution 国立国会図書館. Our posture (research, polite serial
retrieval with local caching) fits without special permission — matches decision #6.

JACAR is a **weak mirror** for this window: Meiji-era roster copies only, no public
API. NDL is the digitization source; JACAR remains relevant for Layer 7 deployment
sources (陣中日誌 survivors), not for rosters.

## Spike C reconnaissance (bonus finding, from fetched pages)

The 1933 volume's officer tables are **typeset, not handwritten**, with strong ruling
lines, a rigid ~10-column-per-page grid, and seniority numbers printed in **Arabic
numerals**, ascending monotonically right-to-left (165→199 observed across one spread
of the 歩兵大佐 section). Every structural assumption of the template-registration
design is visible on the real artifact. Spike C's remaining work — an actual
deskew/align/assign experiment on ~10 pages — now starts from downloaded samples
(pid 1449426, frames 60±).
