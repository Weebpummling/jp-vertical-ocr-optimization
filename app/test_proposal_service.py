"""Tests for the proposal service - what a reader is offered, and what taking it sends.

Built from registered-page objects and boxed lines directly, so nothing here
needs a scan, NDL, or a database.
"""

import unittest

import page_service as PS
import proposal_service as props
from ndl_lines import BoxedLine

FIELDS = ["seniority_no", "name_raw", "commissioning_date", "post"]
BAND = 100          # each field is a 100 px band; each officer a 100 px strip


def spread(officers_per_leaf=(2, 1)) -> PS.RegisteredPage:
    """Officers numbered through both leaves, right-hand leaf first.

    Officer i occupies x = (N-1-i)*100 .. (N-i)*100, so index 0 is rightmost.
    """
    total = sum(officers_per_leaf)
    officers = []
    index = 0
    for panel, count in enumerate(officers_per_leaf):
        for column in range(count):
            x = (total - 1 - index) * BAND
            cells = [PS.Cell(field=f, bbox=(x, i * BAND, BAND, BAND),
                             suspect=False, confirmed_label=True)
                     for i, f in enumerate(FIELDS)]
            officers.append(PS.Officer(index=index, bbox=(x, 0, BAND, BAND * len(FIELDS)),
                                       cells=cells, panel=panel, column=column))
            index += 1
    return PS.RegisteredPage(
        pid="p", frame=1, panel=0, template_id="t", skew_deg=0.0,
        bands_matched=5, bands_total=5, explained_frac=1.0, officers=officers,
        panels_total=len(officers_per_leaf),
        panels_registered=tuple(range(len(officers_per_leaf))))


def at(officer: int, field: str, text: str, *, dx=10, dy=10, w=30, h=40,
       total=3) -> BoxedLine:
    x = (total - 1 - officer) * BAND + dx
    y = FIELDS.index(field) * BAND + dy
    return BoxedLine(text, x, y, x + w, y + h)


class ProposalTests(unittest.TestCase):
    def propose(self, lines, leaves=(2, 1)):
        return props.propose_registered(spread(leaves), lines)["officers"]

    def test_officers_are_keyed_by_their_spread_wide_index(self):
        got = self.propose([at(0, "seniority_no", "915")])
        self.assertEqual([o["index"] for o in got], [0, 1, 2])
        self.assertEqual([(o["panel"], o["column"]) for o in got],
                         [(0, 0), (0, 1), (1, 0)])

    def test_a_date_fills_the_form_as_printed_not_as_the_machine_read_it(self):
        """eradate on the server decides what a printed date means."""
        got = self.propose([at(0, "commissioning_date", "明四四", dx=50, dy=5, h=35),
                            at(0, "commissioning_date", "一二、二六", dx=40, dy=45, h=45)])
        p = got[0]["fields"]["commissioning_date"]
        self.assertEqual(p["value"], "1911-12-26")
        self.assertEqual(p["fill"], "明四四、一二、二六")
        self.assertEqual(p["form_key"], "commissioning_date")
        self.assertTrue(p["wholesale"])

    def test_a_ditto_fills_as_the_mark_so_the_server_resolves_it_from_the_record(self):
        got = self.propose([at(0, "commissioning_date", "明四三、一二、二六"),
                            at(1, "commissioning_date", "同")])
        p = got[1]["fields"]["commissioning_date"]
        self.assertEqual(p["method"], "inherited")
        self.assertEqual(p["value"], "1910-12-26")
        self.assertEqual(p["fill"], "同")

    def test_a_ditto_chain_crosses_the_gutter(self):
        """The left leaf's first officer is dittoed from the right leaf's last."""
        got = self.propose([at(0, "commissioning_date", "明四三、一二、二六"),
                            at(1, "commissioning_date", "同"),
                            at(2, "commissioning_date", "同")])
        self.assertEqual(got[2]["panel"], 1)
        self.assertEqual(got[2]["fields"]["commissioning_date"]["value"], "1910-12-26")

    def test_a_ditto_below_an_unreadable_head_is_still_offered_as_the_mark(self):
        """One human keystroke at the head should unlock the chain beneath it."""
        got = self.propose([at(0, "commissioning_date", "昭〓〓〓"),
                            at(1, "commissioning_date", "同")])
        head, below = got[0]["fields"]["commissioning_date"], got[1]["fields"]["commissioning_date"]
        self.assertEqual(head["method"], "refused")
        self.assertFalse(head["wholesale"])
        self.assertEqual(below["method"], "refused")
        self.assertEqual(below["fill"], "同")
        self.assertTrue(below["wholesale"])

    def test_a_refused_reading_fills_as_raw_text_but_never_wholesale(self):
        got = self.propose([at(0, "seniority_no", "九一五")])
        p = got[0]["fields"]["seniority_no"]
        self.assertIsNone(p["value"])
        self.assertEqual(p["fill"], "九一五")
        self.assertFalse(p["wholesale"])

    def test_a_clean_reading_fills_as_its_value(self):
        got = self.propose([at(0, "seniority_no", "915"), at(0, "post", "步兵第九聯隊附")])
        self.assertEqual(got[0]["fields"]["seniority_no"]["fill"], "915")
        self.assertEqual(got[0]["fields"]["post"]["fill"], "步兵第九聯隊附")

    def test_a_blank_cell_offers_nothing(self):
        p = self.propose([])[0]["fields"]["name_raw"]
        self.assertEqual(p["method"], "blank")
        self.assertIsNone(p["fill"])
        self.assertFalse(p["wholesale"])

    def test_the_birth_date_beside_a_name_is_kept_apart_from_it(self):
        got = self.propose([at(0, "name_raw", "平岩棟一", dx=55, w=35, h=60),
                            at(0, "name_raw", "明二〇、四、一", dx=10, w=15, h=70)])
        self.assertEqual(got[0]["fields"]["name_raw"]["value"], "平岩棟一")
        self.assertEqual(got[0]["birth_raw"], "明二〇、四、一")

    def test_fields_without_a_form_column_are_context_only(self):
        page = spread((1,))
        for officer in page.officers:
            officer.cells.append(PS.Cell(field="cohort", bbox=(0, 400, BAND, BAND),
                                         suspect=False, confirmed_label=True))
        got = props.propose_registered(page, [BoxedLine("23", 10, 410, 40, 450)])
        self.assertIsNone(got["officers"][0]["fields"]["cohort"]["form_key"])

    def test_lines_outside_every_cell_are_reported(self):
        got = props.propose_registered(spread(), [BoxedLine("步兵大佐", 5, 900, 40, 990)])
        self.assertEqual(got["lines_outside"], ["步兵大佐"])


VOCAB = {"branches": [{"ja": "歩兵", "variants": ["步兵"]}],
         "ranks": [{"ja": "中佐", "variants": []}]}


SECTION_VOCAB = {
    "branches": [{"code": "hohei", "ja": "歩兵", "variants": ["步兵"]},
                 {"code": "hohei_ho", "ja": "砲兵", "variants": []},
                 {"code": "yasen_ho", "ja": "野戦砲兵", "variants": ["野砲兵"]}],
    "ranks": [{"code": "chusa", "ja": "中佐", "variants": []},
              {"code": "chui", "ja": "中尉", "variants": []},
              {"code": "shosho", "ja": "少将", "variants": []}],
    "kanji_variants": [{"variant": "步", "canonical": "歩"}, {"variant": "將", "canonical": "将"}],
}


class SectionLabelTests(unittest.TestCase):
    """兵科 and 階級 are printed once per leaf, in the margin - not in any cell."""

    def label(self, *texts):
        return props.section_label(list(texts), SECTION_VOCAB)

    def test_the_margin_label_names_branch_and_rank(self):
        got = self.label("步兵中佐", "一六六")
        self.assertEqual((got["branch"]["code"], got["rank"]["code"]), ("hohei", "chusa"))
        self.assertEqual(got["branch"]["ja"], "歩兵")

    def test_both_leaves_carrying_the_same_label_is_one_label(self):
        self.assertEqual(self.label("步兵中佐", "歩兵中佐")["seen"], 2)

    def test_a_regiment_heading_still_names_branch_and_rank(self):
        got = self.label("步兵第二十八聯隊中尉", "(第七師團)")
        self.assertEqual((got["branch"]["code"], got["rank"]["code"]), ("hohei", "chui"))

    def test_the_longer_branch_name_wins(self):
        self.assertEqual(self.label("野砲兵中尉")["branch"]["code"], "yasen_ho")

    def test_an_old_form_rank_is_folded(self):
        self.assertEqual(self.label("少將"), None)        # a rank alone names no branch
        self.assertEqual(self.label("砲兵少將")["rank"]["code"], "shosho")

    def test_two_different_labels_on_one_page_propose_nothing(self):
        """One section ends and the next begins: the reader decides who is where."""
        self.assertIsNone(self.label("步兵中佐", "步兵中尉"))

    def test_a_misread_label_proposes_nothing(self):
        self.assertIsNone(self.label("步兵中性", "ノ一六六"))

    def sections(self, leaves, lines):
        got = props.propose_registered(spread(leaves), lines, vocab=SECTION_VOCAB)
        return [o["section"] and o["section"]["rank"]["ja"] for o in got["officers"]]

    def test_each_officer_is_offered_the_label_of_their_own_leaf(self):
        # spread((2, 2)): the right-hand leaf is x 200-400, the left-hand leaf x 0-200.
        lines = [BoxedLine("步兵中尉", 410, 10, 440, 200),      # beside the right-hand leaf
                 BoxedLine("步兵中佐", -40, 10, -10, 200)]      # beside the left-hand leaf
        self.assertEqual(self.sections((2, 2), lines), ["中尉", "中尉", "中佐", "中佐"])

    def test_a_label_far_from_the_table_belongs_to_no_leaf(self):
        """The label of a leaf that did not register is not given to the one that did."""
        lines = [BoxedLine("步兵中佐", 1500, 10, 1530, 200)]
        self.assertEqual(self.sections((1,), lines), [None])

    def test_a_label_inside_an_officers_cell_is_not_a_section_label(self):
        self.assertEqual(self.sections((1,), [at(0, "post", "步兵中佐", total=1)]), [None])


class ColumnKindTests(unittest.TestCase):
    """A column of the grid that holds no officer, proposed from what was read."""

    def kind(self, lines):
        got = props.propose_registered(spread((1,)), lines, vocab=VOCAB)
        return got["officers"][0]["column_kind"]

    def test_an_officer_has_a_seniority_number(self):
        k = self.kind([at(0, "seniority_no", "915", total=1),
                       at(0, "post", "步兵第九聯隊附", total=1)])
        self.assertEqual(k["kind"], "officer")

    def test_the_section_label_column(self):
        k = self.kind([at(0, "commissioning_date", "步兵中佐", total=1),
                       at(0, "name_raw", "一六七", total=1)])
        self.assertEqual(k["kind"], "section_label")
        self.assertIn("步兵", k["evidence"])

    def test_the_column_legend(self):
        k = self.kind([at(0, "seniority_no", "次列", total=1),
                       at(0, "name_raw", "學位爵氏名", total=1),
                       at(0, "post", "職名命課ノ年月日", total=1)])
        self.assertEqual(k["kind"], "legend")

    def test_an_unused_slot(self):
        self.assertEqual(self.kind([])["kind"], "blank")

    def test_an_officer_whose_number_did_not_read_is_not_taken_for_a_label(self):
        k = self.kind([at(0, "seniority_no", "九一五", total=1),
                       at(0, "post", "步兵第九聯隊附", total=1),
                       at(0, "commissioning_date", "步兵", total=1)])
        self.assertEqual(k["kind"], "officer")


if __name__ == "__main__":
    unittest.main()
