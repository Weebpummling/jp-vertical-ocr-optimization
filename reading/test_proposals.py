"""Tests for the review-first proposal layer.

Cases are drawn from the prior effort's real benchmark output rather than invented,
so the thresholds are exercised against readings the pipeline actually produced:
the page-55 workbook matches and the page-55 truncated seniority run 112/111/110.

Run:
    python -m unittest discover -s reading -p "test_*.py" -v
"""
import csv
import tempfile
import unittest
from pathlib import Path

from proposals import (
    Agreement,
    Candidate,
    Lexicon,
    LexiconHit,
    Status,
    Suggestion,
    agreement,
    canonicalize,
    classify,
    load_variant_map,
    recover_truncated_seniority,
    similarity,
)


class VariantFolding(unittest.TestCase):
    def setUp(self):
        self.vm = load_variant_map()

    def test_vocab_table_loads(self):
        self.assertGreater(len(self.vm), 0)
        self.assertEqual(self.vm["澤"], "沢")

    def test_folds_kyujitai_to_shinjitai(self):
        # 澤田亀良 appears as 沢田亀良 in the dataset's pre-normalized column.
        self.assertEqual(
            canonicalize("澤田亀良", self.vm), canonicalize("沢田亀良", self.vm)
        )

    def test_does_not_conflate_lookalikes(self):
        # The vocab table maps 齋->斎 and 齊->斉 as separate rows precisely
        # because they are different characters. Folding must preserve that.
        self.assertNotEqual(canonicalize("齋", self.vm), canonicalize("齊", self.vm))

    def test_similarity_is_one_for_variant_equal(self):
        self.assertEqual(similarity("濱田", "浜田", self.vm), 1.0)

    def test_similarity_of_empty_is_zero(self):
        self.assertEqual(similarity("", "浜田", self.vm), 0.0)


class Classification(unittest.TestCase):
    def test_probable_needs_score_and_margin(self):
        # Real page-55 result: 1.00 富永信政 against a 0.75 runner-up.
        sug = classify(
            "富永信政",
            [
                LexiconHit("富永信政", 1.00, row_ref="3892"),
                LexiconHit("富永政雄", 0.75, row_ref="9984"),
            ],
        )
        self.assertIs(sug.status, Status.PROBABLE)
        self.assertAlmostEqual(sug.margin, 0.25)

    def test_high_score_in_crowded_field_is_ambiguous(self):
        # This is the case the prior effort kept getting wrong: a strong best
        # score means little when the runner-up is just as strong.
        sug = classify(
            "田中久一",
            [LexiconHit("田中久一", 0.95), LexiconHit("田中久二", 0.94)],
        )
        self.assertIs(sug.status, Status.AMBIGUOUS)
        self.assertAlmostEqual(sug.margin, 0.01)

    def test_weak_best_is_no_match(self):
        sug = classify("て鱗田本市", [LexiconHit("鎌田福市", 0.444)])
        self.assertIs(sug.status, Status.NO_MATCH)

    def test_no_hits_is_no_match(self):
        sug = classify("横山勇", [])
        self.assertIs(sug.status, Status.NO_MATCH)
        self.assertIsNone(sug.best)
        self.assertEqual(sug.margin, 0.0)

    def test_single_hit_margin_is_its_score(self):
        sug = classify("牛島満", [LexiconHit("牛島満", 1.0)])
        self.assertIs(sug.status, Status.PROBABLE)
        self.assertAlmostEqual(sug.margin, 1.0)

    def test_ranked_is_sorted_descending(self):
        sug = classify(
            "上野亀甫",
            [LexiconHit("A", 0.2), LexiconHit("B", 0.9), LexiconHit("C", 0.5)],
        )
        self.assertEqual([h.score for h in sug.ranked], [0.9, 0.5, 0.2])


class NeverAutoApplies(unittest.TestCase):
    """The invariant that matters most: a suggestion cannot become a value."""

    def test_suggestion_has_no_accepted_field(self):
        sug = classify("百武晴吉", [LexiconHit("百武晴吉", 1.0)])
        for forbidden in ("accepted", "final", "confirmed", "apply"):
            self.assertFalse(
                hasattr(sug, forbidden), f"Suggestion must not expose .{forbidden}"
            )

    def test_suggestion_is_immutable(self):
        sug = classify("百武晴吉", [LexiconHit("百武晴吉", 1.0)])
        with self.assertRaises(Exception):
            sug.reading = "something else"  # type: ignore[misc]

    def test_everything_needs_review(self):
        sug = classify("百武晴吉", [LexiconHit("百武晴吉", 1.0)])
        self.assertTrue(sug.needs_review)

    def test_machine_reading_keeps_reading_and_suggestion_separate(self):
        sug = classify(
            "吉野榮一郎",
            [LexiconHit("吉野榮一郎", 1.0, row_ref="1650"), LexiconHit("吉井一郎", 0.67)],
        )
        row = sug.to_machine_reading(cell_id="cell-1", field_name="name", engine="vlm")
        # The reading is the value; the lexicon hit stays in provenance.
        self.assertEqual(row["value"], "吉野榮一郎")
        self.assertEqual(row["provenance"]["suggestion_status"], "probable")
        self.assertEqual(row["provenance"]["suggestion_row_ref"], "1650")
        self.assertEqual(row["provenance"]["runner_up_score"], 0.67)
        self.assertNotIn("accepted", row)


class AgreementStatus(unittest.TestCase):
    def setUp(self):
        self.vm = load_variant_map()

    def test_exact_match_agrees(self):
        cands = [Candidate("牟田口廉也", engine="ndlkoten_lite")]
        self.assertIs(agreement(cands, "牟田口廉也", self.vm), Agreement.AGREE)

    def test_variant_form_is_its_own_status(self):
        # The engine read the glyph right and it is the same name, but which form
        # the roster prints is a genuine question — not a silent pass.
        cands = [Candidate("澤田亀良", engine="vlm")]
        self.assertIs(agreement(cands, "沢田亀良", self.vm), Agreement.VARIANT_EQUAL)

    def test_different_name_disagrees(self):
        cands = [Candidate("鎌田福市", engine="vlm")]
        self.assertIs(agreement(cands, "亀井眞清", self.vm), Agreement.DISAGREE)

    def test_missing_human_value(self):
        cands = [Candidate("横山勇", engine="vlm")]
        self.assertIs(agreement(cands, None, self.vm), Agreement.NO_HUMAN_VALUE)
        self.assertIs(agreement(cands, "   ", self.vm), Agreement.NO_HUMAN_VALUE)

    def test_no_candidate_values(self):
        self.assertIs(agreement([], "横山勇", self.vm), Agreement.NO_HUMAN_VALUE)
        self.assertIs(
            agreement([Candidate("", engine="vlm")], "横山勇", self.vm),
            Agreement.NO_HUMAN_VALUE,
        )

    def test_any_engine_agreeing_is_agreement(self):
        cands = [Candidate("誤読", engine="ndlkoten_lite"), Candidate("横山勇", engine="vlm")]
        self.assertIs(agreement(cands, "横山勇", self.vm), Agreement.AGREE)


class SequenceRepair(unittest.TestCase):
    """Page 55 read 112/111/110 as 12/11/10 — the crop ate the leading digit."""

    def test_recovers_dropped_prefix(self):
        rep = recover_truncated_seniority("12", previous=113, following=111)
        self.assertIsNotNone(rep)
        self.assertEqual(rep.value, 112)
        self.assertEqual(rep.original, "12")
        self.assertIn("monotone_prefix_recovery", rep.method)
        self.assertTrue(rep.inferred)

    def test_recovers_next_in_run(self):
        rep = recover_truncated_seniority("11", previous=112, following=110)
        self.assertEqual(rep.value, 111)

    def test_consistent_reading_needs_no_repair(self):
        self.assertIsNone(recover_truncated_seniority("112", previous=113, following=111))

    def test_no_room_between_neighbours(self):
        # 112 and 111 are adjacent; nothing fits strictly between them.
        self.assertIsNone(recover_truncated_seniority("11", previous=112, following=111))

    def test_ambiguity_yields_no_repair(self):
        # Reading "5" between 500 and 400 is inconsistent, so a repair is
        # attempted — but 405, 415 ... 495 all fit, so it must decline rather
        # than pick one. Deliberately not the "already consistent" path.
        self.assertIsNone(recover_truncated_seniority("5", previous=500, following=400))

    def test_missing_neighbours_yield_no_repair(self):
        self.assertIsNone(recover_truncated_seniority("12", previous=None, following=111))
        self.assertIsNone(recover_truncated_seniority("12", previous=113, following=None))

    def test_non_numeric_yields_no_repair(self):
        self.assertIsNone(recover_truncated_seniority("一二", previous=113, following=111))
        self.assertIsNone(recover_truncated_seniority("", previous=113, following=111))


class LexiconMatching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "names.csv"
        with self.path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["fullname", "cohort", "branch"])
            for name in ("富永信政", "富永政雄", "牛島満", "黒田重徳", "澤田亀良"):
                w.writerow([name, "21", "歩兵"])
        self.addCleanup(self.tmp.cleanup)

    def test_loads_entries(self):
        lex = Lexicon.from_csv(self.path)
        self.assertEqual(len(lex.entries), 5)
        self.assertEqual(lex.entries[0].cohort, "21")

    def test_exact_reading_is_probable(self):
        lex = Lexicon.from_csv(self.path)
        sug = lex.suggest("牛島満")
        self.assertIs(sug.status, Status.PROBABLE)
        self.assertEqual(sug.best.value, "牛島満")

    def test_variant_reading_still_matches(self):
        lex = Lexicon.from_csv(self.path)
        sug = lex.suggest("沢田亀良")
        self.assertIs(sug.status, Status.PROBABLE)
        self.assertEqual(sug.best.value, "澤田亀良")

    def test_empty_reading_is_no_match(self):
        lex = Lexicon.from_csv(self.path)
        self.assertIs(lex.suggest("").status, Status.NO_MATCH)

    def test_unrelated_reading_is_no_match(self):
        lex = Lexicon.from_csv(self.path)
        self.assertIs(lex.suggest("東京").status, Status.NO_MATCH)


if __name__ == "__main__":
    unittest.main()
