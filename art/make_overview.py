"""The Overview page: data/scripts/FNN_OVERVIEW_800x600.screen.

    python art/make_overview.py

Top: the nation's facts in the look of the Log's Successes page (ERFOLGSPAGE: symbol, caption,
value, 20 px rows, a separator line). Below: the Chronicle Nations page's "Size and strength"
block (NATION_PAGE block 1: light header bar, double frame, a flag over each column, table
lines, the Wars band) with the nation as a fifth column next to the four powers
(x = 120 + 58 k, the private screen catalogue). At the bottom a text block for what needs the
player's attention (petitions, wars, unrest, an empty treasury).

All names FNO_*. dll/panel.c fills everything.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
from screen_dump import Screen  # noqa: E402
from sn_paths import WORKDIR  # noqa: E402
from make_treasury import anim_sizes  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting SN_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_OVERVIEW_800x600.screen"
FLAGS = ["Pr2_Flagge_England", "Pr2_Flagge_Frankreich", "Pr2_Flagge_Holland", "Pr2_Flagge_Spanien"]
FACT_ICONS = [None, "Pr2_Symbol_Erfolge_Rang", "Pr2_Symbol_Stadt_AH", "Pr2_MiniSymbol_Schild", "Geld_Icon_01",
              "Pr2_Symbol_Anker", "Pr2_Symbol_Papier"]          # row 0: the nation's flag
TABLE = ["Pop", "Towns", "Rel", "Wars"]                         # rows of the comparison
COL_X, COL_W = 120, 52


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def main():
    sizes = anim_sizes()
    erf, nat, ent = load("ERFOLGSPAGE"), load("NATION_PAGE"), load("STADT_ENTRY")
    p = load("ERFOLGSPAGE")
    root = p.root
    root.rename("FNN_OVERVIEW")
    kids = []
    kids.append(erf.find("LOE_CaptionBg").clone("FNO_CaptionBg"))
    kids.append(erf.find("LOE_Caption").clone("FNO_Caption").set("x", 50).set("w", 340))
    icon = erf.find("LOE_Icn_10")
    for i, anim in enumerate(FACT_ICONS):
        y = 58 + 20 * i
        if anim is None:
            kids.append(ent.find("LOS_NationFrame").clone("FNO_FlagFrame").set("x", 28).set("y", y + 3))
            kids.append(ent.find("LOS_Nation").clone("FNO_Flag").set("x", 30).set("y", y + 5))
        else:
            w, h = sizes.get(anim, (16, 14))
            kids.append(icon.clone(f"FNO_Icn_{i}").set("anim", f"scripts\\{anim}.anim")
                        .set_rect(40 - w // 2, y + 10 - h // 2, w, h))
        kids.append(erf.find("LOE_TxtCap_12").clone(f"FNO_Cap_{i}").set("y", y))
        kids.append(erf.find("LOE_Txt_00").clone(f"FNO_Val_{i}").set_rect(202, y + 3, 216, 20))
    kids.append(erf.find("LOE_Trenner_00").clone("FNO_Sep_0").set("y", 200))

    # size and strength: the nation and the four powers
    y = 212
    kids.append(nat.find("CHN_Bg1").clone("FNO_Bg1").set("y", y))
    kids.append(nat.find("CHN_Txt6").clone("FNO_Txt6").set("y", y - 4))
    top, rows = y + 24, [y + 50, y + 71, y + 92]
    kids.append(nat.find("CHN_Noname_05").clone("FNO_Band_0").set_rect(27, top + 2, 386, 18))
    kids.append(nat.find("CHN_Noname_04").clone("FNO_Band_1").set_rect(27, y + 114, 386, 41))
    kids.append(nat.find("CHN_Noname_00").clone("FNO_Frame").set_rect(25, top, 390, y + 158 - top))
    kids.append(nat.find("CHN_Noname_02").clone("FNO_Line_0").set_rect(28, top + 16, 384, 7))
    kids.append(nat.find("CHN_Noname_03").clone("FNO_Line_1").set_rect(28, y + 110, 384, 7))
    fx = COL_X + (COL_W - 25) // 2
    kids.append(ent.find("LOS_NationFrame").clone("FNO_ColFrame").set("x", fx).set("y", top + 3))
    kids.append(ent.find("LOS_Nation").clone("FNO_ColFlag").set("x", fx + 2).set("y", top + 5))
    for k, anim in enumerate(FLAGS):
        kids.append(nat.find("CHN_Nation_Tmpl_1").clone(f"FNO_ColFlag_{k}").set("anim", f"scripts\\{anim}.anim")
                    .set_rect(COL_X + 58 * (k + 1) + (COL_W - 25) // 2, top + 3, 25, 15))
    label = nat.find("CHN_Txt1")
    cell = ent.find("LOS_Wohlstand")
    for r, name in enumerate(TABLE):
        ly = rows[r] if r < 3 else y + 125
        kids.append(label.clone(f"FNO_Row_{name}").set_rect(20, ly, 92, 20))
        for k in range(5):
            if name == "Wars":      # "-" on the label's line; its centre is the cell's anchor
                c = cell.clone(f"FNO_{name}_{k}").set_rect(COL_X + 58 * k - 5, ly, COL_W + 8, 20)
            else:
                c = cell.clone(f"FNO_{name}_{k}").set_rect(COL_X + 58 * k - 4, ly + 2, COL_W + 8, 20)
            kids.append(c.set("align", 2))
    # the Wars row's entries: per cell a flag of each power and "you", hidden; dll/panel.c
    # (overview_wars) shows the cell's entries and lays them out round the cell's centre, under
    # the column's header flag (one line for one or two entries, two lines for three or four)
    for k in range(5):
        cx, cy = COL_X + 58 * k + 25, y + 135
        for q, anim in enumerate(FLAGS):
            kids.append(nat.find("CHN_Nation_Tmpl_1").clone(f"FNO_WarFlag_{k}_{q}")
                        .set("anim", f"scripts\\{anim}.anim").set_rect(cx - 12, cy - 7, 25, 15)
                        .set("flags", 1))
        you = cell.clone(f"FNO_WarYou_{k}").set_rect(cx - 15, cy - 9, 31, 19).set("align", 2).set("flags", 1)
        you.set_text_id("text", "ID_NONE")
        kids.append(you)
    kids.append(erf.find("LOE_Trenner_00").clone("FNO_Sep_1").set("y", y + 162))
    note = load("BILANZ_INFO_PAGE").find("LOB_LineCap__00").clone("FNO_Notice").set_rect(28, y + 176, 386, 438 - (y + 176))
    note.set_text_id("text", "ID_NONE")
    kids.append(note)
    root.children = kids
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
        if n.cls == "CTextBoxEx" and n.has("text"):
            n.set_text_id("text", "ID_NONE")
    p.save(OUT)
    names = [n.name for n in Screen.load(OUT).walk()]
    assert len(names) == len(set(names)), "duplicate control names"
    assert not any(n.startswith(("LOE_", "CHN_", "LOS_", "LOB_", "S0000")) for n in names), names
    print(f"{OUT}: {len(names)} controls")


if __name__ == "__main__":
    main()
