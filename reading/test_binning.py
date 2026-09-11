import unittest

import binning
from ndl_lines import BoxedLine

FIELDS = ["seniority_no", "name_raw", "commissioning_date", "post"]


def cells_for(columns, bands, *, suspect=False):
    """A toy page: `columns` officer strips 100 wide, `bands` stacked 100 tall."""
    for c in range(columns):
        for i, name in enumerate(bands):
            yield (c, name, (c * 100, i * 100, 100, 100), suspect)


class BinningTests(unittest.TestCase):
    def test_a_line_lands_in_the_cell_that_contains_most_of_it(self):
        line = BoxedLine("915", 10, 10, 40, 40)
        cells, outside = binning.bin_page([line], cells_for(2, FIELDS))
        self.assertEqual(cells[(0, "seniority_no")].text, "915")
        self.assertEqual(cells[(1, "seniority_no")].text, "")
        self.assertEqual(outside, [])

    def test_a_line_straddling_two_cells_is_owned_by_one_of_them(self):
        """The prototype's doubling bug: text must not be counted twice."""
        line = BoxedLine("x", 80, 10, 130, 40)
        cells, _ = binning.bin_page([line], cells_for(2, FIELDS))
        got = [k for k, v in cells.items() if v.text]
        self.assertEqual(len(got), 1)

    def test_a_line_outside_every_cell_is_reported_not_absorbed(self):
        line = BoxedLine("步兵中佐", 10, 5000, 40, 5040)
        cells, outside = binning.bin_page([line], cells_for(2, FIELDS))
        self.assertEqual([l.text for l in outside], ["步兵中佐"])
        self.assertFalse(any(c.text for c in cells.values()))

    def test_blank_lines_are_neither_binned_nor_reported(self):
        cells, outside = binning.bin_page(
            [BoxedLine("  ", 10, 10, 40, 40)], cells_for(1, FIELDS))
        self.assertEqual(outside, [])
        self.assertFalse(any(c.text for c in cells.values()))


class RunTests(unittest.TestCase):
    def test_a_name_and_the_birth_date_beside_it_are_never_welded_together(self):
        """The birth date is set aside by what it says (see NameBirthDateTests)."""
        name = BoxedLine("伊東武夫", 60, 110, 95, 180)
        birth = BoxedLine("明三〇、七、六", 20, 110, 40, 175)
        cells, _ = binning.bin_page([name, birth], cells_for(1, FIELDS))
        cell = cells[(0, "name_raw")]
        self.assertEqual(cell.text, "伊東武夫")
        self.assertEqual([l.text for l in cell.aside], ["明三〇、七、六"])

    def test_side_by_side_text_stays_two_runs(self):
        """Two columns of text in one cell are two runs, read right to left."""
        first = BoxedLine("步兵第九聯隊附", 60, 305, 95, 390)
        second = BoxedLine("京都帝國大學服務", 20, 305, 55, 395)
        cells, _ = binning.bin_page([first, second], cells_for(1, FIELDS))
        cell = cells[(0, "post")]
        self.assertEqual(len(cell.runs), 2)
        self.assertEqual(cell.text, "步兵第九聯隊附京都帝國大學服務")

    def test_stacked_fragments_of_one_column_join_top_to_bottom(self):
        parts = [BoxedLine("平", 60, 110, 95, 130),
                 BoxedLine("岩", 60, 132, 95, 152),
                 BoxedLine("棟一", 60, 154, 95, 190)]
        cells, _ = binning.bin_page(list(reversed(parts)), cells_for(1, FIELDS))
        self.assertEqual(cells[(0, "name_raw")].text, "平岩棟一")


class ProposalTests(unittest.TestCase):
    def propose(self, lines, columns=2):
        cells, _ = binning.bin_page(lines, cells_for(columns, FIELDS))
        return binning.propose(cells, columns, FIELDS)

    def test_a_date_is_normalised_and_carries_its_raw_reading(self):
        got = self.propose([BoxedLine("明四三、一二、二六", 10, 210, 40, 280)])
        p = got[0].fields["commissioning_date"]
        self.assertEqual(p.value, "1910-12-26")
        self.assertEqual(p.method, "eradate")
        self.assertEqual(p.raw, "明四三、一二、二六")

    def test_an_unparseable_date_is_refused_with_its_reason_not_guessed(self):
        got = self.propose([BoxedLine("昭〓〓〓一", 10, 210, 40, 280)])
        p = got[0].fields["commissioning_date"]
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "refused")
        self.assertTrue(p.note)

    def test_a_ditto_inherits_from_the_officer_directly_above(self):
        got = self.propose([BoxedLine("明四三、一二、二六", 10, 210, 40, 280),
                            BoxedLine("同", 110, 210, 140, 280)])
        p = got[1].fields["commissioning_date"]
        self.assertEqual(p.value, "1910-12-26")
        self.assertEqual(p.method, "inherited")
        self.assertEqual(p.raw, "同")

    def test_a_ditto_with_nothing_above_is_refused_never_reached_past(self):
        got = self.propose([BoxedLine("同", 10, 210, 40, 280)])
        p = got[0].fields["commissioning_date"]
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "refused")

    def test_a_ditto_chain_resolves_through_the_resolved_value(self):
        got = self.propose([BoxedLine("明四三、一二、二六", 10, 210, 40, 280),
                            BoxedLine("同", 110, 210, 140, 280),
                            BoxedLine("同", 210, 210, 240, 280)], columns=3)
        self.assertEqual(got[2].fields["commissioning_date"].value, "1910-12-26")

    def test_a_seniority_number_that_is_not_digits_is_refused(self):
        got = self.propose([BoxedLine("九一五", 10, 10, 40, 40)])
        self.assertIsNone(got[0].fields["seniority_no"].value)

    def test_a_mark_printed_beside_the_number_is_set_aside(self):
        """The Taishō volumes print a small circled mark by some seniority
        numbers; NDL reads it as a geta. The digits are still the number."""
        for raw in ("403〓", "〓1505", "⊖1505"):
            with self.subTest(raw=raw):
                p = self.propose([BoxedLine(raw, 10, 10, 40, 40)])[0].fields["seniority_no"]
                self.assertEqual(p.method, "digits")
                self.assertEqual(p.value, "".join(ch for ch in raw if ch.isdigit()))
                self.assertIn("mark", p.note)

    def test_a_letter_beside_the_number_still_refuses(self):
        """5少 in the cohort row is not a stray mark: what it means is for the lead."""
        p = self.propose([BoxedLine("少5", 10, 10, 40, 40)])[0].fields["seniority_no"]
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "refused")

    def test_an_empty_cell_proposes_nothing_and_says_so(self):
        got = self.propose([])
        p = got[0].fields["name_raw"]
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "blank")

    def test_a_date_split_across_staggered_boxes_is_reassembled(self):
        """NDL boxes a date as stacked segments; the largest run is half of it."""
        got = self.propose([BoxedLine("明四四", 68, 210, 95, 240),
                            BoxedLine("一二、二六", 60, 245, 82, 290)])
        p = got[0].fields["commissioning_date"]
        self.assertEqual(p.value, "1911-12-26")
        self.assertEqual(p.raw, "明四四、一二、二六")

    def test_reassembly_does_not_double_a_separator_already_printed(self):
        got = self.propose([BoxedLine("明四四、", 68, 210, 95, 240),
                            BoxedLine("一二、二六", 60, 245, 82, 290)])
        self.assertEqual(got[0].fields["commissioning_date"].raw,
                         "明四四、一二、二六")

    def test_reassembly_cannot_manufacture_a_date(self):
        """The separator is inserted, so the guard is that eradate still refuses."""
        got = self.propose([BoxedLine("昭〓〓", 68, 210, 95, 240),
                            BoxedLine("一", 60, 245, 82, 290)])
        self.assertIsNone(got[0].fields["commissioning_date"].value)

    def test_a_ditto_boxed_with_its_separator_is_still_a_ditto(self):
        got = self.propose([BoxedLine("明四三、一二、二六", 10, 210, 40, 280),
                            BoxedLine("同、", 110, 210, 140, 280)])
        self.assertEqual(got[1].fields["commissioning_date"].method, "inherited")

    def test_a_column_the_page_does_not_ditto_refuses_the_mark(self):
        """Only columns the print actually dittos may resolve one."""
        got = self.propose([BoxedLine("伊東武夫", 10, 110, 40, 180),
                            BoxedLine("同", 110, 110, 140, 180)])
        p = got[1].fields["name_raw"]
        self.assertIsNone(p.value)
        self.assertIn("not a column", p.note)

    def test_an_inferred_edge_marks_every_proposal_from_that_cell(self):
        cells, _ = binning.bin_page(
            [BoxedLine("915", 10, 10, 40, 40)],
            cells_for(1, FIELDS, suspect=True))
        got = binning.propose(cells, 1, FIELDS)
        self.assertTrue(got[0].fields["seniority_no"].suspect)


class RubyTests(unittest.TestCase):
    """Furigana beside a name must not become part of the name."""

    def propose(self, lines):
        cells, _ = binning.bin_page(lines, cells_for(1, FIELDS))
        return binning.propose(cells, 1, FIELDS)[0].fields["name_raw"]

    NAME = [BoxedLine("上", 55, 105, 95, 135),
            BoxedLine("住", 55, 137, 95, 167),
            BoxedLine("良吉", 55, 169, 95, 199)]

    def test_furigana_overlapping_the_name_is_taken_out_and_kept_in_the_note(self):
        p = self.propose(self.NAME + [BoxedLine("ウ", 52, 108, 64, 120),
                                      BoxedLine("た", 52, 172, 64, 184)])
        self.assertEqual(p.value, "上住良吉")
        self.assertIn("furigana read beside it: ウ た", p.note)

    def test_a_name_written_in_kana_is_not_stripped(self):
        p = self.propose([BoxedLine("ハル", 55, 105, 95, 160)])
        self.assertEqual(p.value, "ハル")

    def test_a_small_type_birth_date_is_not_mistaken_for_furigana(self):
        p = self.propose(self.NAME + [BoxedLine("明二三、五、二一", 10, 105, 22, 195)])
        self.assertEqual(p.value, "上住良吉")
        self.assertIn("明二三、五、二一", p.note)
        self.assertNotIn("furigana", p.note)


class PostingDateTests(unittest.TestCase):
    """The small date at the foot of a post is not part of the post."""

    def propose(self, lines):
        cells, _ = binning.bin_page(lines, cells_for(1, FIELDS))
        return binning.propose(cells, 1, FIELDS)[0].fields["post"]

    POST = [BoxedLine("步兵第九聯隊附", 55, 305, 95, 390)]

    def test_the_small_posting_date_is_kept_out_of_the_post_and_in_the_note(self):
        p = self.propose(self.POST + [BoxedLine("八、八、", 60, 391, 75, 399)])
        self.assertEqual(p.value, "步兵第九聯隊附")
        self.assertIn("posting date read at the foot: 八、八、", p.note)

    def test_a_posting_date_boxed_as_wide_as_the_post_is_still_set_aside(self):
        """NDLOCR-Lite's box for the small foot is no narrower than the post's."""
        p = self.propose(self.POST + [BoxedLine("八、八、一", 56, 340, 94, 399)])
        self.assertEqual(p.value, "步兵第九聯隊附")
        self.assertIn("八、八、一", p.note)

    def test_a_post_read_as_nothing_but_its_posting_date_is_refused(self):
        """Officer 19 of frame 101: the post itself was missed, only 八、三、一八 read."""
        p = self.propose([BoxedLine("八、 三、一八", 55, 305, 95, 390)])
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "refused")

    def test_a_post_whose_name_contains_numerals_is_not_cut(self):
        p = self.propose([BoxedLine("步兵第四十三聯隊長", 55, 305, 95, 395)])
        self.assertEqual(p.value, "步兵第四十三聯隊長")


class NameBirthDateTests(unittest.TestCase):
    """The birth date beside a name is never the name, however it is boxed."""

    def propose(self, lines):
        cells, _ = binning.bin_page(lines, cells_for(1, FIELDS))
        return binning.propose(cells, 1, FIELDS)[0].fields["name_raw"]

    def test_a_birth_date_boxed_wider_than_the_name_is_still_not_the_name(self):
        p = self.propose(RubyTests.NAME + [BoxedLine("明二一、九、二〇", 10, 105, 50, 195)])
        self.assertEqual(p.value, "上住良吉")
        self.assertIn("birth date read alongside: 明二一、九、二〇", p.note)

    def test_a_name_cell_read_as_only_a_birth_date_is_refused(self):
        p = self.propose([BoxedLine("明二一、九、二〇", 10, 105, 50, 195)])
        self.assertIsNone(p.value)
        self.assertEqual(p.method, "refused")


class NameOriginAndBirthPieceTests(unittest.TestCase):
    """1935 prints 本籍・族籍 above the name, and NDL boxes birth dates in pieces."""

    def cell(self, lines):
        cells, _ = binning.bin_page(lines, cells_for(1, FIELDS))
        return cells[(0, "name_raw")], binning.propose(cells, 1, FIELDS)[0].fields["name_raw"]

    def test_the_home_prefecture_and_class_are_not_part_of_the_name(self):
        """Officer 0 of pid 1449474 frame 100 came back as 和歌山、士土橋-正."""
        cell, p = self.cell(RubyTests.NAME + [BoxedLine("和歌山、士", 72, 105, 92, 150)])
        self.assertEqual(p.value, "上住良吉")
        self.assertEqual([l.text for l in cell.origin], ["和歌山、士"])

    def test_a_surname_that_is_a_prefecture_name_stays_the_name(self):
        cell, p = self.cell([BoxedLine("山口", 55, 105, 95, 140), BoxedLine("毅", 55, 150, 95, 185)])
        self.assertEqual(p.value, "山口毅")
        self.assertEqual(cell.origin, ())

    def test_the_pieces_of_a_birth_date_stay_with_it(self):
        cell, p = self.cell(RubyTests.NAME + [BoxedLine("明二二、", 10, 105, 22, 150),
                                              BoxedLine("七、一六", 10, 152, 22, 195)])
        self.assertEqual(p.value, "上住良吉")
        self.assertEqual("".join(l.text for l in cell.aside), "明二二、七、一六")

    def test_a_numeral_in_the_name_is_not_taken_for_a_birth_date_piece(self):
        cell, p = self.cell([BoxedLine("三", 55, 105, 95, 135), BoxedLine("郞", 55, 137, 95, 167),
                             BoxedLine("明二二、七、一六", 10, 105, 22, 195)])
        self.assertEqual(p.value, "三郞")

    def test_numerals_without_a_birth_date_are_left_in_the_cell(self):
        cell, _ = self.cell(RubyTests.NAME + [BoxedLine("七、一六", 10, 152, 22, 195)])
        self.assertEqual(cell.aside, ())


class RubyWithSpacesTests(unittest.TestCase):
    def test_furigana_read_with_a_space_in_it_is_still_furigana(self):
        cells, _ = binning.bin_page(RubyTests.NAME + [BoxedLine("ウヘ ズミ", 52, 108, 64, 160)],
                                    cells_for(1, FIELDS))
        p = binning.propose(cells, 1, FIELDS)[0].fields["name_raw"]
        self.assertEqual(p.value, "上住良吉")


if __name__ == "__main__":
    unittest.main()
