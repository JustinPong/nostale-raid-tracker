"""Owed-reward math and OCR name matching. Pure functions, no UI."""
import re
from difflib import SequenceMatcher

ROUNDING = {"half_up": "四捨五入", "ceil": "無條件進位", "floor": "無條件捨去"}
NAME_JUNK = re.compile(r"[\s/\\,.;:'\"`|()（）〔〕\[\]{}<>]")
MATCH_MIN = 0.5     # similarity needed to auto-match an OCR reading to a known player
MATCH_MARGIN = 0.15  # best match must beat the runner-up by this much


def owed(runs: int, per_game: int, percent: int, rounding: str = "half_up") -> int:
    """Items to hand back: runs * per_game * percent%, rounded to whole items."""
    hundredths = runs * per_game * percent
    if rounding == "ceil":
        return -(-hundredths // 100)
    if rounding == "floor":
        return hundredths // 100
    return (hundredths + 50) // 100


def clean_name(text: str) -> str:
    return NAME_JUNK.sub("", text)


def resolve_name(candidates: list[str], known: set[str], aliases: dict[str, str]) -> tuple[str, str]:
    """Map OCR readings (best first) to a player name.

    Returns (name, flag): flag "" = sure (alias or exact), "fuzzy" = guessed known player, "new" = unknown name.
    """
    cands = [c for c in dict.fromkeys(clean_name(c) for c in candidates) if c]
    if not cands:
        return "", "new"
    for c in cands:
        if c in aliases:
            return aliases[c], ""
    for c in cands:
        if c in known:
            return c, ""

    scores = {}
    for k in known:
        scores[k] = max(SequenceMatcher(None, c, k).ratio() for c in cands)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if ranked and ranked[0][1] >= MATCH_MIN:
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if ranked[0][1] - runner_up >= MATCH_MARGIN:
            return ranked[0][0], "fuzzy"
    return cands[0], "new"


def member_owed(session: dict, member: dict) -> tuple[int, int]:
    if member["name"] == session.get("me"):
        return 0, 0
    pct, rnd = session["percent"], session["rounding"]
    return (owed(member["runs"], session["boxes"], pct, rnd),
            owed(member["runs"], session["coins"], pct, rnd))


def owes_something(session: dict, member: dict) -> bool:
    """False for yourself and for players whose share rounds to nothing (e.g. 0 runs)."""
    return any(member_owed(session, member))


def session_summary(session: dict) -> dict:
    due_n = paid_n = due_boxes = due_coins = 0
    for m in session["members"]:
        b, c = member_owed(session, m)
        if not (b or c):
            continue
        if m["returned"]:
            paid_n += 1
        else:
            due_n += 1
            due_boxes += b
            due_coins += c
    slots = session["games"] * session["team_size"]
    used = sum(m["runs"] for m in session["members"])
    return {"due_n": due_n, "paid_n": paid_n, "due_boxes": due_boxes, "due_coins": due_coins,
            "empty_runs": slots - used}


def outstanding(sessions: list[dict]) -> list[dict]:
    """Everything not yet returned, one row per player per session, grouped by player."""
    rows = []
    for s in sessions:
        for m in s["members"]:
            b, c = member_owed(s, m)
            if m["returned"] or not (b or c):
                continue
            rows.append({"session": s, "member": m, "name": m["name"], "raid": s["raid"], "created": s["created"],
                         "runs": m["runs"], "boxes": b, "coins": c, "mailed": m.get("mailed", False)})
    return sorted(rows, key=lambda r: (r["name"], r["created"]))


def can_mail(session: dict, member: dict) -> bool:
    """A reminder only makes sense while something is owed and not yet returned."""
    return owes_something(session, member) and not member["returned"]


def needs_mail(session: dict, member: dict) -> bool:
    return can_mail(session, member) and not member.get("mailed", False)


MAIL_DEFAULT = {"title": "{副本}{完成次數}回{應還箱子}", "body": "{副本}{完成次數}回{應還箱子} 可以寄給我嗎 謝謝"}
MAIL_FIELDS = ("副本", "名字", "完成次數", "應還箱子", "應還硬幣", "日期")


def render_mail(template: str, session: dict, member: dict) -> str:
    """Fill {副本} {名字} {完成次數} {應還箱子} {應還硬幣} {日期}; anything else in braces is left as typed."""
    b, c = member_owed(session, member)
    values = dict(zip(MAIL_FIELDS, (session["raid"], member["name"], member["runs"], b, c, session["created"][:10])))
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template
