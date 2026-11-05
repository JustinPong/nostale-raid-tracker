"""JSON persistence: sessions, known players, learned OCR aliases, pasted screenshots."""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import logic

DEFAULT = {
    "version": 1,
    "settings": {"me": "", "raid": "不死龍", "team_size": 15, "percent": 70,
                 "boxes": 1, "coins": 1, "rounding": "half_up"},
    "players": [],
    "aliases": {},
    "sessions": [],
}


class Store:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in DEFAULT.items():
                self.data.setdefault(key, value)
        else:
            self.data = json.loads(json.dumps(DEFAULT))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def sessions(self) -> list[dict]:
        return self.data["sessions"]

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def known(self) -> set[str]:
        return set(self.data["players"])

    def new_session(self) -> dict:
        now = datetime.now()
        s = {"id": now.strftime("%Y%m%d-%H%M%S"), "created": now.strftime("%Y-%m-%d %H:%M"),
             "games": 0, "members": [], "shots": [], **self.settings}
        self.sessions.insert(0, s)
        return s

    def delete_session(self, session: dict):
        self.sessions.remove(session)
        shutil.rmtree(self.path.parent / "screens" / session["id"], ignore_errors=True)

    def add_shot(self, session: dict, img) -> str:
        """Keep a pasted screenshot so names can be checked against it later. Returns its data-relative path."""
        rel = f"screens/{session['id']}/{datetime.now():%H%M%S%f}.png"
        self.shot_file(rel).parent.mkdir(parents=True, exist_ok=True)
        img.save(self.shot_file(rel))
        session.setdefault("shots", []).append(rel)
        return rel

    def remove_shot(self, session: dict, rel: str):
        if rel in session.get("shots", []):
            session["shots"].remove(rel)
        self.shot_file(rel).unlink(missing_ok=True)

    def shot_file(self, rel: str) -> Path:
        return self.path.parent / rel

    def remember_settings(self, session: dict):
        for key in self.settings:
            self.settings[key] = session[key]

    def confirm(self, member: dict):
        """Member name is correct: learn it, and map every OCR reading of it to it."""
        name = member["name"]
        if name and name not in self.data["players"]:
            self.data["players"].append(name)
        for reading in member.get("ocr", []):
            reading = logic.clean_name(reading)
            if reading and reading != name:
                self.data["aliases"][reading] = name
        member["flag"] = ""

    def merge_sheet(self, session: dict, sheet, shot: str | None = None) -> tuple[int, int]:
        """Add OCR rows to a session (pasting page 2 after page 1 merges). Returns (rows, rows needing a check)."""
        known, aliases = self.known(), self.data["aliases"]
        by_name = {m["name"]: m for m in session["members"]}
        flagged = 0
        for row in sheet.rows:
            if row.exact:
                # pixel-exact in the game font: trust it, unless the user deliberately renamed this player before
                name, flag = aliases.get(logic.clean_name(row.candidates[0]), row.candidates[0]), ""
                if name not in self.data["players"]:
                    self.data["players"].append(name)
            else:
                name, flag = logic.resolve_name(row.candidates, known, aliases)
                if name in by_name and flag:
                    # Fuzzy guess collides with someone already listed: keep the raw reading so nobody is overwritten.
                    name, flag = logic.clean_name(row.candidates[0]) or "?", "new"
            member = by_name.get(name)
            if member is None:
                member = {"name": name, "runs": 0, "left": False, "returned": False, "ocr": [], "flag": flag}
                session["members"].append(member)
                by_name[name] = member
            elif row.exact:
                member["flag"] = ""
            member["runs"] = row.runs if row.runs is not None else member["runs"]
            member["left"] = row.left
            member["ocr"] = list(dict.fromkeys(member["ocr"] + row.candidates))
            if shot:
                member.update(shot=shot, box=list(row.box), name_box=list(row.name_box))
            if row.runs is None:
                member["flag"] = member["flag"] or "new"
            flagged += bool(member["flag"])
        if sheet.games and sheet.games > session["games"]:
            session["games"] = sheet.games
        return len(sheet.rows), flagged
