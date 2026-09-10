"""Zoomed re-reading: NDLOCR-Lite on each cell, compared with NDL's reading.

NDL's volume OCR (`proposal_service.py`) read each page once, as a whole page, in
2021. This reads every cell again on its own - the page image cropped to the
registered cell - with NDLOCR-Lite, NDL's current engine running on this
machine, and compares the two cell by cell:

    agrees       both readings mean the same thing - corroboration
    alternative  they differ, and the re-reading is settled enough to offer; the
                 reader takes one or the other, or types their own
    unreadable   the re-reading could not be interpreted; nothing is offered

A person's reading is always the last word. Nothing here writes to the record,
and the workstation's "take all" never takes an alternative.

**Crops, chosen on evidence** (pid 1449426 frame 100, five officers, three crop
recipes each, 9 Sep 2026):

* Most fields - the registered cell exactly, on a white border. Padding outward
  pulled in neighbouring print (a name came back as "( ) 正 位 四 經");
  insetting lost strokes (步兵 → 歩兵 → ル兵). At the exact cell, seniority,
  names, cohort and posts all read cleanly.
* Dates and elapsed service - each of NDL's own line boxes inside the cell,
  cropped separately and reassembled. Whole date cells read as garbage at every
  inset (****, 10.11, 198, 000…) at 0.95-0.99 confidence. Segments read
  明四三 / 一二、二六, including one that NDL itself had wrong (「二、二六).

**Two guards from the same sample.** Confidence decides nothing, because the
garbage came back at 0.98. And a reading in a date column that contains Arabic
digits or Latin letters is treated as unreadable: these rosters print dates in
kanji numerals, and every such reading in the sample was wrong.

**Measured on a whole page** (frame 100, 21 officers, three crop variants,
9 Sep 2026). Erasing the table rulings from crops was tried and dropped: it
fixed a ruling read as 一 on one name and cost far more - seniority agreement
fell from 20 of 20 to 19 and 13, cohort from 16 to 9 and 13. And NDLOCR-Lite
writes modern forms where the page prints kyūjitai (歩 for 步, 郎 for 郞, 瀬 for
瀨), which made most posts look like disagreements; readings that differ only by
a pair in the frozen kanji variant table therefore agree, and NDL's reading,
which keeps the printed form, stays the proposal.

Every re-reading is interpreted by exactly the rules NDL's text is -
`binning.propose_cell`: date reassembly, `eradate`, ditto marks, digit checks,
furigana - so the two engines' proposals are directly comparable.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import functools
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("app", "reading", "ingestion"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import cv2  # noqa: E402

import binning  # noqa: E402
import ndl_lines  # noqa: E402
import page_service as ps  # noqa: E402
import proposal_service as props  # noqa: E402
import volume_service as vs  # noqa: E402
from ndl_lines import BoxedLine  # noqa: E402

RECIPE = "cell-exact/border60; dates+service: ndl-line-segments/margin6 (2026-09-10)"
# A space between characters of a zoomed name reading: NDLOCR-Lite's mark of
# characters it detected nothing for. Every such name on frames 100-101 was wrong
# (土 屋 民 for 土屋靖民, 靑 山 治 for 靑山三治, 長島 長 前 for 長島勤).
NAME_GAP = re.compile(r"\S\s+\S")
BORDER = 60
SEGMENT_MARGIN = 6
# appointment_dates is the Taishō cell that holds every appointment date at once.
SEGMENT_FIELDS = ("commissioning_date", "rank_date", "prev_rank_date", "service_in_rank",
                  "appointment_dates")
# The officer in hand is read field by field, the fields that re-read reliably
# first, so the useful alternatives arrive before the dates do.
FIELD_ORDER = ("seniority_no", "name_raw", "post", "cohort", "court_rank_decorations",
               "commissioning_date", "rank_date", "prev_rank_date", "appointment_dates",
               "service_in_rank")
NOT_KANJI_NUMERALS = re.compile(r"[0-9A-Za-z*＊０-９Ａ-Ｚａ-ｚ]")
WORKER_SCRIPT = Path(__file__).with_name("ndlocr_worker.py")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EngineUnavailable(RuntimeError):
    """NDLOCR-Lite cannot be driven from here; the message says why."""


class WorkerError(RuntimeError):
    """NDLOCR-Lite was reachable but did not produce a reading."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Engine:
    home: Path
    python: Path
    src: Path


def engine_home() -> Path:
    configured = os.environ.get("NDLOCR_LITE_HOME")
    if configured:
        return Path(configured)
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home()) / "ndlocr-lite"


def find_engine(home: str | Path | None = None) -> tuple[Engine | None, str | None]:
    """A runnable NDLOCR-Lite install, or the reason there is none.

    Needs both its command-line source and its own interpreter. The two ways
    this went wrong before (NDL Workbench 1.2.1): NDL's desktop release is a GUI
    with no command line at all, and a bare `python` on Windows is the Microsoft
    Store alias, which prints an advert and runs nothing.
    """
    home = Path(home) if home else engine_home()
    src = home / "cli" / "src"
    if not (src / "ocr.py").exists():
        return None, (f"NDLOCR-Lite's command-line source is not at {src}. NDL's "
                      f"desktop build is a GUI and cannot be driven; install the git "
                      f"release with its own venv (NDL Workbench's Install NDLOCR-Lite "
                      f"does this), or set NDLOCR_LITE_HOME.")
    for python in (home / "venv" / "Scripts" / "python.exe", home / "venv" / "bin" / "python"):
        if python.exists() and "WindowsApps" not in python.parts:
            return Engine(home=home, python=python, src=src), None
    return None, (f"NDLOCR-Lite has no interpreter of its own at {home / 'venv'}. A bare "
                  f"python is never substituted: on Windows that is the Microsoft Store "
                  f"alias, which runs nothing.")


def engine_version(engine: Engine) -> str | None:
    """The release actually checked out.

    NDLOCR-Lite's own __version__ reads 0.0.0.dev0 in a git checkout - only the
    release binaries are stamped - and readings from different releases are not
    comparable, so the tag is what the cache keys on.
    """
    git = shutil.which("git")
    cli = engine.home / "cli"
    if not git or not (cli / ".git").exists():
        return None
    try:
        out = subprocess.run([git, "-C", str(cli), "describe", "--tags", "--always"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


class Worker:
    """NDLOCR-Lite kept running, so its models load once rather than per cell.

    Loading is about seven seconds and a cell about half a second; a page is some
    two hundred crops. One request at a time: onnxruntime already uses every core
    for each read.
    """

    def __init__(self, engine: Engine, *, script: Path = WORKER_SCRIPT,
                 start_timeout: float = 240.0, read_timeout: float = 120.0,
                 log_path: Path | None = None):
        self.engine = engine
        self.script = Path(script)
        self.start_timeout = start_timeout
        self.read_timeout = read_timeout
        self.log_path = log_path
        self.version: str | None = None
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._lock = threading.RLock()
        self._next_id = 0
        self._log = None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure(self) -> None:
        with self._lock:
            if not self.alive():
                self._spawn()

    def _spawn(self) -> None:
        self.close()
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = open(self.log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [str(self.engine.python), "-u", str(self.script)],
            cwd=str(self.engine.src), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._log if self._log is not None else subprocess.DEVNULL,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=CREATE_NO_WINDOW)
        self._proc = proc
        lines: queue.Queue = queue.Queue()
        self._lines = lines

        def pump():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, name="ndlocr-lite-stdout", daemon=True).start()
        hello = self._receive(self.start_timeout, starting=True)
        if not hello.get("ready"):
            self.close()
            raise WorkerError("NDLOCR-Lite did not start: "
                              + str(hello.get("error") or hello))
        self.version = engine_version(self.engine) or hello.get("version")

    def _receive(self, timeout: float, *, starting: bool = False) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise WorkerError(f"NDLOCR-Lite gave no answer in {timeout:.0f} s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                self.close()
                raise WorkerError("NDLOCR-Lite stopped "
                                  + ("while loading its models" if starting else "mid-read")
                                  + " - see the worker log")
            try:
                return json.loads(line)
            except ValueError:
                continue            # the engine's own chatter, not a reply

    def read(self, image: str | Path) -> dict:
        with self._lock:
            if not self.alive():
                self._spawn()
            self._next_id += 1
            request_id = self._next_id
            try:
                self._proc.stdin.write(json.dumps({"id": request_id, "image": str(image)}) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.close()
                raise WorkerError(f"NDLOCR-Lite is not accepting work: {exc}") from exc
            while True:
                reply = self._receive(self.read_timeout)
                if reply.get("id") == request_id:
                    break
            if not reply.get("ok"):
                raise WorkerError(reply.get("error") or "NDLOCR-Lite could not read this crop")
            return reply

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None


_worker: Worker | None = None
_worker_lock = threading.Lock()


def _log_path() -> Path | None:
    home = os.environ.get("JP_OCR_DATA")
    return Path(home) / "cache" / "ndlocr-lite-worker.log" if home else None


def shared_worker() -> Worker:
    global _worker
    with _worker_lock:
        if _worker is None:
            engine, reason = find_engine()
            if engine is None:
                raise EngineUnavailable(reason)
            _worker = Worker(engine, log_path=_log_path())
        return _worker


def engine_status() -> dict:
    engine, reason = find_engine()
    return {
        "available": engine is not None,
        "reason": reason,
        "home": str(engine.home if engine else engine_home()),
        "running": bool(_worker and _worker.alive()),
        "version": _worker.version if _worker else None,
        "recipe": RECIPE,
    }


# --------------------------------------------------------------------------
# crops, interpretation, comparison
# --------------------------------------------------------------------------

def crop_image(image, box, margin: int = 0):
    """A greyscale crop of the page on a white border, and its origin in the scan.

    Left exactly as printed, rulings and all: erasing them was measured and made
    the digits worse (see the module docstring).
    """
    x, y, w, h = box
    height, width = image.shape[:2]
    x0 = max(int(x) - margin, 0)
    y0 = max(int(y) - margin, 0)
    x1 = min(int(x + w) + margin, width)
    y1 = min(int(y + h) + margin, height)
    patch = image[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)]
    if patch.ndim == 3:
        patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    crop = cv2.copyMakeBorder(patch, BORDER, BORDER, BORDER, BORDER,
                              cv2.BORDER_CONSTANT, value=255)
    return crop, (x0, y0)


def to_scan(worker_lines: list[dict], origin: tuple[int, int]) -> list[BoxedLine]:
    """The worker's boxes, from crop pixels back to scan pixels."""
    ox, oy = origin
    out = []
    for line in worker_lines:
        text = (line.get("text") or "").strip()
        box = line.get("box")
        if not text or not box:
            continue
        x0, y0, x1, y1 = box
        out.append(BoxedLine(text, x0 - BORDER + ox, y0 - BORDER + oy,
                             x1 - BORDER + ox, y1 - BORDER + oy))
    return out


def crops_for(field: str, bbox, ndl_cell: binning.Cell | None) -> list[tuple[tuple, int]]:
    """What to crop for a field: NDL's line segments for dates, else the cell."""
    if field in SEGMENT_FIELDS and ndl_cell is not None:
        segments = [((int(l.xmin), int(l.ymin), int(l.width), int(l.height)), SEGMENT_MARGIN)
                    for run in ndl_cell.runs for l in run.lines]
        if segments:
            return segments
    return [(tuple(int(v) for v in bbox), 0)]


def interpret(field: str, bbox, suspect: bool, lines: list[BoxedLine]) -> binning.Proposal:
    """A re-reading's lines, interpreted exactly as NDL's are."""
    raw = "".join(l.text for l in sorted(lines, key=lambda l: (-l.xmin, l.ymin)))
    if field in SEGMENT_FIELDS and any(NOT_KANJI_NUMERALS.search(l.text) for l in lines):
        return binning.Proposal(field, None, raw, "refused",
                                "Arabic digits or Latin letters in a column printed in "
                                "kanji numerals - not trusted", suspect)
    if field == "name_raw" and any(
            NAME_GAP.search(l.text.strip())
            and not binning.KANA_ONLY.match("".join(l.text.split()))
            and not binning.BIRTH_DATE.match("".join(l.text.split()))
            for l in lines):
        return binning.Proposal(field, None, raw, "refused",
                                "gaps in the name reading - characters were missed",
                                suspect)
    cell = binning.cell_from_lines(0, field, tuple(bbox), lines, suspect)
    return binning.propose_cell(field, cell)


@functools.lru_cache(maxsize=1)
def _variant_fold() -> dict[str, str]:
    """The frozen kanji variant table as a folding map - for comparing only.

    Never applied to a value anyone sees: which form the page prints is what a
    reader records.
    """
    try:
        table = ps.vocabularies().get("kanji_variants", [])
    except Exception:
        return {}
    return {e["variant"]: e["canonical"] for e in table
            if e.get("variant") and e.get("canonical")}


def _norm(text, *, fold: bool = False) -> str:
    """For comparison: no whitespace, Unicode compatibility forms unified, and
    (with `fold`) kanji variants folded to one form."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", "".join(str(text).split()))
    if fold:
        table = _variant_fold()
        t = "".join(table.get(ch, ch) for ch in t)
    return t


def variant_only(ndl: dict | None, rerun: binning.Proposal) -> bool:
    """True when the two readings agree only once kanji variants are folded."""
    ndl_fill, fill = (ndl or {}).get("fill"), props.fill_for(rerun)
    return (bool(ndl_fill and fill) and _norm(fill) != _norm(ndl_fill)
            and _norm(fill, fold=True) == _norm(ndl_fill, fold=True))


def compare(ndl: dict | None, rerun: binning.Proposal) -> str:
    """agrees / alternative / unreadable - see the module docstring.

    Readings that differ only by a pair in the frozen kanji variant table agree.
    NDLOCR-Lite writes modern forms where the page prints kyūjitai (歩 for 步,
    郎 for 郞), so counting those as disagreement offered the modern form as an
    "alternative" on nearly every post - inviting the reader to record what the
    page does not print.
    """
    fill = props.fill_for(rerun)
    if not fill or not props.takes_wholesale(rerun):
        return "unreadable"
    ndl = ndl or {}
    if ndl.get("wholesale") and ndl.get("fill"):
        if (rerun.method in ("eradate", "digits") and rerun.method == ndl.get("method")
                and rerun.value and ndl.get("value")):
            return "agrees" if str(rerun.value) == str(ndl["value"]) else "alternative"
        if _norm(fill, fold=True) == _norm(ndl["fill"], fold=True):
            return "agrees"
    return "alternative"


def plan(page: ps.RegisteredPage, first_officer: int = 0) -> list[tuple[ps.Officer, str]]:
    """The officer in hand first, then the rest in reading order, wrapping round."""
    officers = list(page.officers)
    if not officers:
        return []
    start = min(max(first_officer, 0), len(officers) - 1)
    ordered = officers[start:] + officers[:start]
    tasks = []
    for officer in ordered:
        present = {c.field for c in officer.cells}
        tasks.extend((officer, f) for f in FIELD_ORDER if f in present)
    return tasks


# --------------------------------------------------------------------------
# results, kept beside the page image
# --------------------------------------------------------------------------

_cache_lock = threading.RLock()


def results_path(pid: str, frame: int) -> Path:
    return vs.cache_dir(pid) / "cell_ocr" / f"frame_{frame:04d}.json"


def cell_key(index: int, field: str) -> str:
    return f"{index}:{field}"


def load_results(pid: str, frame: int) -> dict[str, dict]:
    """The page's stored re-readings, for display. Unreadable reads as empty.

    Taken under the same lock as writes, so a status poll in this process can
    never hold the file open at the moment a job swaps it in.
    """
    with _cache_lock:
        doc = vs.read_json(results_path(pid, frame), strict=False)
    return (doc or {}).get("cells", {})


def store_result(pid: str, frame: int, record: dict) -> None:
    """Add one cell's reading: read strictly, write atomically.

    A lenient read here returned empty whenever Windows refused it, and the next
    write would then have kept only the newest cell - a page's readings gone. A
    read that still fails after retrying now stops the job instead.
    """
    with _cache_lock:
        path = results_path(pid, frame)
        doc = vs.read_json(path, strict=True) or {}
        cells = doc.get("cells", {})
        cells[cell_key(record["index"], record["field"])] = record
        vs.write_json_atomic(path, {
            "pid": pid,
            "frame": frame,
            "note": "zoomed NDLOCR-Lite re-readings; derived, regenerable (app/cell_ocr.py)",
            "cells": cells,
        })


def still_valid(record: dict, bbox, version: str | None) -> bool:
    """A stored reading stands only for the same cell, recipe and engine release."""
    return (record.get("recipe") == RECIPE
            and [int(v) for v in record.get("bbox") or []] == [int(v) for v in bbox]
            and record.get("engine_version") == version)


# --------------------------------------------------------------------------
# reading a page
# --------------------------------------------------------------------------

@dataclass
class PageContext:
    pid: str
    frame: int
    page: ps.RegisteredPage
    ndl: dict            # officer index -> NDL's proposals by field
    ndl_cells: dict      # (officer index, field) -> NDL's binned cell
    image: object


def page_context(pid: str, frame: int) -> PageContext:
    import iiif_client
    path = iiif_client.fetch_page(pid, frame)
    page = ps.register_file(path, pid, frame)
    try:
        lines = ndl_lines.frame(props.fulltext(pid), frame)
    except (props.ProposalsUnavailable, ndl_lines.NoCoordinateData, IndexError):
        lines = []
    proposals = props.propose_registered(page, lines)
    spec = [(o.index, c.field, tuple(c.bbox), c.suspect)
            for o in page.officers for c in o.cells]
    ndl_cells, _ = binning.bin_page(lines, spec)
    image = cv2.imread(str(path))
    if image is None:
        raise WorkerError(f"cannot read the page image {path}")
    return PageContext(pid, frame, page,
                       {o["index"]: o["fields"] for o in proposals["officers"]},
                       ndl_cells, image)


def read_cell(worker: Worker, ctx: PageContext, officer: ps.Officer, field: str,
              scratch: Path) -> dict:
    cell = next(c for c in officer.cells if c.field == field)
    ndl_entry = ctx.ndl.get(officer.index, {}).get(field)
    crops = crops_for(field, cell.bbox, ctx.ndl_cells.get((officer.index, field)))
    lines: list[BoxedLine] = []
    seen, seconds = [], 0.0
    for n, (box, margin) in enumerate(crops):
        crop, origin = crop_image(ctx.image, box, margin)
        path = scratch / f"f{ctx.frame:04d}_o{officer.index:02d}_{field}_{n}.png"
        cv2.imwrite(str(path), crop)
        try:
            reply = worker.read(path)
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        seconds += reply.get("seconds") or 0.0
        lines.extend(to_scan(reply.get("lines") or [], origin))
        seen.extend({"text": l.get("text"), "confidence": l.get("confidence")}
                    for l in reply.get("lines") or [])
    proposal = interpret(field, cell.bbox, cell.suspect, lines)
    status = compare(ndl_entry, proposal)
    return {
        "index": officer.index,
        "field": field,
        "status": status,
        "variant_only": status == "agrees" and variant_only(ndl_entry, proposal),
        "rerun": {
            "value": proposal.value, "raw": proposal.raw, "method": proposal.method,
            "note": proposal.note, "suspect": proposal.suspect,
            "fill": props.fill_for(proposal),
            "form_key": props.FORM_FIELDS.get(field),
            "wholesale": props.takes_wholesale(proposal),
        },
        "ndl": {k: (ndl_entry or {}).get(k) for k in ("fill", "value", "method")},
        "lines": seen,
        "crops": len(crops),
        "seconds": round(seconds, 3),
        "bbox": [int(v) for v in cell.bbox],
        "recipe": RECIPE,
        "engine": "ndlocr-lite",
        "engine_version": worker.version,
        "read_at": _now(),
    }


def reread(pid: str, frame: int, index: int, field: str, *, fresh: bool = False) -> dict:
    """Re-read one cell now. A stored reading of the same cell is reused unless fresh."""
    worker = shared_worker()
    worker.ensure()
    ctx = page_context(pid, frame)
    officer = next((o for o in ctx.page.officers if o.index == index), None)
    if officer is None:
        raise KeyError(f"no officer {index + 1} on {pid} frame {frame}")
    cell = next((c for c in officer.cells if c.field == field), None)
    if cell is None:
        raise KeyError(f"no {field} cell for officer {index + 1}")
    if not fresh:
        prior = load_results(pid, frame).get(cell_key(index, field))
        if prior and still_valid(prior, cell.bbox, worker.version):
            return prior
    with tempfile.TemporaryDirectory(prefix="cell-ocr-") as scratch:
        record = read_cell(worker, ctx, officer, field, Path(scratch))
    store_result(pid, frame, record)
    return record


@dataclass
class Job:
    pid: str
    frame: int
    state: str = "running"          # running | done | cancelled | failed
    done: int = 0
    total: int = 0
    error: str | None = None
    started_at: str = ""
    finished_at: str | None = None
    cancel: bool = False

    def as_dict(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total,
                "error": self.error, "started_at": self.started_at,
                "finished_at": self.finished_at}


class Jobs:
    """One background zoom-reading job per page, at most."""

    def __init__(self):
        self._jobs: dict[tuple[str, int], Job] = {}
        self._lock = threading.Lock()

    def start(self, pid: str, frame: int, *, first_officer: int = 0,
              fresh: bool = False) -> dict:
        with self._lock:
            job = self._jobs.get((pid, frame))
            if job is None or job.state != "running":
                job = Job(pid, frame, started_at=_now())
                self._jobs[(pid, frame)] = job
                threading.Thread(target=self._run, args=(job, first_officer, fresh),
                                 name=f"cell-ocr-{pid}-{frame}", daemon=True).start()
        return self.status(pid, frame)

    def cancel(self, pid: str, frame: int) -> None:
        job = self._jobs.get((pid, frame))
        if job is not None and job.state == "running":
            job.cancel = True

    def status(self, pid: str, frame: int) -> dict:
        job = self._jobs.get((pid, frame))
        try:
            results = load_results(pid, frame)
        except RuntimeError:
            results = {}
        return {
            "pid": pid,
            "frame": frame,
            "engine": engine_status(),
            "job": job.as_dict() if job else None,
            "summary": dict(Counter(r.get("status") for r in results.values())),
            "results": results,
        }

    def _run(self, job: Job, first_officer: int, fresh: bool) -> None:
        try:
            worker = shared_worker()
            worker.ensure()
            ctx = page_context(job.pid, job.frame)
            tasks = plan(ctx.page, first_officer)
            job.total = len(tasks)
            stored = {} if fresh else load_results(job.pid, job.frame)
            with tempfile.TemporaryDirectory(prefix="cell-ocr-") as scratch:
                for officer, field in tasks:
                    if job.cancel:
                        job.state = "cancelled"
                        break
                    cell = next(c for c in officer.cells if c.field == field)
                    prior = stored.get(cell_key(officer.index, field))
                    if not (prior and still_valid(prior, cell.bbox, worker.version)):
                        store_result(job.pid, job.frame,
                                     read_cell(worker, ctx, officer, field, Path(scratch)))
                    job.done += 1
            if job.state == "running":
                job.state = "done"
        except Exception as exc:   # reported to the reader, not swallowed
            job.state = "failed"
            job.error = str(exc) if isinstance(exc, (EngineUnavailable, WorkerError)) \
                else f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = _now()


JOBS = Jobs()
