"""Tests for the workstation's page service.

Synthetic spreads, so the suite runs in CI without page scans. One integration
test uses a real cached page and skips when the cache is absent - it is a local
check, never a CI gate (data policy: no scans in the repository).
"""

import os
import unittest
from pathlib import Path

import numpy as np

import page_service as PS
import registration as R

# A synthetic two-page spread: bright throughout with a dark gutter down the
# middle, which is how find_panels locates the right-hand page.
W, H = 1600, 1200
GUTTER = (780, 820)
TABLE_X0, TABLE_X1, PITCH = 900, 1500, 100      # 7 rulings -> 6 officers
TABLE_Y0, TABLE_Y1 = 100, 1100
BANDS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)


def make_spread(*, drop_column: int | None = None) -> np.ndarray:
    img = np.full((H, W), 255, np.uint8)
    img[:, GUTTER[0]:GUTTER[1]] = 30
    height = TABLE_Y1 - TABLE_Y0
    for f in BANDS:
        y = int(TABLE_Y0 + f * height)
        img[y - 2:y + 3, TABLE_X0:TABLE_X1 + 1] = 0
    for i, x in enumerate(range(TABLE_X0, TABLE_X1 + 1, PITCH)):
        if i == drop_column:
            continue
        img[TABLE_Y0:TABLE_Y1, x - 2:x + 3] = 0
    return img


def make_template() -> R.Template:
    return R.Template.from_dict({
        "template_id": "synthetic-A",
        "layout_family": "synthetic",
        "band_fracs": list(BANDS),
        "match": {"tolerance_frac": 0.02, "min_bands_matched": 5,
                  "min_explained_frac": 0.8, "min_columns": 2},
        "fields": [
            {"name": "alpha", "band": [1, 2]},
            {"name": "beta", "band": [2, 4]},
        ],
    })


class RegisterImageTests(unittest.TestCase):
    def setUp(self):
        self.templates = [make_template()]

    def register(self, image=None, **kw):
        return PS.register_image(image if image is not None else make_spread(),
                                 "test-pid", 42, templates=self.templates, **kw)

    def test_places_every_officer_and_field(self):
        page = self.register()
        self.assertEqual(page.template_id, "synthetic-A")
        self.assertEqual(len(page.officers), 6)
        for officer in page.officers:
            self.assertEqual([c.field for c in officer.cells], ["alpha", "beta"])

    def test_officers_are_indexed_right_to_left(self):
        page = self.register()
        xs = [o.bbox[0] for o in page.officers]
        self.assertEqual(xs, sorted(xs, reverse=True),
                         "officer 0 must be the rightmost strip")

    def test_cells_sit_inside_their_officer_strip(self):
        page = self.register()
        for officer in page.officers:
            ox, oy, ow, oh = officer.bbox
            for cell in officer.cells:
                cx, cy, cw, ch = cell.bbox
                self.assertGreaterEqual(cx, ox - 2)
                self.assertLessEqual(cx + cw, ox + ow + 2)
                self.assertGreaterEqual(cy, oy - 2)
                self.assertLessEqual(cy + ch, oy + oh + 2)

    def test_unregistrable_page_is_refused_not_guessed(self):
        blank = np.full((H, W), 255, np.uint8)
        blank[:, GUTTER[0]:GUTTER[1]] = 30
        with self.assertRaises(PS.PageNotRegistrable):
            self.register(blank)

    def test_missing_panel_is_refused(self):
        with self.assertRaises(PS.PageNotRegistrable):
            self.register(panel=7)

    def test_inferred_edges_mark_cells_suspect(self):
        clean = self.register()
        self.assertFalse(clean.needs_review)
        patched = self.register(make_spread(drop_column=3))
        self.assertTrue(patched.needs_review,
                        "an interpolated ruling must surface as needs_review")

    def test_crop_urls_are_built_only_when_asked(self):
        page = self.register()
        self.assertIsNone(page.officers[0].crop_url)
        self.assertIsNone(page.officers[0].cells[0].crop_url)

        calls = []

        def url_for(pid, frame, bbox):
            calls.append((pid, frame, bbox))
            return f"https://example/{pid}/{frame}/{bbox[0]},{bbox[1]}"

        page = self.register(url_for=url_for)
        self.assertTrue(page.officers[0].crop_url.startswith("https://example/"))
        self.assertTrue(all(c.crop_url for o in page.officers for c in o.cells))
        self.assertEqual(len(calls), 6 + 6 * 2)  # one per strip, one per cell

    def test_payload_is_json_serialisable(self):
        import json
        payload = self.register().as_dict()
        json.loads(json.dumps(payload))
        self.assertEqual(payload["officer_count"], 6)
        self.assertIn("needs_review", payload)


class ShippedTemplateLabellingTests(unittest.TestCase):
    def test_label_confirmation_is_read_from_the_artifacts(self):
        """The UI must be able to tell a settled label from a provisional one."""
        templates = R.load_library(PS.TEMPLATE_DIR)
        table = PS._label_confirmation(templates)
        self.assertIn("showa-teinen-meibo-A", table)
        self.assertTrue(table["showa-teinen-meibo-A"]["seniority_no"])


class VocabularyTests(unittest.TestCase):
    """The entry form's autocomplete is only as good as this shaping."""

    def setUp(self):
        self.vocab = PS.vocabularies()

    def test_frozen_counts(self):
        # Frozen 31 Jul 2026: 11 ranks / 14 branches / 28 variants.
        self.assertEqual(len(self.vocab["ranks"]), 11)
        self.assertEqual(len(self.vocab["branches"]), 14)
        self.assertEqual(len(self.vocab["kanji_variants"]), 28)

    def test_ranks_come_back_in_service_order(self):
        """Not alphabetical: a rank list an officer would recognise."""
        labels = [r["ja"] for r in self.vocab["ranks"]]
        self.assertEqual(labels[0], "准尉")
        self.assertEqual(labels[-1], "元帥")
        orders = [r["order"] for r in self.vocab["ranks"] if r["order"] is not None]
        self.assertEqual(orders, sorted(orders))

    def test_multiple_printed_forms_split_apart(self):
        """The CSVs separate variants with ';'.

        Regression: treating the field as a single token made 野戦砲兵 carry the
        literal variant "野戦砲;野砲兵", so neither printed form would ever match
        and an annotator typing what is on the page would be told it is not in
        the vocabulary.
        """
        by_label = {b["ja"]: b for b in self.vocab["branches"]}
        self.assertEqual(by_label["野戦砲兵"]["variants"], ["野戦砲", "野砲兵"])
        self.assertEqual(by_label["歩兵"]["variants"], ["步兵"])
        for entry in self.vocab["branches"] + self.vocab["ranks"]:
            for variant in entry["variants"]:
                self.assertNotIn(";", variant)
                self.assertTrue(variant.strip())


class RealPageIntegrationTests(unittest.TestCase):
    """Local-only: exercises the shipped template against an actual scan."""

    def setUp(self):
        home = os.environ.get("JP_OCR_DATA")
        if not home:
            self.skipTest("JP_OCR_DATA not set")
        self.page = Path(home) / "cache" / "1449426" / "frame_0100.jpg"
        if not self.page.exists():
            self.skipTest(f"page not cached: {self.page}")

    def test_registers_a_known_roster_page(self):
        page = PS.register_file(self.page, "1449426", 100)
        self.assertEqual(page.template_id, "showa-teinen-meibo-A")
        self.assertEqual(len(page.officers), 10)
        fields = {c.field for c in page.officers[0].cells}
        self.assertIn("seniority_no", fields)
        self.assertIn("name_raw", fields)

    def test_refuses_the_index_page(self):
        index = self.page.with_name("frame_0850.jpg")
        if not index.exists():
            self.skipTest("index page not cached")
        with self.assertRaises(PS.PageNotRegistrable):
            PS.register_file(index, "1449426", 850)


if __name__ == "__main__":
    unittest.main()
