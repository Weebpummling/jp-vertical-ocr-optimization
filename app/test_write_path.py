"""Tests for the write side.

These used to skip whenever a database was not running, which meant the rules
they pin were unverified exactly when someone was least likely to notice. The
database is a file now, so every test here builds one in a temp directory and
runs for real - in CI, on a laptop, always.

What they pin is what is easy to lose quietly: attribution, refusal over
guessing, idempotency, and the constraints that stop a bad row existing at all.
"""

import os
import sqlite3
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "reading"))

import db  # noqa: E402
import eradate  # noqa: E402


class TempDatabase(unittest.TestCase):
    """A fresh database per test, pointed at by JPOCR_DB.

    In memory, not on disk. Every db.* call opens its own connection, so the
    database is a shared-cache `file:` URI that they all resolve to, kept alive
    by the one connection held here. Writing a real file per test cost about
    three seconds each on Windows - the antivirus scans every new database - and
    left locked files behind that broke temp-directory cleanup.
    """

    def setUp(self):
        self.uri = f"file:test-{uuid.uuid4().hex}?mode=memory&cache=shared"
        previous = os.environ.get("JPOCR_DB")
        os.environ["JPOCR_DB"] = self.uri

        # Last connection out destroys a shared-cache memory database, so this
        # one stays open for the lifetime of the test.
        self.keepalive = db.create(self.uri)

        def restore():
            self.keepalive.close()
            if previous is None:
                os.environ.pop("JPOCR_DB", None)
            else:
                os.environ["JPOCR_DB"] = previous

        self.addCleanup(restore)
        self.seed()

    def seed(self):
        """One worker, one volume, one page, one rank - enough to write against."""
        self.user_id = db.new_id()
        self.volume_id = db.new_id()
        self.page_id = db.new_id()
        with db.session() as conn:
            conn.execute(
                "INSERT INTO app_user (user_id, login, display_name) VALUES (?,?,?)",
                (self.user_id, "JP-TEST-CODE-0001", "Alice Tanaka"))
            conn.execute(
                "INSERT INTO source_volume (volume_id, title, pid, edition_date) "
                "VALUES (?,'t','test-pid','1933-09-01')", (self.volume_id,))
            conn.execute(
                "INSERT INTO source_page (page_id, volume_id, frame_no) VALUES (?,?,1)",
                (self.page_id, self.volume_id))
            conn.execute(
                "INSERT INTO rank_vocab (rank_code, label_ja, seniority_order) "
                "VALUES ('taisa','大佐',7)")

    def cell(self, row_index=0):
        cells = db.upsert_cells(self.page_id, [{"index": row_index, "bbox": [1, 2, 3, 4]}],
                                self.user_id)
        return cells[0]["cell_id"]


class AttributionTests(TempDatabase):
    """Every write is recorded to the worker who made it."""

    def test_actor_session_refuses_an_empty_user(self):
        with self.assertRaises(ValueError):
            with db.actor_session(""):
                pass

    def test_recording_an_officer_logs_the_work(self):
        cell = self.cell()
        db.create_observation(page_id=self.page_id, cell_id=cell,
                              as_of_date=date(1933, 9, 1), user_id=self.user_id,
                              values={"name_raw": "平岩棟一"},
                              volume_pid="test-pid", frame_no=1, row_index=0)
        with db.read_session() as cur:
            cur.execute("SELECT user_id, action, volume_pid, frame_no, row_index "
                        "FROM work_log WHERE action = 'record_officer'")
            row = cur.fetchone()
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual((row["volume_pid"], row["frame_no"], row["row_index"]),
                         ("test-pid", 1, 0))

    def test_the_observation_itself_carries_its_author(self):
        cell = self.cell()
        db.create_observation(page_id=self.page_id, cell_id=cell,
                              as_of_date="1933-09-01", user_id=self.user_id,
                              values={"name_raw": "乾忠夫"})
        with db.read_session() as cur:
            cur.execute("SELECT author_user_id, status FROM observation")
            row = cur.fetchone()
        self.assertEqual(row["author_user_id"], self.user_id)
        self.assertEqual(row["status"], "draft")

    def test_a_failed_write_leaves_no_log_behind(self):
        """The log and the data it describes can never disagree."""
        with self.assertRaises(sqlite3.IntegrityError):
            db.create_observation(page_id=self.page_id, cell_id="no-such-cell",
                                  as_of_date="1933-09-01", user_id=self.user_id,
                                  values={"name_raw": "x"})
        with db.read_session() as cur:
            cur.execute("SELECT count(*) AS n FROM work_log")
            self.assertEqual(cur.fetchone()["n"], 0)


class ConstraintTests(TempDatabase):
    """Rows that should not be able to exist."""

    def test_cells_are_idempotent_per_row_index(self):
        """Re-registering a page refreshes geometry, never duplicates officers."""
        db.upsert_cells(self.page_id, [{"index": 0, "bbox": [1, 2, 3, 4]}], self.user_id)
        db.upsert_cells(self.page_id, [{"index": 0, "bbox": [9, 9, 9, 9]}], self.user_id)
        with db.read_session() as cur:
            cur.execute("SELECT crop_bbox, count(*) AS n FROM roster_cell")
            row = cur.fetchone()
        self.assertEqual(row["n"], 1)
        self.assertEqual(row["crop_bbox"], "[9, 9, 9, 9]")

    def test_observation_requires_a_snapshot_date(self):
        """as_of_date is what makes an observation mean anything in the panel."""
        cell = self.cell()
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            with db.session() as conn:
                conn.execute("INSERT INTO observation (obs_id, page_id, cell_id, name_raw) "
                             "VALUES (?,?,?,'x')", (db.new_id(), self.page_id, cell))
        self.assertIn("NOT NULL", str(caught.exception))

    def test_rank_code_must_be_in_the_controlled_vocabulary(self):
        cell = self.cell()
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            db.create_observation(page_id=self.page_id, cell_id=cell,
                                  as_of_date="1933-09-01", user_id=self.user_id,
                                  values={"rank_code": "not_a_rank"})
        self.assertIn("FOREIGN KEY", str(caught.exception))

    def test_a_known_rank_is_accepted(self):
        cell = self.cell()
        saved = db.create_observation(page_id=self.page_id, cell_id=cell,
                                      as_of_date="1933-09-01", user_id=self.user_id,
                                      values={"rank_code": "taisa"})
        self.assertEqual(saved["status"], "draft")

    def test_foreign_keys_are_actually_enforced(self):
        """SQLite has them off by default; a connection that forgets is silent."""
        with db.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class UnreadableCharacterTests(TempDatabase):
    """A character nobody can read must not block the record.

    The reader marks it 〓 and the row saves with everything they *could* see.
    What must not happen is the server reporting that as a refusal: the value
    was recorded, and calling it "not recorded" would teach annotators to
    distrust the flag that does mean something.
    """

    def setUp(self):
        super().setUp()
        import api
        self.api = api

    def record(self, **body):
        from api import ObservationIn
        self.cell()          # an observation hangs off a roster_cell
        return self.api.create_observation(
            "test-pid", 1, ObservationIn(row_index=0, **body),
            {"user_id": self.user_id})

    def test_a_marked_name_is_saved_as_read(self):
        result = self.record(
            name_raw="平岩〓一",
            field_confidence={"name_raw": {"raw": "平岩〓一", "unreadable": 1,
                                           "crop_url": "https://example/crop.jpg"}})
        self.assertEqual(result["status"], "draft")
        with db.read_session() as cur:
            cur.execute("SELECT name_raw FROM observation")
            self.assertEqual(cur.fetchone()["name_raw"], "平岩〓一")

    def test_an_unread_character_is_a_recheck_not_a_refusal(self):
        result = self.record(
            name_raw="平岩〓一",
            field_confidence={"name_raw": {"raw": "平岩〓一", "unreadable": 1,
                                           "crop_url": "https://example/crop.jpg"}})
        self.assertEqual(result["flagged"], {})
        self.assertIn("name_raw", result["needs_recheck"])
        self.assertEqual(result["needs_recheck"]["name_raw"]["crop_url"],
                         "https://example/crop.jpg")

    def test_a_refused_date_is_still_a_refusal(self):
        """The two must not collapse into each other."""
        result = self.record(name_raw="乾忠夫", commissioning_date="明四三、一二")
        self.assertIn("commissioning_date", result["flagged"])
        self.assertEqual(result["needs_recheck"], {})
        self.assertIsNone(result["commissioning_date"])


class DateNormalisationTests(unittest.TestCase):
    """The write path must refuse an unclear date, never guess one."""

    def test_both_notations_reach_the_same_day(self):
        self.assertEqual(eradate.parse("明四三、一二、二六").value, date(1910, 12, 26))
        self.assertEqual(eradate.parse("明治43年12月26日").value, date(1910, 12, 26))

    def test_incomplete_reading_is_refused_with_a_reason(self):
        parsed = eradate.parse("明四三、一二")
        self.assertFalse(parsed.ok)
        self.assertIsNone(parsed.value)
        self.assertIn("expected year/month/day", parsed.reason)

    def test_out_of_era_reading_is_refused(self):
        # Meiji ended in 1912; year 50 would be 1917.
        parsed = eradate.parse("明五〇、一、一")
        self.assertFalse(parsed.ok)
        self.assertIn("outside", parsed.reason)


if __name__ == "__main__":
    unittest.main()
