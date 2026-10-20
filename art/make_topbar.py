"""Top menu bar with a nation button: data/scripts/TOPMENUBAR_800x600.screen.

    python art/make_topbar.py

Clones the vanilla coin button TMB_Gold (the "economy" button next to the gold
amount, which opens the Log) and its wooden rim TMB_Holzrand_01 into TMB_Nation /
TMB_Holzrand_Nation, placed in the free gap between the convoy-list button
(x 787..827) and the globe button (x 907). The DLL (panel.c) gives it the
nation icon and a tooltip and connects its click to the nation panel. Loose
files override the archives, so the game loads this copy.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from sn_paths import WORKDIR  # noqa: E402  (first: puts the kit's tools on sys.path)
from screen_dump import Screen  # noqa: E402

SRC = WORKDIR / "arcd" / "scripts" / "TOPMENUBAR_800x600.screen"      # vanilla (setting PR2_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "TOPMENUBAR_800x600.screen"
X = 846


def main():
    scr = Screen.load(SRC)
    root = scr.root
    if root.find("TMB_Nation"):
        raise SystemExit("source already has TMB_Nation")
    names = [c.name for c in root.children]
    gold, rim = root.find("TMB_Gold"), root.find("TMB_Holzrand_01")
    btn = gold.clone("TMB_Nation").set("x", X)
    if btn.has("tooltip"):
        btn.set_text_id("tooltip", "")
    wood = rim.clone("TMB_Holzrand_Nation").set("x", X)
    # keep the vanilla drawing order: rims with the rims, buttons with the buttons
    root.children.insert(names.index("TMB_Holzrand_01") + 1, wood)
    root.children.insert(names.index("TMB_KonvoiListe") + 2, btn)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    scr.save(OUT)
    back = Screen.load(OUT)
    assert back.find("TMB_Nation") and back.find("TMB_Holzrand_Nation")
    print(f"{OUT}: TMB_Nation at x={X} ({len(back.root.children)} controls)")


if __name__ == "__main__":
    main()
