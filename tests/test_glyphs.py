"""Pixel-exact reading of names and run counts against real 連戰統計 screenshots (needs Windows: Tahoma + MingLiU)."""
import unittest
from pathlib import Path

from PIL import Image

import ocr

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = {  # file: [(name, runs), ...]
    "page1.png": [("劍鬥士夢古", 100), ("寬頻佬寬頻", 100), ("fungfungfung", 100), ("秋尤嫣姬", 100), ("evanesce", 55),
                  ("耶穌基督", 100), ("元素小榮", 100), ("炎王仔仔", 100), ("乙骨憂太", 45), ("Arashi嵐", 100)],
    "page2.png": [("C一c一", 100), ("帕路奇亞", 100), ("萌萌小蝶", 100), ("天元凱", 100), ("翼裙撞壁沙雕", 11),
                  ("就跟你說了不要", 100), ("紅豆泥", 84)],
    "page3.png": [("EnamiAsa", 207), ("小氣", 200), ("啤啤仔", 207), ("Staywithbear", 207), ("Straywithcat", 207),
                  ("BoomBoom", 207), ("與我無關", 207), ("你老豆", 0), ("肥汁汁汁汁", 207), ("C一c一", 0)],
    "page4.png": [("荒天帝", 207), ("洛冰", 207), ("UR7543", 207), ("RealGold", 207), ("萌萌小蝶", 2), ("曉雅", 207),
                  ("衰彎片煎屎", 0), ("小熊貓", 207), ("賽勒棍", 207)],
    # neighbouring lines used to bleed in as ˙˙˙ before names; OCR dropped 98/99 and read 94 as 4
    "page5.png": [("法號夢遺", 100), ("秋尤嫣姬", 5), ("熾黑熾白", 100), ("Ferrothorn", 98), ("智秀OvO", 100),
                  ("可微即連續", 99), ("雞掰俠", 100), ("萬寶路", 100), ("肥汁汁汁汁", 100), ("櫻羽瞳v", 26)],
    "page6.png": [("KITXD", 100), ("00000", 100), ("RealGold", 94), ("萌萌小蝶", 100), ("呆呆小健", 71), ("和葉", 2),
                  ("索多", 100), ("coward", 100)],
    "page7.png": [("陳水扁你全家", 110), ("卡哇邦嘎", 110), ("哈基米", 110), ("Killua", 110), ("有我無敵", 50),
                  ("CallMeHim", 110), ("最下愛", 110), ("Casetify", 60), ("Nate", 110), ("Leungking", 110)],
    "page8.png": [("UR7543", 110), ("RealGold", 110), ("萌萌小蝶", 110), ("不牧羊的牧羊犬", 110), ("天元凱", 110),
                  ("ImKyle", 110)],
}


class ExactReadingTest(unittest.TestCase):
    def test_every_name_and_run_count(self):
        for file, expected in EXPECTED.items():
            with self.subTest(file=file):
                rows = ocr.parse_sheet(Image.open(FIXTURES / file)).rows
                self.assertEqual([(r.candidates[0], r.runs) for r in rows], expected)
                self.assertTrue(all(r.exact for r in rows), [r.candidates[0] for r in rows if not r.exact])


if __name__ == "__main__":
    unittest.main()
