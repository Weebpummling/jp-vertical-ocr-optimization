"""Marking a column of the grid not an officer: who may, what survives, what counts."""

import unittest

import db
import volume_service as vs
from test_write_path import TempDatabase


class RowAuditTests(TempDatabase):
    def test_a_column_marked_not_an_officer_is_listed_and_logged(self):
        self.cell(3)
        self.assertEqual(db.set_row_audit(self.page_id, 3, "extra_row", self.user_id), "extra_row")
        self.assertEqual(db.row_audit(self.page_id), {3: "extra_row"})
        with db.read_session() as cur:
            cur.execute("SELECT action, row_index FROM work_log ORDER BY log_id DESC LIMIT 1")
            self.assertEqual(tuple(cur.fetchone()), ("mark_not_officer", 3))

    def test_re_registering_the_page_keeps_the_mark(self):
        self.cell(3)
        db.set_row_audit(self.page_id, 3, "extra_row", self.user_id)
        self.cell(3)
        self.assertEqual(db.row_audit(self.page_id), {3: "extra_row"})

    def test_the_mark_can_be_undone(self):
        self.cell(3)
        db.set_row_audit(self.page_id, 3, "extra_row", self.user_id)
        self.assertEqual(db.set_row_audit(self.page_id, 3, "ok", self.user_id), "ok")
        self.assertEqual(db.row_audit(self.page_id), {})

    def test_a_validation_flag_is_not_cleared_by_a_reader(self):
        self.cell(3)
        with db.session() as conn:
            conn.execute("UPDATE roster_cell SET audit_status = 'sequence_break' "
                         "WHERE page_id = ? AND row_index = 3", (self.page_id,))
        self.assertEqual(db.set_row_audit(self.page_id, 3, "ok", self.user_id), "sequence_break")

    def test_a_reader_may_not_set_any_other_status(self):
        self.cell(3)
        with self.assertRaises(ValueError):
            db.set_row_audit(self.page_id, 3, "damaged", self.user_id)

    def test_a_row_that_does_not_exist_is_refused(self):
        with self.assertRaises(LookupError):
            db.set_row_audit(self.page_id, 9, "extra_row", self.user_id)

    def test_marked_columns_are_counted_per_frame_and_stop_counting_as_officers(self):
        self.cell(3)
        self.cell(4)
        db.set_row_audit(self.page_id, 3, "extra_row", self.user_id)
        self.assertEqual(db.extra_rows_by_frame("test-pid"), {1: 1})
        entry = {"status": "roster", "officers": 21, "panels_missing": []}
        self.assertEqual(vs.page_status(entry, 20, not_officers=1)["status"], "complete")


if __name__ == "__main__":
    unittest.main()
