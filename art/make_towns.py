"""The Towns page: data/scripts/FNN_TOWNS_800x600.screen and its row FNN_TOWN_ROW_800x600.screen.

    python art/make_towns.py

The nation's towns in the look of the Chronicle's town list (STAEDTE_PAGE + STADT_ENTRY,
the private screen catalogue deep dive 2 of the Chronicle): title bar, column heads on light tiles,
shaded columns, separator lines, a scrolling table of 25 px rows that touch, each with the
flag cell. Columns: town, inhabitants, loyalty, tax, garrison (mode 1, towns for sale:
town, inhabitants, price, chance, garrison). Heads are vanilla symbols with tooltips, as in
the convoy list. A click on a row selects it (the list's own press slot); the footer shows
the selected town with a tax spinner (the unused STANDARD_SPINNER's +/- buttons) and two
long buttons: Town info / Offer and the mode switch.

Page controls are FNW_*, row controls FNR_* (rows are list entries: their names repeat per
row and are found with FindEntryChild). dll/panel.c fills everything.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
from sn_paths import WORKDIR  # noqa: E402  (first: puts the kit's tools on sys.path)
from screen_dump import Screen  # noqa: E402
from make_treasury import anim_sizes  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting PR2_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_TOWNS_800x600.screen"
ROW_OUT = HERE.parent / "data" / "scripts" / "FNN_TOWN_ROW_800x600.screen"
LIST_X, LIST_Y, ROWS = 19, 110, 9
# cells of a row (x, w, align) after the flag and the name; the page's column heads sit above them
CELLS = [(140, 66, 1), (206, 50, 2), (256, 50, 2), (306, 70, 2)]
HEAD_A = ["Pr2_Symbol_Kopf_m", "Pr2_MiniSymbol_Schild", "Pr2_MiniIcon_3xGold", "Pr2_Symbol_Garde"]   # members
HEAD_B = ["Pr2_Symbol_Kopf_m", "Pr2_MiniIcon_3xGold", "Pr2_Symbol_Wuerfel", "Pr2_Symbol_Garde"]  # for sale


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def row():
    r = load("STADT_ENTRY")
    root = r.root
    root.rename("FNN_TOWN_ROW")
    root.remove("LOS_nation_Texture")
    root.rename_children("LOS_", "FNR_")
    hl = load("PRODUKTIONS_EINTRAG").find("LOP_HighLight")
    sel = hl.clone("FNR_Sel").set_rect(1, 1, 374, 23).set("flags", 1)
    hov = hl.clone("FNR_Hover").set_rect(1, 1, 374, 23).set("flags", 1).set("bg_color", 0x40FFF5D2)
    root.children = [sel, hov] + root.children           # the tints under the texts
    root.find("FNR_StadtName").rename("FNR_Name").set("w", 99)
    tmpl = root.find("FNR_Einwohner")
    root.remove("FNR_Einwohner")
    root.remove("FNR_Wohlstand")
    for i, (x, w, align) in enumerate(CELLS):
        c = tmpl.clone(f"FNR_C{i + 1}").set("x", x).set("w", w).set("align", align)
        c.set_text_id("text", "ID_NONE")
        root.children.append(c)
    root.set("w", 385)
    r.save(ROW_OUT)
    return r


def page():
    sizes = anim_sizes()
    p = load("STAEDTE_PAGE")
    root = p.root
    root.rename("FNN_TOWNS")
    root.remove("S0000_Kopie11Auf_TAB_BG2")
    root.rename_children("LOS_", "FNW_")
    root.rename_children("LOB_", "FNW_")
    root.find("FNW_Cap_01").set("x", 50).set("w", 340)
    h = ROWS * 25
    root.find("FNW_ScrollDrawable").set("h", h)
    sl = root.find("FNW_Scrollbar").set("h", h)
    sl.children[0].set("h", h - 23)                       # background, + button, - button, drag
    sl.children[1].set("y", h - 22)
    bottom = LIST_Y + h + 4
    root.find("FNW_Stuff_00").set("y", bottom)            # the separator under the table
    # column heads: one light tile per column with a symbol (two sets: members / towns for sale)
    tile = root.find("FNW_Stuff_02")
    shade = root.find("FNW_Bg_Shadow_01")
    for name in ("FNW_Stuff_02", "FNW_Bg2", "FNW_Cap_Row1", "FNW_Cap_Row2", "FNW_Bg_Shadow_00", "FNW_Bg_Shadow_01",
                 "FNW_GesamtTxt", "FNW_gesamt", "FNW_blla"):
        root.remove(name)
    heads = []
    for i, (x, w, _) in enumerate(CELLS):
        px = LIST_X + x
        if i % 2 == 0:
            heads.append(shade.clone(f"FNW_Shade_{i}").set_rect(px, 84, w, bottom - 84))
        heads.append(tile.clone(f"FNW_Head_{i}").set_rect(px + 1, 70, w - 2, 19))
        for set_name, icons in (("A", HEAD_A), ("B", HEAD_B)):
            iw, ih = sizes.get(icons[i], (18, 14))
            ic = tile.clone(f"FNW_Head{set_name}_{i}").set("anim", f"scripts\\{icons[i]}.anim")
            ic.set_rect(px + (w - iw) // 2, 70 + (19 - ih) // 2, iw, ih)
            if set_name == "B":
                ic.set("flags", 1)
            heads.append(ic)
    idx = next(i for i, c in enumerate(root.children) if c.name == "FNW_Stuff_01")
    root.children[idx:idx] = heads

    # the footer: the selected town, its tax spinner, two long buttons
    ent = load("STADT_ENTRY")
    info = load("BILANZ_INFO_PAGE")
    spin = load("STANDARD_SPINNER")
    ahs = load("AUTOHANDEL_SPEICHERN_LADEN")
    y0 = bottom + 10
    root.children.append(ent.find("LOS_NationFrame").clone("FNW_SelFrame").set("x", 24).set("y", y0 + 4))
    root.children.append(ent.find("LOS_Nation").clone("FNW_SelFlag").set("x", 26).set("y", y0 + 6))
    root.children.append(ent.find("LOS_StadtName").clone("FNW_SelName").set_rect(58, y0, 180, 25))
    tax = info.find("LOB_LineCap__00").clone("FNW_TaxCap").set_rect(228, y0 + 4, 70, 18).set("align", 1)
    tax.set_text_id("text", "ID_NONE")
    root.children.append(tax)
    root.children.append(spin.find("SS_SpinDec").clone("FNW_TaxDec").set("x", 302).set("y", y0 - 2))
    root.children.append(spin.find("SS_TextBox").clone("FNW_TaxValue").set_rect(331, y0 + 1, 46, 20))
    root.children.append(spin.find("SS_SpinInc").clone("FNW_TaxInc").set("x", 380).set("y", y0 - 2))
    note = info.find("LOB_LineCap__00").clone("FNW_SelInfo").set_rect(28, y0 + 26, 386, 36)
    note.set_text_id("text", "ID_NONE")
    root.children.append(note)
    root.children.append(ahs.find("AHS_ActionBtn").clone("FNW_Btn1").set("x", 55).set("y", 412))
    root.children.append(ahs.find("AHS_ActionBtn").clone("FNW_Mode").set("x", 228).set("y", 412))
    root.children.append(ahs.find("AHS_ActionBtn").clone("FNW_Btn2").set("x", 228).set("y", y0 - 2).set("flags", 1))
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
    p.save(OUT)
    return p


def check(path, bad):
    back = Screen.load(path)
    names = [n.name for n in back.walk()]
    assert len(names) == len(set(names)), f"{path}: duplicate control names"
    assert not any(n.startswith(bad) for n in names), names
    return names


def main():
    row()
    page()
    rn = check(ROW_OUT, ("LOS_", "LOP_"))
    pn = check(OUT, ("LOS_", "LOB_", "SS_", "AHS_", "S0000"))
    assert not set(rn) & set(pn)
    print(f"{OUT}: {len(pn)} controls; {ROW_OUT.name}: {', '.join(rn)}")


if __name__ == "__main__":
    main()
