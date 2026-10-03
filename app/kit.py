"""Kit mode - one reader, one volume, one folder, no network.

A reader is sent a zip holding the workstation, one volume's page images and
OCR, and a database with only that volume in it (scripts/build_volume_kit.py).
They unzip it, start it, and read. Nothing syncs: which volume a reader has is
settled by the lead before the kit is built, and the work comes home as one
small file the reader sends back (`build_return`), merged into the master
database by scripts/merge_returned.py.

The kit is described by `data/assignment.json`, named by the JPOCR_KIT
environment variable, which the launcher sets (kit/launcher.py). With it set:

  * the reader is not asked for an id code - the kit is theirs, and a request
    with no code is attributed to the reader the assignment names. Attribution
    is unchanged: every write still lands under their own app_user row;
  * nothing is fetched from NDL (JPOCR_OFFLINE): a page the kit lacks is an
    error that says so, not a download the reader never asked for;
  * `build_return` packs what the reader did for the trip home.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import db
import record_export

ENV = "JPOCR_KIT"
OFFLINE_ENV = "JPOCR_OFFLINE"
KIT_VERSION = 1


class KitBroken(RuntimeError):
    """The assignment file is named but cannot be used."""


def offline() -> bool:
    """True when nothing may be fetched from NDL - always the case inside a kit."""
    return os.environ.get(OFFLINE_ENV, "") not in ("", "0")


def assignment_path() -> Path | None:
    value = os.environ.get(ENV)
    return Path(value) if value else None


def assignment() -> dict | None:
    """The kit's assignment, or None when this is not a kit."""
    path = assignment_path()
    if path is None:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KitBroken(f"the kit's assignment file cannot be read ({path.name}): {exc}") from exc
    for key in ("pid", "reader"):
        if key not in doc:
            raise KitBroken(f"the kit's assignment file has no {key!r}")
    return doc


def reader() -> dict | None:
    """The app_user row of the reader this kit belongs to, or None outside a kit."""
    doc = assignment()
    if doc is None:
        return None
    user_id = doc["reader"]["user_id"]
    with db.read_session() as cur:
        cur.execute("SELECT user_id, login, display_name FROM app_user WHERE user_id = ?",
                    (user_id,))
        row = cur.fetchone()
    if row is None:
        raise KitBroken("the kit's database does not know the reader it was built for")
    return dict(row)


def kit_root() -> Path:
    """The folder the reader unzipped: the one that holds data/."""
    path = assignment_path()
    if path is None:
        raise KitBroken("not a kit")
    return path.resolve().parent.parent


def _counts(cur, pid: str, user_id: str) -> dict:
    cur.execute("""
        SELECT COUNT(*) AS readings,
               COUNT(DISTINCT o.page_id) AS pages,
               SUM(o.author_user_id = ?) AS by_reader
          FROM observation o
          JOIN source_page p   ON p.page_id = o.page_id
          JOIN source_volume v ON v.volume_id = p.volume_id
         WHERE v.pid = ?
    """, (user_id, pid))
    row = cur.fetchone()
    return {"readings": row["readings"] or 0, "pages_with_readings": row["pages"] or 0,
            "readings_by_reader": row["by_reader"] or 0}


def build_return(out_dir: Path | None = None) -> Path:
    """Pack the reader's work for sending home; returns the zip's path.

    One file, small enough to email: a consistent copy of the database (the
    work itself), the officer record and work log as CSV (so it can be read
    without any of this code), and the assignment (so the merge knows whose
    work it is and for which volume). The page images stay behind - the lead
    already has them.
    """
    doc = assignment()
    if doc is None:
        raise KitBroken("not a kit")
    out_dir = out_dir or (kit_root() / "outbox")
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    user_id = doc["reader"]["user_id"]
    name = f"roster-{doc['pid']}-{user_id[:8]}-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    dest = out_dir / name

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # sqlite's own backup: a consistent copy even while the app is writing.
        source = sqlite3.connect(db.db_path())
        try:
            copy = sqlite3.connect(tmp / "officer-index.db")
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        with db.read_session(tmp / "officer-index.db") as cur:
            officers, logged = record_export.write_record(tmp, cur)
            summary = {
                "kit_version": doc.get("kit_version"),
                "kit_id": doc.get("kit_id"),
                "pid": doc["pid"],
                "reader": doc["reader"],
                "returned_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "officers_in_record": officers,
                "work_log_entries": logged,
                **_counts(cur, doc["pid"], user_id),
            }
        (tmp / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        (tmp / "assignment.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        part = dest.with_suffix(".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for item in ("officer-index.db", "officer-record.csv", "work-log.csv",
                         "summary.json", "assignment.json"):
                z.write(tmp / item, item)
        part.replace(dest)
    return dest


def reveal(path: Path) -> None:
    """Open the folder holding `path` with the file selected, so it can be attached
    to a message from there. Best effort: failing to show it is not failing to save it."""
    import subprocess
    if os.environ.get("JPOCR_KIT_QUIET"):     # a self-test or headless run opens no windows
        return
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(path)])
    except OSError:
        pass


def info() -> dict:
    """What the UI needs to know about the kit - never the reader's id code."""
    doc = assignment()
    if doc is None:
        return {"kit": False}
    import volume_service as vs  # here, not at import: vs pulls in the reading layer

    who = reader()
    with db.read_session() as cur:
        counts = _counts(cur, doc["pid"], who["user_id"])
    return {
        "kit": True,
        "pid": doc["pid"],
        "title": doc.get("title"),
        "reader": who["display_name"] or "(unnamed)",
        "return_to": doc.get("return_to"),
        "start_frame": vs.next_unread(doc["pid"], 0),
        **counts,
    }
