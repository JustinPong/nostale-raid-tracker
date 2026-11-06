"""Right-hand panel: the selected player next to the screenshot row it was read from."""
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

import logic
import theme

PLACEHOLDER = "在左邊選一位玩家\n\n這裡會顯示截圖中對應的那一行\n方便對照名字有沒有讀錯"


def _marked(img: Image.Image, box) -> Image.Image:
    """Screenshot with one row highlighted."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(box, fill=(87, 200, 255, 50), outline=(87, 200, 255, 255), width=2)
    return Image.alpha_composite(img.convert("RGBA"), layer)


class DetailPanel(ttk.Frame):
    def __init__(self, parent, app, width: int):
        px = app.px
        super().__init__(parent, padding=(px(16), 0, px(4), px(4)), width=width + px(20))
        self.pack_propagate(False)  # fixed width: long names or big screenshots must not push the table around
        self.app, self.width = app, width
        self.session = self.member = None
        self.loading = False
        self._cache: dict[str, Image.Image] = {}
        self._photos = {}  # Tk drops images that aren't referenced from Python
        self._scale, self._shot, self._top, self._job = 1.0, None, 0, None

        self.placeholder = ttk.Label(self, text=PLACEHOLDER, justify="center", foreground=theme.MUTED,
                                     font=theme.font(11), width=30, anchor="center")
        self.body = ttk.Frame(self, width=width)

        self.title = ttk.Label(self.body, font=theme.font(16, "bold"), wraplength=width)
        self.title.pack(anchor="w")
        self.sub = ttk.Label(self.body, foreground=theme.MUTED)
        self.sub.pack(anchor="w")

        self._section("截圖中的名字（放大）")
        self.zoom = tk.Label(self.body, bg=theme.TILE, highlightthickness=1, highlightbackground=theme.BORDER,
                             anchor="w", padx=px(4), pady=px(4))
        self.zoom.pack(fill="x", pady=(px(4), 0))

        self.chips_head = self._section("OCR 讀到（點一下套用）")
        self.chips = ttk.Frame(self.body)
        self.chips.pack(fill="x", pady=(px(4), 0))

        self._section("正確名字")
        name_row = ttk.Frame(self.body)
        name_row.pack(fill="x", pady=(px(4), 0))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(name_row, textvariable=self.name_var, font=theme.font(12))
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.name_entry.bind("<Return>", lambda e: self.confirm())
        self.name_entry.bind("<KP_Enter>", lambda e: self.confirm())
        ttk.Button(name_row, text="✓ 確認", style="Accent.TButton", command=self.confirm).pack(
            side="left", padx=(px(8), 0))

        grid = ttk.Frame(self.body)
        grid.pack(fill="x", pady=(px(12), 0))
        self.runs_var, self.ret_var, self.mail_var = tk.StringVar(), tk.BooleanVar(), tk.BooleanVar()
        ttk.Label(grid, text="完成次數").grid(row=0, column=0, sticky="w")
        self.runs_box = ttk.Spinbox(grid, textvariable=self.runs_var, from_=0, to=9999, width=6)
        self.runs_box.grid(row=0, column=1, sticky="w", padx=(px(8), px(18)))
        self.ret_check = ttk.Checkbutton(grid, text="已歸還", variable=self.ret_var, style="Switch.TCheckbutton")
        self.ret_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(10), 0))
        self.mail_check = ttk.Checkbutton(grid, text="已寄信", variable=self.mail_var, style="Switch.TCheckbutton")
        self.mail_check.grid(row=1, column=2, sticky="w", pady=(px(10), 0))
        self.owed = ttk.Label(grid, foreground=theme.AMBER, font=theme.font(12, "bold"))
        self.owed.grid(row=2, column=0, columnspan=3, sticky="w", pady=(px(8), 0))
        self.runs_var.trace_add("write", lambda *_: self._edited("runs"))
        self.ret_var.trace_add("write", lambda *_: self._edited("returned"))
        self.mail_var.trace_add("write", lambda *_: self._edited("mailed"))

        mail_head = self._section("寄信（複製後貼到遊戲信件）")
        ttk.Button(mail_head, text="編輯範本", command=app.open_mail_templates).pack(side="right")
        mail = ttk.Frame(self.body)
        mail.pack(fill="x", pady=(px(4), 0))
        mail.columnconfigure(1, weight=1)
        self.mail_fields = {}
        for r, (key, label) in enumerate((("title", "標題"), ("to", "收件人"), ("body", "內容"))):  # in-game order
            ttk.Label(mail, text=label, foreground=theme.MUTED).grid(row=r, column=0, sticky="nw", pady=px(2))
            text = ttk.Label(mail, wraplength=width - px(110), justify="left")
            text.grid(row=r, column=1, sticky="w", padx=px(8), pady=px(2))
            link = ttk.Label(mail, text="複製", cursor="hand2", font=theme.font(10, "underline"))
            link.grid(row=r, column=2, sticky="ne", pady=px(2))
            link.bind("<Button-1>", lambda e, k=key, l=label: self._copy(k, l))
            self.mail_fields[key] = (text, link)

        shot_head = self._section("截圖（點一行可跳到該玩家）")
        ttk.Button(shot_head, text="放大", command=self.open_large).pack(side="right")
        self.canvas = tk.Canvas(self.body, bg=theme.BG, highlightthickness=0, cursor="hand2",
                                width=width, height=px(40))
        self.canvas.pack(anchor="w", pady=(px(4), 0))
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-1>", lambda e: self.open_large())
        self.body.bind("<Configure>", lambda e: self._schedule_render())

        self.show(None, None)

    def _section(self, text) -> ttk.Frame:
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(self.app.px(10), 0))
        ttk.Label(row, text=text, foreground=theme.MUTED, font=theme.font(9)).pack(side="left", anchor="s")
        return row

    # ---------- public ----------
    def show(self, session, member):
        self.session, self.member = session, member
        if member is None:
            self.body.pack_forget()
            self.placeholder.pack(fill="both", expand=True)
            return
        self.placeholder.pack_forget()
        self.body.pack(fill="both", expand=True)
        self.loading = True
        self.name_var.set(member["name"])
        self.runs_var.set(str(member["runs"]))
        self.ret_var.set(member["returned"])
        self.mail_var.set(member.get("mailed", False))
        self.loading = False
        if member.get("flag"):  # OCR alternatives only matter while the name is unconfirmed
            pady = (self.app.px(10), 0)
            self.chips_head.pack(fill="x", pady=pady, after=self.zoom)
            self.chips.pack(fill="x", pady=(self.app.px(4), 0), after=self.chips_head)
        else:
            self.chips_head.pack_forget()
            self.chips.pack_forget()
        self._build_chips()
        self.refresh_light()
        self._render()

    def refresh_light(self):
        """Update labels/toggles after a change without disturbing what's typed in the name box."""
        s, m = self.session, self.member
        if m is None:
            return
        is_me = m["name"] == s["me"]
        self.title.configure(text=m["name"] + ("（我）" if is_me else ""))
        bits = [f"完成 {m['runs']} 場"]
        if m.get("flag"):
            bits.append("⚠ 名字未確認")
        self.sub.configure(text="　·　".join(bits), foreground=theme.AMBER if m.get("flag") else theme.MUTED)
        b, c = logic.member_owed(s, m)
        owes = not is_me and bool(b or c)
        self.owed.configure(text=f"應還　箱子 {b}　·　硬幣 {c}" if owes else
                            ("自己，不用還" if is_me else "沒有要還的"))
        mailable = owes and not m["returned"]  # returned: nothing left to remind them about
        self.ret_check.state(["!disabled"] if owes else ["disabled"])
        self.mail_check.state(["!disabled"] if mailable else ["disabled"])
        mail = self.app.store.data["mail"]
        texts = {"to": m["name"], "title": logic.render_mail(mail["title"], s, m),
                 "body": logic.render_mail(mail["body"], s, m)}
        for key, (label, link) in self.mail_fields.items():
            label.configure(text=texts[key] if mailable else "—")
            link.configure(foreground=theme.ACCENT if mailable else theme.MUTED)
        self.loading = True
        if self.runs_var.get() != str(m["runs"]):
            self.runs_var.set(str(m["runs"]))
        if self.ret_var.get() != m["returned"]:
            self.ret_var.set(m["returned"])
        if self.mail_var.get() != m.get("mailed", False):
            self.mail_var.set(m.get("mailed", False))
        self.loading = False

    def focus_name(self):
        self.name_entry.focus_set()
        self.name_entry.select_range(0, "end")

    def focus_runs(self):
        self.runs_box.focus_set()
        self.runs_box.selection_range(0, "end")

    def confirm(self):
        if self.member is not None and self.app.rename_member(self.member, self.name_var.get().strip()):
            self.app.select_next_flagged(self.member)

    # ---------- internals ----------
    def _edited(self, key):
        if self.loading or self.member is None:
            return
        if key == "runs":
            raw = self.runs_var.get().strip()
            if raw.isdigit() and int(raw) != self.member["runs"]:
                self.app.update_member(self.member, runs=int(raw))
        elif key == "mailed":
            self.app.set_mailed([self.member], self.mail_var.get())
        else:
            self.app.set_returned([self.member], self.ret_var.get())

    def _copy(self, key, label):
        if self.member is None or not logic.can_mail(self.session, self.member):
            return
        s, m, mail = self.session, self.member, self.app.store.data["mail"]
        text = m["name"] if key == "to" else logic.render_mail(mail[key], s, m)
        self.app.copy_text(text, label)

    def _build_chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        readings = [r for r in dict.fromkeys(logic.clean_name(o) for o in self.member.get("ocr", [])) if r][:6]
        if not readings:
            ttk.Label(self.chips, text="（沒有）", foreground=theme.MUTED).grid(row=0, column=0, sticky="w")
        for i, text in enumerate(readings):
            ttk.Button(self.chips, text=text, command=lambda t=text: self._use(t)).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, self.app.px(6)), pady=(0, self.app.px(4)))

    def _use(self, text):
        self.name_var.set(text)
        self.name_entry.focus_set()
        self.name_entry.icursor("end")

    def _schedule_render(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(80, self._render)

    def _image(self, path) -> Image.Image:
        key = str(path)
        if key not in self._cache:
            self._cache[key] = Image.open(path).convert("RGB")
        return self._cache[key]

    def _render(self):
        self._job = None
        m, px = self.member, self.app.px
        self.canvas.delete("all")
        if m is None:
            return
        path = self.app.store.shot_file(m["shot"]) if m.get("shot") else None
        if path is None or not path.exists():
            self._photos.clear()
            self.zoom.configure(image="", text="沒有截圖（手動新增的玩家）", fg=theme.MUTED, font=theme.font(10))
            self.canvas.configure(height=px(4))
            self._shot = None
            return
        img = self._image(path)
        width = self.body.winfo_width() if self.body.winfo_width() > 1 else self.width

        # zoomed name: name cell trimmed to where the text actually is
        cell = img.crop(tuple(m["name_box"]))
        ink = ImageOps.grayscale(cell).point(lambda p: 255 if p > 110 else 0).getbbox()
        if ink:
            cell = cell.crop((max(0, ink[0] - 6), 0, min(cell.width, ink[2] + 6), cell.height))
        k = min(3.5, (width - px(12)) / max(1, cell.width))
        self._photos["zoom"] = ImageTk.PhotoImage(cell.resize((max(1, int(cell.width * k)),
                                                                max(1, int(cell.height * k))), Image.LANCZOS))
        self.zoom.configure(image=self._photos["zoom"], text="")

        # screenshot at full panel width with the row highlighted; if it doesn't fit, the slice around the row
        room = max(self.body.winfo_height() - self.canvas.winfo_y() - px(6), px(120))
        k = min(width / img.width, 2.0)
        y0, y1 = 0, img.height
        if img.height * k > room:
            span = room / k
            middle = (m["box"][1] + m["box"][3]) / 2
            y0 = int(max(0, min(img.height - span, middle - span / 2)))
            y1 = int(y0 + span)
        part = _marked(img, m["box"]).crop((0, y0, img.width, y1))
        size = (max(1, int(part.width * k)), max(1, int(part.height * k)))
        self._photos["shot"] = ImageTk.PhotoImage(part.resize(size, Image.LANCZOS))
        self.canvas.configure(width=size[0], height=size[1])
        self.canvas.create_image(0, 0, anchor="nw", image=self._photos["shot"])
        self._scale, self._shot, self._top = k, m["shot"], y0

    def open_large(self):
        m = self.member
        if m is None or not self._shot:
            return
        img = self._image(self.app.store.shot_file(m["shot"]))
        k = min(2.0, self.winfo_screenheight() * 0.8 / img.height, self.winfo_screenwidth() * 0.8 / img.width)
        photo = ImageTk.PhotoImage(_marked(img, m["box"]).resize((int(img.width * k), int(img.height * k)),
                                                                  Image.LANCZOS))
        win = tk.Toplevel(self)
        win.withdraw()
        win.title(f"截圖：{m['name']}")
        win.transient(self.winfo_toplevel())
        win.configure(background=theme.BG)
        view = tk.Label(win, image=photo, bg=theme.BG, bd=0, cursor="hand2")
        view.image = photo
        view.pack(padx=self.app.px(10), pady=self.app.px(10))
        ttk.Label(win, text="點圖片或按 Esc 關閉", foreground=theme.MUTED).pack(pady=(0, self.app.px(8)))
        view.bind("<Button-1>", lambda e: win.destroy())
        win.bind("<Escape>", lambda e: win.destroy())
        theme.dark_title_bar(win)
        win.update_idletasks()
        win.geometry(f"+{(win.winfo_screenwidth() - win.winfo_reqwidth()) // 2}"
                     f"+{max(0, (win.winfo_screenheight() - win.winfo_reqheight()) // 2 - self.app.px(30))}")
        win.deiconify()
        win.focus_set()

    def on_canvas_click(self, event):
        if not self._shot or self.session is None:
            return
        y = self._top + event.y / self._scale
        for m in self.session["members"]:
            box = m.get("box")
            if m.get("shot") == self._shot and box and box[1] <= y <= box[3]:
                self.app.select_member(m)
                return
