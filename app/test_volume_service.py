"""Tests for page completeness and the survey sidecar."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import volume_service as vs


def roster(officers=20, missing=(), review=False):
    return {"status": "roster", "officers": officers, "panels_total": 2,
            "panels_missing": list(missing), "needs_review": review}


class PageStatusTests(unittest.TestCase):
    def test_a_page_never_surveyed_has_no_known_officer_count(self):
        got = vs.page_status(None, 0)
        self.assertEqual(got["status"], "unsurveyed")
        self.assertIsNone(got["officers"])

    def test_an_unsurveyed_page_someone_has_read_is_in_progress(self):
        self.assertEqual(vs.page_status(None, 3)["status"], "in_progress")

    def test_not_started_in_progress_complete(self):
        self.assertEqual(vs.page_status(roster(), 0)["status"], "not_started")
        self.assertEqual(vs.page_status(roster(), 7)["status"], "in_progress")
        self.assertEqual(vs.page_status(roster(), 20)["status"], "complete")

    def test_every_reachable_officer_recorded_with_a_leaf_missing_is_not_complete(self):
        """The failure this exists to prevent: a half-read spread that looks done."""
        got = vs.page_status(roster(10, missing=(1,)), 10)
        self.assertEqual(got["status"], "leaf_missing")
        self.assertTrue(got["leaf_missing"])

    def test_a_partly_read_page_with_a_leaf_missing_is_in_progress_and_flagged(self):
        got = vs.page_status(roster(10, missing=(1,)), 4)
        self.assertEqual(got["status"], "in_progress")
        self.assertTrue(got["leaf_missing"])

    def test_a_page_that_is_not_a_roster(self):
        got = vs.page_status({"status": "not_roster", "reason": "index"}, 0)
        self.assertEqual(got["status"], "not_roster")
        self.assertEqual(got["reason"], "index")

    def test_needs_review_travels_through(self):
        self.assertTrue(vs.page_status(roster(review=True), 0)["needs_review"])


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        previous = os.environ.get("JP_OCR_DATA")
        os.environ["JP_OCR_DATA"] = self.tmp.name

        def restore():
            if previous is None:
                os.environ.pop("JP_OCR_DATA", None)
            else:
                os.environ["JP_OCR_DATA"] = previous
            self.tmp.cleanup()
        self.addCleanup(restore)

    def test_entries_round_trip_and_accumulate(self):
        vs.record_survey("p", 12, roster(18))
        vs.record_survey("p", 3, {"status": "not_roster", "reason": "front matter"})
        got = vs.load_survey("p")
        self.assertEqual(sorted(got), [3, 12])
        self.assertEqual(got[12]["officers"], 18)

    def test_a_damaged_sidecar_reads_as_empty_rather_than_failing(self):
        path = vs.survey_path("p")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(vs.load_survey("p"), {})

    def test_a_swap_refused_while_another_handle_holds_the_file_is_retried(self):
        real = Path.replace
        calls = {"n": 0}

        def refused_twice(self, target):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "Access is denied")
            return real(self, target)

        with mock.patch.object(vs, "REPLACE_DELAY_S", 0), \
                mock.patch.object(Path, "replace", autospec=True, side_effect=refused_twice):
            vs.record_survey("p", 7, roster(5))
        self.assertEqual(vs.load_survey("p")[7]["officers"], 5)
        self.assertEqual(calls["n"], 3)

    def test_a_read_that_keeps_failing_stops_the_write_rather_than_empty_the_survey(self):
        vs.record_survey("p", 1, roster(3))
        vs.record_survey("p", 2, roster(4))
        with mock.patch.object(vs, "REPLACE_DELAY_S", 0), \
                mock.patch.object(Path, "read_text", side_effect=PermissionError(5, "Access is denied")):
            with self.assertRaises(PermissionError):
                vs.record_survey("p", 3, roster(5))
        self.assertEqual(sorted(vs.load_survey("p")), [1, 2])

    def test_a_corrupt_sidecar_is_set_aside_not_silently_overwritten(self):
        path = vs.survey_path("p")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        vs.record_survey("p", 9, roster(2))
        self.assertEqual(sorted(vs.load_survey("p")), [9])
        self.assertTrue(list(path.parent.glob("survey.json.corrupt-*")))

    def test_cached_frames_lists_only_real_page_images(self):
        folder = Path(self.tmp.name) / "cache" / "p"
        folder.mkdir(parents=True)
        (folder / "frame_0060.jpg").write_bytes(b"x")
        (folder / "frame_0061.jpg").write_bytes(b"")          # interrupted download
        (folder / "frame_0062.part").write_bytes(b"x")
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertEqual(vs.cached_frames("p"), {60})


if __name__ == "__main__":
    unittest.main()
