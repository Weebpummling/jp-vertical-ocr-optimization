"""Which volumes exist, and how complete each page of them is.

"What is left?" has to be answerable for a whole volume at a glance, and the
database alone cannot answer it: it knows how many officers someone *recorded*
on a frame, not how many the frame *has*. That second number comes from
registering the scan, which needs the page image - so it is surveyed once and
kept in a sidecar, `<data home>/cache/<pid>/survey.json`.

The sidecar is derived data, regenerable at any time by re-running the survey,
which is why it lives in the cache beside the images rather than in the frozen
schema. Every page the workstation opens refreshes its entry for free, and
`scripts/survey_volume.py` fills in the rest in bulk.

A frame's status is one of:

    unsurveyed    never registered - how many officers it has is unknown
    not_roster    registers against no template (index, plate, front matter)
    not_started   a roster page nobody has recorded anything on
    in_progress   some of its officers recorded
    leaf_missing  every reachable officer recorded, but a leaf did not register,
                  so the page is NOT done
    complete      every officer on every leaf recorded

`leaf_missing` is its own status rather than a flag on `complete` because the
two must never be confusable in a list: a page that looks finished while half
its officers are unreachable is exactly the failure this exists to prevent.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("app", "reading", "ingestion"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import db  # noqa: E402
import page_service as ps  # noqa: E402

STATUSES = ("unsurveyed", "not_roster", "not_started", "in_progress",
            "leaf_missing", "complete")

_lock = threading.RLock()

# Windows refuses to replace or read a file while another handle holds it
# (WinError 5, "Access is denied") - a status poll reading the file, or the
# antivirus scanning one just written. That aborted a zoom-reading job at cell
# 127 of 189 on 10 Sep 2026. Such refusals are retried for about three seconds.
REPLACE_ATTEMPTS = 60
REPLACE_DELAY_S = 0.05


def _retry_locked(action):
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return action()
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_DELAY_S)


def read_json(path: Path, *, strict: bool):
    """A JSON sidecar, or None when there is none.

    Lenient (for display): anything unreadable is None. Strict (before a write):
    a file held by another handle is retried and then raised, and a file that is
    not JSON is moved aside as `<name>.corrupt-<time>` - never read as empty and
    silently written over. Read-merge-write with a lenient read would write one
    frame back as the whole file whenever a read happened to be refused.
    """
    if not path.exists():
        return None
    try:
        text = _retry_locked(lambda: path.read_text(encoding="utf-8"))
    except OSError:
        if strict:
            raise
        return None
    try:
        return json.loads(text)
    except ValueError:
        if not strict:
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside = path.with_name(f"{path.name}.corrupt-{stamp}")
        _retry_locked(lambda: path.replace(aside))
        return None


def write_json_atomic(path: Path, doc: dict) -> None:
    """Write beside the target, then swap it in - retrying a refused swap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.part")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _retry_locked(lambda: tmp.replace(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def data_home() -> Path:
    home = os.environ.get("JP_OCR_DATA")
    if not home:
        raise RuntimeError("JP_OCR_DATA is not set")
    return Path(home)


def cache_dir(pid: str) -> Path:
    return data_home() / "cache" / pid


def survey_path(pid: str) -> Path:
    return cache_dir(pid) / "survey.json"


def cached_frames(pid: str) -> set[int]:
    """Frames whose page image is on disk - the ones that can be worked offline."""
    out = set()
    folder = cache_dir(pid)
    if not folder.exists():
        return out
    for path in folder.glob("frame_*.jpg"):
        try:
            if path.stat().st_size > 0:
                out.add(int(path.stem.split("_")[1]))
        except (ValueError, IndexError, OSError):
            continue
    return out


def load_survey(pid: str) -> dict[int, dict]:
    """The survey for display. Unreadable reads as empty: it is regenerable, and
    the page list must still open."""
    with _lock:
        try:
            raw = read_json(survey_path(pid), strict=False)
        except OSError:
            raw = None
    return {int(k): v for k, v in (raw or {}).get("frames", {}).items()}


def record_survey(pid: str, frame: int, entry: dict) -> None:
    """Add one frame's entry: read strictly, write atomically, under the lock."""
    with _lock:
        path = survey_path(pid)
        raw = read_json(path, strict=True) or {}
        frames = {int(k): v for k, v in raw.get("frames", {}).items()}
        frames[frame] = entry
        write_json_atomic(path, {
            "pid": pid,
            "note": "derived by registering each scan; regenerate with "
                    "scripts/survey_volume.py",
            "frames": {str(k): frames[k] for k in sorted(frames)},
        })


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_for_page(page: ps.RegisteredPage) -> dict:
    return {
        "status": "roster",
        "officers": len(page.officers),
        "panels_total": page.panels_total,
        "panels_missing": list(page.panels_missing),
        "needs_review": page.needs_review,
        "template": page.template_id,
        "surveyed_at": _now(),
    }


def entry_not_roster(reason: str) -> dict:
    return {"status": "not_roster", "reason": reason, "surveyed_at": _now()}


def record_page(pid: str, frame: int, page: ps.RegisteredPage) -> None:
    """Refresh a frame's entry from a registration that already happened."""
    record_survey(pid, frame, entry_for_page(page))


def survey_frame(pid: str, frame: int, *, fetch: bool = False) -> dict:
    """Register one frame and record what it holds.

    Uncached frames are skipped unless `fetch` is set: a survey must never turn
    into an unplanned bulk download from NDL.
    """
    path = cache_dir(pid) / f"frame_{frame:04d}.jpg"
    if not path.exists():
        if not fetch:
            return {"status": "uncached"}
        import iiif_client
        path = iiif_client.fetch_page(pid, frame)
    try:
        page = ps.register_file(path, pid, frame)
    except ps.PageNotRegistrable as exc:
        entry = entry_not_roster(str(exc))
    else:
        entry = entry_for_page(page)
    record_survey(pid, frame, entry)
    return entry


def page_status(entry: dict | None, rows_read: int, not_officers: int = 0) -> dict:
    """One frame's completeness, from its survey entry and its recorded rows.

    `not_officers` are columns a reader marked as holding no officer (a section
    label, the column legend, an unused slot); they do not count toward the page.
    """
    if entry is None:
        return {"status": "in_progress" if rows_read else "unsurveyed",
                "officers": None, "rows_read": rows_read,
                "leaf_missing": False, "needs_review": False}
    if entry.get("status") == "not_roster":
        return {"status": "not_roster", "officers": 0, "rows_read": rows_read,
                "leaf_missing": False, "needs_review": False,
                "reason": entry.get("reason")}
    officers = max(int(entry.get("officers") or 0) - not_officers, 0)
    missing = bool(entry.get("panels_missing"))
    if rows_read == 0:
        status = "not_started"
    elif rows_read < officers:
        status = "in_progress"
    elif missing:
        status = "leaf_missing"
    else:
        status = "complete"
    return {"status": status, "officers": officers, "rows_read": rows_read,
            "not_officers": not_officers, "leaf_missing": missing,
            "needs_review": bool(entry.get("needs_review"))}


def page_statuses(pid: str) -> dict:
    """Every registered frame of a volume with its completeness."""
    frames = db.volume_frames(pid)
    progress = {f["frame_no"]: f for f in db.volume_progress(pid)}
    marked = db.extra_rows_by_frame(pid)
    survey = load_survey(pid)
    cached = cached_frames(pid)
    pages = []
    counts: Counter = Counter()
    for frame in frames:
        read = progress.get(frame, {})
        status = page_status(survey.get(frame), int(read.get("rows_read") or 0),
                             marked.get(frame, 0))
        status.update({"frame": frame, "cached": frame in cached,
                       "last_touched": read.get("last_touched")})
        counts[status["status"]] += 1
        pages.append(status)
    roster = [p for p in pages if p["officers"]]
    return {
        "pid": pid,
        "frames_total": len(frames),
        "surveyed": sum(1 for p in pages if p["status"] != "unsurveyed"
                        or p["frame"] in survey),
        "cached": len(cached),
        "officers_known": sum(p["officers"] or 0 for p in roster),
        "rows_read": sum(p["rows_read"] for p in pages),
        "counts": {s: counts.get(s, 0) for s in STATUSES},
        "pages": pages,
    }


def volumes() -> list[dict]:
    """Registered volumes, each with its survey and cache coverage."""
    out = []
    for vol in db.volumes_summary():
        pid = vol["pid"]
        survey = load_survey(pid)
        vol = dict(vol)
        vol.update({
            "surveyed": len(survey),
            "cached": len(cached_frames(pid)),
            "officers_known": sum(int(e.get("officers") or 0)
                                  for e in survey.values()
                                  if e.get("status") == "roster"),
            "ocr_cached": (cache_dir(pid) / "ndl_fulltext_raw.json").exists(),
        })
        out.append(vol)
    return out
