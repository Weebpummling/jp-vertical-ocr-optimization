"""Tests for zoomed re-reading: engine discovery, crops, interpretation,
comparison, the job plan, the cache, and the worker plumbing.

NDLOCR-Lite itself never runs here. A stand-in worker speaks the same protocol,
so the suite runs in CI on a machine that has never seen the engine.
"""

import os
import sys
import tempfile
import textwrap
import unicodedata
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

import cell_ocr as C  # first: it puts reading/ on the path for the imports below
import binning
from ndl_lines import BoxedLine
from test_proposal_service import spread


def ndl(fill, value=None, method="ndl-ocr", wholesale=True):
    return {"fill": fill, "value": value, "method": method, "wholesale": wholesale}


class TempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class EngineDiscoveryTests(TempDir):
    def test_a_desktop_app_folder_with_no_command_line_is_refused(self):
        (self.tmp / "NDLOCR-Lite.exe").write_bytes(b"x")
        engine, reason = C.find_engine(self.tmp)
        self.assertIsNone(engine)
        self.assertIn("command-line", reason)

    def test_source_without_its_own_interpreter_is_refused_not_given_bare_python(self):
        src = self.tmp / "cli" / "src"
        src.mkdir(parents=True)
        (src / "ocr.py").write_text("", encoding="utf-8")
        engine, reason = C.find_engine(self.tmp)
        self.assertIsNone(engine)
        self.assertIn("Store", reason)

    def test_a_checkout_with_its_own_venv_is_found(self):
        src = self.tmp / "cli" / "src"
        src.mkdir(parents=True)
        (src / "ocr.py").write_text("", encoding="utf-8")
        python = self.tmp / "venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        engine, reason = C.find_engine(self.tmp)
        self.assertIsNone(reason)
        self.assertEqual((engine.src, engine.python), (src, python))


class InterpretTests(unittest.TestCase):
    DATE = (0, 0, 100, 300)

    def test_date_segments_are_reassembled_and_read(self):
        p = C.interpret("commissioning_date", self.DATE, False,
                        [BoxedLine("明四三", 40, 10, 70, 60),
                         BoxedLine("一二、二六", 30, 70, 60, 150)])
        self.assertEqual(p.value, "1910-12-26")

    def test_arabic_digits_in_a_kanji_numeral_column_are_not_trusted(self):
        for text in ("198", "10.11", "R.", "****", "0.0"):
            with self.subTest(text=text):
                p = C.interpret("rank_date", self.DATE, False, [BoxedLine(text, 40, 10, 70, 60)])
                self.assertEqual(p.method, "refused")
                self.assertIsNone(p.value)
                self.assertFalse(C.props.takes_wholesale(p))

    def test_a_doubled_ditto_is_still_a_ditto(self):
        p = C.interpret("rank_date", self.DATE, False, [BoxedLine("同同", 40, 10, 70, 60)])
        self.assertEqual(C.props.fill_for(p), "同")

    def test_seniority_reads_as_digits(self):
        p = C.interpret("seniority_no", (0, 0, 100, 100), False,
                        [BoxedLine("931", 20, 20, 60, 80)])
        self.assertEqual(p.value, "931")

    def test_a_name_reading_with_gaps_is_not_offered(self):
        p = C.interpret("name_raw", (0, 0, 100, 220), False,
                        [BoxedLine("靑 山 治", 50, 10, 95, 200)])
        self.assertEqual(p.method, "refused")
        self.assertEqual(C.compare(ndl("靑山三治"), p), "unreadable")

    def test_spaced_furigana_and_birth_dates_do_not_count_as_gaps(self):
        p = C.interpret("name_raw", (0, 0, 100, 220), False,
                        [BoxedLine("上住良吉", 50, 10, 95, 200),
                         BoxedLine("ウヘ ズミ", 40, 12, 52, 90),
                         BoxedLine("明二三、 五、二一", 8, 20, 30, 200)])
        self.assertEqual(p.value, "上住良吉")

    def test_furigana_is_kept_out_of_a_name(self):
        p = C.interpret("name_raw", (0, 0, 100, 220), False,
                        [BoxedLine("上住良吉", 50, 10, 95, 200),
                         BoxedLine("ウヘズミ", 40, 12, 52, 90)])
        self.assertEqual(p.value, "上住良吉")


class CompareTests(unittest.TestCase):
    def test_the_same_reading_agrees(self):
        p = C.interpret("seniority_no", (0, 0, 100, 100), False, [BoxedLine("931", 20, 20, 60, 80)])
        self.assertEqual(C.compare(ndl("931", "931", "digits"), p), "agrees")

    def test_a_different_settled_reading_is_offered_as_an_alternative(self):
        p = C.interpret("seniority_no", (0, 0, 100, 100), False, [BoxedLine("916", 20, 20, 60, 80)])
        self.assertEqual(C.compare(ndl("931", "931", "digits"), p), "alternative")

    def test_an_unreadable_rereading_offers_nothing(self):
        p = C.interpret("rank_date", (0, 0, 100, 300), False, [BoxedLine("198", 40, 10, 70, 60)])
        self.assertEqual(C.compare(ndl("同", None, "inherited"), p), "unreadable")

    def test_a_rereading_that_settles_what_ndl_could_not_is_an_alternative(self):
        p = C.interpret("commissioning_date", (0, 0, 100, 300), False,
                        [BoxedLine("明四三", 40, 10, 70, 60), BoxedLine("一二、二六", 30, 70, 60, 150)])
        self.assertEqual(C.compare(ndl("明四三、「二、二六", None, "refused", False), p),
                         "alternative")

    def test_the_same_date_is_agreement_whatever_the_separators(self):
        p = C.interpret("commissioning_date", (0, 0, 100, 300), False,
                        [BoxedLine("明四三", 40, 10, 70, 60), BoxedLine("一二、二六", 30, 70, 60, 150)])
        self.assertEqual(C.compare(ndl("明四三一二、二六", "1910-12-26", "eradate"), p), "agrees")

    def test_whitespace_and_full_width_digits_are_not_differences(self):
        p = C.interpret("seniority_no", (0, 0, 100, 100), False, [BoxedLine("931", 20, 20, 60, 80)])
        self.assertEqual(C.compare(ndl("９ ３１"), p), "agrees")

    def test_a_modern_form_of_the_printed_kyujitai_is_agreement_and_says_so(self):
        """NDLOCR-Lite writes 歩 where the page prints 步; that is not a second reading."""
        p = C.interpret("post", (0, 0, 100, 400), False, [BoxedLine("歩兵第九聯隊附", 40, 10, 80, 380)])
        with mock.patch.object(C, "_variant_fold", return_value={"步": "歩"}):
            self.assertEqual(C.compare(ndl("步兵第九聯隊附"), p), "agrees")
            self.assertTrue(C.variant_only(ndl("步兵第九聯隊附"), p))

    def test_a_different_character_is_still_an_alternative(self):
        p = C.interpret("post", (0, 0, 100, 400), False, [BoxedLine("騎兵第九聯隊附", 40, 10, 80, 380)])
        with mock.patch.object(C, "_variant_fold", return_value={"步": "歩"}):
            self.assertEqual(C.compare(ndl("步兵第九聯隊附"), p), "alternative")

    def test_compatibility_forms_are_not_differences(self):
        compat = "\uf92c"
        unified = unicodedata.normalize("NFKC", compat)
        self.assertNotEqual(compat, unified)
        p = C.interpret("post", (0, 0, 100, 400), False, [BoxedLine(compat, 40, 10, 80, 380)])
        self.assertEqual(C.compare(ndl(unified), p), "agrees")


class PlanTests(unittest.TestCase):
    def test_the_officer_in_hand_comes_first_then_the_rest_wrapping_round(self):
        order = []
        for officer, _field in C.plan(spread((2, 1)), 1):
            if not order or order[-1] != officer.index:
                order.append(officer.index)
        self.assertEqual(order, [1, 2, 0])

    def test_fields_that_reread_reliably_come_before_dates(self):
        fields = [f for _o, f in C.plan(spread((1,)), 0)]
        self.assertEqual(fields, ["seniority_no", "name_raw", "post", "commissioning_date"])

    def test_date_columns_crop_ndl_line_segments_and_other_fields_the_cell(self):
        cell = binning.cell_from_lines(0, "commissioning_date", (0, 0, 100, 300),
                                       [BoxedLine("明四三", 40, 10, 70, 60),
                                        BoxedLine("一二、二六", 30, 70, 60, 150)])
        crops = C.crops_for("commissioning_date", (0, 0, 100, 300), cell)
        self.assertEqual(len(crops), 2)
        self.assertTrue(all(margin == C.SEGMENT_MARGIN for _box, margin in crops))
        self.assertEqual(C.crops_for("name_raw", (0, 0, 100, 300), cell), [((0, 0, 100, 300), 0)])
        self.assertEqual(C.crops_for("rank_date", (0, 0, 100, 300), None), [((0, 0, 100, 300), 0)])


class CropTests(unittest.TestCase):
    def test_worker_boxes_map_back_to_scan_pixels(self):
        image = np.full((1000, 800, 3), 255, np.uint8)
        crop, origin = C.crop_image(image, (300, 400, 100, 200))
        self.assertEqual(crop.shape[:2], (200 + 2 * C.BORDER, 100 + 2 * C.BORDER))
        b = C.BORDER
        line = C.to_scan([{"text": "931", "box": [b + 10, b + 20, b + 50, b + 80]}], origin)[0]
        self.assertEqual((line.xmin, line.ymin, line.xmax, line.ymax), (310, 420, 350, 480))

    def test_a_crop_keeps_the_print_as_it_is(self):
        """Ruling erasure was measured and dropped; nothing is painted out."""
        image = np.full((200, 200, 3), 255, np.uint8)
        image[50:53, 20:180] = 0
        crop, _ = C.crop_image(image, (20, 45, 160, 12))
        self.assertTrue((crop == 0).any())

    def test_a_crop_at_the_page_edge_is_clipped_not_wrapped(self):
        image = np.full((100, 100, 3), 255, np.uint8)
        _crop, origin = C.crop_image(image, (-5, -5, 20, 20), 6)
        self.assertEqual(origin, (0, 0))


class CacheTests(TempDir):
    def setUp(self):
        super().setUp()
        previous = os.environ.get("JP_OCR_DATA")
        os.environ["JP_OCR_DATA"] = str(self.tmp)
        self.addCleanup(lambda: os.environ.__setitem__("JP_OCR_DATA", previous)
                        if previous is not None else os.environ.pop("JP_OCR_DATA", None))

    def test_readings_round_trip_and_a_changed_cell_or_release_invalidates_them(self):
        record = {"index": 0, "field": "seniority_no", "bbox": [1, 2, 3, 4],
                  "recipe": C.RECIPE, "engine_version": "1.3.1", "status": "agrees"}
        C.store_result("p", 5, record)
        self.assertIn("0:seniority_no", C.load_results("p", 5))
        self.assertTrue(C.still_valid(record, (1, 2, 3, 4), "1.3.1"))
        self.assertFalse(C.still_valid(record, (1, 2, 3, 5), "1.3.1"))
        self.assertFalse(C.still_valid(record, (1, 2, 3, 4), "1.2.3"))

    def test_a_read_refused_by_another_handle_never_empties_the_stored_page(self):
        """The job failure of 10 Sep 2026, and the data loss it was one read from."""
        def record(n):
            return {"index": n, "field": "seniority_no", "bbox": [0, 0, 1, 1],
                    "recipe": C.RECIPE, "engine_version": "v", "status": "agrees"}
        for n in range(3):
            C.store_result("p", 5, record(n))
        real = Path.read_text
        calls = {"n": 0}

        def refused_once(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(5, "Access is denied")
            return real(self, *args, **kwargs)

        with mock.patch.object(C.vs, "REPLACE_DELAY_S", 0), \
                mock.patch.object(Path, "read_text", autospec=True, side_effect=refused_once):
            C.store_result("p", 5, record(3))
        self.assertEqual(len(C.load_results("p", 5)), 4)


FAKE_WORKER = textwrap.dedent('''
    import json, os, sys
    mode = os.environ.get("FAKE_NDLOCR", "ok")
    if mode == "broken":
        print(json.dumps({"ready": False, "error": "no models here"}), flush=True)
        sys.exit(2)
    print("engine chatter before the models load", flush=True)
    print(json.dumps({"ready": True, "version": "fake-1"}), flush=True)
    for n, line in enumerate(sys.stdin):
        request = json.loads(line)
        if mode == "die":
            sys.exit(3)
        print(json.dumps({"id": request["id"], "ok": True, "seconds": 0.01,
                          "lines": [{"text": os.path.basename(request["image"]),
                                     "confidence": 0.9, "box": [1, 2, 3, 4]}]}), flush=True)
''')


class WorkerTests(TempDir):
    def setUp(self):
        super().setUp()
        self.script = self.tmp / "fake_worker.py"
        self.script.write_text(FAKE_WORKER, encoding="utf-8")
        self.engine = C.Engine(home=self.tmp, python=Path(sys.executable), src=self.tmp)
        previous = os.environ.get("FAKE_NDLOCR")
        self.addCleanup(lambda: os.environ.__setitem__("FAKE_NDLOCR", previous)
                        if previous is not None else os.environ.pop("FAKE_NDLOCR", None))

    def worker(self, mode="ok"):
        os.environ["FAKE_NDLOCR"] = mode
        w = C.Worker(self.engine, script=self.script, start_timeout=30, read_timeout=30)
        self.addCleanup(w.close)
        return w

    def test_each_request_gets_its_own_reply_past_the_engine_chatter(self):
        w = self.worker()
        reply = w.read(self.tmp / "a.png")
        self.assertEqual(reply["lines"][0]["text"], "a.png")
        self.assertEqual(w.version, "fake-1")

    def test_the_models_load_once_for_many_cells(self):
        w = self.worker()
        w.read(self.tmp / "a.png")
        pid = w._proc.pid
        w.read(self.tmp / "b.png")
        self.assertEqual(w._proc.pid, pid)

    def test_a_worker_that_dies_is_reported_and_then_restarted(self):
        w = self.worker("die")
        with self.assertRaises(C.WorkerError):
            w.read(self.tmp / "a.png")
        os.environ["FAKE_NDLOCR"] = "ok"
        self.assertEqual(w.read(self.tmp / "b.png")["lines"][0]["text"], "b.png")

    def test_an_engine_that_cannot_load_says_why(self):
        w = self.worker("broken")
        with self.assertRaises(C.WorkerError) as caught:
            w.read(self.tmp / "a.png")
        self.assertIn("no models here", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
