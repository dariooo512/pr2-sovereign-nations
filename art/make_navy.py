"""The Navy and defence page: data/scripts/FNN_NAVY_800x600.screen and its row FNN_FLEET_ROW_800x600.screen.

    python art/make_navy.py

Three modes, switched by the third button:
- Fleets: the nation's fleets in the look of the convoy list (KONVOI_LISTE rows
  KONVOILISTEN_EINTRAG narrowed to the panel: dark plate, ship symbol, white name, state
  symbol, situation line, ship and crew counts). A click selects a fleet; the footer shows
  its order, an eye button (Go to) and Next order / Next target.
- Naval command: the standing order on the founding page's value row (OPE_*), the fleets in
  service and their costs, Commission fleet / Pay off a fleet.
- Town defence: the member towns as town-list rows (FNN_TOWN_ROW, art/make_towns.py) with
  soldiers, towers, towers paid by the treasury and recruits on the way; Recruit soldiers /
  Build tower for the selected town.
Buttons are the game's middle buttons (Pr2_Btn_Mid, BETRIEB_ABREISSEN's BID_Ok, 123 px), three
in a row. Page controls FNV_*, row controls FNR_*. dll/panel.c fills everything.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
from screen_dump import Screen  # noqa: E402
from sn_paths import WORKDIR  # noqa: E402
from make_treasury import anim_sizes  # noqa: E402
from make_towns import CELLS as TOWN_CELLS  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting SN_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_NAVY_800x600.screen"
ROW_OUT = HERE.parent / "data" / "scripts" / "FNN_FLEET_ROW_800x600.screen"
ROW_W, ROW_H = 370, 55
LIST_X, LIST_Y, ROWS = 19, 84, 4
HEAD_T = ["Pr2_Symbol_Garde", "Pr2_Symbol_Kanonen", "Geld_Icon_01", "Pr2_Symbol_Uhr1"]   # town defence columns


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def row():
    r = load("KONVOILISTEN_EINTRAG")
    root = r.root
    root.rename("FNN_FLEET_ROW")
    old = {c.name: c for c in root.children}
    kids = [
        old["KLE_BgHL"].rename("FNR_Sel").set_rect(4, 4, ROW_W - 8, 47),
        old["KLE_Bg"].rename("FNR_Bg").set("w", ROW_W - 8),
        old["KLE_KonvoiIcon"].rename("FNR_Ship"),
        old["KLE_BgHL"].clone("FNR_Hover").set_rect(4, 4, ROW_W - 8, 47).set("flags", 1).set("bg_color", 0x40FFFAF1),
        old["KLE_Symbol_01"].rename("FNR_SymPort"),                 # in port: anchor
        old["KLE_Symbol_02"].rename("FNR_SymSea"),                  # at sea: clock
        old["KLE_Symbol_05"].rename("FNR_SymBattle"),               # in battle
        old["KLE_Name"].rename("FNR_Name").set("w", 180),
        old["KLE_Situation"].rename("FNR_C1Box").set_rect(118, 32, 156, 14),
        old["KLE_7"].rename("FNR_IcnShips").set("x", 286),
        old["KLE_Maennel"].rename("FNR_IcnCrew").set("x", 322),
    ]
    # counts as rich text cells so the list's FillEntry helpers work on every row type
    cell = load("STADT_ENTRY").find("LOS_Wohlstand")
    kids.append(cell.clone("FNR_C1").set_rect(110, 29, 168, 18).set("align", 2))
    kids.append(cell.clone("FNR_C2").set_rect(277, 28, 36, 18).set("align", 2))
    kids.append(cell.clone("FNR_C3").set_rect(316, 28, 36, 18).set("align", 2))
    for n in kids:
        if n.name in ("FNR_SymSea", "FNR_SymBattle"):
            n.set("flags", 1)
    kids = [k for k in kids if k.name != "FNR_C1Box"]
    root.children = kids
    root.set("w", ROW_W).set("h", ROW_H)
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
        if n.cls == "CTextBoxEx" and n.has("text"):
            n.set_text_id("text", "ID_NONE")
    r.save(ROW_OUT)


def page():
    sizes = anim_sizes()
    towns = load("STAEDTE_PAGE")
    p = load("STAEDTE_PAGE")
    root = p.root
    root.rename("FNN_NAVY")
    root.remove("S0000_Kopie11Auf_TAB_BG2")
    root.rename_children("LOS_", "FNV_")
    root.rename_children("LOB_", "FNV_")
    old = {c.name: c for c in root.children}
    kids = [old["FNV_Cap_00"], old["FNV_Cap_01"].set("x", 50).set("w", 340)]
    info = load("BILANZ_INFO_PAGE").find("LOB_LineCap__00")
    head = info.clone("FNV_Head").set_rect(28, 54, 386, 30)
    head.set_text_id("text", "ID_NONE")
    kids.append(head)
    h = ROWS * ROW_H
    kids.append(old["FNV_ScrollDrawable"].set_rect(LIST_X + 6, LIST_Y + 4, 385, h))
    sl = old["FNV_Scrollbar"].set_rect(397, LIST_Y + 4, 27, h)
    sl.children[0].set("h", h - 23)
    sl.children[1].set("y", h - 22)
    kids.append(sl)
    # town defence: column heads over the town rows (hidden in the other modes)
    tile, shade = old["FNV_Stuff_02"], old["FNV_Bg_Shadow_01"]
    for i, (x, w, _) in enumerate(TOWN_CELLS):
        px = LIST_X + 6 + x
        iw, ih = sizes.get(HEAD_T[i], (18, 14))
        kids.append(tile.clone(f"FNV_HeadT_{i}").set_rect(px + 1, LIST_Y - 16, w - 2, 19).set("flags", 1))
        kids.append(tile.clone(f"FNV_HeadTI_{i}").set("anim", f"scripts\\{HEAD_T[i]}.anim")
                    .set_rect(px + (w - iw) // 2, LIST_Y - 16 + (19 - ih) // 2, iw, ih).set("flags", 1))
    bottom = LIST_Y + 4 + h + 3
    kids.append(old["FNV_Stuff_00"].set("y", bottom))

    # naval command (mode 1): the standing order on the value row, then the fleets in service
    ope, wkr = load("OPTIONEN_GAMEPLAYEINSTELLUNGEN"), load("WERFT_RENAME_INFO")
    cmd = load("BILANZ_INFO_PAGE").root.clone("FNV_Command")
    cmd.children = []
    cmd.set_rect(0, 0, 440, 400).set("flags", 1)

    def add(src, name, new, x, y, w=None, hh=None):
        n = src.find(name).clone(new).set("x", x).set("y", y)
        if w is not None:
            n.set("w", w)
        if hh is not None:
            n.set("h", hh)
        cmd.children.append(n)
        return n

    add(wkr, "WKR_Cap", "FNV_OrderCap", 70, 92, 300, 22)
    add(ope, "OPE_BgValue_Level", "FNV_OrderBg", 112, 114)
    add(ope, "OPE_TbValue_Level", "FNV_OrderValue", 120, 119, 200, 21)
    add(ope, "OPE_Btn_logo_dec", "FNV_OrderPrev", 81, 117)
    add(ope, "OPE_Btn_logo_inc", "FNV_OrderNext", 331, 117)
    add(load("BILANZ_INFO_PAGE"), "LOB_LineCap__00", "FNV_OrderNote", 30, 150, 380, 46).set_text_id("text", "ID_NONE")
    add(wkr, "WKR_Cap", "FNV_FleetsCap", 70, 206, 300, 22)
    add(load("BILANZ_INFO_PAGE"), "LOB_LineCap__00", "FNV_FleetsNote", 30, 230, 380, 110).set_text_id("text", "ID_NONE")
    kids.append(cmd)

    # the footer: the selected fleet or town, the eye button, three buttons
    y0 = bottom + 8
    kids.append(load("STADT_ENTRY").find("LOS_StadtName").clone("FNV_SelName").set_rect(28, y0, 300, 22))
    eye = Screen.load(HERE.parent / "data" / "scripts" / "FNN_CARD_800x600.screen").find("FNC_BtnRemove")
    kids.append(eye.clone("FNV_GoTo").set("x", 386).set("y", y0 - 4))
    note = info.clone("FNV_SelInfo").set_rect(28, y0 + 20, 386, 404 - (y0 + 20))
    note.set_text_id("text", "ID_NONE")
    kids.append(note)
    mid = load("BETRIEB_ABREISSEN").find("BID_Ok")
    for i, x in enumerate((28, 159, 290)):
        kids.append(mid.clone(f"FNV_Btn{i + 1}").set("x", x).set("y", 412))
    root.children = kids
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
    p.save(OUT)


def check(path, bad):
    names = [n.name for n in Screen.load(path).walk()]
    assert len(names) == len(set(names)), f"{path}: duplicate control names"
    assert not any(n.startswith(bad) for n in names), names
    return names


def main():
    row()
    page()
    rn = check(ROW_OUT, ("KLE", "LOS_"))
    pn = check(OUT, ("LOS_", "LOB_", "OPE_", "WKR_", "BID_", "FNC_", "S0000"))
    assert not set(rn) & set(pn)
    print(f"{OUT}: {len(pn)} controls; {ROW_OUT.name}: {', '.join(rn)}")


if __name__ == "__main__":
    main()
