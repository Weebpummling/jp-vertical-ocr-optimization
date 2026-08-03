# JACAR handwritten documents — retrieval and decipher workflow

How to take a JACAR reference code (e.g. `C14030374300`, `C14030562600` — the
髑髏隊 combat-account pair) from URL to a referenced transcription + translation,
using the tooling this project already has. JACAR has **no fulltext API and no
OCR text layer** (Spike E); everything below treats machine output as a proposal,
never authoritative, per the standing commitments.

## 1. Retrieval — JACAR serves one raw PDF per reference code

The modern JACAR viewer (`/das/image/{REF}`) is PDF.js loading a single PDF.
The URL is embedded in the viewer page HTML and is extractable non-interactively:

```bash
curl -s "https://www.jacar.archives.go.jp/das/image/C14030562600" \
  | grep -o 'content/item[^"]*\.pdf'
# → content/item/aj12/C200130641800/cover/C14030562600.c1126200009.mansyuu_zihen_033.0305_01.pdf
```

Prefix with `https://www.jacar.archives.go.jp/` and GET (the `cover`/`raw` path
segment variants serve the same file). Verified 31 Jul 2026 on both 髑髏隊 records
(3.2 MB / 4.8 MB, 31 pages each). The parent code in the path (`C2001306…`) is the
simple-search bundle id; it is not constructible from the ref code — always parse
it out of the viewer page. Metadata (title, hierarchy, dates) is at
`/das/meta/{REF}`.

Scripted: [`scripts/jacar_pull.ps1`](../scripts/jacar_pull.ps1) does the
resolve + download (cached into `%JP_OCR_DATA%/jacar/{REF}/`) and the page
rendering below in one call.

## 2. Page images

`pypdfium2` (already a dependency of NDLOCR-Lite, also on the system Python)
renders the JBIG2 scans cleanly; 150 DPI ≈ 1242×1756 px is enough for both the
vision-LLM and NDLOCR-Lite. NDLOCR-Lite's CLI also accepts `--sourcepdf` directly,
so page extraction is only needed for the vision engine and for cell/line crops.

On machines with no Python at all, `scripts/jacar_pull.ps1` renders instead via
the Windows built-in PDF engine (`Windows.Data.Pdf`, WinRT) — no installs, and
it decodes the JBIG2 scans; this is how the C14030374300 pages were produced
(2200 px wide).

## 3. Engine A — NDLOCR-Lite (local, CPU)

Installed at `%LOCALAPPDATA%\ndlocr-lite\` (v1.2.3, CC BY 4.0):

- `windows\ndlocr_lite_gui.exe` — GUI for interactive use.
- `cli\` — the repo checkout; `venv\` — Python 3.11 venv with its requirements.
  The **tegaki3 (April 2026) handwriting PARSeq models are the defaults**; models
  ship in `cli\src\model\`.

```bash
"%LOCALAPPDATA%\ndlocr-lite\venv\Scripts\python.exe" \
  "%LOCALAPPDATA%\ndlocr-lite\cli\src\ocr.py" \
  --sourcepdf <doc>.pdf --output <outdir>
```

Measured on C14030562600 (31 handwritten pages): **36 s total on CPU**. Outputs
`.txt` (reading-order text), `.json`/`.xml` (per-line boxes — save these; they are
the line-aligned ground-truth substrate), and a text-layer PDF. Quality on Shōwa
pen 行書: reading order and layout reliable, character accuracy roughly the
expected ~0.3 CER — a corroboration engine, not a reader.

## 4. Engine B — vision-LLM page reading

The C14030374300 precedent (transcribed + translated offsite, 31/31 images,
files in `Downloads\C14030374300_*`) sets the conventions:

- one `=== Image N ===` block per JACAR viewer image, folio stamps noted;
- `〓` = unreadable, `〔?〕` = low-confidence (translation: `[illegible]`,
  `[uncertain: …]`);
- header records source URL, provenance chain, and the machine-proposal caveat.

## 5. Ensemble + human pass

Per Spike E §4: LLMs fail *fluently*, NDLOCR fails *visibly* — so diff Engine A
against Engine B per column; disagreements become uncertainty marks for the human
pass. Verified lines (image crop from the JSON boxes + confirmed text) accrue as
fine-tuning data for the PARSeq recognizer (`train/` recipe upstream).

## 6. Translation + delivery

Unchanged from the NDL passthrough capability: chunk the transcription, translate
with frame references intact, render with `scripts/translation_docx.ps1`
(markdown → Word COM → .docx). Outputs live in the private data home, not this repo.

## Status of the 髑髏隊 pair (31 Jul 2026)

| Ref | Title | State |
|---|---|---|
| C14030374300 | 南天門 東矢大隊の夜間攻撃 (1935 lecture, 31 imgs, handwritten) | **Done + reviewed (31 Jul 2026)** — vision transcription; EN translation human-reviewed, then rank/symbol usage normalized against `data/vocab` (中尉/少尉 distinctions, unit-symbol glosses). The reviewed .docx is the authoritative text; office-machine files in `%JP_OCR_DATA%/jacar/C14030374300/`. Outstanding: handwriting verification list (names, dates, image 12/20/31) queued for the NDLOCR-Lite ensemble pass |
| C14030562600 | 髑髏隊ヲ語ル 歩32-3 (1933/34, 31 imgs, handwritten + cover art) | **Done (31 Jul 2026)** — full pipeline run: NDLOCR-Lite pass + independent vision reading (4-way parallel), per-page engine-agreement appendix, EN translation rendered to docx via `translation_docx.ps1`. Files in Downloads (`C14030562600_*`); first end-to-end validation of this workflow |
