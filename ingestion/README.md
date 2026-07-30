# Layer 1 — Ingestion & imaging

Bring roster pages and *Kanpō* issues under management with stable, provenanced references.

- **Worklist registry** seeded from the NDL Research Navi military guide (roster PIDs and
  editions), plus JACAR / Shōwakan mirrors and *Kanpō* date ranges. Each becomes a
  `source_volume` with coverage notes.
- **IIIF-first retrieval** — `https://dl.ndl.go.jp/api/iiif/{PID}/manifest.json`; per-frame
  region API for on-demand crops. Non-IIIF sources store source URL + retrieval date.
- **Deep-zoom delivery** via OpenSeadragon/Mirador; region crops addressable by URL, so every
  value stays independently re-checkable.
- **Multi-scan pages** — one logical page may hold several institutional scans, so an
  annotator can flip to a cleaner copy when one is degraded or seal-obscured.

## Verified endpoints (Spike B, July 2026)

- Manifest: `https://dl.ndl.go.jp/api/iiif/{PID}/manifest.json`
- Region: `https://dl.ndl.go.jp/api/iiif/{PID}/R{frame:07d}/{region}/{size}/{rotation}/default.jpg`
- Metadata search: `ndlsearch.ndl.go.jp/api/opensearch?title=…` and
  `/api/sru?operation=searchRetrieve&query={CQL}&recordSchema=dcndl`
- NDL OCR text for roster volumes (Next-Gen DL):
  `https://lab.ndl.go.jp/dl/api/book/fulltext-json/{PID}` (with coordinates) and
  `GET /page/search?f-book={PID}&q-contents={term}` for within-volume search
- Observed ~1.5 s/image; no keys; politeness + local cache, per `docs/spikes/spike-b-ndl-access.md`

`worklist-roster.csv` seeds the volume registry with verified PIDs for 1914–1936.