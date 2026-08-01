"""Tests for Layer 2 template registration.

Synthetic ruled tables only - no page scans. Source images are not committed
(data policy), so the suite must run in CI on a clean checkout. The real 1933
pages are exercised by hand when a template artifact is derived; what is pinned
here is the machinery: which rulings count as table, how missing ones are filled,
how a page is accepted or rejected, and that a cell rectangle lands where it
should in original-scan coordinates.
"""

import unittest

import numpy as np

import registration as R

PANEL_W, PANEL_H = 800, 1000
TABLE_TOP, TABLE_BOT = 50, 950
BAND_FRACS = (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0)
COL_X0, COL_PITCH, COL_N = 100, 80, 9  # 9 rulings -> 8 officer columns


def band_ys() -> list[int]:
    height = TABLE_BOT - TABLE_TOP
    return [int(TABLE_TOP + f * height) for f in BAND_FRACS]


def column_xs() -> list[int]:
    return [COL_X0 + i * COL_PITCH for i in range(COL_N)]


def make_panel(*, drop_columns=(), borders=False) -> np.ndarray:
    """A white panel ruled like a roster table.

    `drop_columns` omits vertical rulings by index (simulating the thin interior
    rulings that alias away on degraded scans); `borders` adds page-edge rulings
    of the kind that must be excluded from the table.
    """
    img = np.full((PANEL_H, PANEL_W), 255, np.uint8)
    for y in band_ys():
        img[y - 1:y + 2, :] = 0
    for i, x in enumerate(column_xs()):
        if i in drop_columns:
            continue
        img[TABLE_TOP:TABLE_BOT, x - 1:x + 2] = 0
    if borders:
        img[:, 2:5] = 0
        img[:, PANEL_W - 6:PANEL_W - 3] = 0
    return img


def make_template(**overrides) -> R.Template:
    d = {
        "template_id": "test-A",
        "layout_family": "test",
        "band_fracs": list(BAND_FRACS),
        "match": {"tolerance_frac": 0.015, "min_bands_matched": 6,
                  "min_explained_frac": 0.8, "min_columns": 2},
        "columns": {"expected": 8},
        "fields": [
            {"name": "first", "band": [0, 1]},
            {"name": "middle", "band": [2, 4]},
            {"name": "last", "band": [5, 6]},
        ],
    }
    d.update(overrides)
    return R.Template.from_dict(d)


class DetectGridTests(unittest.TestCase):
    def test_finds_every_band_and_officer_column(self):
        grid = R.detect_grid(make_panel(), R.Panel(0, 0, PANEL_W, PANEL_H))
        self.assertIsNotNone(grid)
        self.assertEqual(len(grid.band_ys), len(BAND_FRACS))
        self.assertEqual(grid.n_officer_columns, COL_N - 1)
        for got, want in zip(grid.band_fracs, BAND_FRACS):
            self.assertAlmostEqual(got, want, delta=0.01)

    def test_page_border_rulings_are_not_table_columns(self):
        """Borders at the panel edge must not become officer columns.

        Regression: taking the table's x-extent from the outermost vertical
        lines made the outer margin - section header and page number - look like
        officer column 0, so every field crop was one column off the table.
        """
        grid = R.detect_grid(make_panel(borders=True),
                             R.Panel(0, 0, PANEL_W, PANEL_H))
        self.assertEqual(grid.table[0], COL_X0)
        self.assertEqual(grid.table[2], COL_X0 + (COL_N - 1) * COL_PITCH)
        self.assertEqual(grid.n_officer_columns, COL_N - 1)

    def test_missing_ruling_is_interpolated_and_reported(self):
        """A dropped ruling must not merge two officers into one crop."""
        grid = R.detect_grid(make_panel(drop_columns=(3,)),
                             R.Panel(0, 0, PANEL_W, PANEL_H))
        self.assertEqual(grid.n_officer_columns, COL_N - 1)
        self.assertEqual(len(grid.interpolated_columns), 1)
        self.assertAlmostEqual(grid.interpolated_columns[0],
                               COL_X0 + 3 * COL_PITCH, delta=3)

    def test_blank_panel_yields_no_grid(self):
        blank = np.full((PANEL_H, PANEL_W), 255, np.uint8)
        self.assertIsNone(R.detect_grid(blank, R.Panel(0, 0, PANEL_W, PANEL_H)))


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.grid = R.detect_grid(make_panel(), R.Panel(0, 0, PANEL_W, PANEL_H))
        self.template = make_template()

    def test_matches_its_own_layout_cleanly(self):
        reg = R.register(self.grid, self.template)
        self.assertEqual(reg.matched, len(BAND_FRACS))
        self.assertTrue(reg.is_clean)
        self.assertEqual(reg.explained_frac, 1.0)
        self.assertLess(reg.mean_residual_frac, 0.01)

    def test_absent_band_is_flagged_not_invented(self):
        """An unmatched band falls back to nominal and says so."""
        extra = list(BAND_FRACS) + [0.62]  # no ruling at 0.62 on this panel
        reg = R.register(self.grid, make_template(band_fracs=extra))
        self.assertIn(len(extra) - 1, reg.unmatched_bands)
        self.assertFalse(reg.is_clean)

    def test_extra_structure_lowers_explained_fraction(self):
        """The reverse check: page structure the template cannot account for."""
        sparse = [0.0, 0.5, 1.0]
        reg = R.register(self.grid, make_template(band_fracs=sparse))
        self.assertEqual(reg.matched, 3)
        self.assertLess(reg.explained_frac, 0.8)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.grid = R.detect_grid(make_panel(), R.Panel(0, 0, PANEL_W, PANEL_H))

    def test_accepts_the_matching_template(self):
        reg = R.classify(self.grid, [make_template()])
        self.assertIsNotNone(reg)
        self.assertEqual(reg.template_id, "test-A")

    def test_rejects_a_different_layout(self):
        other = make_template(template_id="other",
                              band_fracs=[0.0, 0.27, 0.43, 0.61, 0.88, 1.0])
        self.assertIsNone(R.classify(self.grid, [other]))

    def test_rejects_page_whose_structure_is_mostly_unexplained(self):
        """Guards the false positive found on a real degraded panel.

        Frame 700 panel 1 of the 1933 volume carried 28 rulings; with that many,
        one lands near every template band by chance and the forward match was a
        perfect 12/12 on a page with a single officer column.
        """
        sparse = make_template(template_id="sparse",
                               band_fracs=[0.0, 0.5, 1.0],
                               match={"tolerance_frac": 0.015,
                                      "min_bands_matched": 3,
                                      "min_explained_frac": 0.8,
                                      "min_columns": 2})
        self.assertIsNone(R.classify(self.grid, [sparse]))

    def test_rejects_page_with_too_few_columns(self):
        strict = make_template(template_id="strict",
                               match={"tolerance_frac": 0.015,
                                      "min_bands_matched": 6,
                                      "min_explained_frac": 0.8,
                                      "min_columns": 99})
        self.assertIsNone(R.classify(self.grid, [strict]))


class CellGeometryTests(unittest.TestCase):
    def setUp(self):
        self.template = make_template()
        self.grid = R.detect_grid(make_panel(), R.Panel(0, 0, PANEL_W, PANEL_H))
        self.reg = R.register(self.grid, self.template)

    def test_cell_lands_on_the_expected_rectangle(self):
        x, y, w, h = R.cell_bbox(self.reg, self.template, "middle", 0, scale=1.0)
        ys = band_ys()
        self.assertAlmostEqual(y, ys[2], delta=3)
        self.assertAlmostEqual(y + h, ys[4], delta=3)
        # column 0 is the rightmost officer
        self.assertAlmostEqual(x + w, COL_X0 + (COL_N - 1) * COL_PITCH, delta=3)
        self.assertAlmostEqual(w, COL_PITCH, delta=3)

    def test_columns_run_right_to_left(self):
        first = R.cell_bbox(self.reg, self.template, "middle", 0, scale=1.0)
        second = R.cell_bbox(self.reg, self.template, "middle", 1, scale=1.0)
        self.assertGreater(first[0], second[0])

    def test_panel_offset_and_scale_round_trip(self):
        """Cells must come back in original-scan pixels, not panel pixels."""
        offset = R.Panel(300, 120, PANEL_W, PANEL_H)
        grid = R.detect_grid(make_panel(), offset)
        reg = R.register(grid, self.template)
        x, y, _, _ = R.cell_bbox(reg, self.template, "middle", 0, scale=0.5)
        base_x, base_y, _, _ = R.cell_bbox(self.reg, self.template, "middle", 0,
                                           scale=1.0)
        self.assertAlmostEqual(x, (base_x + 300) / 0.5, delta=4)
        self.assertAlmostEqual(y, (base_y + 120) / 0.5, delta=4)

    def test_officer_strip_spans_the_whole_record(self):
        strip = R.column_bbox(self.reg, 0, scale=1.0)
        cell = R.cell_bbox(self.reg, self.template, "middle", 0, scale=1.0)
        self.assertLessEqual(strip[1], cell[1])
        self.assertGreaterEqual(strip[1] + strip[3], cell[1] + cell[3])
        self.assertAlmostEqual(strip[3], TABLE_BOT - TABLE_TOP, delta=6)

    def test_unknown_field_is_an_error(self):
        with self.assertRaises(KeyError):
            R.cell_bbox(self.reg, self.template, "nope", 0)

    def test_column_out_of_range_is_an_error(self):
        with self.assertRaises(IndexError):
            R.cell_bbox(self.reg, self.template, "middle", 999)

    def test_cells_flags_interpolated_columns_as_suspect(self):
        grid = R.detect_grid(make_panel(drop_columns=(3,)),
                             R.Panel(0, 0, PANEL_W, PANEL_H))
        reg = R.register(grid, self.template)
        suspect_cols = {c for c, _, _, s in R.cells(reg, self.template, scale=1.0) if s}
        # the interpolated ruling bounds the two officers either side of it
        self.assertEqual(len(suspect_cols), 2)

    def test_cells_covers_every_column_and_field(self):
        produced = list(R.cells(self.reg, self.template, scale=1.0))
        self.assertEqual(len(produced),
                         self.grid.n_officer_columns * len(self.template.fields))


class ShippedTemplateTests(unittest.TestCase):
    """The committed artifact must stay loadable and self-consistent."""

    def setUp(self):
        from pathlib import Path
        self.dir = Path(__file__).resolve().parent.parent / "templates"

    def test_library_loads(self):
        lib = R.load_library(self.dir)
        self.assertTrue(lib, "no template artifacts found")

    def test_field_bands_are_in_range_and_ordered(self):
        for t in R.load_library(self.dir):
            n = len(t.band_fracs)
            self.assertEqual(sorted(t.band_fracs), list(t.band_fracs))
            for name, a, b in t.fields:
                self.assertLess(a, b, f"{t.template_id}:{name} bands reversed")
                self.assertLess(b, n, f"{t.template_id}:{name} band out of range")

    def test_thresholds_are_satisfiable(self):
        for t in R.load_library(self.dir):
            self.assertLessEqual(t.min_bands_matched, len(t.band_fracs))
            self.assertGreaterEqual(t.min_columns, 2)

    def test_every_field_declares_its_provenance(self):
        """A field name is a reading decision, so it must say who backs it.

        `confirmed` records that a human settled the label; `evidence` records
        whether it rests on something printed in the source ("documentary") or
        on inference a later reader may want to retest ("inferred"). Losing that
        distinction would let a guess harden into an apparent fact.
        """
        import json
        from pathlib import Path
        for path in Path(self.dir).glob("*.json"):
            spec = json.loads(path.read_text(encoding="utf-8"))
            for field in spec.get("fields", []):
                where = f"{path.name}:{field['name']}"
                self.assertIn("confirmed", field, where)
                self.assertTrue(field.get("note"), f"{where} has no note")
                if field["confirmed"]:
                    self.assertIn(field.get("evidence"), ("documentary", "inferred"),
                                  f"{where} is confirmed but declares no evidence basis")


if __name__ == "__main__":
    unittest.main()
