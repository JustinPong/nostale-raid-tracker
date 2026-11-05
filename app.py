"""副本代打記帳: paste 連戰統計 screenshots, track who still owes their share of boxes/coins."""
import csv
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab, ImageTk

import glyphs
import logic
import ocr
import theme
from store import Store
from viewer import DetailPanel

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "data" / "raid_data.json"

COLS = ("ret", "mail", "name", "runs", "boxes", "coins")
HEAD = {"ret": "已還", "mail": "已寄信", "name": "名字", "runs": "完成次數", "boxes": "應還箱子", "coins": "應還硬幣"}
WIDTH = {"ret": 56, "mail": 66, "name": 210, "runs": 90, "boxes": 90, "coins": 90}
OVER_COLS = (("name", "名字", 200), ("raid", "副本", 110), ("when", "日期", 140), ("runs", "完成次數", 90),
             ("boxes", "欠箱子", 90), ("coins", "欠硬幣", 90), ("mail", "已寄信", 70))
INT_FIELDS = ("games", "team_size", "percent", "boxes", "coins")
TEXT_INPUTS = (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Spinbox, tk.Text)
FILTERS = (("all", "全部"), ("due", "未還"), ("unmailed", "未寄信"), ("check", "要檢查"))
EMPTY_HINT = ("還沒有資料\n\n① 遊戲內打開「連戰統計」\n② Win+Shift+S 截取整個視窗\n"
              "③ 回到這裡按 Ctrl+V（第 2 頁照樣貼上）")


class App:
    def __init__(self, root: tk.Tk, store: Store):
        self.root, self.store = root, store
        self.current: dict | None = None
        self.busy = False
        self.results = queue.Queue()
        self.k = root.winfo_fpixels("1i") / 96  # DPI scale for pixel sizes
        self.filter_var = tk.StringVar(value="all")
        self.search_var = tk.StringVar()

        self._build()
        root.bind_all("<Control-v>", self.on_paste)
        root.bind_all("<Control-V>", self.on_paste)
        root.bind_all("<Control-f>", lambda e: self.search.focus_set())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=glyphs.shared, daemon=True).start()  # first run renders the game font (~10 s)

        if store.sessions:
            self.select_session(store.sessions[0])
        else:
            self.refresh_all()

    def px(self, n):
        return int(n * self.k)

    # ---------- layout ----------
    def _build(self):
        root, px = self.root, self.px
        root.title("副本代打記帳")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(px(1460), sw - px(40)), min(px(900), sh - px(90))
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - px(20))}")
        root.minsize(min(px(1150), w), min(px(640), h))

        header = ttk.Frame(root, padding=(px(18), px(14), px(18), px(8)))
        header.pack(fill="x")
        self._logo = ImageTk.PhotoImage(Image.open(theme.ASSETS / "icon.png").resize((px(44), px(44)), Image.LANCZOS))
        ttk.Label(header, image=self._logo).pack(side="left")
        titles = ttk.Frame(header)
        titles.pack(side="left", padx=px(12))
        ttk.Label(titles, text="副本代打記帳", font=theme.font(18, "bold")).pack(anchor="w")
        ttk.Label(titles, text="截圖貼上 → 自動讀取 → 記錄誰未還", foreground=theme.MUTED).pack(anchor="w")
        ttk.Button(header, text="＋ 新場次", command=self.new_session).pack(side="right")
        ttk.Button(header, text="貼上截圖　Ctrl+V", style="Accent.TButton", command=self.on_paste).pack(
            side="right", padx=px(10))

        self.nb = nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=px(14))
        tab = ttk.Frame(nb, padding=(px(10), px(12), px(10), px(8)))
        over = ttk.Frame(nb, padding=px(16))
        nb.add(tab, text="   場次   ")
        nb.add(over, text="   欠款總覽   ")
        nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh_overview())

        self.status = ttk.Label(root, foreground=theme.MUTED, padding=(px(18), px(6)))
        self.status.pack(fill="x")

        ttk.Style(root).configure("Treeview", rowheight=px(30))
        side = ttk.Frame(tab, padding=(0, 0, px(12), 0), width=px(290))
        side.pack_propagate(False)
        side.pack(side="left", fill="y")
        self.detail = DetailPanel(tab, self, px(370))
        self.detail.pack(side="right", fill="y")
        ttk.Separator(tab, orient="vertical").pack(side="right", fill="y", padx=(px(8), 0))
        main = ttk.Frame(tab, padding=(px(8), 0))
        main.pack(side="left", fill="both", expand=True)
        self._build_sidebar(side)
        self._build_main(main)
        self._build_overview(over)

    def _build_sidebar(self, side):
        px = self.px
        ttk.Label(side, text="場次紀錄", font=theme.font(11, "bold")).pack(anchor="w", pady=(0, px(8)))
        self.sess_tree = ttk.Treeview(side, columns=("when", "raid", "due"), show="headings", selectmode="browse")
        for col, text, w in (("when", "日期", 130), ("raid", "副本", 74), ("due", "未還", 52)):
            self.sess_tree.heading(col, text=text)
            self.sess_tree.column(col, width=px(w), stretch=False, anchor="center")
        self.sess_tree.tag_configure("done", foreground=theme.GREEN)
        self.sess_tree.pack(fill="both", expand=True)
        self.sess_tree.bind("<<TreeviewSelect>>", self.on_session_select)
        ttk.Button(side, text="刪除場次", command=self.delete_session).pack(fill="x", pady=(px(10), 0))

    def _build_main(self, main):
        px = self.px
        top = ttk.Frame(main)
        top.pack(fill="x")
        self.raid_title = ttk.Label(top, font=theme.font(16, "bold"))
        self.raid_title.pack(side="left")
        ttk.Button(top, text="⚙ 設定", command=self.open_settings).pack(side="right")
        self.meta = ttk.Label(main, foreground=theme.MUTED)
        self.meta.pack(anchor="w", pady=(px(2), px(12)))

        tiles = ttk.Frame(main)
        tiles.pack(fill="x")
        self.tiles = {}
        for i, (key, label, color) in enumerate((("due_n", "未還人數", theme.RED), ("due_boxes", "欠箱子", theme.AMBER),
                                                 ("due_coins", "欠硬幣", theme.AMBER), ("paid", "已歸還", theme.GREEN))):
            box = tk.Frame(tiles, bg=theme.TILE, highlightthickness=1, highlightbackground=theme.BORDER,
                           padx=px(16), pady=px(10))
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(10), 0))
            tiles.columnconfigure(i, weight=1, uniform="tile")
            tk.Label(box, text=label, bg=theme.TILE, fg=theme.MUTED, font=theme.font(10)).pack(anchor="w")
            self.tiles[key] = tk.Label(box, bg=theme.TILE, fg=color, font=theme.font(22, "bold"))
            self.tiles[key].pack(anchor="w")
        self.warn = ttk.Label(main, foreground=theme.AMBER)
        self.warn.pack(anchor="w", pady=(px(8), 0))

        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=px(8))
        self.filter_buttons = {}
        for value, text in FILTERS:
            b = ttk.Radiobutton(bar, text=text, value=value, variable=self.filter_var, style="Toggle.TButton",
                                command=self.refresh_table)
            b.pack(side="left", padx=(0, px(6)))
            self.filter_buttons[value] = b
        ttk.Label(bar, text="搜尋").pack(side="left", padx=(px(14), px(6)))
        self.search = ttk.Entry(bar, textvariable=self.search_var, width=14)
        self.search.pack(side="left")
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        more = ttk.Menubutton(bar, text="更多")
        more.pack(side="right")
        menu = theme.menu(more)
        menu.add_command(label="新增玩家", command=self.add_member)
        menu.add_command(label="全部標記已還", command=self.all_returned)
        menu.add_command(label="刪除選取的玩家", command=self.delete_members)
        menu.add_separator()
        menu.add_command(label="編輯信件範本…", command=self.open_mail_templates)
        menu.add_command(label="匯出 CSV…", command=self.export_csv)
        more["menu"] = menu
        ttk.Button(bar, text="✓ 名字全部確認", command=self.confirm_all).pack(side="right", padx=px(8))

        table = ttk.Frame(main)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=COLS, show="headings", selectmode="extended")
        for col in COLS:
            self.tree.heading(col, text=HEAD[col])
            self.tree.column(col, width=px(WIDTH[col]), anchor="w" if col == "name" else "center",
                             stretch=col == "name")
        self.tree.tag_configure("odd", background=theme.ROW_ALT)
        self.tree.tag_configure("done", foreground=theme.GREEN)
        self.tree.tag_configure("muted", foreground=theme.MUTED)
        self.tree.tag_configure("check", foreground=theme.AMBER)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.empty = ttk.Label(table, justify="center", foreground=theme.MUTED, font=theme.font(12))
        self.tree.bind("<<TreeviewSelect>>", self.on_member_select)
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.tree.bind("<space>", lambda e: self.toggle_returned(self.tree.selection()))
        self.tree.bind("<Delete>", lambda e: self.delete_members())
        self.row_menu = theme.menu(self.tree)

    def _build_overview(self, over):
        px = self.px
        ttk.Label(over, text="所有場次中還未歸還的玩家（點「已寄信」打勾；雙擊一行跳到該場次）",
                  foreground=theme.MUTED).pack(anchor="w", pady=(0, px(10)))
        table = ttk.Frame(over)
        table.pack(fill="both", expand=True)
        self.over_tree = ttk.Treeview(table, columns=[c for c, _, _ in OVER_COLS], show="headings",
                                      selectmode="browse")
        for col, text, w in OVER_COLS:
            self.over_tree.heading(col, text=text)
            self.over_tree.column(col, width=px(w), anchor="w" if col in ("name", "raid") else "center",
                                  stretch=col == "name")
        self.over_tree.tag_configure("odd", background=theme.ROW_ALT)
        self.over_tree.tag_configure("mailed", foreground=theme.MUTED)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.over_tree.yview)
        self.over_tree.configure(yscrollcommand=scroll.set)
        self.over_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.over_tree.bind("<Button-1>", self.on_over_click)
        self.over_tree.bind("<Double-1>", self.on_over_double)
        self.over_rows = []
        self.over_total = ttk.Label(over, foreground=theme.AMBER, font=theme.font(12, "bold"))
        self.over_total.pack(anchor="w", pady=(px(10), 0))

    # ---------- refresh ----------
    def refresh_all(self):
        self.refresh_header()
        self.refresh_table()
        self.refresh_sessions()

    def refresh_sessions(self):
        self.sess_tree.delete(*self.sess_tree.get_children())
        for i, s in enumerate(self.store.sessions):
            due = logic.session_summary(s)["due_n"]
            tags = ("done",) if s["members"] and not due else ()
            self.sess_tree.insert("", "end", iid=str(i), values=(s["created"], s["raid"], due), tags=tags)
        idx = self._index(self.current)
        if idx is not None:
            self.sess_tree.selection_set(str(idx))

    def refresh_header(self):
        s = self.current
        if not s:
            self.raid_title.configure(text="還沒有場次")
            self.meta.configure(text="按「＋ 新場次」，或直接 Ctrl+V 貼上截圖")
            for tile in self.tiles.values():
                tile.configure(text="—")
            self.warn.configure(text="")
            return
        self.raid_title.configure(text=s["raid"] or "未命名副本")
        self.meta.configure(text=f"{s['created']}　·　完成 {s['games']} 場　·　{s['team_size']} 人隊　·　"
                                 f"歸還 {s['percent']}%（{logic.ROUNDING[s['rounding']]}）　·　"
                                 f"每場 {s['boxes']} 箱 {s['coins']} 幣　·　我：{s['me'] or '未設定'}")
        sm = logic.session_summary(s)
        self.tiles["due_n"].configure(text=f"{sm['due_n']} 人")
        self.tiles["due_boxes"].configure(text=sm["due_boxes"])
        self.tiles["due_coins"].configure(text=sm["due_coins"])
        self.tiles["paid"].configure(text=f"{sm['paid_n']} / {sm['due_n'] + sm['paid_n']}")
        warnings = []
        flagged = sum(bool(m.get("flag")) for m in s["members"])
        if flagged:
            warnings.append(f"⚠ {flagged} 個名字未確認")
        if s["members"] and not s["me"]:
            warnings.append("⚠ 未設定我的名字：右鍵自己那一行 →「設為我的名字」")
        if s["members"] and sm["empty_runs"] > 0:
            warnings.append(f"空位 {sm['empty_runs']} 場次")
        elif sm["empty_runs"] < 0:
            warnings.append("⚠ 次數加起來超過「場數 × 人數」，請檢查設定")
        self.warn.configure(text="　｜　".join(warnings))

    def refresh_table(self):
        s = self.current
        selected = [s["members"][int(i)] for i in self.tree.selection()] if s else []
        self.tree.delete(*self.tree.get_children())
        members = s["members"] if s else []
        counts = {"all": len(members),
                  "due": sum(not m["returned"] and logic.owes_something(s, m) for m in members),
                  "unmailed": sum(logic.needs_mail(s, m) for m in members),
                  "check": sum(bool(m.get("flag")) for m in members)}
        for value, text in FILTERS:
            self.filter_buttons[value].configure(text=f"{text}  {counts[value]}")
        if not members:
            self.empty.configure(text=EMPTY_HINT)
            self.empty.place(relx=0.5, rely=0.45, anchor="center")
            return

        query, mode, shown = self.search_var.get().strip().lower(), self.filter_var.get(), 0
        for i, m in enumerate(members):
            is_me, owes = m["name"] == s["me"], logic.owes_something(s, m)
            hidden = {"due": not owes or m["returned"], "unmailed": not logic.needs_mail(s, m),
                      "check": not m.get("flag")}.get(mode, False)
            if hidden:
                continue
            if query and query not in m["name"].lower() and not any(query in o.lower() for o in m.get("ocr", [])):
                continue
            b, c = logic.member_owed(s, m)
            name = ("⚠ " if m.get("flag") else "") + m["name"] + ("（我）" if is_me else "")
            box = lambda on: ("☑" if on else "☐") if owes else "—"
            values = (box(m["returned"]), box(m.get("mailed", False)), name, m["runs"],
                      "—" if is_me else b, "—" if is_me else c)
            tags = ["odd"] if shown % 2 else []
            tags.append("muted" if not owes else "done" if m["returned"] else "")
            if m.get("flag"):
                tags.append("check")
            self.tree.insert("", "end", iid=str(i), values=values, tags=[t for t in tags if t])
            shown += 1
        if shown:
            self.empty.place_forget()
        else:
            self.empty.configure(text="沒有符合的玩家")
            self.empty.place(relx=0.5, rely=0.3, anchor="center")
        keep = [str(i) for i, m in enumerate(members) if any(m is x for x in selected) and self.tree.exists(str(i))]
        self.tree.selection_set(keep)

    def refresh_overview(self):
        self.over_tree.delete(*self.over_tree.get_children())
        self.over_rows = rows = logic.outstanding(self.store.sessions)
        for i, r in enumerate(rows):
            tags = (["odd"] if i % 2 else []) + (["mailed"] if r["mailed"] else [])
            self.over_tree.insert("", "end", iid=str(i), tags=tags, values=(
                r["name"], r["raid"], r["created"], r["runs"], r["boxes"], r["coins"], "☑" if r["mailed"] else "☐"))
        unmailed = sum(not r["mailed"] for r in rows)
        self.over_total.configure(
            text=f"共 {len({r['name'] for r in rows})} 人未還：箱子 {sum(r['boxes'] for r in rows)}　"
                 f"硬幣 {sum(r['coins'] for r in rows)}　｜　未寄信 {unmailed} 筆")

    def on_over_click(self, event):
        tree = self.over_tree
        if tree.identify_region(event.x, event.y) != "cell" or tree.identify_column(event.x) != f"#{len(OVER_COLS)}":
            return None
        iid = tree.identify_row(event.y)
        if iid:
            m = self.over_rows[int(iid)]["member"]
            m["mailed"] = not m.get("mailed", False)
            self.changed()
            self.detail.refresh_light()
            self.refresh_overview()
        return "break"

    def on_over_double(self, event):
        iid = self.over_tree.identify_row(event.y)
        if not iid or self.over_tree.identify_column(event.x) == f"#{len(OVER_COLS)}":
            return
        row = self.over_rows[int(iid)]
        self.nb.select(0)
        if row["session"] is not self.current:
            self.select_session(row["session"])
        self.select_member(row["member"])

    def changed(self):
        self.save()
        self.refresh_all()

    # ---------- sessions ----------
    def _index(self, session):
        return next((i for i, s in enumerate(self.store.sessions) if s is session), None)

    def select_session(self, session):
        self.current = session
        self.tree.selection_set(())
        self.detail.show(session, None)
        self.refresh_all()

    def on_session_select(self, _event):
        sel = self.sess_tree.selection()
        if sel and self.store.sessions[int(sel[0])] is not self.current:
            self.select_session(self.store.sessions[int(sel[0])])

    def new_session(self):
        self.select_session(self.store.new_session())
        self.save()
        self.set_status("新場次已建立。用 Win+Shift+S 截圖，然後按 Ctrl+V。")

    def delete_session(self):
        s = self.current
        if not s or not messagebox.askyesno(
                "刪除場次", f"刪除 {s['created']} {s['raid']} 這個場次和它的截圖？\n刪除後無法復原。"):
            return
        self.store.delete_session(s)
        self.save()
        self.current = None
        if self.store.sessions:
            self.select_session(self.store.sessions[0])
        else:
            self.select_session(None)

    def open_settings(self):
        s, px = self.current, self.px
        if not s:
            return
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("場次設定")
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(background=theme.BG)
        frame = ttk.Frame(win, padding=px(20))
        frame.pack(fill="both", expand=True)
        raids = list(dict.fromkeys(["不死龍"] + [x["raid"] for x in self.store.sessions if x["raid"]]))
        names = sorted(self.store.known() | {m["name"] for m in s["members"]})
        fields = [("副本", "raid", ttk.Combobox, {"values": raids}),
                  ("我的名字", "me", ttk.Combobox, {"values": names}),
                  ("完成場數", "games", ttk.Spinbox, {"from_": 0, "to": 9999}),
                  ("隊伍人數", "team_size", ttk.Combobox, {"values": (15, 8)}),
                  ("歸還比例 %", "percent", ttk.Spinbox, {"from_": 0, "to": 100}),
                  ("每場箱子", "boxes", ttk.Spinbox, {"from_": 0, "to": 999}),
                  ("每場硬幣", "coins", ttk.Spinbox, {"from_": 0, "to": 999}),
                  ("小數處理", "rounding", ttk.Combobox, {"values": list(logic.ROUNDING.values()), "state": "readonly"})]
        values = {}
        for r, (label, key, widget, opts) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky="e", padx=(0, px(12)), pady=px(5))
            values[key] = tk.StringVar(value=logic.ROUNDING[s[key]] if key == "rounding" else s[key])
            widget(frame, textvariable=values[key], width=22, **opts).grid(row=r, column=1, sticky="w", pady=px(5))

        def save(_event=None):
            new = {}
            for label, key, _, _ in fields:
                raw = values[key].get().strip()
                if key == "rounding":
                    new[key] = next(k for k, text in logic.ROUNDING.items() if text == raw)
                elif key in INT_FIELDS:
                    if not raw.isdigit():
                        messagebox.showwarning("設定", f"「{label}」要填數字", parent=win)
                        return
                    new[key] = int(raw)
                else:
                    new[key] = raw
            s.update(new)
            self.store.remember_settings(s)
            win.destroy()
            self.changed()
            self.detail.refresh_light()

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(px(16), 0))
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="儲存", style="Accent.TButton", command=save).pack(side="right", padx=px(8))
        win.bind("<Return>", save)
        win.bind("<Escape>", lambda e: win.destroy())
        theme.dark_title_bar(win)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.grab_set()

    # ---------- members ----------
    def member(self, iid):
        return self.current["members"][int(iid)]

    def select_member(self, m):
        idx = next((i for i, x in enumerate(self.current["members"]) if x is m), None)
        if idx is None:
            return
        if not self.tree.exists(str(idx)):
            self.filter_var.set("all")
            self.search_var.set("")
            self.refresh_table()
        self.tree.selection_set(str(idx))
        self.tree.focus(str(idx))
        self.tree.see(str(idx))

    def select_next_flagged(self, after):
        members = self.current["members"]
        start = next(i for i, x in enumerate(members) if x is after)
        nxt = next((m for m in members[start + 1:] + members[:start] if m.get("flag")), None)
        if nxt is not None:
            self.select_member(nxt)
            self.detail.show(self.current, nxt)  # now, not when <<TreeviewSelect>> arrives, so focus sticks
            self.detail.focus_name()
        else:
            self.set_status("全部名字已確認 ✓")

    def on_member_select(self, _event=None):
        sel = self.tree.selection()
        m = self.member(sel[0]) if self.current and sel else None
        if m is not None and m is self.detail.member:
            self.detail.refresh_light()
        else:
            self.detail.show(self.current, m)

    def update_member(self, m, **changes):
        m.update(changes)
        self.changed()
        self.detail.refresh_light()

    def rename_member(self, m, name) -> bool:
        if not name:
            return False
        if any(o is not m and o["name"] == name for o in self.current["members"]):
            messagebox.showwarning("名字重複", f"名單已經有「{name}」。")
            return False
        if self.current["me"] == m["name"]:
            self.current["me"] = name
        m["name"] = name
        self.store.confirm(m)
        self.changed()
        self.detail.refresh_light()
        return True

    def on_click(self, event):
        column = self.tree.identify_column(event.x)
        if self.tree.identify_region(event.x, event.y) != "cell" or column not in ("#1", "#2"):
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            (self.toggle_returned if column == "#1" else self.toggle_mailed)([iid])
        return "break"

    def on_double(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        key = COLS[int(self.tree.identify_column(event.x)[1:]) - 1]
        if key == "runs":
            self.detail.focus_runs()
        elif key == "name":
            self.detail.focus_name()

    def on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        m, menu = self.member(iid), self.row_menu
        menu.delete(0, "end")
        menu.add_command(label="標記未還" if m["returned"] else "標記已還",
                         command=lambda: self.toggle_returned(self.tree.selection()))
        menu.add_command(label="標記未寄信" if m.get("mailed") else "標記已寄信",
                         command=lambda: self.toggle_mailed(self.tree.selection()))
        menu.add_command(label="確認名字", command=lambda: self.confirm_members(self.tree.selection()))
        menu.add_command(label="設為我的名字", command=lambda: self.set_me(m))
        menu.add_separator()
        menu.add_command(label="刪除玩家", command=self.delete_members)
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_returned(self, iids):
        if not self.current:
            return
        members = [self.member(i) for i in iids if logic.owes_something(self.current, self.member(i))]
        if members:
            self.set_returned(members, not all(m["returned"] for m in members))

    def set_returned(self, members, value: bool) -> bool:
        """Mark members returned / not returned. Unticking asks first. Returns False if the user backed out."""
        if not value:
            names = "、".join(m["name"] for m in members if m["returned"])
            if names and not messagebox.askyesno(
                    "取消已還", f"確定要取消「{names}」的已還記錄？\n會變回未還。",
                    icon=messagebox.WARNING, default=messagebox.NO):
                self.detail.refresh_light()  # put the panel switch back
                return False
        for m in members:
            m["returned"] = value
        self.changed()
        self.detail.refresh_light()
        return True

    def toggle_mailed(self, iids):
        if not self.current:
            return
        members = [self.member(i) for i in iids if logic.owes_something(self.current, self.member(i))]
        if members:
            self.set_mailed(members, not all(m.get("mailed", False) for m in members))

    def set_mailed(self, members, value: bool):
        for m in members:
            m["mailed"] = value
        self.changed()
        self.detail.refresh_light()

    def copy_text(self, text: str, what: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(f"已複製{what}：{text}")

    def open_mail_templates(self):
        px, mail = self.px, self.store.data["mail"]
        sample = (self.current, self.detail.member) if self.current and self.detail.member else None
        if sample is None:
            demo = {"raid": "不死龍", "created": "2026-11-05 21:00", "me": "", "percent": 70, "boxes": 1, "coins": 1,
                    "rounding": "half_up"}
            sample = (demo, {"name": "玩家名字", "runs": 110})
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("信件範本")
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(background=theme.BG)
        frame = ttk.Frame(win, padding=px(20))
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="標題").grid(row=0, column=0, sticky="nw", padx=(0, px(12)), pady=px(5))
        title_var = tk.StringVar(value=mail["title"])
        ttk.Entry(frame, textvariable=title_var, width=44, font=theme.font(11)).grid(row=0, column=1, sticky="we")
        ttk.Label(frame, text="內容").grid(row=1, column=0, sticky="nw", padx=(0, px(12)), pady=px(8))
        body = tk.Text(frame, width=44, height=5, wrap="word", font=theme.font(11), bg=theme.MENU, fg=theme.TEXT,
                       insertbackground=theme.TEXT, relief="flat", padx=px(8), pady=px(6),
                       highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        body.insert("1.0", mail["body"])
        body.grid(row=1, column=1, sticky="we", pady=px(8))
        fields = "　".join("{" + f + "}" for f in logic.MAIL_FIELDS)
        ttk.Label(frame, text=f"可以用：{fields}\n收件人會自動用玩家名字。", foreground=theme.MUTED,
                  justify="left").grid(row=2, column=1, sticky="w")
        ttk.Label(frame, text="預覽", foreground=theme.MUTED).grid(row=3, column=0, sticky="nw", pady=(px(14), 0))
        preview = ttk.Label(frame, foreground=theme.AMBER, justify="left", wraplength=px(420))
        preview.grid(row=3, column=1, sticky="w", pady=(px(14), 0))

        def update_preview(*_):
            s, m = sample
            preview.configure(text=f"標題：{logic.render_mail(title_var.get(), s, m)}\n收件人：{m['name']}\n"
                                   f"內容：{logic.render_mail(body.get('1.0', 'end-1c'), s, m)}")

        def reset():
            title_var.set(logic.MAIL_DEFAULT["title"])
            body.delete("1.0", "end")
            body.insert("1.0", logic.MAIL_DEFAULT["body"])
            update_preview()

        def save():
            mail.update(title=title_var.get(), body=body.get("1.0", "end-1c"))
            self.save()
            win.destroy()
            self.detail.refresh_light()
            self.set_status("信件範本已儲存。")

        title_var.trace_add("write", update_preview)
        body.bind("<KeyRelease>", update_preview)
        update_preview()
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="we", pady=(px(18), 0))
        ttk.Button(buttons, text="恢復預設", command=reset).pack(side="left")
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="儲存", style="Accent.TButton", command=save).pack(side="right", padx=px(8))
        win.bind("<Escape>", lambda e: win.destroy())
        theme.dark_title_bar(win)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.grab_set()

    def confirm_members(self, iids):
        for i in iids:
            self.store.confirm(self.member(i))
        self.changed()
        self.detail.refresh_light()

    def set_me(self, m):
        self.current["me"] = m["name"]
        self.store.remember_settings(self.current)
        self.changed()
        self.detail.refresh_light()

    def add_member(self):
        if not self.current:
            self.new_session()
        names = {m["name"] for m in self.current["members"]}
        name, n = "新玩家", 2
        while name in names:
            name, n = f"新玩家{n}", n + 1
        m = {"name": name, "runs": self.current["games"], "left": False, "returned": False, "ocr": [], "flag": "new"}
        self.current["members"].append(m)
        self.changed()
        self.select_member(m)
        self.detail.show(self.current, m)
        self.detail.focus_name()

    def confirm_all(self):
        if not self.current:
            return
        for m in self.current["members"]:
            self.store.confirm(m)
        self.changed()
        self.detail.refresh_light()
        self.set_status("名字已確認，下次截圖會自動認得。")

    def all_returned(self):
        if not self.current:
            return
        for m in self.current["members"]:
            if logic.owes_something(self.current, m):
                m["returned"] = True
        self.changed()
        self.detail.refresh_light()

    def delete_members(self):
        sel = self.tree.selection()
        if not self.current or not sel:
            return
        names = "、".join(self.member(i)["name"] for i in sel)
        if not messagebox.askyesno("刪除玩家", f"從這個場次刪除：{names}？"):
            return
        for i in sorted((int(i) for i in sel), reverse=True):
            del self.current["members"][i]
        self.tree.selection_set(())
        self.detail.show(self.current, None)
        self.changed()

    def export_csv(self):
        s = self.current
        if not s or not s["members"]:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile=f"{s['raid']}_{s['id']}.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig so Excel shows Chinese
            w = csv.writer(f)
            w.writerow(["名字", "完成次數", "應還箱子", "應還硬幣", "已還", "已寄信"])
            for m in s["members"]:
                is_me = m["name"] == s["me"]
                b, c = logic.member_owed(s, m)
                yes_no = lambda on: "我" if is_me else ("是" if on else "否")
                w.writerow([m["name"], m["runs"], "" if is_me else b, "" if is_me else c,
                            yes_no(m["returned"]), yes_no(m.get("mailed", False))])
        self.set_status(f"已匯出：{path}")

    # ---------- paste + OCR ----------
    def on_paste(self, event=None):
        try:
            clip = ImageGrab.grabclipboard()
        except OSError:
            clip = None
        if isinstance(clip, list):  # files copied in Explorer
            files = [p for p in clip if str(p).lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
            clip = Image.open(files[0]) if files else None
        if not isinstance(clip, Image.Image):
            if event is not None and isinstance(event.widget, TEXT_INPUTS):
                return None  # ordinary text paste into an input box
            self.set_status("剪貼簿沒有圖片。先按 Win+Shift+S 截取「連戰統計」視窗。")
            return "break"
        if self.busy:
            return "break"
        if not self.current:
            self.new_session()
        self.busy = True
        self.set_status("辨識中…")
        img, session = clip.convert("RGB"), self.current
        shot = self.store.add_shot(session, img)
        threading.Thread(target=self._ocr_worker, args=(img, session, shot), daemon=True).start()
        self.root.after(100, self._poll_ocr)
        return "break"

    def _ocr_worker(self, img, session, shot):
        try:
            self.results.put((session, shot, ocr.parse_sheet(img), None))
        except Exception as exc:  # report anything to the UI instead of dying silently in the thread
            self.results.put((session, shot, None, exc))

    def _poll_ocr(self):
        try:
            session, shot, sheet, error = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_ocr)
            return
        self.busy = False
        if self._index(session) is None:
            return  # session deleted while OCR ran
        if error is not None or not sheet.rows:
            self.store.remove_shot(session, shot)
            self.save()
            if error is not None:
                self.set_status("辨識失敗。")
                messagebox.showerror("辨識失敗", str(error))
            else:
                self.set_status("沒有讀到成員。請截取整個「連戰統計」視窗再試。")
            return
        rows, flagged = self.store.merge_sheet(session, sheet, shot)
        self.save()
        self.refresh_all()
        msg = f"讀到 {rows} 人，完成 {session['games']} 場。"
        if flagged:
            msg += f"　{flagged} 個名字要檢查：右邊對照截圖，改好按 Enter 會跳到下一個。"
            if session is self.current:
                self.select_member(next(m for m in session["members"] if m.get("flag")))
        self.set_status(msg)

    # ---------- misc ----------
    def save(self):
        try:
            self.store.save()
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc))

    def set_status(self, text):
        self.status.configure(text=text)

    def on_close(self):
        self.save()
        self.root.destroy()


def main():
    theme.before_tk()
    root = tk.Tk()
    root.withdraw()
    theme.apply(root)
    App(root, Store(DATA_FILE))
    theme.dark_title_bar(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
