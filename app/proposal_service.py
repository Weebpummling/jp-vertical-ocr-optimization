"""Layer 4, first engine - machine proposals for every officer on a scan.

Joins three things that already exist: `page_service`'s spread geometry (where
every field of every officer sits, numbered in reading order), NDL's own OCR for
the volume (`reading/ndl_lines.py`), and the top-down binning that puts one into
the other (`reading/binning.py`). No OCR runs here and nothing is decided here.

Output is keyed by the officer's spread-wide `index`, which is the value
`roster_cell.row_index` stores - so a proposal, a recorded observation and a
row of the exported worksheet all name the same officer the same way.

**What a proposal may do at the workstation.** Standing commitment 2: humans
decide. A proposal is offered, never pre-filled, and taking it is a keystroke.
Each proposal carries `fill` - the text a form field receives if the reader
takes it - chosen so the server's rules still do the deciding:

* a date fills as *printed* (明四四、一二、二六), because `eradate` is the one
  place allowed to say what that means;
* a ditto fills as 同, never as the value the machine inherited, so the server
  resolves it against what a *person* recorded on the row above. A machine
  chain-head the OCR could not read therefore costs one human keystroke, after
  which every 同 below it resolves from the human reading;
* a refused reading fills as the raw OCR text, so a reader correcting one bad
  character does not retype the other eight - but it is never taken by
  "accept all".
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("app", "reading", "ingestion"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import binning  # noqa: E402
import ditto  # noqa: E402
import ndl_lines  # noqa: E402
import page_service as ps  # noqa: E402

FULLTEXT_URL = "https://lab.ndl.go.jp/dl/api/book/fulltext-json/{pid}"
USER_AGENT = "jp-vertical-ocr-optimization (research ingestion; polite, cached)"

DITTO = "同"

# Template field -> the workstation form field it can fill. Fields absent here
# have no observation column yet; they are shown to the reader as context.
FORM_FIELDS = {
    "seniority_no": "seniority_no",
    "name_raw": "name_raw",
    "post": "post",
    "commissioning_date": "commissioning_date",
}

# Methods a reader may take wholesale with "accept all". A refusal is not one of
# them however plausible its raw text looks: blank beats plausible.
CONFIDENT = ("ndl-ocr", "digits", "eradate", "inherited")

# Words of the roster's own column legend (次列, 氏名, 出身期別 ...). A column
# carrying two of them is the legend printed where a section begins.
LEGEND_WORDS = ("次列", "氏名", "期別", "出身", "命課", "現任官", "前官", "初任", "位勳功")
# Bands a section label is printed across - never the post, which an officer has.
LABEL_BANDS = ("service_in_rank", "rank_date", "prev_rank_date", "commissioning_date")

# A parsed volume is ~35 MB of JSON. Keep the two most recent in memory - the
# volume being worked and the one it was compared against - and no more.
_MAX_DOCS = 2
_docs: dict[str, dict] = {}
_lock = threading.Lock()


class ProposalsUnavailable(Exception):
    """No machine reading can be offered for this page, and why."""


def data_home() -> Path:
    home = os.environ.get("JP_OCR_DATA")
    if not home:
        raise ProposalsUnavailable("JP_OCR_DATA is not set")
    return Path(home)


def fulltext_path(pid: str) -> Path:
    return data_home() / "cache" / pid / "ndl_fulltext_raw.json"


def _fetch_fulltext(pid: str, dest: Path) -> None:
    """One fetch per volume, ever - the result is cached beside the page images.

    A 403 is NDL's rights gate (`This PID is not allowed`): the item is not
    internet-public, and signing in does not change that. It is reported as such
    rather than as a network failure, because nothing retrying will fix it.
    """
    req = urllib.request.Request(FULLTEXT_URL.format(pid=pid),
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise ProposalsUnavailable(
                f"NDL does not serve OCR text for {pid}: the item is not "
                f"internet-public") from exc
        raise ProposalsUnavailable(f"NDL fulltext fetch failed: HTTP {exc.code}") from exc
    except OSError as exc:
        raise ProposalsUnavailable(f"NDL fulltext fetch failed: {exc}") from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)


def fulltext(pid: str, *, fetch: bool = True) -> dict:
    """The volume's NDL OCR document, cached on disk and (briefly) in memory."""
    with _lock:
        if pid in _docs:
            _docs[pid] = _docs.pop(pid)          # most recently used last
            return _docs[pid]
        path = fulltext_path(pid)
        if not path.exists():
            if not fetch:
                raise ProposalsUnavailable(
                    f"NDL's OCR for {pid} is not cached ({path})")
            _fetch_fulltext(pid, path)
        with io.open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        _docs[pid] = doc
        while len(_docs) > _MAX_DOCS:
            _docs.pop(next(iter(_docs)))
        return doc


def _is_ditto_mark(raw: str) -> bool:
    return ditto.is_ditto((raw or "").strip().strip("、。 "))


def fill_for(proposal: binning.Proposal) -> str | None:
    """The text a form field receives if the reader takes this proposal."""
    raw = (proposal.raw or "").strip()
    if proposal.method == "inherited" or (raw and _is_ditto_mark(raw)):
        return DITTO
    if proposal.method == "eradate":
        return raw
    if proposal.method in ("ndl-ocr", "digits"):
        return proposal.value
    if proposal.method == "refused":
        return raw or None
    return None


def takes_wholesale(proposal: binning.Proposal) -> bool:
    """Whether "accept all" may take this one. A printed ditto mark always may:
    what it means is settled server-side against the human reading above."""
    return proposal.method in CONFIDENT or _is_ditto_mark(proposal.raw)


def column_kind(fields: dict[str, dict], vocab: dict) -> dict:
    """What a column of the grid appears to hold - a proposal, never a decision.

    Registration places every column the rulings define, and not every column is
    an officer. On pid 1449426 frames 95-108 the last column of the left leaf is
    the section label (步兵中佐 and a count); a section starting mid-spread opens
    with a column of headings (次列, 氏名, 出身期別, frame 105); a section's end
    leaves unused slots (frame 104). Counted as officers, they kept every such page
    from ever reading complete.

    Narrow on purpose. Only a column whose seniority cell has no digits is
    considered - an officer always has a seniority number - and a section label
    must be read in the date bands with nothing in the post, so an officer whose
    number simply did not read is not taken for a heading. A reader confirms by
    marking the row (roster_cell.audit_status = 'extra_row'), or ignores it.
    """
    texts = {name: "".join((e.get("raw") or "").split()) for name, e in fields.items()}
    if any(ch.isdigit() for ch in texts.get("seniority_no", "")):
        return {"kind": "officer"}
    joined = "".join(texts.values())
    if not joined:
        return {"kind": "blank", "evidence": "nothing read in any band"}
    legend = [w for w in LEGEND_WORDS if w in joined]
    if len(legend) >= 2:
        return {"kind": "legend", "evidence": "column headings read: " + "、".join(legend)}
    if not texts.get("post"):
        in_bands = "".join(texts.get(b, "") for b in LABEL_BANDS).replace("、", "")
        labels = []
        for group in ("branches", "ranks"):
            for entry in vocab.get(group, []):
                for label in [entry.get("ja")] + list(entry.get("variants") or []):
                    if label and label in in_bands and label not in labels:
                        labels.append(label)
        if labels:
            return {"kind": "section_label",
                    "evidence": "section label read: " + "、".join(labels)}
    return {"kind": "officer"}


def birth_as_read(cell) -> str:
    """Everything read beside a name, top to bottom: the birth date set aside by
    what it says, and any other small-type column left in the cell. Both, because
    NDL boxes some dates in pieces a rule cannot all recognise (ニ for 二), and
    showing only one of the two dropped the other half of the date."""
    if not cell.runs and not cell.aside:
        return ""
    main = max(cell.runs, key=lambda r: r.thickness) if cell.runs else None
    lines = list(cell.aside) + [l for r in cell.runs if r is not main for l in r.lines]
    return "".join(l.text for l in sorted(lines, key=lambda l: l.ymin))


def propose_registered(page: ps.RegisteredPage,
                       lines: list[ndl_lines.BoxedLine],
                       vocab: dict | None = None) -> dict:
    """Proposals for an already-registered scan. Pure: no disk, no network."""
    vocab = vocab if vocab is not None else ps.vocabularies()
    spec = [(o.index, c.field, tuple(c.bbox), c.suspect)
            for o in page.officers for c in o.cells]
    fields = [c.field for c in page.officers[0].cells] if page.officers else []
    cells, outside = binning.bin_page(lines, spec)
    proposed = binning.propose(cells, len(page.officers), fields)

    officers = []
    for officer, prop in zip(page.officers, proposed):
        name_cell = cells.get((officer.index, "name_raw"))
        entries = {}
        for name in fields:
            p = prop.fields.get(name)
            if p is None:
                continue
            entries[name] = {
                "value": p.value,
                "raw": p.raw,
                "method": p.method,
                "note": p.note,
                "suspect": p.suspect,
                "fill": fill_for(p),
                "form_key": FORM_FIELDS.get(name),
                "wholesale": takes_wholesale(p),
            }
        officers.append({
            "index": officer.index,
            "panel": officer.panel,
            "column": officer.column,
            "birth_raw": birth_as_read(name_cell) if name_cell else "",
            # 本籍・族籍 printed above the name (1935 edition), set aside from it.
            "origin_raw": "".join(l.text for l in sorted(name_cell.origin, key=lambda l: l.ymin))
            if name_cell else "",
            "column_kind": column_kind(entries, vocab),
            "fields": entries,
        })
    return {"officers": officers, "lines_outside": [l.text for l in outside]}


def propose_page(pid: str, frame: int, *, page: ps.RegisteredPage | None = None,
                 image_path: str | Path | None = None,
                 fetch_fulltext: bool = True) -> dict:
    """Proposals for one scan, registering it first if not already registered."""
    if page is None:
        if image_path is None:
            import iiif_client
            image_path = iiif_client.fetch_page(pid, frame)
        page = ps.register_file(image_path, pid, frame)

    doc = fulltext(pid, fetch=fetch_fulltext)
    note = None
    try:
        lines = ndl_lines.frame(doc, frame)
    except ndl_lines.NoCoordinateData:
        lines, note = [], "NDL's OCR has no text for this frame"
    except IndexError:
        lines, note = [], "this frame is outside NDL's OCR for the volume"

    result = propose_registered(page, lines)
    result.update({
        "pid": pid,
        "frame": frame,
        "engine": "ndl-fulltext",
        "available": True,
        "ocr_note": note,
        "officer_count": len(page.officers),
        "panels_missing": list(page.panels_missing),
    })
    return result
