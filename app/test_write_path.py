"""Tests for the write side.

These need a live database, so they skip without one rather than fail: CI runs
the schema job separately and a developer without the stack up should still get
a green suite. What they pin is the part that is easy to lose quietly -
attribution, refusal-over-guessing, and idempotency.

Everything runs inside a transaction that is rolled back, so the tests never
leave rows behind.
"""

import os
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reading"))

import eradate  # noqa: E402

try:
    import db
    import psycopg
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    _IMPORT_ERROR = exc


def database_available() -> bool:
    if _IMPORT_ERROR is not None:
        return False
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


AVAILABLE = database_available()


@unittest.skipUnless(AVAILABLE, "no database (set JPOCR_DSN or POSTGRES_PASSWORD)")
class ActorAttributionTests(unittest.TestCase):
    """The audit triggers read the actor from a session setting.

    A write that forgets to set it is recorded with a NULL actor, which is an
    unattributable change to the project's most expensive asset. These tests
    exist so that regression is loud.
    """

    def setUp(self):
        self.conn = db.connect()
        self.conn.autocommit = False
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(
            "INSERT INTO app_user (login, display_name, role) VALUES (%s,%s,'annotator') "
            "RETURNING user_id", (f"test-{uuid.uuid4().hex[:8]}", "Test"))
        self.user_id = str(self.cur.fetchone()["user_id"])

    def test_setting_scopes_to_the_transaction(self):
        self.cur.execute("SELECT set_config('app.user_id', %s, true)", (self.user_id,))
        self.cur.execute("SELECT current_setting('app.user_id', true) AS v")
        self.assertEqual(self.cur.fetchone()["v"], self.user_id)

    def test_write_without_the_setting_has_no_actor(self):
        """Documents the failure mode the helper exists to prevent."""
        self.cur.execute("SELECT set_config('app.user_id', '', true)")
        self.cur.execute(
            "INSERT INTO source_volume (title, pid) VALUES ('t', %s) RETURNING volume_id",
            (f"test-{uuid.uuid4().hex[:8]}",))
        vol = self.cur.fetchone()["volume_id"]
        self.cur.execute(
            "SELECT actor FROM audit_log WHERE table_name='source_volume' AND row_id=%s",
            (vol,))
        self.assertIsNone(self.cur.fetchone()["actor"])

    def test_write_with_the_setting_is_attributed(self):
        self.cur.execute("SELECT set_config('app.user_id', %s, true)", (self.user_id,))
        self.cur.execute(
            "INSERT INTO source_volume (title, pid) VALUES ('t', %s) RETURNING volume_id",
            (f"test-{uuid.uuid4().hex[:8]}",))
        vol = self.cur.fetchone()["volume_id"]
        self.cur.execute(
            "SELECT actor FROM audit_log WHERE table_name='source_volume' AND row_id=%s",
            (vol,))
        self.assertEqual(str(self.cur.fetchone()["actor"]), self.user_id)

    def test_actor_session_refuses_an_empty_user(self):
        with self.assertRaises(ValueError):
            with db.actor_session(""):
                pass


@unittest.skipUnless(AVAILABLE, "no database")
class CellAndObservationTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.conn.autocommit = False
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        suffix = uuid.uuid4().hex[:8]
        self.cur.execute(
            "INSERT INTO app_user (login, display_name, role) VALUES (%s,'T','annotator') "
            "RETURNING user_id", (f"test-{suffix}",))
        self.user_id = str(self.cur.fetchone()["user_id"])
        self.cur.execute(
            "INSERT INTO source_volume (title, pid, edition_date) "
            "VALUES ('t', %s, DATE '1933-09-01') RETURNING volume_id", (f"test-{suffix}",))
        vol = self.cur.fetchone()["volume_id"]
        self.cur.execute(
            "INSERT INTO source_page (volume_id, frame_no) VALUES (%s, 1) RETURNING page_id",
            (vol,))
        self.page_id = self.cur.fetchone()["page_id"]

    def _cell(self, row_index=0):
        self.cur.execute(
            "INSERT INTO roster_cell (page_id, row_index, crop_bbox) "
            "VALUES (%s, %s, %s) RETURNING cell_id",
            (self.page_id, row_index, [1, 2, 3, 4]))
        return self.cur.fetchone()["cell_id"]

    def test_cells_are_unique_per_row_index(self):
        """Re-registering a page must refresh geometry, not duplicate officers."""
        self._cell(0)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._cell(0)

    def test_observation_defaults_to_draft(self):
        cell = self._cell(0)
        self.cur.execute(
            "INSERT INTO observation (page_id, cell_id, name_raw, as_of_date, author_user_id) "
            "VALUES (%s,%s,'x',DATE '1933-09-01',%s) RETURNING status",
            (self.page_id, cell, self.user_id))
        self.assertEqual(self.cur.fetchone()["status"], "draft")

    def test_observation_requires_a_snapshot_date(self):
        """as_of_date is what makes an observation mean anything in the panel."""
        cell = self._cell(0)
        with self.assertRaises(psycopg.errors.NotNullViolation):
            self.cur.execute(
                "INSERT INTO observation (page_id, cell_id, name_raw, author_user_id) "
                "VALUES (%s,%s,'x',%s)", (self.page_id, cell, self.user_id))

    def test_rank_code_must_be_in_the_controlled_vocabulary(self):
        cell = self._cell(0)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.cur.execute(
                "INSERT INTO observation (page_id, cell_id, rank_code, as_of_date, author_user_id) "
                "VALUES (%s,%s,'not_a_rank',DATE '1933-09-01',%s)",
                (self.page_id, cell, self.user_id))


class DateNormalisationTests(unittest.TestCase):
    """The write path must refuse an unclear date, never guess one.

    No database needed: this is the rule the endpoint applies before writing.
    """

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
