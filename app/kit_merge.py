"""Merge the work a reader sent home into the master database.

A kit database was cut from the master with every id intact (app/kit_build.py),
so what comes back is the master's own pages and cells plus rows it has never
seen: the reader's observations, the cells they were recorded against, the
columns they marked as holding no officer, and their work log. Merging is
therefore insertion. Nothing in the master is overwritten except a cell's
audit status and crop, which are the reader's to set.

Safe to run twice: rows already present are skipped, by id - and for the work
log, which has no portable id, by content.

It refuses rather than guesses when the two databases disagree about something
that should be identical: a different volume, a reader the master does not
know, a cell both sides created separately, or work on this volume in the
master that the kit never saw - which means two people were given the same
volume, and that is for the lead to untangle, not for a script.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

WORK_LOG_COLUMNS = ("at", "user_id", "action", "volume_pid", "frame_no", "row_index", "detail")


class MergeRefused(RuntimeError):
    """The returned work cannot be merged as it stands; the message says why."""


def open_return(package: Path, workdir: Path) -> tuple[Path, dict]:
    """Unpack a reader's return zip; (database path, assignment)."""
    with zipfile.ZipFile(package) as z:
        names = set(z.namelist())
        for needed in ("officer-index.db", "assignment.json"):
            if needed not in names:
                raise MergeRefused(f"{package.name} is not a kit return: it has no {needed}")
        z.extract("officer-index.db", workdir)
        assignment = json.loads(z.read("assignment.json").decode("utf-8"))
    return workdir / "officer-index.db", assignment


def _connect(master: Path, returned: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(master, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")     # checked as a whole before commit
    conn.execute("ATTACH DATABASE ? AS k", (str(returned),))
    return conn


def _check(conn: sqlite3.Connection, assignment: dict, allow_other_work: bool) -> dict:
    """Everything that must hold before a row moves; returns the ids to work with."""
    pid = assignment["pid"]
    reader = assignment["reader"]["user_id"]

    bad = conn.execute("PRAGMA k.integrity_check").fetchone()[0]
    if bad != "ok":
        raise MergeRefused(f"the returned database is damaged: {bad}")
    kit_volumes = [r[0] for r in conn.execute("SELECT pid FROM k.source_volume")]
    if kit_volumes != [pid]:
        raise MergeRefused(f"the returned database holds {kit_volumes}, "
                           f"but its assignment says {pid}")
    row = conn.execute("SELECT volume_id FROM main.source_volume WHERE pid = ?",
                       (pid,)).fetchone()
    kit_vid = conn.execute("SELECT volume_id FROM k.source_volume").fetchone()[0]
    if row is None or row[0] != kit_vid:
        raise MergeRefused(f"volume {pid} in the master is not the volume this kit was cut from")
    vid = row[0]
    if conn.execute("SELECT 1 FROM main.app_user WHERE user_id = ?", (reader,)).fetchone() is None:
        raise MergeRefused("the master database does not know this kit's reader")

    strangers = conn.execute("""
        SELECT COUNT(*) FROM k.observation o
         WHERE o.author_user_id NOT IN (SELECT user_id FROM main.app_user)
    """).fetchone()[0]
    if strangers:
        raise MergeRefused(f"{strangers} returned readings were recorded by someone "
                           f"the master database does not know")
    unknown_pages = conn.execute("""
        SELECT COUNT(*) FROM k.source_page
         WHERE page_id NOT IN (SELECT page_id FROM main.source_page WHERE volume_id = ?)
    """, (vid,)).fetchone()[0]
    if unknown_pages:
        raise MergeRefused(f"{unknown_pages} pages in the returned database are not "
                           f"the master's pages for {pid}")
    # The same position on the same page, created separately on each side.
    clashes = conn.execute("""
        SELECT COUNT(*) FROM k.roster_cell c
          JOIN main.roster_cell mc ON mc.page_id = c.page_id AND mc.row_index = c.row_index
         WHERE mc.cell_id <> c.cell_id
    """).fetchone()[0]
    if clashes:
        raise MergeRefused(f"{clashes} cells were registered separately in the master and "
                           f"in the kit - someone else has worked on {pid} since the kit was built")
    if not allow_other_work:
        other = conn.execute("""
            SELECT COUNT(*) FROM main.observation o
              JOIN main.source_page p ON p.page_id = o.page_id
             WHERE p.volume_id = ?
               AND o.obs_id NOT IN (SELECT obs_id FROM k.observation)
        """, (vid,)).fetchone()[0]
        if other:
            raise MergeRefused(
                f"the master holds {other} readings on {pid} that this kit never saw - "
                f"two people may have been given the same volume. Look before merging; "
                f"--allow-other-work merges anyway.")
    return {"pid": pid, "volume_id": vid, "reader": reader}


def _plan(conn: sqlite3.Connection) -> dict:
    """What a merge would add, counted - the dry run."""
    count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    same_log = " AND ".join(f"m.{c} IS w.{c}" for c in WORK_LOG_COLUMNS)
    return {
        "cells_new": count("SELECT COUNT(*) FROM k.roster_cell "
                           "WHERE cell_id NOT IN (SELECT cell_id FROM main.roster_cell)"),
        "cells_changed": count("""
            SELECT COUNT(*) FROM k.roster_cell c JOIN main.roster_cell m ON m.cell_id = c.cell_id
             WHERE m.audit_status IS NOT c.audit_status OR m.crop_bbox IS NOT c.crop_bbox
                OR m.crop_url IS NOT c.crop_url OR m.seniority_no IS NOT c.seniority_no"""),
        "observations_new": count("SELECT COUNT(*) FROM k.observation "
                                  "WHERE obs_id NOT IN (SELECT obs_id FROM main.observation)"),
        "observations_already_merged": count(
            "SELECT COUNT(*) FROM k.observation "
            "WHERE obs_id IN (SELECT obs_id FROM main.observation)"),
        "machine_readings_new": count(
            "SELECT COUNT(*) FROM k.machine_reading "
            "WHERE reading_id NOT IN (SELECT reading_id FROM main.machine_reading)"),
        "templates_new": count("SELECT COUNT(*) FROM k.layout_template "
                               "WHERE name NOT IN (SELECT name FROM main.layout_template)"),
        "work_log_new": count(f"SELECT COUNT(*) FROM k.work_log w WHERE NOT EXISTS "
                              f"(SELECT 1 FROM main.work_log m WHERE {same_log})"),
        "pages_touched": count("""
            SELECT COUNT(DISTINCT page_id) FROM k.observation
             WHERE obs_id NOT IN (SELECT obs_id FROM main.observation)"""),
    }


def _apply(conn: sqlite3.Connection) -> None:
    same_log = " AND ".join(f"m.{c} IS w.{c}" for c in WORK_LOG_COLUMNS)
    log_cols = ", ".join(WORK_LOG_COLUMNS)
    conn.execute("INSERT INTO main.layout_template SELECT * FROM k.layout_template "
                 "WHERE name NOT IN (SELECT name FROM main.layout_template)")
    conn.execute("INSERT INTO main.roster_cell SELECT * FROM k.roster_cell "
                 "WHERE cell_id NOT IN (SELECT cell_id FROM main.roster_cell)")
    conn.execute("""
        UPDATE main.roster_cell SET
               audit_status = (SELECT c.audit_status FROM k.roster_cell c WHERE c.cell_id = main.roster_cell.cell_id),
               crop_bbox    = (SELECT c.crop_bbox    FROM k.roster_cell c WHERE c.cell_id = main.roster_cell.cell_id),
               crop_url     = (SELECT c.crop_url     FROM k.roster_cell c WHERE c.cell_id = main.roster_cell.cell_id),
               seniority_no = (SELECT c.seniority_no FROM k.roster_cell c WHERE c.cell_id = main.roster_cell.cell_id)
         WHERE cell_id IN (SELECT cell_id FROM k.roster_cell)""")
    conn.execute("INSERT INTO main.observation SELECT * FROM k.observation "
                 "WHERE obs_id NOT IN (SELECT obs_id FROM main.observation)")
    conn.execute("INSERT INTO main.machine_reading SELECT * FROM k.machine_reading "
                 "WHERE reading_id NOT IN (SELECT reading_id FROM main.machine_reading)")
    conn.execute(f"INSERT INTO main.work_log ({log_cols}) "
                 f"SELECT {log_cols} FROM k.work_log w WHERE NOT EXISTS "
                 f"(SELECT 1 FROM main.work_log m WHERE {same_log}) ORDER BY w.log_id")


def merge(master: Path, package: Path, *, apply: bool = False,
          allow_other_work: bool = False) -> dict:
    """Check a reader's return and report what it adds; with `apply`, add it.

    One transaction: either everything the reader did lands, or nothing does.
    """
    with tempfile.TemporaryDirectory() as tmp:
        returned, assignment = open_return(Path(package), Path(tmp))
        conn = _connect(Path(master), returned)
        try:
            for table in ("roster_cell", "observation", "machine_reading",
                          "layout_template", "work_log"):
                cols = lambda s: [tuple(r)[1:3] for r in  # noqa: E731
                                  conn.execute(f"PRAGMA {s}.table_info({table})")]
                if cols("main") != cols("k"):
                    raise MergeRefused(f"the returned database's {table} table does not "
                                       f"match the master's - it came from a different version")
            ids = _check(conn, assignment, allow_other_work)
            report = {**ids, "reader_name": assignment["reader"].get("display_name"),
                      "kit_id": assignment.get("kit_id"), **_plan(conn), "applied": False}
            if apply:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _apply(conn)
                    broken = conn.execute("PRAGMA main.foreign_key_check").fetchall()
                    if broken:
                        raise MergeRefused(f"merging would leave {len(broken)} rows pointing "
                                           f"at nothing (first: {tuple(broken[0])})")
                    who = ids["reader"]
                    added = sum(report[k] for k in (
                        "observations_new", "cells_new", "cells_changed", "work_log_new"))
                    # A second run that finds nothing new leaves no trace either.
                    if added:
                        conn.execute(
                            "INSERT INTO main.work_log (user_id, action, volume_pid, detail) "
                            "VALUES (?, 'merge_kit_return', ?, ?)",
                            (who, ids["pid"], json.dumps(
                                {"package": Path(package).name,
                                 "kit_id": assignment.get("kit_id"),
                                 "observations": report["observations_new"]},
                                ensure_ascii=False)))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                report["applied"] = True
            return report
        finally:
            conn.close()
