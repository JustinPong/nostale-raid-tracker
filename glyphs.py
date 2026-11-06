"""Read names pixel-exactly with the game's own text rendering.

The game draws names with GDI "Tahoma" 12px, no anti-aliasing; Windows font linking supplies Chinese glyphs
(MingLiU 12px bitmaps, then SimSun ...). Every character is drawn once the same way into a bitmask template, and a
name is decoded by finding the glyph sequence that reproduces its pixels. Chinese and English need no separate
handling: they are just different templates.
"""
import ctypes
import struct
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FACE, HEIGHT = "Tahoma", 12
CODECS = ("cp950", "big5hkscs", "gbk")  # Traditional + Hong Kong + Simplified characters
PAD, BASE, CANVAS_W, CANVAS_H = 8, 22, 56, 32
MAX_W = 32  # template box width limit (uint32 row masks)
CACHE_VERSION = 3
CACHE = Path(__file__).resolve().parent / "data" / "cache" / f"glyphs-v{CACHE_VERSION}.npz"

SKIP_COST = 0.3  # step over one column without placing a glyph (+ its unexplained ink)
GLYPH_COST = 0.05  # per glyph, so one wide glyph beats two narrow ones that happen to fit
SHIFT_COST = 0.2  # glyph starts one column before the previous glyph's advance ends
SURE_MAX_ERR = 1  # every glyph within this many wrong pixels -> treat the reading as certain


@dataclass
class Reading:
    text: str
    sure: bool
    errors: list[int]  # wrong pixels per glyph


class GlyphSet:
    def __init__(self, chars, bits, lo, width, adv):
        self.chars = chars
        self.bits = bits  # (N, H) uint32: row bitmasks, bit i = column lo + i from the pen position
        self.lo, self.width, self.adv = lo, width, adv
        self.H = bits.shape[1]
        self.groups = []
        for key in sorted(set(zip(lo.tolist(), width.tolist(), adv.tolist()))):
            idx = np.nonzero((lo == key[0]) & (width == key[1]) & (adv == key[2]))[0]
            mask = np.uint32((1 << key[1]) - 1 if key[1] < 32 else 0xFFFFFFFF)
            self.groups.append((*key, mask, idx, bits[idx]))

    @classmethod
    def load(cls, cache: Path) -> "GlyphSet":
        if cache.exists():
            z = np.load(cache, allow_pickle=False)
            if int(z["version"]) == CACHE_VERSION:
                return cls(list(z["chars"]), z["bits"], z["lo"], z["width"], z["adv"])
        gs = cls.build()
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, version=CACHE_VERSION, chars=np.array(gs.chars), bits=gs.bits, lo=gs.lo,
                            width=gs.width, adv=gs.adv)
        return gs

    @classmethod
    def build(cls) -> "GlyphSet":
        rendered, seen = [], {}
        with _GdiCanvas() as canvas:
            notdef = canvas.draw("\U000f0000")[0]
            for ch in [chr(c) for c in range(0x21, 0x7F)] + _codec_chars(CODECS):
                mask, adv = canvas.draw(ch)
                cols = np.nonzero(mask.any(axis=0))[0]
                if not len(cols) or np.array_equal(mask, notdef):
                    continue  # blank (gaps are skipped columns) or no font has it
                lo = min(0, cols[0] - PAD)
                width = max(adv, cols[-1] + 1 - PAD) - lo
                if width > MAX_W:
                    continue
                box = mask[:, PAD + lo: PAD + lo + width]
                key = (lo, width, adv, box.tobytes())
                if key in seen:
                    continue  # draws identical pixels (e.g. Cyrillic а vs a): keep the first, more common one
                seen[key] = True
                rendered.append([ch, box, lo, width, adv])

        rows = np.nonzero(np.any([r[1].any(axis=1) for r in rendered], axis=0))[0]
        r0, r1 = rows[0], rows[-1] + 1
        weights = np.left_shift(np.uint64(1), np.arange(MAX_W, dtype=np.uint64))
        bits = np.zeros((len(rendered), r1 - r0), dtype=np.uint32)
        for i, (_, box, _, width, _) in enumerate(rendered):
            bits[i] = (box[r0:r1].astype(np.uint64) @ weights[:width]).astype(np.uint32)
        col = lambda k: np.array([r[k] for r in rendered])
        return cls([r[0] for r in rendered], bits, col(2), col(3), col(4))

    # ---------- reading ----------
    def subset(self, chars: str) -> "GlyphSet":
        """Only these characters, e.g. digits for the run-count column."""
        idx = np.array([i for i, c in enumerate(self.chars) if c in chars])
        return GlyphSet([self.chars[i] for i in idx], self.bits[idx], self.lo[idx], self.width[idx], self.adv[idx])

    def read(self, ink: np.ndarray) -> Reading | None:
        """ink: bool mask of one line of text (see text_mask)."""
        cols = np.nonzero(ink.any(axis=0))[0]
        if not len(cols):
            return None
        H, margin = self.H, MAX_W + 4
        strip = np.zeros((ink.shape[0] + 2 * H, ink.shape[1] + 2 * margin), dtype=bool)
        strip[H:H + ink.shape[0], margin:margin + ink.shape[1]] = ink
        x0, x1 = cols[0] + margin, cols[-1] + margin
        ink_rows = np.nonzero(strip.any(axis=1))[0]
        tops = range(ink_rows[-1] - H + 1, ink_rows[0] + 1)  # placements that contain all the ink
        if not len(tops):  # taller than any glyph: not a name line
            return None
        best = min((self._decode(strip[t:t + H], x0, x1) for t in tops), key=lambda r: r[0])
        _, text, errors = best
        return Reading(text, bool(text) and max(errors) <= SURE_MAX_ERR, errors)

    def _decode(self, rows: np.ndarray, x0: int, x1: int):
        weights = np.left_shift(np.uint64(1), np.arange(MAX_W, dtype=np.uint64))
        padded = np.pad(rows, ((0, 0), (0, MAX_W)))
        wins = (np.lib.stride_tricks.sliding_window_view(padded, MAX_W, axis=1)[:, :rows.shape[1]]
                .astype(np.uint64) @ weights).astype(np.uint32).T  # (W, H): rows[:, x:x+32] as bitmasks
        col_ink = rows.sum(axis=0)
        start, end = x0 - 4, x1 + 1
        INF = float("inf")
        cost = [INF] * (end + MAX_W + 2)
        back = [None] * len(cost)
        for s in range(start, x0 + 1):
            cost[s] = 0.0
        for x in range(start, end):
            if cost[x] == INF:
                continue
            c = cost[x] + SKIP_COST + col_ink[x]
            if c < cost[x + 1]:
                cost[x + 1], back[x + 1] = c, (x, None, 0)
            if not col_ink[x:x + MAX_W].any():
                continue  # nothing to draw here
            for lo, width, adv, mask, idx, bits in self.groups:
                err = np.bitwise_count(bits ^ (wins[x + lo] & mask)).sum(axis=1)
                j = int(err.argmin())
                for nx, extra in ((x + adv, 0.0), (x + adv - 1, SHIFT_COST)):
                    c = cost[x] + int(err[j]) + GLYPH_COST + extra
                    if nx > x and c < cost[nx]:
                        cost[nx], back[nx] = c, (x, int(idx[j]), int(err[j]))
        # stop anywhere; ink after the stopping point counts as unexplained
        tail = np.concatenate([np.cumsum(col_ink[::-1])[::-1], [0]])
        stop = min(range(start + 1, len(cost)), key=lambda x: cost[x] + (tail[x] if x < len(tail) else 0))
        text, errors, x = [], [], stop
        while back[x] is not None:
            px, i, err = back[x]
            if i is not None:
                text.append(self.chars[i])
                errors.append(err)
            x = px
        total = cost[stop] + (tail[stop] if stop < len(tail) else 0)
        return total, "".join(reversed(text)), list(reversed(errors)) or [99]


_shared: GlyphSet | None = None
_digits: GlyphSet | None = None
_lock = threading.Lock()


def shared() -> GlyphSet:
    """The glyph set, built on first use (~10 s, once) and cached on disk."""
    global _shared
    with _lock:
        if _shared is None:
            _shared = GlyphSet.load(CACHE)
        return _shared


def digits() -> GlyphSet:
    global _digits
    if _digits is None:
        _digits = shared().subset("0123456789")
    return _digits


def text_mask(rgb: np.ndarray) -> np.ndarray:
    """Pixels in the game's text colour (near-white grey, ~235): drops the window border and anything bright
    showing through the semi-transparent panel, which plain brightness would mistake for ink."""
    lo, hi = rgb.min(axis=2), rgb.max(axis=2)
    return (lo >= 215) & (hi - lo <= 12)


class _GdiCanvas:
    """Draws single characters exactly like the game: GDI TextOut, Tahoma 12px, no anti-aliasing, font linking."""

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class TEXTMETRICW(ctypes.Structure):
        _fields_ = [(n, wintypes.LONG) for n in ("tmHeight", "tmAscent", "tmDescent", "tmInternalLeading",
                                                  "tmExternalLeading", "tmAveCharWidth", "tmMaxCharWidth",
                                                  "tmWeight", "tmOverhang", "tmDigitizedAspectX",
                                                  "tmDigitizedAspectY")] + \
                   [(n, wintypes.WCHAR) for n in ("tmFirstChar", "tmLastChar", "tmDefaultChar", "tmBreakChar")] + \
                   [(n, wintypes.BYTE) for n in ("tmItalic", "tmUnderlined", "tmStruckOut", "tmPitchAndFamily",
                                                 "tmCharSet")]

    def __enter__(self):
        gdi = self.gdi = ctypes.WinDLL("gdi32")
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateDIBSection.restype = wintypes.HBITMAP
        gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        gdi.CreateFontW.restype = wintypes.HFONT
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        gdi.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
        gdi.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                              ctypes.POINTER(wintypes.SIZE)]
        gdi.SetTextColor.argtypes = gdi.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi.GetTextMetricsW.argtypes = [wintypes.HDC, ctypes.c_void_p]

        self.dc = gdi.CreateCompatibleDC(None)
        header = self.BITMAPINFOHEADER(ctypes.sizeof(self.BITMAPINFOHEADER), CANVAS_W, -CANVAS_H, 1, 32, 0)
        self.pixels = ctypes.c_void_p()
        self.bitmap = gdi.CreateDIBSection(self.dc, ctypes.byref(header), 0, ctypes.byref(self.pixels), None, 0)
        gdi.SelectObject(self.dc, self.bitmap)
        # NONANTIALIASED_QUALITY = 3, DEFAULT_CHARSET = 1
        self.font = gdi.CreateFontW(-HEIGHT, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 3, 0, FACE)
        gdi.SelectObject(self.dc, self.font)
        gdi.SetTextColor(self.dc, 0xFFFFFF)
        gdi.SetBkMode(self.dc, 1)  # TRANSPARENT
        tm = self.TEXTMETRICW()
        gdi.GetTextMetricsW(self.dc, ctypes.byref(tm))
        self.top = BASE - tm.tmAscent
        self.buffer = (ctypes.c_uint32 * (CANVAS_W * CANVAS_H)).from_address(self.pixels.value)
        return self

    def draw(self, ch: str):
        ctypes.memset(self.pixels, 0, CANVAS_W * CANVAS_H * 4)
        self.gdi.TextOutW(self.dc, PAD, self.top, ch, len(ch))
        size = wintypes.SIZE()
        self.gdi.GetTextExtentPoint32W(self.dc, ch, len(ch), ctypes.byref(size))
        img = np.frombuffer(self.buffer, dtype=np.uint32).reshape(CANVAS_H, CANVAS_W)
        return (img & 0xFFFFFF) > 0x808080, size.cx

    def __exit__(self, *exc):
        self.gdi.DeleteObject(self.font)
        self.gdi.DeleteObject(self.bitmap)
        self.gdi.DeleteDC(self.dc)


def _codec_chars(codecs) -> list[str]:
    """Every character the codecs encode as two bytes, in code order (common characters first)."""
    out = {}
    for codec in codecs:
        for lead in range(0x81, 0xFF):
            for trail in range(0x40, 0xFF):
                try:
                    ch = struct.pack("BB", lead, trail).decode(codec)
                except UnicodeDecodeError:
                    continue
                if len(ch) == 1:
                    out.setdefault(ch, None)
    # Big5 lists symbols (A1xx) before ideographs (A4xx); prefer ideographs when two draw identically (一 vs —).
    ideograph = lambda c: "㐀" <= c <= "鿿"
    return [c for c in out if ideograph(c)] + [c for c in out if not ideograph(c)]
