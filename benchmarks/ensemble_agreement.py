"""Cross-engine agreement scoring for the handwritten ensemble benchmark.

Compares an NDLOCR-Lite JSON output against a vision-LLM transcription of the
same document (the ``=== Image N ... ===`` block format used by the JACAR
workflow, docs/jacar-handwritten-workflow.md).

Agreement is not accuracy: both engines can err together. See
benchmarks/handwritten-ensemble-2026-07.md for interpretation.

Usage:
    python ensemble_agreement.py <ndlocr.json> <transcription.txt>

Engine outputs live in the private data home, never in this repository.
"""

import difflib
import json
import re
import sys

# Vision-transcription uncertainty marks (kept out of matching):
# 〓 = geta mark for unreadable chars; 〔?〕 = low-confidence mark.
GETA = "〓"
LOWCONF = "〔?〕"

# Characters that count as text for matching: CJK, kana, ASCII alnum.
TEXT_CHARS = re.compile(r"[^　-鿿゠-ヿA-Za-z0-9]")
IMAGE_HEADER = re.compile(r"^=== Image (\d+)", re.M)
BOILERPLATE = re.compile(r"^(0\d{3}|.*jacar\.go\.jp.*|Japan Center.*)$")


def strip_marks(text):
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text, flags=re.S)
    text = text.replace(LOWCONF, "").replace(GETA, "")
    return TEXT_CHARS.sub("", text)


def vision_pages(path):
    """Split the transcription into per-image cleaned text."""
    body = open(path, encoding="utf-8").read()
    pages = {}
    for block in re.split(r"(?=^=== Image \d+)", body, flags=re.M):
        m = IMAGE_HEADER.match(block)
        if m:
            text = re.sub(r"^===.*$", "", block, flags=re.M)
            pages[int(m.group(1))] = strip_marks(text)
    return pages


def line_coverage(line, page_text):
    """Fraction of the line's characters found in order in the page text."""
    sm = difflib.SequenceMatcher(None, line, page_text, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / max(1, len(line))


def main(ndlocr_json, transcription_txt):
    ocr = json.load(open(ndlocr_json, encoding="utf-8"))
    vision = vision_pages(transcription_txt)

    buckets = {}
    page_scores = {}
    for page_no, page in enumerate(ocr["contents"], 1):
        vt = vision.get(page_no, "")
        ocr_text = []
        for line in page:
            if line.get("isTextline") != "true":
                continue
            txt = re.sub(r"\s", "", line["text"])
            if BOILERPLATE.match(txt):
                continue
            ocr_text.append(txt)
            if len(txt) < 6:
                continue
            c = line["confidence"]
            key = ("0.9+" if c >= 0.9 else "0.8-0.9" if c >= 0.8
                   else "0.7-0.8" if c >= 0.7 else "0.5-0.7" if c >= 0.5
                   else "<0.5")
            buckets.setdefault(key, []).append(line_coverage(txt, vt))
        page_scores[page_no] = difflib.SequenceMatcher(
            None, strip_marks("".join(ocr_text)), vt, autojunk=False
        ).ratio()

    print("Corroboration by Engine-A confidence (lines >= 6 chars):")
    for key in ["0.9+", "0.8-0.9", "0.7-0.8", "0.5-0.7", "<0.5"]:
        vals = buckets.get(key, [])
        if vals:
            print(f"  {key:8} {len(vals):4d} lines  mean {sum(vals) / len(vals):.2f}")

    print("\nPer-page agreement:")
    for n in sorted(page_scores):
        print(f"  Image {n:2d}: {page_scores[n]:.2f}")
    mean = sum(page_scores.values()) / len(page_scores)
    low = [n for n, s in sorted(page_scores.items()) if s < 0.25]
    print(f"\nMean: {mean:.2f}   Review-priority pages (< 0.25): {low}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
