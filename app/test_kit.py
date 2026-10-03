"""A reader's kit: cut from the master, worked on alone, sent home, merged.

Real files, not the in-memory database the other suites use: a kit is cut with
ATTACH and sent home as a file, and that is the thing under test. The master,
the kit and one return package are built once for the module - on Windows every
new database file costs a second or more of antivirus attention - and each test
that changes something works on its own copy.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kit"))

import db  # noqa: E402
import kit  # noqa: E402
import kit_build  # noqa: E402
import kit_merge  # noqa: E402
import launcher  # noqa: E402
import page_service as ps  # noqa: E402
import volume_service as vs  # noqa: E402
from test_proposal_service import spread  # noqa: E402

LEAD_CODE = "JP-LEAD-CODE-0001"
READER_CODE = "JP-READ-CODE-0002"
ENV_KEYS = ("JPOCR_DB", "JP_OCR_DATA", kit.ENV, kit.OFFLINE_ENV)

FIX: Path
IDS: dict = {}
COUNTS: dict = {}
_saved_env: dict = {}


def enter_kit(root: Path):
    os.environ["JPOCR_DB"] = str(root / "data" / "officer-index.db")
    os.environ["JP_OCR_DATA"] = str(root / "data")
    os.environ[kit.ENV] = str(root / "data" / "assignment.json")
    os.environ[kit.OFFLINE_ENV] = "1"


def leave_kit(database: Path):
    for key in (kit.ENV, kit.OFFLINE_ENV, "JP_OCR_DATA"):
        os.environ.pop(key, None)
    os.environ["JPOCR_DB"] = str(database)


def record(database: Path, key: str, frame: int, row: int, user: str, name: str):
    os.environ["JPOCR_DB"] = str(database)
    page_id = IDS["pages"][key, frame]
    cell = db.upsert_cells(page_id, [{"index": row, "bbox": [1, 2, 3, 4]}], user,
                           volume_pid=f"pid-{key}", frame_no=frame)[0]["cell_id"]
    return db.create_observation(page_id=page_id, cell_id=cell, as_of_date="1933-09-01",
                                 user_id=user, values={"name_raw": name},
                                 volume_pid=f"pid-{key}", frame_no=frame, row_index=row)


def setUpModule():
    """A master with two volumes; a kit cut for volume A; the reader's return."""
    global FIX
    _saved_env.update({k: os.environ.get(k) for k in ENV_KEYS})
    FIX = Path(tempfile.mkdtemp(prefix="kit-test-"))
    import load_vocab

    master = FIX / "master.db"
    IDS.update(lead=db.new_id(), reader=db.new_id(),
               vol={"A": db.new_id(), "B": db.new_id()}, pages={})
    conn = db.create(master)
    load_vocab.load(conn)
    conn.execute("INSERT INTO app_user VALUES (?,?,?)", (IDS["lead"], LEAD_CODE, "Project lead"))
    conn.execute("INSERT INTO app_user VALUES (?,?,?)", (IDS["reader"], READER_CODE, "Tanaka"))
    for key in ("A", "B"):
        conn.execute("INSERT INTO source_volume (volume_id, title, pid, edition_date) "
                     "VALUES (?,?,?,'1933-09-01')", (IDS["vol"][key], f"vol {key}", f"pid-{key}"))
        for frame in range(1, 6):
            IDS["pages"][key, frame] = db.new_id()
            conn.execute("INSERT INTO source_page (page_id, volume_id, frame_no) VALUES (?,?,?)",
                         (IDS["pages"][key, frame], IDS["vol"][key], frame))
    conn.commit()
    conn.close()
    leave_kit(master)
    # The lead read one officer of volume A before any kit existed.
    record(master, "A", 2, 0, IDS["lead"], "先任者")

    root = FIX / "kit"
    (root / "data").mkdir(parents=True)
    COUNTS.update(kit_build.make_kit_db(master, root / "data" / "officer-index.db",
                                        "pid-A", IDS["reader"]))
    kit_build.write_assignment(
        root / "data" / "assignment.json",
        volume={"pid": "pid-A", "title": "vol A", "edition_date": "1933-09-01"},
        reader={"user_id": IDS["reader"], "display_name": "Tanaka"},
        return_to="send it to the lead", images="original", app_commit=None)

    # The reader records two officers and marks a column as holding no officer.
    worked = FIX / "worked"
    shutil.copytree(root, worked)
    enter_kit(worked)
    kit_db = worked / "data" / "officer-index.db"
    record(kit_db, "A", 3, 0, IDS["reader"], "土橋一正")
    record(kit_db, "A", 3, 1, IDS["reader"], "武田米太郞")
    db.upsert_cells(IDS["pages"]["A", 3], [{"index": 2, "bbox": [5, 6, 7, 8]}], IDS["reader"])
    db.set_row_audit(IDS["pages"]["A", 3], 2, "extra_row", IDS["reader"],
                     volume_pid="pid-A", frame_no=3)
    IDS["package"] = kit.build_return()
    leave_kit(master)


def tearDownModule():
    for key, value in _saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    shutil.rmtree(FIX, ignore_errors=True)


def count(database: Path, sql: str, *args):
    conn = sqlite3.connect(database)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


class KitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-case-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(leave_kit, FIX / "master.db")
        leave_kit(FIX / "master.db")

    def own_master(self) -> Path:
        """A master this test may write to."""
        return Path(shutil.copyfile(FIX / "master.db", self.tmp / "master.db"))

    def own_kit(self, which: str = "kit") -> Path:
        return Path(shutil.copytree(FIX / which, self.tmp / which))


class KitDatabaseTests(KitCase):
    KIT_DB = property(lambda self: FIX / "kit" / "data" / "officer-index.db")

    def test_a_kit_holds_its_volume_and_nothing_else(self):
        self.assertEqual(count(self.KIT_DB, "SELECT COUNT(*) FROM source_volume"), 1)
        self.assertEqual(count(self.KIT_DB, "SELECT pid FROM source_volume"), "pid-A")
        self.assertEqual(count(self.KIT_DB, "SELECT COUNT(*) FROM source_page"), 5)
        self.assertEqual(count(self.KIT_DB, "SELECT COUNT(*) FROM observation"), 1)
        self.assertEqual(count(self.KIT_DB, "SELECT COUNT(*) FROM work_log"), 0)

    def test_ids_are_the_masters_own(self):
        self.assertEqual(count(self.KIT_DB, "SELECT volume_id FROM source_volume"),
                         IDS["vol"]["A"])
        self.assertEqual(count(self.KIT_DB, "SELECT page_id FROM source_page WHERE frame_no = 3"),
                         IDS["pages"]["A", 3])

    def test_only_the_reader_keeps_a_usable_id_code(self):
        """A code is a bearer secret, and a kit leaves the building."""
        conn = sqlite3.connect(self.KIT_DB)
        logins = dict(conn.execute("SELECT user_id, login FROM app_user"))
        conn.close()
        self.assertEqual(logins[IDS["reader"]], READER_CODE)
        self.assertNotIn(LEAD_CODE, logins.values())
        self.assertIn(IDS["lead"], logins, "the lead's reading needs its author row")

    def test_vocabularies_come_from_the_versioned_files(self):
        self.assertEqual(COUNTS["rank_vocab"], 11)
        self.assertEqual(COUNTS["branch_vocab"], 14)
        self.assertGreaterEqual(COUNTS["kanji_variant"], 30)

    def test_an_unregistered_volume_is_refused(self):
        with self.assertRaises(kit_build.KitError):
            kit_build.make_kit_db(FIX / "master.db", self.tmp / "x.db", "pid-Z", IDS["reader"])


class KitModeTests(KitCase):
    def test_outside_a_kit_nothing_changes(self):
        self.assertIsNone(kit.assignment())
        self.assertIsNone(kit.reader())
        self.assertFalse(kit.offline())

    def test_inside_a_kit_work_is_attributed_to_its_reader_without_a_code(self):
        import api
        enter_kit(FIX / "kit")
        self.assertEqual(api.current_user(None)["user_id"], IDS["reader"])

    def test_a_code_is_still_required_outside_a_kit(self):
        import api
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            api.current_user(None)
        self.assertEqual(caught.exception.status_code, 401)

    def test_kit_info_never_carries_the_id_code(self):
        enter_kit(FIX / "kit")
        info = kit.info()
        self.assertTrue(info["kit"])
        self.assertEqual((info["pid"], info["reader"]), ("pid-A", "Tanaka"))
        self.assertNotIn(READER_CODE, json.dumps(info))

    def test_a_kit_does_not_fetch(self):
        import iiif_client
        enter_kit(FIX / "kit")
        with self.assertRaises(iiif_client.Offline):
            iiif_client._get("https://example.invalid/")


class NextUnreadTests(KitCase):
    def survey(self, root: Path, entries: dict):
        folder = root / "data" / "cache" / "pid-A"
        folder.mkdir(parents=True)
        (folder / "survey.json").write_text(json.dumps({"pid": "pid-A", "frames": entries}),
                                            encoding="utf-8")

    def roster(self, officers: int) -> dict:
        return {"status": "roster", "officers": officers, "panels_total": 2,
                "panels_missing": [], "needs_review": False, "template": "t"}

    def test_front_matter_and_finished_pages_are_skipped(self):
        root = self.own_kit()
        self.survey(root, {"1": {"status": "not_roster"}, "2": self.roster(1),
                           "3": self.roster(2), "4": {"status": "not_roster"},
                           "5": self.roster(2)})
        enter_kit(root)
        # Frame 2's one officer was read by the lead before the kit was cut.
        self.assertEqual(vs.next_unread("pid-A", 0), 3)
        self.assertEqual(vs.next_unread("pid-A", 3), 5)
        self.assertEqual(vs.next_unread("pid-A", 5), 3, "wraps to what was passed over")
        self.assertEqual(kit.info()["start_frame"], 3)

    def test_nothing_left_is_none(self):
        root = self.own_kit()
        self.survey(root, {"2": self.roster(1)})
        enter_kit(root)
        self.assertIsNone(vs.next_unread("pid-A", 0))


class StoredRegistrationTests(KitCase):
    """A kit reads back the lead's registration of a page; it never makes its own."""

    def home(self) -> Path:
        home = self.tmp / "data"
        os.environ["JP_OCR_DATA"] = str(home)
        return home

    def test_a_stored_page_comes_back_as_it_was_registered(self):
        page = spread((2, 1))
        ps.store_registration(self.home(), page.pid, page.frame, page)
        # No image is read: the path does not exist.
        got = ps.register_file(self.tmp / "no-such.jpg", page.pid, page.frame)
        self.assertEqual(got.as_dict(), page.as_dict())

    def test_a_page_stored_as_having_no_grid_is_refused_the_same_way(self):
        ps.store_registration(self.home(), "p", 7, None, "p frame 7: no panel matches")
        with self.assertRaises(ps.PageNotRegistrable) as caught:
            ps.register_file(self.tmp / "no-such.jpg", "p", 7)
        self.assertIn("no panel matches", str(caught.exception))

    def test_crop_urls_are_built_on_the_way_out(self):
        page = spread((1,))
        ps.store_registration(self.home(), page.pid, page.frame, page)
        got = ps.register_file(self.tmp / "no-such.jpg", page.pid, page.frame,
                               url_for=lambda pid, frame, bbox: f"{pid}/{frame}/{bbox[0]}")
        self.assertEqual(got.officers[0].crop_url, f"p/1/{page.officers[0].bbox[0]}")
        self.assertTrue(all(c.crop_url for c in got.officers[0].cells))

    def test_a_kit_never_registers_a_page_itself(self):
        self.home()
        os.environ[kit.OFFLINE_ENV] = "1"
        with self.assertRaises(ps.PageNotRegistrable) as caught:
            ps.register_file(self.tmp / "no-such.jpg", "p", 3)
        self.assertIn("carries no registration", str(caught.exception))

    def test_outside_a_kit_a_page_with_nothing_stored_is_registered_from_its_scan(self):
        self.home()
        with self.assertRaises(FileNotFoundError):
            ps.register_file(self.tmp / "no-such.jpg", "p", 3)

    def test_a_kit_is_not_built_from_inside_another_kit(self):
        cache = self.home() / "cache" / "p"
        (cache / kit_build.STORED).mkdir(parents=True)
        with self.assertRaises(kit_build.KitError):
            kit_build.prepare_volume_data(cache, self.tmp / "out", "p", [1])


class LauncherTests(KitCase):
    """What a double-click checks before anything starts."""

    def test_a_folder_that_was_not_fully_extracted_says_so(self):
        self.assertEqual(launcher.check_folder(self.tmp), launcher.NOT_EXTRACTED)
        self.assertIn("Extract All", launcher.NOT_EXTRACTED)

    def test_a_complete_kit_folder_is_accepted_and_left_clean(self):
        root = self.own_kit()
        self.assertIsNone(launcher.check_folder(root))
        self.assertFalse((root / "data" / ".write-test").exists())

    def test_the_preferred_port_is_used_when_free_and_another_when_not(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            taken = held.getsockname()[1]
            self.assertNotEqual(launcher.free_port(taken), taken)
        self.assertEqual(launcher.free_port(taken), taken)

    def test_a_kit_that_is_not_running_is_not_mistaken_for_one(self):
        root = self.own_kit()
        (root / "data" / "kit-running.json").write_text('{"port": 9, "pid": 1}')
        self.assertIsNone(launcher.already_running(root, {"pid": "pid-A"}))


class ReturnTests(KitCase):
    def test_the_return_is_one_small_file_that_reads_without_this_code(self):
        package = IDS["package"]
        self.assertEqual(package.parent.name, "outbox")
        with zipfile.ZipFile(package) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["assignment.json", "officer-index.db", "officer-record.csv",
                              "summary.json", "work-log.csv"])
            officers = z.read("officer-record.csv").decode("utf-8-sig")
            summary = json.loads(z.read("summary.json"))
        self.assertIn("土橋一正", officers)
        self.assertEqual(summary["readings_by_reader"], 2)
        self.assertEqual(summary["readings"], 3)


class MergeTests(KitCase):
    def test_a_dry_run_reports_and_changes_nothing(self):
        report = kit_merge.merge(FIX / "master.db", IDS["package"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["observations_new"], 2)
        self.assertEqual(report["cells_new"], 3)
        self.assertEqual(count(FIX / "master.db", "SELECT COUNT(*) FROM observation"), 1)

    def test_merged_work_lands_under_the_reader(self):
        master = self.own_master()
        report = kit_merge.merge(master, IDS["package"], apply=True)
        self.assertTrue(report["applied"])
        self.assertEqual(count(master, "SELECT COUNT(*) FROM observation "
                                       "WHERE author_user_id = ?", IDS["reader"]), 2)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM roster_cell "
                                       "WHERE audit_status = 'extra_row'"), 1)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM work_log WHERE user_id = ? "
                                       "AND action = 'record_officer'", IDS["reader"]), 2)
        conn = sqlite3.connect(master)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        conn.close()

    def test_merging_twice_adds_nothing_the_second_time(self):
        master = self.own_master()
        kit_merge.merge(master, IDS["package"], apply=True)
        before = count(master, "SELECT COUNT(*) FROM work_log")
        again = kit_merge.merge(master, IDS["package"], apply=True)
        self.assertEqual((again["observations_new"], again["cells_new"], again["work_log_new"]),
                         (0, 0, 0))
        self.assertEqual(again["observations_already_merged"], 3)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM observation"), 3)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM work_log"), before)

    def test_a_later_return_adds_only_what_is_new(self):
        master = self.own_master()
        kit_merge.merge(master, IDS["package"], apply=True)
        worked = self.own_kit("worked")
        enter_kit(worked)
        record(worked / "data" / "officer-index.db", "A", 5, 0, IDS["reader"], "渡邊洋")
        second = kit.build_return(self.tmp / "later")
        report = kit_merge.merge(master, second, apply=True)
        self.assertEqual(report["observations_new"], 1)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM observation"), 4)

    def test_work_the_kit_never_saw_is_refused(self):
        """Two people given the same volume is for the lead to untangle."""
        master = self.own_master()
        record(master, "A", 4, 0, IDS["lead"], "後から")
        with self.assertRaises(kit_merge.MergeRefused) as caught:
            kit_merge.merge(master, IDS["package"], apply=True)
        self.assertIn("never saw", str(caught.exception))
        report = kit_merge.merge(master, IDS["package"], apply=True, allow_other_work=True)
        self.assertEqual(report["observations_new"], 2)

    def test_the_same_cell_made_on_both_sides_is_refused(self):
        master = self.own_master()
        os.environ["JPOCR_DB"] = str(master)
        db.upsert_cells(IDS["pages"]["A", 3], [{"index": 0, "bbox": [9, 9, 9, 9]}], IDS["lead"])
        with self.assertRaises(kit_merge.MergeRefused):
            kit_merge.merge(master, IDS["package"], apply=True, allow_other_work=True)
        self.assertEqual(count(master, "SELECT COUNT(*) FROM observation"), 1)

    def test_work_on_another_volume_in_the_master_is_no_obstacle(self):
        master = self.own_master()
        record(master, "B", 1, 0, IDS["lead"], "別巻")
        report = kit_merge.merge(master, IDS["package"], apply=True)
        self.assertEqual(report["observations_new"], 2)

    def test_a_zip_that_is_not_a_return_is_refused(self):
        bogus = self.tmp / "bogus.zip"
        with zipfile.ZipFile(bogus, "w") as z:
            z.writestr("readme.txt", "hello")
        with self.assertRaises(kit_merge.MergeRefused):
            kit_merge.merge(FIX / "master.db", bogus)


if __name__ == "__main__":
    unittest.main()
