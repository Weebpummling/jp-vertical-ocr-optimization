"""Kanpō miner, stage 0: survey 叙任及辞令-section coverage in IIIF manifest TOCs.

Spike A found that per-issue IIIF manifests carry article-level TOCs in `structures`,
including the personnel-orders section (old kanji 敍任及辭令). Phase 4's retrieval
plan depends on that TOC being present reliably. This script measures it: for sample
months, resolve each issue's PID via NDL Search, fetch its manifest, and record
whether a personnel-orders range exists and where it points.

Usage:
    python survey_sections.py 1922-04 1925-04 1930-04 1935-04

Output: kanpo/survey_results.json + console table. Polite: ~0.5 s between requests.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

UA = {"User-Agent": "jp-vertical-ocr-optimization (research; polite serial retrieval)"}
SECTION_RE = re.compile(r"[叙敍]任及[辞辭]令")
DELAY = 0.5


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


LABEL_DATE_RE = re.compile(r"(\d{4})年(\d{2})月(\d{2})日")


def first_pid_of_month(yyyy_mm: str) -> str:
    """Resolve the month's first issue PID via NDL Search (narrow date window)."""
    y, m = yyyy_mm.split("-")
    title = urllib.parse.quote("官報")
    url = (f"https://ndlsearch.ndl.go.jp/api/opensearch?title={title}"
           f"&from={y}-{m}-01&until={y}-{m}-05&cnt=50")
    root = ElementTree.fromstring(fetch(url))
    best = None
    for item in root.iter("item"):
        ids = [e.text for e in item if e.tag.endswith("identifier") and e.text]
        pid = next((i.rsplit("/", 1)[1] for i in ids if "ndljp/pid" in i), None)
        date = next((e.text for e in item if e.tag.endswith("date")
                     and e.text and e.text.startswith(f"{y}-{m}")), None)
        if pid and date and (best is None or date < best[0]):
            best = (date, pid)
    if not best:
        raise RuntimeError(f"no PID found for {yyyy_mm}")
    return best[1]


def issues_for_month(yyyy_mm: str, max_walk: int = 40):
    """PIDs are sequential by issue: walk forward from the month's first issue,
    reading each manifest's own date label, until the month ends. Returns
    {date: (pid, manifest_json)} so the caller reuses the fetched manifests."""
    y, m = yyyy_mm.split("-")
    pid = int(first_pid_of_month(yyyy_mm))
    time.sleep(DELAY)
    out = {}
    for _ in range(max_walk):
        try:
            man = json.loads(fetch(f"https://dl.ndl.go.jp/api/iiif/{pid}/manifest.json"))
        except Exception:                              # noqa: BLE001 — gap in sequence
            pid += 1
            time.sleep(DELAY)
            continue
        label = str(man.get("label", ""))
        mt = LABEL_DATE_RE.search(label)
        if mt:
            date = f"{mt.group(1)}-{mt.group(2)}-{mt.group(3)}"
            if (mt.group(1), mt.group(2)) > (y, m):
                break
            if (mt.group(1), mt.group(2)) == (y, m):
                # 号外 (extra editions) share the date with the regular issue and
                # often carry the personnel orders — never collapse them.
                gogai = "号外" in label or "號外" in label
                out[f"{date}#{pid}"] = (str(pid), man, gogai)
        pid += 1
        time.sleep(DELAY)
    return dict(sorted(out.items()))


def section_in_manifest(man: dict):
    n_canvases = len(man["sequences"][0]["canvases"])
    hits = []
    for s in man.get("structures", []):
        label = s.get("label") or ""
        if SECTION_RE.search(str(label)):
            canvases = s.get("canvases") or []
            frame = canvases[0].rsplit("/", 1)[1] if canvases else None
            hits.append({"label": str(label)[:60], "first_canvas": frame})
    return {"n_canvases": n_canvases,
            "has_structures": bool(man.get("structures")),
            "section_hits": hits}


def main(months):
    results = {}
    for month in months:
        issues = issues_for_month(month)
        month_rows = []
        for key, (pid, man, gogai) in issues.items():
            try:
                info = section_in_manifest(man)
            except Exception as e:                     # noqa: BLE001 — survey must finish
                info = {"error": str(e)[:80]}
            month_rows.append({"date": key.split("#")[0], "pid": pid,
                               "gogai": gogai, **info})
        n = len(month_rows)
        n_gogai = sum(1 for r in month_rows if r.get("gogai"))
        with_struct = sum(1 for r in month_rows if r.get("has_structures"))
        with_section = sum(1 for r in month_rows if r.get("section_hits"))
        sect_in_gogai = sum(1 for r in month_rows if r.get("section_hits") and r.get("gogai"))
        results[month] = {
            "issues": n, "gogai": n_gogai,
            "with_structures": with_struct,
            "with_section": with_section,
            "section_in_gogai": sect_in_gogai,
            "rows": month_rows,
        }
        print(f"{month}: {n} issues ({n_gogai} gogai) | structures {with_struct}/{n} "
              f"| section {with_section}/{n} (of which in gogai: {sect_in_gogai})")

    out = Path(__file__).parent / "survey_results.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1:] or ["1925-04"])
