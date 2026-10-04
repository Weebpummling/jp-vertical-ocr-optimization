"""Assemble a reader's kit: one volume's database and data, ready to zip.

The lead's side of app/kit.py. `scripts/build_volume_kit.py` drives it; the
pieces live here so they can be tested without building anything.

The kit database is cut from the master with every id intact. That is what
makes the trip home simple: a reader's rows are new rows under ids the master
has never seen, on pages and cells whose ids it already knows, so merging is
insertion (app/kit_merge.py), not reconciliation.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("app", "scripts"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import db  # noqa: E402
import kit  # noqa: E402

# Tables cut from the master for one volume, in dependency order. Everything
# else in the schema is either reloaded from the versioned CSVs (vocabularies)
# or starts empty in a kit (work_log: the kit's log is the reader's own).
COPIED = ("app_user", "source_volume", "layout_template", "source_page",
          "roster_cell", "observation", "machine_reading")
REQUIRED_FILES = ("manifest.json", "ndl_fulltext_raw.json")
STORED = "registered"       # page_service.STORED_DIR, named here to keep imports light
SMALL = "small"             # recompressed page images, made when a volume is prepared


class KitError(RuntimeError):
    """The kit cannot be built as asked; the message says what to fix."""


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[tuple]:
    return [(r[1], r[2].upper()) for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def make_kit_db(master: Path, dest: Path, pid: str, reader_id: str) -> dict:
    """A fresh database holding one volume, cut from `master`. Returns row counts.

    Other people's readings on the volume come along - the reader should see a
    page that is already done as done - but their id codes do not: a code is a
    bearer secret, and a kit leaves the building. Only the kit's own reader
    keeps a usable code.
    """
    import load_vocab

    if dest.exists():
        raise KitError(f"{dest} already exists")
    conn = db.create(dest)
    try:
        load_vocab.load(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ATTACH DATABASE ? AS m", (str(master),))
        for table in COPIED:
            if _columns(conn, "main", table) != _columns(conn, "m", table):
                raise KitError(f"the master database's {table} table does not match "
                               f"db/schema.sql; a kit cannot be cut from it")
        row = conn.execute("SELECT volume_id FROM m.source_volume WHERE pid = ?",
                           (pid,)).fetchone()
        if row is None:
            raise KitError(f"{pid} is not registered in the master database")
        vid = row[0]
        if conn.execute("SELECT 1 FROM m.app_user WHERE user_id = ?",
                        (reader_id,)).fetchone() is None:
            raise KitError("the reader is not in the master database")

        pages = "SELECT page_id FROM m.source_page WHERE volume_id = :vid"
        cells = f"SELECT cell_id FROM m.roster_cell WHERE page_id IN ({pages})"
        args = {"vid": vid, "reader": reader_id}
        conn.execute("INSERT INTO source_volume SELECT * FROM m.source_volume "
                     "WHERE volume_id = :vid", args)
        conn.execute("INSERT INTO layout_template SELECT * FROM m.layout_template")
        conn.execute("INSERT INTO source_page SELECT * FROM m.source_page "
                     "WHERE volume_id = :vid", args)
        conn.execute(f"INSERT INTO roster_cell SELECT * FROM m.roster_cell "
                     f"WHERE page_id IN ({pages})", args)
        conn.execute(f"INSERT INTO observation SELECT * FROM m.observation "
                     f"WHERE page_id IN ({pages})", args)
        conn.execute(f"INSERT INTO machine_reading SELECT * FROM m.machine_reading "
                     f"WHERE cell_id IN ({cells})", args)
        conn.execute("""
            INSERT INTO app_user (user_id, login, display_name)
            SELECT user_id,
                   CASE WHEN user_id = :reader THEN login
                        ELSE 'not-in-this-kit:' || user_id END,
                   display_name
              FROM m.app_user
             WHERE user_id = :reader
                OR user_id IN (SELECT author_user_id FROM observation)
        """, args)
        conn.commit()
        conn.execute("DETACH DATABASE m")
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise KitError(f"the volume's rows point at {len(broken)} rows outside it "
                           f"(first: {tuple(broken[0])}); a kit cannot carry them")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in COPIED + ("rank_vocab", "branch_vocab", "kanji_variant")}
        conn.execute("VACUUM")
    finally:
        conn.close()
    return counts


def volume_row(master: Path, pid: str) -> dict:
    conn = sqlite3.connect(master)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM source_volume WHERE pid = ?", (pid,)).fetchone()
        if row is None:
            raise KitError(f"{pid} is not registered in the master database")
        frames = [r[0] for r in conn.execute(
            "SELECT frame_no FROM source_page WHERE volume_id = ? ORDER BY frame_no",
            (row["volume_id"],))]
        return {**dict(row), "frames": frames}
    finally:
        conn.close()


def frame_name(frame: int) -> str:
    return f"frame_{frame:04d}.jpg"


def check_volume_data(cache: Path, frames: list[int]) -> list[str]:
    """Everything a kit needs from <data home>/cache/<pid>; what is missing, in words.

    A kit cannot fetch (it runs with no network), so a page absent here is a
    page the reader can never open. Better found now than by them.
    """
    problems = []
    for name in REQUIRED_FILES:
        if not (cache / name).exists():
            problems.append(f"{name} is missing")
    missing = [f for f in frames if not (cache / frame_name(f)).exists()]
    if missing:
        problems.append(f"{len(missing)} page images are missing "
                        f"(first: frame {missing[0]}) - fetch them with "
                        f"scripts/survey_volume.py <pid> --fetch")
    return problems


def registration_fingerprint() -> str:
    """What decides how a page registers: the detector and the templates.

    A prepared volume records it, so a kit is never cut from registrations made
    by code that has since changed without someone deciding to re-prepare.
    """
    import hashlib
    h = hashlib.sha256()
    for path in [ROOT / "reading" / "registration.py",
                 *sorted((ROOT / "templates").glob("*.json"))]:
        h.update(path.name.encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def prepare_frame(job: tuple) -> tuple:
    """Register one page from its original scan and store the result; make its
    smaller image. (frame, survey entry, leaves re-read, bytes of the small image)."""
    import page_service as ps
    import volume_service as vs
    from PIL import Image

    home, pid, frame, quality = job
    home = Path(home)
    cache = home / "cache" / pid
    src = cache / frame_name(frame)
    reread = 0
    try:
        page = ps.register_file(src, pid, frame, fresh=True)
        ps.store_registration(home, pid, frame, page)
        entry = vs.entry_for_page(page)
        reread = len(page.panels_reread)
    except ps.PageNotRegistrable as exc:
        ps.store_registration(home, pid, frame, None, str(exc))
        entry = vs.entry_not_roster(str(exc))
    small = cache / SMALL / frame_name(frame)
    small.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.convert("L").save(small, "JPEG", quality=quality, optimize=True)
    return frame, entry, reread, small.stat().st_size


def prepared(home: Path, pid: str) -> dict | None:
    """The record of a volume's preparation, or None if it has not been prepared."""
    path = home / "cache" / pid / "prepared.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_volume(home: Path, pid: str, frames: list[int], *, quality: int = 75,
                   workers: int = 1, progress=None) -> dict:
    """Prepare a volume for transcription: register every page here, once.

    Every page is registered from its original scan by this machine and the
    result stored under the data home (cache/<pid>/registered). From then on the
    lead's workstation and every kit read that same result, so they cannot
    disagree about where an officer is - and nothing that changes later (a
    library upgrade, a recompressed image, a new template) moves a cell on a
    page someone has already read, until the volume is deliberately prepared
    again. Also makes the smaller images kits carry, and rewrites the survey
    from the registrations it stored.
    """
    if os.environ.get("JPOCR_OFFLINE", "") not in ("", "0"):
        raise KitError("a volume is prepared on the lead's machine, from its original "
                       "scans - not inside a kit")
    cache = home / "cache" / pid
    problems = check_volume_data(cache, frames)
    if problems:
        raise KitError("the volume's data is not complete:\n  " + "\n  ".join(problems))
    jobs = [(str(home), pid, f, quality) for f in frames]
    entries: dict[str, dict] = {}
    stats = {"frames": len(frames), "roster": 0, "officers": 0, "leaf_missing": 0,
             "leaves_reread": 0, "small_bytes": 0}
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=workers)
        results = pool.map(prepare_frame, jobs, chunksize=4)
    else:
        pool, results = None, map(prepare_frame, jobs)
    try:
        for n, (frame, entry, reread, size) in enumerate(results, 1):
            entries[str(frame)] = entry
            stats["small_bytes"] += size
            stats["leaves_reread"] += reread
            if entry["status"] == "roster":
                stats["roster"] += 1
                stats["officers"] += entry["officers"]
                stats["leaf_missing"] += bool(entry.get("panels_missing"))
            if progress:
                progress(n, len(frames))
    finally:
        if pool is not None:
            pool.shutdown()
    (cache / "survey.json").write_text(json.dumps(
        {"pid": pid, "note": "derived from the registrations stored beside it "
                             "(scripts/prepare_volume.py)",
         "frames": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    record = {
        "pid": pid,
        "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registration": registration_fingerprint(),
        "registered_with": libraries(),
        "image_quality": quality,
        **stats,
    }
    (cache / "prepared.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return record


def install_volume(home: Path, kit_data: Path, pid: str, frames: list[int], *,
                   images: str = "small") -> dict:
    """Copy a prepared volume into a kit's data folder. Returns what was copied."""
    if images not in ("original", "small"):
        raise KitError(f"images must be 'original' or 'small', not {images!r}")
    cache = home / "cache" / pid
    record = prepared(home, pid)
    if record is None:
        raise KitError(f"{pid} has not been prepared: run scripts/prepare_volume.py {pid}")
    if record["registration"] != registration_fingerprint():
        raise KitError(f"{pid} was prepared with different registration code or templates; "
                       f"run scripts/prepare_volume.py {pid} --redo and look at what changed")
    missing = [f for f in frames
               if not (cache / STORED / f"frame_{f:04d}.json").exists()
               or not (cache / (SMALL if images == "small" else "") / frame_name(f)).exists()]
    if missing:
        raise KitError(f"{len(missing)} pages of {pid} are not prepared "
                       f"(first: frame {missing[0]}); run scripts/prepare_volume.py {pid}")
    dest = kit_data / "cache" / pid
    (dest / STORED).mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES + ("survey.json",):
        shutil.copyfile(cache / name, dest / name)
    size = 0
    source = cache / SMALL if images == "small" else cache
    for f in frames:
        shutil.copyfile(cache / STORED / f"frame_{f:04d}.json",
                        dest / STORED / f"frame_{f:04d}.json")
        shutil.copyfile(source / frame_name(f), dest / frame_name(f))
        size += (dest / frame_name(f)).stat().st_size
    return {"frames": len(frames), "bytes": size, "roster": record["roster"],
            "officers": record["officers"], "registered_with": record["registered_with"]}


# --------------------------------------------------------------------------
# readiness - what a reader of this volume can and cannot reach
# --------------------------------------------------------------------------

# A roster page carries a seniority number per officer; NDL read most of them.
# A page that did not register but carries this many short numbers is a roster
# page a reader will never be shown.
ROSTER_LOOKING = 8
# Numbers at seniority height that no cell holds: officers outside the grid.
CUT_SHORT = 2


def _numbers(lines) -> list[tuple[float, float]]:
    """Centres of the short digit strings NDL read on a page - seniority numbers,
    and the cohort row beneath the names."""
    return [((l.xmin + l.xmax) / 2, (l.ymin + l.ymax) / 2) for l in lines
            if any(ch.isdigit() for ch in l.text) and len(l.text.strip()) <= 5]


def readiness(home: Path, pid: str, frames: list[int]) -> dict:
    """What stands between this volume and a complete record, page by page.

    Read from the registrations stored when the volume was prepared, against
    NDL's OCR - which knows nothing of the grid, so it can say what the grid
    missed. Three kinds of page come out, each a place where officers exist on
    paper and a reader cannot record them:

      leaf_missing   one leaf of the spread registered and the other did not;
      not_registered the page carries numbers like a roster page but fits no
                     template at all;
      cut_short      both leaves registered, but numbers sit at seniority
                     height outside every cell - the table is wider than the
                     grid laid on it.

    Counts of officers out of reach are NDL's count of numbers and so run a
    little low (it misses about one in twelve).
    """
    import ndl_lines
    import page_service as ps

    cache = home / "cache" / pid
    doc = json.loads((cache / "ndl_fulltext_raw.json").read_text(encoding="utf-8"))
    pages, roster_frames = [], []
    totals = {"frames": len(frames), "roster": 0, "officers": 0, "leaves_reread": 0,
              "leaf_missing": 0, "not_registered": 0, "cut_short": 0,
              "out_of_reach": 0, "needs_review": 0}
    loaded = {}
    for frame in frames:
        stored = json.loads((cache / STORED / f"frame_{frame:04d}.json").read_text(encoding="utf-8"))
        loaded[frame] = None if "not_registrable" in stored else ps.page_from_dict(stored)
        if loaded[frame] is not None:
            roster_frames.append(frame)
    first, last = (roster_frames[0], roster_frames[-1]) if roster_frames else (0, -1)
    for frame in frames:
        page = loaded[frame]
        try:
            numbers = _numbers(ndl_lines.frame(doc, frame))
        except (IndexError, ndl_lines.NoCoordinateData):
            numbers = []                 # a frame NDL has no OCR for
        if page is None:
            # Two numeric rows per officer on a roster page: seniority and cohort.
            if first < frame < last and len(numbers) >= ROSTER_LOOKING:
                lost = len(numbers) // 2
                totals["not_registered"] += 1
                totals["out_of_reach"] += lost
                pages.append({"frame": frame, "problem": "not_registered", "officers_lost": lost})
            continue
        totals["roster"] += 1
        totals["officers"] += len(page.officers)
        totals["leaves_reread"] += len(page.panels_reread)
        totals["needs_review"] += page.needs_review
        boxes = [c.bbox for o in page.officers for c in o.cells if c.field == "seniority_no"]
        orphans = 0
        if boxes:
            y0 = min(b[1] for b in boxes)
            y1 = max(b[1] + b[3] for b in boxes)
            orphans = sum(1 for cx, cy in numbers if y0 <= cy <= y1
                          and not any(b[0] <= cx <= b[0] + b[2] for b in boxes))
        if page.panels_missing:
            totals["leaf_missing"] += 1
            totals["out_of_reach"] += orphans
            pages.append({"frame": frame, "problem": "leaf_missing", "officers_lost": orphans,
                          "leaf": "right" if 0 in page.panels_missing else "left"})
        elif orphans >= CUT_SHORT:
            totals["cut_short"] += 1
            totals["out_of_reach"] += orphans
            pages.append({"frame": frame, "problem": "cut_short", "officers_lost": orphans})
    reach = totals["officers"] + totals["out_of_reach"]
    totals["out_of_reach_pct"] = round(100 * totals["out_of_reach"] / reach, 1) if reach else 0.0
    return {"pid": pid, "roster_run": [first, last], **totals, "pages": pages}


PROBLEM_WORDS = {
    "leaf_missing": "one leaf did not register",
    "not_registered": "looks like a roster page; fits no template",
    "cut_short": "numbers outside the grid; table may be wider",
}


def write_readiness(out: Path, report: dict, title: str) -> tuple[Path, Path]:
    """The readiness report as a page to read and a table to sort."""
    import csv
    out.mkdir(parents=True, exist_ok=True)
    pid = report["pid"]
    md, table = out / f"{pid}-readiness.md", out / f"{pid}-pages-to-check.csv"
    lines = [
        f"# {pid} - readiness for transcription", "", title, "",
        f"- {report['frames']} pages; roster pages {report['roster_run'][0]}-"
        f"{report['roster_run'][1]}",
        f"- **{report['roster']} roster pages registered, {report['officers']} officers a "
        f"reader can record**",
        f"- {report['leaves_reread']} leaves registered only on the second reading",
        f"- about **{report['out_of_reach']} officers ({report['out_of_reach_pct']}%) are on "
        f"paper but out of a reader's reach**:",
        f"  - {report['leaf_missing']} pages where one leaf did not register",
        f"  - {report['not_registered']} pages that look like roster pages and fit no template",
        f"  - {report['cut_short']} pages where numbers sit outside the grid",
        f"- {report['needs_review']} registered pages have a cell edge that was inferred",
        "", f"Page by page: `{table.name}`. Officer counts out of reach are NDL's count of "
        "the numbers it read, and run a little low.", ""]
    md.write_text("\n".join(lines), encoding="utf-8")
    with open(table, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["frame", "problem", "in words", "leaf", "officers out of reach (approx)"])
        for p in report["pages"]:
            w.writerow([p["frame"], p["problem"], PROBLEM_WORDS[p["problem"]],
                        p.get("leaf", ""), p["officers_lost"]])
    return md, table


def moved_readings(home: Path, master: Path, pid: str) -> list[dict]:
    """Readings whose officer would sit somewhere else under a fresh registration.

    A reading is recorded against a cell - a position on the page and the strip
    it was read from. Before a volume's stored registrations are replaced, every
    page that already has readings is registered afresh and each recorded cell
    is looked for where it was: same position, same strip. Any that moved are
    returned, and the caller decides.
    """
    import page_service as ps

    conn = sqlite3.connect(master)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT DISTINCT p.frame_no, c.row_index, c.crop_bbox
              FROM observation o
              JOIN roster_cell c   ON c.cell_id = o.cell_id
              JOIN source_page p   ON p.page_id = o.page_id
              JOIN source_volume v ON v.volume_id = p.volume_id
             WHERE v.pid = ? ORDER BY p.frame_no, c.row_index""", (pid,)).fetchall()
    finally:
        conn.close()
    moved, pages = [], {}
    for row in rows:
        frame = row["frame_no"]
        if frame not in pages:
            try:
                pages[frame] = ps.register_file(home / "cache" / pid / frame_name(frame),
                                                pid, frame, fresh=True)
            except ps.PageNotRegistrable:
                pages[frame] = None
        page = pages[frame]
        x, _, w, _ = json.loads(row["crop_bbox"])
        officer = next((o for o in page.officers if o.index == row["row_index"]), None) \
            if page else None
        if officer is None or abs((officer.bbox[0] + officer.bbox[2] / 2) - (x + w / 2)) > w / 2:
            moved.append({"frame": frame, "row_index": row["row_index"],
                          "was": [x, w], "now": list(officer.bbox) if officer else None})
    return moved


def libraries() -> dict:
    """The versions that registered this kit's pages - for the day two disagree."""
    import cv2
    import numpy
    return {"python": sys.version.split()[0], "opencv": cv2.__version__,
            "numpy": numpy.__version__}


def write_assignment(path: Path, *, volume: dict, reader: dict, return_to: str | None,
                     images: str, app_commit: str | None,
                     registered_with: dict | None = None) -> dict:
    doc = {
        "kit_version": kit.KIT_VERSION,
        "kit_id": str(uuid.uuid4()),
        "pid": volume["pid"],
        "title": volume["title"],
        "edition_date": volume.get("edition_date"),
        "reader": {"user_id": reader["user_id"], "display_name": reader["display_name"]},
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_commit": app_commit,
        "images": images,
        "registered_with": registered_with,
        "return_to": return_to,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc
