# 副本代打記帳 (raid tracker)

Tracks who still owes their share (default 70%) of raid boxes/coins after you carry an AFK team.

## Run

Double-click `run.bat` (or the desktop shortcut).

First-time setup on a new PC:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Needs Windows 10/11 with the Traditional Chinese OCR language (comes with the zh-TW / zh-HK language pack).

## Use

1. 「＋ 新場次」 for each new raid streak.
2. In game open 連戰統計 → `Win+Shift+S` → snip the whole window → back in the app press `Ctrl+V`. Do the same for page 2.
3. ⚠ rows = name needs a check. The right panel shows that row of the screenshot (zoomed name + highlighted row; 「放大」 for a big view). Fix the name, press Enter → jumps to the next ⚠ row (right-click → 確認名字 also works on several rows at once). Fixes are remembered, so the same misreading is auto-corrected next time.
4. Click the 已還 box (or Space) when someone hands their share back; unticking asks first. Right-click a row for 設為我的名字 / 確認名字 / 刪除.
5. Chasing people: filter 「未寄信」, pick a player, and the right panel's 寄信 section has 標題 / 收件人 / 內容 ready to 複製 into the in-game mail. Tick 已寄信 once sent. The text comes from an editable template (「編輯範本」, placeholders `{副本} {名字} {完成次數} {應還箱子} {應還硬幣} {日期}`), default `{副本}{完成次數}回{應還箱子}` → 「不死龍110回77」.
6. 「欠款總覽」 lists every unpaid share across all sessions, one row per player per raid; tick 已寄信 there, double-click to jump to the session.

Owed per player = 完成次數 × 每場箱子/硬幣 × 歸還比例%, rounded per the 小數處理 setting (⚙ 設定). Your own row and players with nothing to hand back are never billed.

## How names are read

The game draws names with GDI Tahoma 12px without anti-aliasing; Windows font linking draws Chinese with the MingLiU 12px bitmaps. `glyphs.py` renders every character (ASCII + Big5 + HKSCS + GBK) the same way into templates and decodes each name by finding the glyph sequence that reproduces its pixels exactly — Chinese, English and mixed names alike. Exact matches are trusted automatically; anything that doesn't match the font (wrong screenshot scaling, a character no font has) falls back to Windows OCR and gets a ⚠ for checking. The templates are built once (~10 s) into `data/cache/`.

## Files

- `app.py` main window · `viewer.py` screenshot comparison panel · `theme.py` dark theme/icon · `ocr.py` rows/numbers via Windows OCR · `glyphs.py` exact name reading · `logic.py` math + name matching · `store.py` saving
- `data/raid_data.json` all your records, `data/screens/` pasted screenshots (back up the whole `data` folder)
- `assets/make_icon.py` redraws the icon
- Tests: `.venv\Scripts\python -m unittest discover -s tests -t .`
