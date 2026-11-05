"""Read 連戰統計 screenshots: Windows OCR finds the rows, numbers and status; names are read pixel-exactly with
the game's font (glyphs.py), falling back to OCR readings when the pixels don't match the font."""
import asyncio
import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import median

import numpy as np
from PIL import Image, ImageOps

import glyphs

NUM_FIX = str.maketrans({"I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
                         "O": "0", "o": "0", "D": "0", "Q": "0", "U": "0",
                         "S": "5", "s": "5", "Z": "2", "z": "2", "B": "8", "G": "6"})
FOOTER = re.compile(r"上一|下一|頁|保留|解散|^\d/\d$")


class OcrError(Exception):
    pass


@dataclass
class Line:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cy(self):
        return self.y + self.h / 2

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h


@dataclass
class Row:
    candidates: list[str]  # name readings, best first
    runs: int | None
    left: bool
    box: tuple[int, int, int, int] = (0, 0, 0, 0)  # whole row in screenshot pixels
    name_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # name cell only
    exact: bool = False  # candidates[0] reproduces the name's pixels in the game font


@dataclass
class Sheet:
    games: int | None
    rows: list[Row]


def parse_sheet(img: Image.Image) -> Sheet:
    """Blocking. Run off the UI thread."""
    return asyncio.run(_parse(img.convert("RGB")))


def parse_number(text: str) -> int | None:
    digits = re.sub(r"\D", "", text.translate(NUM_FIX))
    return int(digits) if digits else None


def parse_left(text: str) -> bool:
    return "已" in text or "離" in text


async def _parse(img: Image.Image) -> Sheet:
    W, H = img.size
    full = await _ocr(img, "zh-Hant-TW", 3, "inv")

    games = None
    for ln in full:
        if "遠征" in ln.text and ":" in ln.text.replace("：", ":"):
            games = parse_number(ln.text.split(":")[-1].split("：")[-1])
            break

    hdr_num = next((l for l in full if "次數" in l.text or ("完成" in l.text and "遠征" not in l.text)), None)
    hdr_stat = next((l for l in full if "狀態" in l.text or l.text == "態"), None)
    num_left = hdr_num.x - 0.04 * W if hdr_num else 0.55 * W
    stat_left = (hdr_num.right + hdr_stat.x) / 2 if hdr_num and hdr_stat else 0.78 * W
    hdrs = [l for l in (hdr_num, hdr_stat) if l]
    top = max(l.bottom for l in hdrs) + 2 if hdrs else 0
    footer = [l.y for l in full if l.cy > top and FOOTER.search(l.text)]
    bottom = min(footer) - 2 if footer else H

    if bottom - top < 10:
        raise OcrError("找不到成員列表，請截取整個「連戰統計」視窗")

    async def band(x0, x1, lang, scale, mode):
        box = (int(x0), int(top), int(x1), int(bottom))
        lines = await _ocr(img.crop(box), lang, scale, mode)
        for ln in lines:
            ln.x += box[0]
            ln.y += box[1]
        return lines

    names = [await band(0, num_left, "zh-Hant-TW", s, m) for s, m in ((3, "inv"), (2, "inv"), (4, "bin90"))]
    # The zh engine turns latin names into junk (BoomBoom -> 日00「n日00「n); en-US reads them cleanly.
    latin = [await band(0, num_left, "en-US", s, "inv") for s in (3, 2)]
    nums = await band(num_left, stat_left, "en-US", 3, "inv")
    stats = await band(stat_left, W, "zh-Hant-TW", 3, "inv")

    every = [l for group in (*names, nums, stats) for l in group]
    if not every:
        return Sheet(games, [])
    line_h = median(l.h for l in every)
    tol = max(4.0, 0.6 * line_h)
    rows = []
    for cy in _cluster([l.cy for l in (*names[0], *nums, *stats)], tol):
        def near(lines):
            hits = [l for l in lines if abs(l.cy - cy) <= tol]
            return min(hits, key=lambda l: abs(l.cy - cy)) if hits else None

        zh = [l.text for l in map(near, names) if l and l.text.strip()]
        en = [l.text for l in map(near, latin) if l and l.text.strip()]
        cands = _rank_names(zh, en)
        num, stat = near(nums), near(stats)
        runs = parse_number(num.text) if num else None
        if runs is None:
            runs = await _read_single_cell(img.crop((int(num_left), int(cy - line_h), int(stat_left), int(cy + line_h))))
        if not cands and runs is None:
            continue
        y0, y1 = max(0, int(cy - 0.95 * line_h)), min(H, int(cy + 0.95 * line_h))
        rows.append(Row(cands, runs, parse_left(stat.text) if stat else False,
                        (0, y0, W, y1), (0, y0, int(num_left), y1)))

    font = glyphs.shared()
    gray = np.asarray(ImageOps.grayscale(img))
    with ThreadPoolExecutor(min(8, os.cpu_count() or 2)) as pool:  # numpy releases the GIL
        readings = list(pool.map(lambda r: font.read(gray[r.name_box[1]:r.name_box[3], :r.name_box[2]]), rows))
    for row, reading in zip(rows, readings):
        if reading and reading.text:
            # even an imperfect font match (e.g. one character outside the font) beats OCR guesses
            row.candidates = [reading.text] + [c for c in row.candidates if c != reading.text]
            row.exact = reading.sure
    if games is None and rows:
        games = max((r.runs or 0) for r in rows) or None
    return Sheet(games, rows)


def _ascii_alnum(text: str) -> int:
    return sum(ch.isascii() and ch.isalnum() for ch in text)


def _has_cjk(text: str) -> bool:
    return any("　" <= ch <= "鿿" or "豈" <= ch <= "﫿" for ch in text)


def _rank_names(zh: list[str], en: list[str]) -> list[str]:
    """Best reading first. Latin-looking names trust en-US, everything else the longest zh reading."""
    zh = sorted(zh, key=len, reverse=True)
    looks_latin = any(_ascii_alnum(z) >= 2 for z in zh)
    en = [e for e in en if not _has_cjk(e) and _ascii_alnum(e) >= 2]
    if not (looks_latin and en):
        return zh
    en = sorted(dict.fromkeys(en), key=lambda e: (e not in zh, -en.count(e)))  # prefer readings both engines agree on
    return en + [z for z in zh if z not in en]


async def _read_single_cell(cell: Image.Image) -> int | None:
    """Windows OCR skips lone glyphs like "0" or "2": crop tight, repeat 3x ("000"), read, split back."""
    bbox = ImageOps.grayscale(cell).point(lambda p: 255 if p > 140 else 0).getbbox()
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    glyph = cell.crop((max(0, x0 - 2), max(0, y0 - 2), min(cell.width, x1 + 2), min(cell.height, y1 + 2)))
    strip = Image.new("RGB", (glyph.width * 3 + 8 + 16, glyph.height + 16), glyph.getpixel((0, 0)))
    for i in range(3):
        strip.paste(glyph, (8 + i * (glyph.width + 4), 8))
    digits = re.sub(r"\D", "", "".join(l.text for l in await _ocr(strip, "en-US", 3, "inv")).translate(NUM_FIX))
    n = len(digits) // 3
    if n and len(digits) == 3 * n and digits[:n] == digits[n:2 * n] == digits[2 * n:]:
        return int(digits[:n])
    return None


def _cluster(ys, tol):
    groups = []
    for y in sorted(ys):
        if groups and y - groups[-1][-1] <= tol:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [sum(g) / len(g) for g in groups]


def _prepare(img: Image.Image, scale: int, mode: str) -> Image.Image:
    gray = ImageOps.grayscale(img)
    big = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
    if mode == "inv":
        return ImageOps.invert(big)
    return big.point(lambda p: 0 if p > 90 else 255)  # "bin90": light text -> black on white


async def _ocr(img: Image.Image, lang: str, scale: int, mode: str) -> list[Line]:
    # winrt imported lazily so the Tk main thread never gets put into a COM apartment.
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = OcrEngine.try_create_from_language(Language(lang))
    if engine is None:
        raise OcrError(f"Windows 沒有安裝 {lang} 文字辨識語言")
    scale = max(1, min(scale, OcrEngine.max_image_dimension // max(img.size)))
    prepared = _prepare(img, scale, mode)

    buf = io.BytesIO()
    prepared.save(buf, "PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    bitmap = await (await BitmapDecoder.create_async(stream)).get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)

    lines = []
    for ln in result.lines:
        rects = [w.bounding_rect for w in ln.words]
        x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
        x1, y1 = max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)
        text = "".join(w.text for w in ln.words)
        lines.append(Line(text, x0 / scale, y0 / scale, (x1 - x0) / scale, (y1 - y0) / scale))
    return lines
