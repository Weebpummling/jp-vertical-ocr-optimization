"""Era-date normalizer tests. The positive cases are readings from real cells
of the registered volumes; the refusals encode 'flagged, not guessed'."""
import unittest
from datetime import date

from eradate import Parsed, kanji_int, parse


class KanjiInt(unittest.TestCase):
    def test_juxtaposition(self):
        # The roster's own notation: 三三 = 33, 一二 = 12.
        for s, n in (("三三", 33), ("一二", 12), ("二一", 21), ("八", 8), ("三〇", 30)):
            self.assertEqual(kanji_int(s), n, s)

    def test_positional_and_gan(self):
        self.assertEqual(kanji_int("二十三"), 23)
        self.assertEqual(kanji_int("十"), 10)
        self.assertEqual(kanji_int("元"), 1)
        self.assertEqual(kanji_int("45"), 45)

    def test_junk_is_none(self):
        for s in ("", "步", "三x", "十x"):
            self.assertIsNone(kanji_int(s), s)


class ParseRealCells(unittest.TestCase):
    def test_page_51_takahashi_birthdate(self):
        # 高橋直吉's cell: 明三三、八、二
        self.assertEqual(parse("明三三、八、二").value, date(1900, 8, 2))

    def test_appointment_with_context_era(self):
        # 九、一二、二一 with era inherited from the column context (大正)
        self.assertEqual(parse("九、一二、二一", context_era="大").value,
                         date(1920, 12, 21))

    def test_full_era_names(self):
        self.assertEqual(parse("昭和一〇、九、一").value, date(1935, 9, 1))
        self.assertEqual(parse("大正元、八、一").value, date(1912, 8, 1))


class FlaggedNotGuessed(unittest.TestCase):
    def assertRefused(self, p: Parsed, fragment: str):
        self.assertIsNone(p.value)
        self.assertIn(fragment, p.reason)

    def test_no_era_no_context(self):
        self.assertRefused(parse("九、一二、二一"), "no era marker")

    def test_era_overflow(self):
        # Meiji ended 1912-07-30; Meiji 46 does not exist.
        self.assertRefused(parse("明四六、一、一"), "outside the 明 era")

    def test_taisho_16_is_refused_not_mapped_to_showa(self):
        self.assertRefused(parse("大一六、三、一"), "outside the 大 era")

    def test_impossible_day_and_month(self):
        self.assertRefused(parse("明三三、一三、一"), "month 13")
        self.assertRefused(parse("明三三、二、三〇"), "day 30 invalid")

    def test_wrong_arity(self):
        self.assertRefused(parse("明三三、八"), "expected year/month/day")

    def test_ocr_junk(self):
        self.assertRefused(parse("明三步、八、二"), "unreadable numeral")

    def test_never_both_value_and_reason(self):
        for p in (parse("明三三、八、二"), parse("junk")):
            self.assertTrue((p.value is None) != (p.reason is None))


import eradate as eradate_module  # noqa: E402


class ReadingTests(unittest.TestCase):
    """parse_reading: what a reader hands back from the worksheet."""

    def test_an_iso_date_is_taken_as_read(self):
        got = eradate_module.parse_reading("1910-12-26")
        self.assertEqual(got.value.isoformat(), "1910-12-26")

    def test_era_notation_still_goes_through_the_era_parser(self):
        got = eradate_module.parse_reading("明四三、一二、二六")
        self.assertEqual(got.value.isoformat(), "1910-12-26")

    def test_an_impossible_iso_date_is_refused_not_rounded(self):
        got = eradate_module.parse_reading("1910-02-30")
        self.assertFalse(got.ok)
        self.assertIn("not a real date", got.reason)

    def test_an_iso_date_outside_the_eras_is_refused(self):
        for text in ("1860-01-01", "2026-09-09"):
            with self.subTest(text=text):
                self.assertFalse(eradate_module.parse_reading(text).ok)

    def test_something_iso_shaped_but_loose_is_not_guessed_at(self):
        self.assertFalse(eradate_module.parse_reading("1910-1-26").ok)


if __name__ == "__main__":
    unittest.main()
