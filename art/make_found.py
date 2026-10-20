"""The founding card: data/scripts/FNN_FOUND_800x600.screen.

    python art/make_found.py

One card on the nation panel's "Found a Nation" page (the founding-page change):
form of state, name and flag on one card, then Found / Cancel. Built from the game's own
controls (control names are global, so every name gets the FNF_ prefix):

- header bar and the two label plates: the Missions card NACHRICHTEN_EINTRAG (as FNN_CARD);
- the form selector: the new-game value row (OPE_BgValue_Level / OPE_TbValue_Level with the
  round OPE_Btn_logo_dec / _inc buttons);
- the name: the shipyard's rename field (WKR_RenameBg + the CEditBox WKR_RenameEdit);
- the flag: the new-game logo selector of OPTIONEN_GAMEPLAYEINSTELLUNGEN (OPE_Frame, the
  96x64 CDynamicImg OPE_LogoDisplay1, OPE_Btn_logo_dec / _inc);
- section labels: WKR_Cap; status text: the card's markup body; buttons: AHS_ActionBtn.

dll/panel.c fills the texts, the flag image, the icons and the clicks.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from sn_paths import WORKDIR  # noqa: E402  (first: puts the kit's tools on sys.path)
from screen_dump import Screen  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting PR2_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_FOUND_800x600.screen"
W = 377
H = 352


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def main():
    card = load("NACHRICHTEN_EINTRAG")
    card.root.rename("FNN_FOUND")
    card.root.rename_children("LON_", "FNF_")
    kids = card.root.children
    ope, wkr = load("OPTIONEN_GAMEPLAYEINSTELLUNGEN"), load("WERFT_RENAME_INFO")
    ahs = load("AUTOHANDEL_SPEICHERN_LADEN")

    def add(src, name, x, y, w=None, h=None):
        n = src.find(name).clone()
        n.set("x", x).set("y", y)
        if w is not None:
            n.set("w", w)
        if h is not None:
            n.set("h", h)
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
        kids.append(n)
        return n

    def label(name, y):
        add(wkr, "WKR_Cap", 38, y, 300, 22).rename(name)

    # the two label plates are not needed: the header bar names the capital
    for name in ("FNF_BalkenLinks", "FNF_BalkenRechts", "FNF_TmplLoka", "FNF_TmplDate"):
        kids.remove(card.find(name))

    # form of state: < [ Republic ] >
    label("FNF_FormCap", 40)
    add(ope, "OPE_BgValue_Level", 81, 62).rename("FNF_FormBg")
    add(ope, "OPE_TbValue_Level", 89, 67, 200, 21).rename("FNF_FormValue")
    add(ope, "OPE_Btn_logo_dec", 50, 65).rename("FNF_FormPrev")
    add(ope, "OPE_Btn_logo_inc", 300, 65).rename("FNF_FormNext")

    # name: the rename field
    label("FNF_NameCap", 98)
    add(wkr, "WKR_RenameBg", 38, 120, 301, 26).rename("FNF_NameBg")
    add(wkr, "WKR_RenameEdit", 42, 123, 293, 19).rename("FNF_NameEdit")

    # flag: < [flag] >
    label("FNF_FlagCap", 152)
    add(ope, "OPE_Frame", 133, 174).rename("FNF_FlagFrame")
    add(ope, "OPE_LogoDisplay1", 140, 182).rename("FNF_FlagImg")
    add(ope, "OPE_Btn_logo_dec", 96, 201).rename("FNF_FlagPrev")
    add(ope, "OPE_Btn_logo_inc", 254, 201).rename("FNF_FlagNext")
    add(wkr, "WKR_Cap", 13, 256, 350, 22).rename("FNF_FlagName")

    # requirements / result, then Found / Cancel
    body = card.find("FNF_TmplText")
    body.set("x", 14).set("y", 280).set("w", 348).set("h", 36)
    for i, x in enumerate((24, 196)):
        add(ahs, "AHS_ActionBtn", x, H - 32).rename(f"FNF_Btn{i + 1}")

    card.root.set("w", W).set("h", H)
    card.find("FNF_TmplRahmen").set("h", H - 8)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    card.save(OUT)
    back = Screen.load(OUT)
    names = [n.name for n in back.walk()]
    assert len(names) == len(set(names)), "duplicate control names"
    assert not any(n.startswith(("LON_", "OPE_", "WKR_", "AHS_")) for n in names), names
    print(f"{OUT}: {', '.join(names)}")


if __name__ == "__main__":
    main()
