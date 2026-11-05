"""Look & feel: Sun Valley dark theme, Chinese UI font, dark title bar, app icon."""
import ctypes
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import sv_ttk

ASSETS = Path(__file__).resolve().parent / "assets"
APP_ID = "myself.raid-tracker"
FONT = "Microsoft JhengHei UI"

BG = "#1c1c1c"
TILE = "#262626"
BORDER = "#3a3a3a"
ROW_ALT = "#232323"
MENU = "#2b2b2b"
TEXT = "#f3f3f3"
MUTED = "#9a9a9a"
ACCENT = "#57c8ff"
RED = "#ff7b72"
AMBER = "#ffd166"
GREEN = "#6fdc8c"


def before_tk():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:  # own taskbar entry + icon instead of Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def apply(root: tk.Tk):
    sv_ttk.set_theme("dark")
    if FONT in tkfont.families():
        for name in tkfont.names():
            if name.startswith("SunValley") or (name.startswith("Tk") and name != "TkFixedFont"):
                tkfont.nametofont(name).configure(family=FONT)
    root.iconbitmap(default=str(ASSETS / "icon.ico"))
    root.configure(background=BG)


def dark_title_bar(win: tk.Misc):
    win.update_idletasks()
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE: Win11 / older Win10 builds
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except (AttributeError, OSError):
        pass


def font(size: int, weight: str = "normal"):
    return (FONT, size, weight)


def menu(parent) -> tk.Menu:
    return tk.Menu(parent, tearoff=0, bg=MENU, fg=TEXT, activebackground=ACCENT, activeforeground="#000000",
                   bd=0, font=font(10))
