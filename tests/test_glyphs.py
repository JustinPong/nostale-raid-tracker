"""Pixel-exact name reading against real 連戰統計 screenshots (needs Windows with Tahoma + MingLiU)."""
import unittest
from pathlib import Path

from PIL import Image

import ocr

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = {
    "page1.png": ["劍鬥士夢古", "寬頻佬寬頻", "fungfungfung", "秋尤嫣姬", "evanesce", "耶穌基督", "元素小榮", "炎王仔仔",
                  "乙骨憂太", "Arashi嵐"],
    "page2.png": ["C一c一", "帕路奇亞", "萌萌小蝶", "天元凱", "翼裙撞壁沙雕", "就跟你說了不要", "紅豆泥"],
    "page3.png": ["EnamiAsa", "小氣", "啤啤仔", "Staywithbear", "Straywithcat", "BoomBoom", "與我無關", "你老豆",
                  "肥汁汁汁汁", "C一c一"],
    "page4.png": ["荒天帝", "洛冰", "UR7543", "RealGold", "萌萌小蝶", "曉雅", "衰彎片煎屎", "小熊貓", "賽勒棍"],
}


class ExactNamesTest(unittest.TestCase):
    def test_every_name_is_read_exactly(self):
        for file, names in NAMES.items():
            with self.subTest(file=file):
                rows = ocr.parse_sheet(Image.open(FIXTURES / file)).rows
                self.assertEqual([r.candidates[0] for r in rows], names)
                self.assertTrue(all(r.exact for r in rows), [r.candidates[0] for r in rows if not r.exact])


if __name__ == "__main__":
    unittest.main()
