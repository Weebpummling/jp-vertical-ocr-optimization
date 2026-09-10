import json
import unittest

from ndl_lines import BoxedLine, NoCoordinateData, frame, frame_lines, frames


def entry(lines):
    return {"coordjson": json.dumps(
        [{"contenttext": t, "xmin": a, "ymin": b, "xmax": c, "ymax": d}
         for t, a, b, c, d in lines])}


class BoxTests(unittest.TestCase):
    def test_thickness_is_the_short_side_either_orientation(self):
        self.assertEqual(BoxedLine("x", 0, 0, 10, 100).thickness, 10)
        self.assertEqual(BoxedLine("x", 0, 0, 100, 10).thickness, 10)

    def test_overlap_is_the_fraction_of_the_line_inside_the_cell(self):
        line = BoxedLine("x", 0, 0, 10, 10)
        self.assertEqual(line.overlap((0, 0, 10, 10)), 1.0)
        self.assertEqual(line.overlap((5, 0, 100, 10)), 0.5)
        self.assertEqual(line.overlap((50, 50, 10, 10)), 0.0)

    def test_a_cell_far_larger_than_the_line_still_scores_one(self):
        """Overlap is asymmetric on purpose - IoU would score this a near-miss."""
        line = BoxedLine("x", 100, 100, 110, 200)
        self.assertEqual(line.overlap((0, 0, 1000, 1000)), 1.0)


class FrameTests(unittest.TestCase):
    def test_blank_leaf_is_an_empty_list_not_an_error(self):
        self.assertEqual(frame_lines({"coordjson": "[]"}), [])

    def test_missing_coordinate_data_raises(self):
        """A frame NDL never read is a different finding from a blank page."""
        for value in (None, "null", ""):
            with self.assertRaises(NoCoordinateData):
                frame_lines({"coordjson": value, "id": "f1"})

    def test_exact_duplicates_are_dropped(self):
        """NDL repeats some entries verbatim; concatenating them doubles text."""
        got = frame_lines(entry([("平", 0, 0, 10, 10), ("平", 0, 0, 10, 10)]))
        self.assertEqual([l.text for l in got], ["平"])

    def test_a_real_repeat_at_a_different_box_survives(self):
        got = frame_lines(entry([("同", 0, 0, 10, 10), ("同", 0, 20, 10, 30)]))
        self.assertEqual(len(got), 2)

    def test_a_line_without_usable_coordinates_is_skipped_not_fatal(self):
        raw = {"coordjson": json.dumps([
            {"contenttext": "good", "xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1},
            {"contenttext": "bad"},
        ])}
        self.assertEqual([l.text for l in frame_lines(raw)], ["good"])

    def test_frames_are_numbered_from_one_in_order(self):
        doc = {"list": [entry([("a", 0, 0, 1, 1)]), entry([("b", 0, 0, 1, 1)])]}
        self.assertEqual([n for n, _ in frames(doc)], [1, 2])
        self.assertEqual([l.text for l in frame(doc, 2)], ["b"])

    def test_a_frame_outside_the_volume_raises(self):
        with self.assertRaises(IndexError):
            frame({"list": []}, 1)


if __name__ == "__main__":
    unittest.main()
