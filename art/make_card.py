"""The nation panel's card: data/scripts/FNN_CARD_800x600.screen.

    python art/make_card.py

A copy of the Missions card NACHRICHTEN_EINTRAG (header bar, two label plates,
markup body) with its control names changed from LON_ to FNC_ (control names
are global in the game's window manager), plus two text buttons FNC_Btn1 /
FNC_Btn2 in the game's long button style (cloned from AHS_ActionBtn). The DLL
(dll/panel.c) sets their captions, places them under the body text and resizes
the card to fit, or hides them on cards without actions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from screen_dump import Screen  # noqa: E402
from sn_paths import WORKDIR  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting SN_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_CARD_800x600.screen"
BTN_Y = 104


def main():
    card = Screen.load(SCRIPTS / "NACHRICHTEN_EINTRAG_800x600.screen")
    card.root.rename("FNN_CARD")
    card.root.rename_children("LON_", "FNC_")
    src = Screen.load(SCRIPTS / "AUTOHANDEL_SPEICHERN_LADEN_800x600.screen").find("AHS_ActionBtn")
    for i, x in enumerate((24, 196)):
        b = src.clone(f"FNC_Btn{i + 1}").set("x", x).set("y", BTN_Y)
        if b.has("tooltip"):
            b.set_text_id("tooltip", "")
        card.root.children.append(b)
    card.root.set("h", BTN_Y + 26 + 6)
    rahmen = card.find("FNC_TmplRahmen")
    rahmen.set("h", BTN_Y + 26 + 6 - 8)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    card.save(OUT)
    back = Screen.load(OUT)
    names = [n.name for n in back.walk()]
    assert "FNC_Btn1" in names and "FNC_Btn2" in names and not any(n.startswith("LON_") for n in names)
    print(f"{OUT}: {', '.join(names)}")


if __name__ == "__main__":
    main()
