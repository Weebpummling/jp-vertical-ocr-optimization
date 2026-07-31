"""Tests for record validation. Cases come from real pages of the registered
volumes — page 51's actual sequence (540, 1077–1084) and page 55's truncated
run — plus the corpus-verified kokuhei dating boundary.

Run:
    python -m unittest discover -s reading -p "test_*.py" -v
"""
import unittest
from datetime import date

from validation import (
    Cell,
    check_agreement,
    check_bounded_dates,
    check_sequence,
    check_vocab_dating,
    flags_to_sql,
    load_vocab_dates,
    validate_page,
)


def cells_from(seq, page="pid 1449474 frame 51", **kw):
    return [
        Cell(cell_id=f"00000000-0000-0000-0000-{i:012d}", page_ref=page,
             seniority_no=n, **kw)
        for i, n in enumerate(seq, start=1)
    ]


class Sequence(unittest.TestCase):
    def test_real_page_51_passes(self):
        # The registered 1935 volume, frame 51: a large gap, still monotone.
        flags = check_sequence(cells_from([540, 1077, 1078, 1079, 1080, 1081, 1082, 1083, 1084]))
        self.assertEqual(flags, [])

    def test_page_55_truncated_run_breaks(self):
        # 110, 11, 112 ... — the cropped 111 reads as 11. Flag, never fix.
        flags = check_sequence(cells_from([110, 11, 112, 113, 114, 117, 118, 119, 121, 123]))
        codes = [f.code for f in flags]
        self.assertIn("sequence_break", codes)
        # exactly the 11 and the following regression boundary flag, no cascade
        self.assertEqual(len([c for c in codes if c == "sequence_break"]), 1)
        self.assertIn("11 after 110", flags[0].detail)

    def test_duplicate_breaks(self):
        flags = check_sequence(cells_from([540, 541, 541]))
        self.assertEqual(flags[0].code, "sequence_break")

    def test_none_seniority_is_skipped_not_flagged(self):
        flags = check_sequence(cells_from([540, None, 542]))
        self.assertEqual(flags, [])

    def test_row_count_vs_template(self):
        self.assertEqual(check_sequence(cells_from([1, 2]), expected_rows=3)[0].code,
                         "missing_row")
        self.assertEqual(check_sequence(cells_from([1, 2, 3, 4]), expected_rows=3)[0].code,
                         "extra_row")
        self.assertEqual(check_sequence(cells_from([1, 2, 3]), expected_rows=3), [])


class VocabDating(unittest.TestCase):
    def setUp(self):
        self.branch = load_vocab_dates("branch.csv", "branch_code")
        self.rank = load_vocab_dates("rank.csv", "rank_code")

    def test_kokuhei_on_1923_page_flags(self):
        # Corpus-verified: the air branch exists from 1925-05-01.
        cells = cells_from([1], branch_code="kokuhei", as_of_date=date(1923, 9, 1))
        flags = check_vocab_dating(cells, self.branch, self.rank)
        self.assertEqual(flags[0].code, "branch_out_of_period")

    def test_kokuhei_on_1926_page_passes(self):
        cells = cells_from([1], branch_code="kokuhei", as_of_date=date(1926, 9, 1))
        self.assertEqual(check_vocab_dating(cells, self.branch, self.rank), [])

    def test_undated_branch_passes_everywhere(self):
        cells = cells_from([1], branch_code="hohei", as_of_date=date(1923, 9, 1))
        self.assertEqual(check_vocab_dating(cells, self.branch, self.rank), [])

    def test_dropped_code_is_not_this_checks_problem(self):
        # Unknown codes are the closed-vocabulary FK's job, not dating's.
        cells = cells_from([1], branch_code="homubu", as_of_date=date(1923, 9, 1))
        self.assertEqual(check_vocab_dating(cells, self.branch, self.rank), [])


class BoundedDates(unittest.TestCase):
    def test_pre_meiji_flags(self):
        cells = cells_from([1], commissioning_date=date(1867, 1, 1))
        self.assertEqual(check_bounded_dates(cells)[0].code, "date_out_of_bounds")

    def test_after_snapshot_flags(self):
        cells = cells_from([1], commissioning_date=date(1936, 1, 1),
                           as_of_date=date(1935, 9, 1))
        self.assertEqual(check_bounded_dates(cells)[0].code, "date_out_of_bounds")

    def test_plausible_date_passes(self):
        cells = cells_from([1], commissioning_date=date(1921, 12, 1),
                           as_of_date=date(1935, 9, 1))
        self.assertEqual(check_bounded_dates(cells), [])


class Agreement(unittest.TestCase):
    def test_disagreement_flags(self):
        cells = cells_from([1], agree_status="disagree")
        self.assertEqual(check_agreement(cells)[0].code, "engine_disagreement")

    def test_agree_and_variant_equal_pass(self):
        for status in ("agree", "variant_equal", "no_human_value", None):
            cells = cells_from([1], agree_status=status)
            self.assertEqual(check_agreement(cells), [], status)


class FlagQueue(unittest.TestCase):
    def test_validate_page_composes(self):
        cells = cells_from([110, 11, 112], branch_code="kokuhei",
                           as_of_date=date(1923, 9, 1))
        flags = validate_page(cells)
        codes = {f.code for f in flags}
        self.assertIn("sequence_break", codes)
        self.assertIn("branch_out_of_period", codes)

    def test_sql_emits_status_and_task_once(self):
        flags = validate_page(cells_from([110, 11, 112]))
        sql = flags_to_sql(flags)
        self.assertIn("SET audit_status = 'sequence_break'", sql)
        self.assertIn("'review_flag'", sql)
        self.assertIn("WHERE NOT EXISTS", sql)  # no duplicate open tasks
        self.assertTrue(sql.startswith("-- Generated"))

    def test_sql_quotes_and_flattens(self):
        from validation import Flag
        # cell_id is the value that reaches SQL string position — must be quoted.
        sql = flags_to_sql([Flag("00000000-0000-0000-0000-000000000001",
                                 "p", "sequence_break", "line one\nline two")])
        self.assertIn("'00000000-0000-0000-0000-000000000001'::uuid", sql)
        # detail lands in a trailing comment: newlines must be flattened, or the
        # second line would escape the comment and become executable SQL.
        for line in sql.splitlines():
            if "line one" in line:
                self.assertIn("line two", line)

    def test_non_status_flags_do_not_touch_audit_status(self):
        cells = cells_from([1], branch_code="kokuhei", as_of_date=date(1923, 9, 1))
        sql = flags_to_sql(validate_page(cells))
        self.assertNotIn("SET audit_status", sql)
        self.assertIn("'review_flag'", sql)


if __name__ == "__main__":
    unittest.main()
