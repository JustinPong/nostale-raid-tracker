"""Runs the real Windows OCR on saved 連戰統計 screenshots."""
import unittest
from pathlib import Path

from PIL import Image

import ocr

FIXTURES = Path(__file__).parent / "fixtures"


class ParseSheetTest(unittest.TestCase):
    def check(self, file, games, runs, left_rows):
        sheet = ocr.parse_sheet(Image.open(FIXTURES / file))
        self.assertEqual(sheet.games, games)
        self.assertEqual([r.runs for r in sheet.rows], runs)
        self.assertEqual([i for i, r in enumerate(sheet.rows) if r.left], left_rows)
        self.assertTrue(all(r.candidates for r in sheet.rows))
        return sheet

    def test_page1(self):
        self.check("page1.png", 100, [100, 100, 100, 100, 55, 100, 100, 100, 45, 100], [8])

    def test_page2(self):
        self.check("page2.png", 100, [100, 100, 100, 100, 11, 100, 84], [6])

    def test_latin_names_and_single_digits(self):
        sheet = self.check("page3.png", 207, [207, 200, 207, 207, 207, 207, 207, 0, 207, 0], [1, 7, 9])
        best = [r.candidates[0] for r in sheet.rows]
        for i, name in ((0, "EnamiAsa"), (3, "Staywithbear"), (4, "Straywithcat"), (5, "BoomBoom")):
            self.assertEqual(best[i], name)

    def test_page4(self):
        sheet = self.check("page4.png", 207, [207, 207, 207, 207, 2, 207, 0, 207, 207], [6])
        self.assertEqual([sheet.rows[i].candidates[0] for i in (2, 3)], ["UR7543", "RealGold"])

    def test_number_cleanup(self):
        self.assertEqual(ocr.parse_number("1D0"), 100)
        self.assertEqual(ocr.parse_number("IOO"), 100)
        self.assertIsNone(ocr.parse_number("--"))


if __name__ == "__main__":
    unittest.main()
