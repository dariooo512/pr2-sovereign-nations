"""The Diplomacy page: data/scripts/FNN_DIPLOMACY_800x600.screen and its row FNN_POWER_ROW_800x600.screen.

    python art/make_diplomacy.py

The nation's relations in the look of the Chronicle's Nations page (NATION_PAGE block 2
"Your relationship with the nations", the private screen catalogue Chronicle deep dive 1): the
light header bar, the double frame with table lines, one row per power with its flag
(Pr2_Flagge_*), name, treaty, relation and mood. The rows are list entries so a click
selects a power (dll/panel.c list pages); the footer shows the selected power (flag, name,
a text block with chances and offers) and two long buttons for the next step.

Page controls are FND_*, row controls FNR_*. dll/panel.c fills everything.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from sn_paths import WORKDIR  # noqa: E402  (first: puts the kit's tools on sys.path)
from screen_dump import Screen  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting PR2_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_DIPLOMACY_800x600.screen"
ROW_OUT = HERE.parent / "data" / "scripts" / "FNN_POWER_ROW_800x600.screen"
FLAGS = ["Pr2_Flagge_England", "Pr2_Flagge_Frankreich", "Pr2_Flagge_Holland", "Pr2_Flagge_Spanien"]  # power order
ROW_H, ROWS, LIST_X, LIST_Y = 36, 4, 27, 112
CELLS = [(118, 96), (214, 78), (292, 92)]                 # treaty, relation, mood


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def row():
    r = load("STADT_ENTRY")
    root = r.root
    root.rename("FNN_POWER_ROW")
    nat = load("NATION_PAGE")
    hl = load("PRODUKTIONS_EINTRAG").find("LOP_HighLight")
    kids = [hl.clone("FNR_Sel").set_rect(1, 1, 384, ROW_H - 2).set("flags", 1),
            hl.clone("FNR_Hover").set_rect(1, 1, 384, ROW_H - 2).set("flags", 1).set("bg_color", 0x40FFF5D2)]
    for i, anim in enumerate(FLAGS):
        f = nat.find("CHN_Nation_Tmpl_1").clone(f"FNR_Flag_{i}").set("anim", f"scripts\\{anim}.anim")
        kids.append(f.set_rect(10, (ROW_H - 15) // 2, 25, 15).set("flags", 1))
    kids.append(root.find("LOS_StadtName").clone("FNR_Name").set_rect(42, 8, 76, 25))
    cell = root.find("LOS_Wohlstand")
    for i, (x, w) in enumerate(CELLS):
        kids.append(cell.clone(f"FNR_C{i + 1}").set_rect(x, 3, w, ROW_H - 4).set("align", 2))
    root.children = kids
    root.set("w", 385).set("h", ROW_H)
    for n in root.walk():
        if n.has("text") and n.cls == "CTextBoxEx":
            n.set_text_id("text", "ID_NONE")
    r.save(ROW_OUT)


def page():
    p = load("NATION_PAGE")
    root = p.root
    root.rename("FNN_DIPLOMACY")
    root.rename_children("CHN_", "FND_")
    keep = {"FND_CaptionBg", "FND_Caption", "FND_Bg2", "FND_Txt5", "FND_Noname_11", "FND_Noname_12",
            "FND_Noname_13", "FND_Noname_14", "FND_Noname_15", "FND_Nation_Tmpl_1"}
    old = {c.name: c for c in root.children}
    tmpl = old["FND_Nation_Tmpl_1"]
    kids = []
    # the header bar and the table frame, moved up under the title
    kids.append(old["FND_CaptionBg"])
    kids.append(old["FND_Caption"].set("x", 50).set("w", 340))
    kids.append(old["FND_Bg2"].set("y", 62))
    kids.append(old["FND_Txt5"].set("y", 58))
    top = LIST_Y - 3
    kids.append(old["FND_Noname_12"].set_rect(27, 88, 386, 20))          # the light band under the heads
    kids.append(old["FND_Noname_11"].set_rect(25, 86, 390, top - 86 + ROWS * ROW_H + 6))
    for i in range(1, ROWS):                                             # table lines between the rows
        kids.append(old["FND_Noname_13"].clone(f"FND_Line_{i}").set_rect(28, LIST_Y + i * ROW_H - 4, 384, 7))
    kids.append(old["FND_Noname_15"].set_rect(28, top - 2, 384, 7))
    heads = load("BILANZ_INFO_PAGE").find("LOB_LineCap__00")
    for i, (x, w) in enumerate(CELLS):
        h = heads.clone(f"FND_Head_{i}").set_rect(LIST_X + x, 90, w, 18).set("align", 2)
        h.set_text_id("text", "ID_NONE")
        kids.append(h)
    towns = load("STAEDTE_PAGE")
    kids.append(towns.find("LOS_ScrollDrawable").clone("FND_ScrollDrawable").set_rect(LIST_X, LIST_Y, 385, ROWS * ROW_H))
    sl = towns.find("LOS_Scrollbar").clone("FND_Scrollbar").set_rect(397, LIST_Y, 27, ROWS * ROW_H)
    sl.rename_children("LOS_", "FND_")
    sl.children[0].set("h", ROWS * ROW_H - 23)
    sl.children[1].set("y", ROWS * ROW_H - 22)
    kids.append(sl)
    # the footer: the selected power
    y0 = LIST_Y + ROWS * ROW_H + 14
    kids.append(load("BILANZ_PAGE").find("LOB_Stuff_01").clone("FND_Sep").set("y", y0 - 10))
    for i, anim in enumerate(FLAGS):
        f = tmpl.clone(f"FND_SelFlag_{i}").set("anim", f"scripts\\{anim}.anim").set_rect(30, y0 + 5, 25, 15)
        kids.append(f.set("flags", 1))
    ent = load("STADT_ENTRY")
    kids.append(ent.find("LOS_StadtName").clone("FND_SelName").set_rect(64, y0 + 1, 300, 25))
    note = heads.clone("FND_SelInfo").set_rect(28, y0 + 28, 386, 404 - (y0 + 28))
    note.set_text_id("text", "ID_NONE")
    kids.append(note)
    ahs = load("AUTOHANDEL_SPEICHERN_LADEN")
    kids.append(ahs.find("AHS_ActionBtn").clone("FND_Btn1").set("x", 55).set("y", 412))
    kids.append(ahs.find("AHS_ActionBtn").clone("FND_Btn2").set("x", 228).set("y", 412))
    root.children = kids
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
    assert keep <= set(old), keep - set(old)
    p.save(OUT)


def check(path, bad):
    names = [n.name for n in Screen.load(path).walk()]
    assert len(names) == len(set(names)), f"{path}: duplicate control names"
    assert not any(n.startswith(bad) for n in names), names
    return names


def main():
    row()
    page()
    rn = check(ROW_OUT, ("LOS_", "LOP_", "CHN_"))
    pn = check(OUT, ("LOS_", "LOB_", "CHN_", "AHS_", "S0000"))
    assert not set(rn) & set(pn)
    print(f"{OUT}: {len(pn)} controls; {ROW_OUT.name}: {', '.join(rn)}")


if __name__ == "__main__":
    main()
