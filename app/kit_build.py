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


def prepare_frame(job: tuple) -> tuple:
    """Register one page from its original scan, and put its image in the kit.

    (frame, survey entry, bytes written). The registration is computed here, on
    the lead's machine, from the scan as NDL served it - and stored, so the kit
    never computes its own (app/page_service.py, "stored registrations"). That
    is what makes a smaller image safe to ship: it is only ever looked at.
    Greyscale at the same pixel size, so every stored rectangle still lands
    where it did.
    """
    import page_service as ps
    import volume_service as vs

    src, data_home, pid, frame, images, quality = job
    src, data_home = Path(src), Path(data_home)
    dest = data_home / "cache" / pid / frame_name(frame)
    try:
        page = ps.register_file(src, pid, frame)
        ps.store_registration(data_home, pid, frame, page)
        entry = vs.entry_for_page(page)
    except ps.PageNotRegistrable as exc:
        ps.store_registration(data_home, pid, frame, None, str(exc))
        entry = vs.entry_not_roster(str(exc))
    if images == "small":
        from PIL import Image
        with Image.open(src) as im:
            im.convert("L").save(dest, "JPEG", quality=quality, optimize=True)
    else:
        shutil.copyfile(src, dest)
    return frame, entry, dest.stat().st_size


def prepare_volume_data(cache: Path, data_home: Path, pid: str, frames: list[int], *,
                        images: str = "small", quality: int = 75,
                        workers: int = 1, progress=None) -> dict:
    """Fill a kit's data folder for one volume: images, OCR, registrations, survey.

    The survey written here is derived from the registrations stored beside it,
    so what the kit reports as a page's officers is what the page will show.
    """
    if images not in ("original", "small"):
        raise KitError(f"images must be 'original' or 'small', not {images!r}")
    if os.environ.get("JPOCR_OFFLINE", "") not in ("", "0") or \
            (cache / STORED).exists():
        raise KitError("a kit is built from the lead's own data home, where pages are "
                       "registered from their scans - not from inside another kit")
    problems = check_volume_data(cache, frames)
    if problems:
        raise KitError("the volume's data is not complete:\n  " + "\n  ".join(problems))
    dest = data_home / "cache" / pid
    dest.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        shutil.copyfile(cache / name, dest / name)
    jobs = [(str(cache / frame_name(f)), str(data_home), pid, f, images, quality)
            for f in frames]
    entries: dict[str, dict] = {}
    stats = {"frames": len(frames), "bytes": 0, "roster": 0, "officers": 0}
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=workers)
        results = pool.map(prepare_frame, jobs, chunksize=4)
    else:
        pool, results = None, map(prepare_frame, jobs)
    try:
        for n, (frame, entry, size) in enumerate(results, 1):
            entries[str(frame)] = entry
            stats["bytes"] += size
            if entry["status"] == "roster":
                stats["roster"] += 1
                stats["officers"] += entry["officers"]
            if progress:
                progress(n, len(frames))
    finally:
        if pool is not None:
            pool.shutdown()
    (dest / "survey.json").write_text(json.dumps(
        {"pid": pid, "note": "derived from the registrations stored in this kit",
         "frames": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


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
