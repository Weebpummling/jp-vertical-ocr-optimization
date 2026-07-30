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
Layer 5's disappearance handling. Worklist task: enumerate reserve-list editions for
the Shōwa window the same way.

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
