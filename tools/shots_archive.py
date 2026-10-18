"""Keep every game screenshot for later use: screenshots/<topic>/<name>.jpg

    python tools/shots_archive.py          # archive all of _build/shots
    (tools/screen.py calls archive() for every new screenshot)

Test runs write PNGs to _build/shots (overwritten by the next run). This keeps a
dated JPG copy of each, sorted by topic, so earlier screens stay available:
  panel/       the nation panel, its founding page and the top-bar button (feature suite UI tests)
  old-dialogs/ the Ctrl+N dialog pages the panel replaced (kept for reference)
  conquest/    conquest battles and the Annex popup
  scenarios/sNN/  per test scenario (tools/scenarios.py)
  misc/        everything else
A shot that is identical to the newest archived copy of the same name is not stored again.
"""
import hashlib
import re
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parents[1]
SHOTS = HERE / "_build" / "shots"
ARCHIVE = HERE / "screenshots"


def topic(name):
    if name.startswith(("panel", "topbar", "ui_", "found_")):
        return "panel"
    if name.startswith("p_"):
        return "old-dialogs"
    if name.startswith(("conquest", "con_")):
        return "conquest"
    m = re.match(r"s(\d+|P\d+|46dbg|46try\d)_", name)
    if m:
        return f"scenarios/s{m.group(1)}"
    return "misc"


def archive(png: Path, stamp=None):
    """Store one PNG as a JPG copy; returns the archived path (or None if unchanged)."""
    png = Path(png)
    if not png.exists():
        return None
    folder = ARCHIVE / topic(png.stem)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S", time.localtime(png.stat().st_mtime))
    digest = hashlib.sha1(png.read_bytes()).hexdigest()[:10]
    if any(digest in p.name for p in folder.glob(f"{png.stem}__*.jpg")):
        return None
    out = folder / f"{png.stem}__{stamp}_{digest}.jpg"
    Image.open(png).convert("RGB").save(out, quality=85)
    return out


def main():
    n = 0
    for png in sorted(SHOTS.glob("*.png")):
        if archive(png):
            n += 1
    total = sum(1 for _ in ARCHIVE.rglob("*.jpg"))
    size = sum(p.stat().st_size for p in ARCHIVE.rglob("*.jpg")) / 2**20
    print(f"{n} new screenshot(s) archived; {total} in {ARCHIVE} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
