# Machine-Reading Handwritten Japanese Military Records (1920s–1940s)
## Systems survey + textbook-bootstrapping feasibility — jp-vertical-ocr-optimization project

Date: 2026-07-31. Target material: IJA war diaries, lecture records, 陣中日誌 (JACAR scans) — pen/brush, vertical, kanji + katakana, kyūjitai, some 行書/草書. Machine: Windows 11, no Python installed (installable), no GPU assumed.

Legend: **[V]** = verified from cited source. **[I]** = my inference/judgment, flagged as such.

---

## 1. Per-system assessment table

| System | Target script/era | Handles modern handwriting? | Trainable on custom data | Windows / CPU viability | License | Verdict for this project |
|---|---|---|---|---|---|---|
| **NDLOCR-Lite v1.2** (ndl-lab, Feb 2026; v1.2 Apr 2026) | Modern printed books/magazines + **experimental handwriting** | **Yes** — CER 0.268 overall, 0.279 vertical on 1,065-image handwritten benchmark [V] | Yes — training recipes in `train/README.md` (PARSeq recognizer) [V] | **Excellent**: prebuilt Windows 11 binary, no GPU, no Python needed for inference; ONNX runtime [V] | CC BY 4.0 (NDL) [V] | **Best dedicated-HTR candidate. Quick win.** |
| **NDLOCR ver.1/ver.2 (ndlocr_cli)** | Meiji–Shōwa **typeset** | No (print-focused) [V] | Partially (per-module) | Docker/Linux, GPU-oriented [V] | NDL portions CC BY 4.0; check per-module [I — verify per module] | Already covered by project's NDL typeset pipeline. Note: there is **no "NDLOCR ver.3"** — ver.3 exists only in the 古典籍 (kotenseki) line [V] |
| **NDL古典籍OCR ver.3 / NDLkotenOCR-Lite** | **Pre-Edo** classical texts, kuzushiji; used みんなで翻刻 data [V] | No — wrong era/script domain | Yes (Lite: RTMDet + PARSeq, ONNX) [V] | Lite: Windows 10, CPU, fast [V] | CC BY 4.0 [V] | Mismatch for Shōwa pen writing; possible fallback for heavily 草書 brush passages [I] |
| **KuroNet / miwo (みを) / Kaggle kuzushiji models** (CODH) | **Edo-period woodblock-printed kuzushiji** (日本古典籍くずし字データセット, 1M+ chars) [V] | KuroNet/RURI not user-trainable in practice; miwo is a mobile-only app [V] | — | miwo: Android/iOS only [V] | Dataset CC BY-SA; app free | **Confirmed mismatch**: CODH itself says accuracy drops on "materials from other periods, manuscripts, and historical documents" [V]. Skip. |
| **Kindai-OCR** (DeepApps91; Le/Kitamoto, NII-CODH lineage) | Kindai (late 19th–early 20th c.) **printed** magazines/documents [V] | Yes (CRAFT + attention/Transformer; pretrained models on Google Drive) [V] | CPU or GPU [V] | **No explicit license in repo** [V] | Not handwriting — but its 2025 paper (arXiv 2508.08537) is the key **precedent for font-rendered parallel data**, see §3 |
| **TOPPAN ふみのは / くずし字AI-OCR** | **Meiji–early-Shōwa handwriting** — explicitly built for modern hands, katakana mix, 旧字旧仮名 [V] | Vendor-side only | Commercial service (法人向け), per-job pricing, no self-serve API [V] | N/A (outsourced) | Proprietary | Only *purpose-built* engine for exactly this era. Real-world case: 50,000 pages / ~9.5M chars in ~1 month at ~70% accuracy (Kumamoto Univ. Hosokawa archive) [V]. Long-term/bulk option. |
| **Kraken / eScriptorium** | Any (trainable seg + recognition; supports vertical/RTL layouts) [V] | **Fully** — the whole point | Linux-first; Windows support weak (WSL2 realistic) [I]; CPU training slow for 3,000+ char sets [I] | Apache 2.0 | Long-term custom-model route; no ready-made Japanese vertical handwriting model exists [V — none found] |
| **TrOCR** (Microsoft) | English handwriting (IAM) / print [V] | Yes, but needs Japanese decoder swap; **no official or established Japanese-handwriting fine-tune found on HF** [V — absence] | PyTorch; CPU inference OK for base/small [I] | MIT | Architecture donor, not off-the-shelf |
| **manga-ocr** (kha-white) | Modern Japanese **print incl. vertical**, trained on Manga109-s + synthetic HTML-rendered text [V] | Not handwriting, but robust to odd fonts/vertical/furigana [V] | Yes — full synthetic-data generator pipeline in repo [V] | ViT + char-level Japanese BERT; CPU-viable, ONNX ports exist [V] | Apache 2.0 | **Best open synthetic-pipeline precedent + a fine-tune base with a Japanese decoder already in place** |
| **PaddleOCR PP-OCRv5** | Multilingual incl. Japanese; claims improved handwriting & ancient-text detection vs v4 [V — vendor claim] | Yes (full training stack) | CPU inference OK; Windows OK | Apache 2.0 | Worth a benchmark pass; vertical-historical accuracy unproven [I] |
| **Google Cloud Vision** (DOCUMENT_TEXT_DETECTION) | General; Japanese handwriting supported but weak on cursive; known trouble with mixed vertical/horizontal layouts [V — practitioner reports] | No | API; trivial | Paid (~$1.50/1k images class) | Cheap baseline to benchmark; expect layout scrambling on 陣中日誌 forms [I] |
| **Azure AI Vision Read** | Japanese is one of 9 handwriting-supported languages [V — MS docs] | No | API; trivial | Paid | Same role as GCV; benchmark both on a gold set |
| **Vision LLMs (GPT-4o/Claude/Gemini)** — current stopgap | General | Yes, with characteristic failure modes (§4) | Prompt/few-shot only | API | Paid | Keep as primary, but ensemble with dedicated HTR for disagreement-based uncertainty flags [I] |

Key sources: [ndlocr-lite](https://github.com/ndl-lab/ndlocr-lite) ([README](https://raw.githubusercontent.com/ndl-lab/ndlocr-lite/master/README.md), [NDL Lab announcement](https://lab.ndl.go.jp/news/2025/2026-02-24/)); [ndlocr_cli](https://github.com/ndl-lab/ndlocr_cli); [ndlkotenocr-lite](https://github.com/ndl-lab/ndlkotenocr-lite) ([NDL Lab](https://lab.ndl.go.jp/news/2024/2024-11-26/)); [koten OCR ver.3](https://lab.ndl.go.jp/news/2023/2024-02-07/); [miwo about](https://codh.rois.ac.jp/miwo/about/); [kuzushiji dataset](https://codh.rois.ac.jp/char-shape/); [Kindai-OCR](https://github.com/DeepApps91/Kindai-OCR); [arXiv 2508.08537](https://arxiv.org/abs/2508.08537); [TOPPAN press release](https://www.holdings.toppan.com/ja/news/2022/11/newsrelease221111.html), [ふみのは](https://www.toppan.com/ja/joho/fuminoha/), [Nikkei xTECH case study](https://xtech.nikkei.com/atcl/nxt/column/18/00138/103001636/); [kraken](https://github.com/mittagessen/kraken), [eScriptorium training guide](https://ub-mannheim.github.io/eScriptorium_Dokumentation/Training-with-eScriptorium-EN.html); [TrOCR handwritten](https://huggingface.co/microsoft/trocr-base-handwritten); [manga-ocr](https://github.com/kha-white/manga-ocr) ([synthetic generator](https://github.com/kha-white/manga-ocr/tree/master/manga_ocr_dev/synthetic_data_generator)); [PP-OCRv5](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html); [GCV vertical/horizontal issues](https://zenn.dev/chot/articles/6587f0a517fb25), [GCV handwriting trial](https://dev.classmethod.jp/articles/ocr-with-lambda-using-cloud-vision-api/); [Azure language support](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/language-support).

---

## 2. Detailed findings

### 2.1 NDL OCR lineage — the headline finding
- The main NDLOCR line goes ver.1 (2022) → ver.2/2.1 (2023, `ndlocr_cli`) → **NDLOCR-Lite (Feb 2026)**. "ver.3" exists only for 古典籍OCR. [V]
- **NDLOCR-Lite v1.2 (April 2026) added handwriting recognition.** Architecture: DEIMv2 layout detection + PARSeq text recognition + NDL reading-order module, all exported to ONNX; runs fast on plain CPUs; **prebuilt Windows binaries on the releases page** (path must contain no full-width characters). License CC BY 4.0. [V — [README](https://raw.githubusercontent.com/ndl-lab/ndlocr-lite/master/README.md)]
- Reported handwriting accuracy: **CER 0.268 overall / 0.279 vertical / 0.264 horizontal** on 1,065 handwritten images from the JaWildText benchmark (Maeda & Okazaki 2026). [V]
- **Caveat [I]:** JaWildText is contemporary "in-the-wild" Japanese handwriting, not kyūjitai 1930s field writing. Expect worse than 0.27 CER on 陣中日誌 out of the box — likely much worse on 草書 passages. But ~73% character accuracy as a *free, local, CPU* second engine is already useful for ensemble/uncertainty work, and the training recipe is published, which makes it the natural fine-tuning target.
- 古典籍OCR ver.3 / kotenOCR-Lite incorporated みんなで翻刻 (crowdsourced transcription) data and does handle *handwritten cursive*, but of the pre-Edo/Edo domain. [V] Possible niche fallback for brush-heavy 草書 pages. [I]

### 2.2 Kuzushiji ecosystem — confirmed mismatch
- KuroNet, the Kaggle-winner models, and miwo (v1.1 uses CODH's newer RURI model) are all trained on the 日本古典籍くずし字データセット built from **Edo-period woodblock-printed books**. CODH's own documentation states accuracy is high for Edo printed editions and "may decrease for materials from other periods, manuscripts, and historical documents." [V — [miwo about](https://codh.rois.ac.jp/miwo/about/)]
- Shōwa military records differ on every axis: pen vs brush, kyūjitai standard forms vs hentaigana-rich kuzushiji, katakana-heavy okurigana, form-based layouts. **[I]: near-zero transfer expected; do not invest here.** miwo is also mobile-only — no batch/API path. [V]

### 2.3 Kindai/modern-handwriting research and commercial systems
- **TOPPAN** announced (Nov 2022) "Japan's first" AI-OCR for **Meiji–early-Shōwa handwritten text**, explicitly citing the challenges of this material: writer-dependent cursive variation, diverse writing implements, mixed katakana, 旧字旧仮名. [V — [press release](https://www.holdings.toppan.com/ja/news/2022/11/newsrelease221111.html)] Delivered as the **ふみのは** service line (transcription service + assisted-reading platform ふみのはゼミ), 法人向け, priced per material type. [V] Real deployment: Kumamoto Univ. Hosokawa-clan archive — ~50,000 pages → ~9.5M characters in about a month, ~70% accuracy, judged worthwhile at that volume. [V — Nikkei xTECH]
- **Academic kindai HTR** (Le, Ly, Nguyen, Kitamoto et al., NII/CODH/UTokyo): attention-based encoder-decoders on kindai documents; the 2025 paper [arXiv 2508.08537](https://arxiv.org/abs/2508.08537) attacks exactly the problem this project has — **scarce labeled kindai training data** — by pairing real textline images with the *same text rendered in modern fonts* and adding a self-attention feature-distance loss (Euclidean/MMD), improving CER by 2.2–3.9 points. [V] This is the closest published precedent for the textbook/synthetic bootstrapping idea.

### 2.4 Trainable frameworks
- **Kraken/eScriptorium**: full train-your-own stack (segmentation + recognition), handles vertical scripts, mature transcription UI. No public Japanese vertical-handwriting model found. [V] Practical friction [I]: Linux-first tooling (WSL2 on this box), CTC models with 3,000+ character classes need more data per class than Latin HTR, and CPU-only training of a from-scratch Japanese model is unrealistic; fine-tuning smaller nets or renting a GPU-hour is the realistic mode.
- **TrOCR**: official handwriting models are English (IAM). No established Japanese handwriting fine-tune surfaced on HuggingFace. [V — absence of evidence] Using it for Japanese means swapping in a Japanese tokenizer/decoder — which is essentially what **manga-ocr** already did (ViT encoder + char-level Japanese BERT decoder), trained on Manga109 plus an **open synthetic pipeline that renders arbitrary text — vertical, furigana, varied fonts — via an HTML engine**. [V] manga-ocr is therefore both a precedent and a plausible fine-tune base. [I]
- **PaddleOCR PP-OCRv5**: vendor reports significant handwriting and Japanese detection gains; Apache 2.0; cheap to benchmark. Vertical historical Japanese performance unpublished. [V/I]
- **ETL character database (AIST)**: ~1.2M handwritten character images (ETL8: 881 education kanji + kana from 1,600 writers; ETL9: 2,965 JIS-1 kanji + kana from 4,000 writers), collected 1973–84, free download after registration. [V — [etlcdb](https://etlcdb.db.aist.go.jp/the-etl-character-database/)] [I]: many ETL writers were educated pre-war; their hands are stylistically closer to Shōwa field writing than any modern dataset — valuable as isolated-character pretraining/augmentation, though it is isolated characters, not lines.

### 2.5 Cloud APIs
- **Azure AI Vision Read**: Japanese is one of only 9 languages with handwritten-text support. [V — MS docs] Accuracy on vertical historical text: unpublished. [V — absence]
- **Google Cloud Vision** DOCUMENT_TEXT_DETECTION: recognizes Japanese handwriting to a degree; practitioner reports show accuracy drops on cursive and **known failures on mixed vertical/horizontal layouts** — which describes 陣中日誌 form pages exactly. [V practitioner-level / I applicability]
- Both are near-zero-effort to benchmark (public-domain material, so no privacy blocker) and should be scored on the project's gold set before assuming anything. [I]

### 2.6 Vision-LLM state of the art
- [arXiv 2511.15059](https://arxiv.org/abs/2511.15059) (Nov 2025): MLLMs measurably **perform worse on vertically written Japanese than horizontal**, and targeted synthetic vertical training fixes much of it; evaluation is printed-text only. [V] This is direct published support for the project's premise (vertical is a first-class problem), and implies the handwriting+vertical combination is even further out of distribution. [I]
- **No rigorous published benchmark of GPT-4o/Claude/Gemini on Shōwa-era Japanese handwriting was found.** [V — absence] Informal Japanese-language comparisons (e.g. [note.com three-way test](https://note.com/donkorokoroko/n/n4910c49c2284), [Tact System tests](https://web.tactsystem.co.jp/2024/08/1538/)) consistently describe GPT-4o-class models as strong on modern handwritten memos precisely because they "infer and guess" from context. [V informal]
- **[I] Error-mode contrast that matters for an archival project:** dedicated HTR fails *visibly* (garbage characters, low-confidence output you can flag); vision-LLMs fail *fluently* — plausible-looking hallucinated readings, silent kyūjitai→shinjitai normalization, skipped or merged columns. For human-primary transcription, LLM output is a good draft generator but a dangerous sole authority; a dedicated HTR second engine whose *disagreements* drive uncertainty marking is the highest-value addition, independent of which engine is "more accurate."

---

## 3. Textbook-bootstrapping feasibility (period 教科書/習字帖/軍隊文範 as training data)

### Corpus availability — verified
- NDL Search returns **軍隊文範 (1901) and 軍隊文範：兵卒須知 (1907, [dl.ndl.go.jp/pid/864612](https://dl.ndl.go.jp/pid/864612))**, plus modern reprint collections of military correspondence manuals (近代日本軍隊教育・生活マニュアル資料集成; 軍隊に関する手紙の書き方・挨拶の仕方). [V — NDL Search API]
- **~1,939 hits for 習字帖** in NDL Search, overwhelmingly Meiji–Shōwa penmanship copybooks (e.g. prefectural 小学習字帖 series). [V] Pre-1946 items are largely インターネット公開 (public domain) and harvestable via NDL's IIIF image API. [V for the access framework / I for per-item status]

### Precedent — partial, and encouraging
1. **Font-rendered parallel textlines for kindai OCR** (Le & Kitamoto 2025): same-text pairs of real and font-rendered lines + feature-distance loss → 2.2–3.9 CER points gained on scarce kindai data. [V] The textbook idea is a strict *upgrade* of this: copybook exemplars are a *mid-domain* between clean fonts and messy field hands.
2. **manga-ocr's synthetic generator** (render arbitrary text vertically in many fonts, incl. brush-style fonts) is a working open implementation of the rendering half. [V]
3. **NVIDIA Nemotron-OCR-style synthetic multilingual pipelines** show synthetic-first training is now standard practice. [V — [HF blog](https://huggingface.co/blog/nvidia/nemotron-ocr-v2)]
4. No published case of specifically "copybook/penmanship-book pretraining" for HTR was found. [V — absence; the idea appears novel in its specific form.]

### The catch — domain gap [I]
- Copybook hands are **idealized 楷書/行書 model calligraphy**; field diaries are hurried, abbreviated, personal 行書/草書 with corrections, stamps, pencil fading, and ruled 罫紙. Character-shape transfer will be real but partial — expect copybooks to teach *canonical kyūjitai glyph inventory and period vocabulary*, not the deformation patterns of tired adjutants.
- Ground truth is *cheap but not free*: many 習字帖/文範 print the model text in type alongside the calligraphy (文範 = model sentences with readings), so image–text pairing is often extractable with the existing NDL typeset OCR — a genuine cost advantage. [I, based on the genre's standard format; verify per title]
- **The decisive training signal will still be real transcribed JACAR lines.** The project's human-primary workflow already produces exactly this; the single most valuable process change is to *save every verified transcription as line-aligned ground truth* (image crop + text), because 500–2,000 verified lines is the typical range where fine-tuning a PARSeq/TrOCR-class model starts to pay off. [I, consistent with HTR fine-tuning literature and the Kindai OCR papers' data scales]

### Verdict
**Feasible and worth doing, as the middle layer of a three-layer data strategy — not as a standalone fix.** Copybooks alone will not make a model read 草書 field notes; combined with font-synthetic data below them and real transcribed lines above them, they should measurably close the domain gap, and they additionally yield a period-correct language model / vocabulary list (military formulae, 候文 closings, unit terminology) that benefits *both* HTR decoding and vision-LLM prompting immediately.

### Concrete pipeline sketch
1. **Harvest**: pull 習字帖/文範/軍隊教育 titles from NDL Digital Collections via IIIF (public domain); also ETL8/9 from AIST (registration).
2. **Pair**: where the model text is printed beside the calligraphy, OCR the typeset side with the existing NDL pipeline → (calligraphy-line image, text) pairs. Manual spot-check ~5%.
3. **Synthesize**: render the same period text corpus (kyūjitai, vertical, katakana okurigana) with the manga-ocr generator using standard + brush/pen-style fonts (e.g. 青柳衡山 family) with degradation augmentation (blur, bleed-through, 罫紙 lines, stamps).
4. **Pretrain/fine-tune**: start from NDLOCR-Lite's PARSeq recognizer using its published `train/` recipe (or manga-ocr's ViT-BERT); curriculum: font-synthetic → copybook → real lines.
5. **Gold data flywheel**: every human-verified JACAR transcription is saved as line-aligned ground truth; refine the model each few hundred lines.
6. **Deploy as ensemble**: fine-tuned local model (ONNX, CPU) + vision-LLM; character-level disagreement → automatic uncertainty marks in the human-primary workflow. Layout (column detection on 罫紙) reused from NDLOCR-Lite's DEIMv2.
- Hardware [I]: inference all-CPU on the Windows 11 box (ONNX). Fine-tuning PARSeq-scale models is *possible* on CPU but slow; one-off rented GPU hours (Colab/paid) are the pragmatic route; nothing requires local GPU.

---

## 4. Ranked recommendation

**Quick win (days, no model training):**
1. Download the **NDLOCR-Lite v1.2 Windows binary** (no Python required) and run it over a 20–30 page gold set of already-transcribed JACAR pages; score CER. It is the only free, local, CPU, CC BY 4.0 engine with any modern-handwriting capability.
2. Benchmark **Azure Read and Google Cloud Vision** on the same gold set (material is public domain; cost trivial).
3. Start **saving line-aligned ground truth** from every human-verified transcription — this costs nothing now and gates everything later.
4. Immediately exploit copybooks the cheap way: extract a **period vocabulary/formulae list** from 軍隊文範-type texts and inject it into the vision-LLM prompt; add copybook glyph exemplars for troublesome kyūjitai as few-shot images.

**Medium (weeks):** install Python; fine-tune NDLOCR-Lite's PARSeq on font-synthetic + copybook + accumulated real lines (pipeline in §3); deploy as CPU ONNX second engine; wire LLM-vs-HTR disagreement into the uncertainty-marking convention.

**Long-term (months / at scale):** if a bulk series (thousands of pages) must be done, get a quote from **TOPPAN ふみのは** — the only engine purpose-built for Meiji–Shōwa handwriting, with a proven 50k-page deployment at ~70% accuracy — and/or graduate to a full eScriptorium/kraken custom-model workflow and publish the resulting dataset+model (there is currently no open Shōwa-handwriting model; this project could own that niche).

**What to skip:** miwo/KuroNet/Kaggle kuzushiji models (wrong era, confirmed by CODH's own caveats); TrOCR-from-scratch (manga-ocr already solved the Japanese-decoder problem); waiting for a published vision-LLM Shōwa-handwriting benchmark (none exists — build the project's own gold-set scoreboard instead).
