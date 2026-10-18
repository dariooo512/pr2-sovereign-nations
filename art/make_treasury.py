"""The Treasury page: data/scripts/FNN_TREASURY_800x600.screen.

    python art/make_treasury.py

The nation's accounts in the look of the Log window's Balance tab (CBilanzPage,
the private screen catalogue deep dive (a)): BILANZ_PAGE (title bar, the two shaded columns
with their heads and coins, separator lines, "Total" with the plus icon, one long
button) with the rows of BILANZ_INFO_PAGE merged in at the LOB_Posider offset (21,111).
The 13 rows are the nation's own categories (core.h LedgerCat) with vanilla symbols.

The long button switches to the second mode, as the Balance tab's "Loans" button does:
"Taxes and finances" with the founding page's value rows (the new-game selector
OPE_BgValue_Level / OPE_TbValue_Level with the round arrow buttons) for the national tax,
the import tariff and the amount to move, plus Donate / Withdraw (AHS_ActionBtn).

Control names are global, so every name gets the FNT_ prefix. dll/panel.c fills the texts.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from screen_dump import Screen  # noqa: E402
from sn_paths import WORKDIR  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting SN_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_TREASURY_800x600.screen"

# row icons per ledger category (core.h LedgerCat order): one or two symbols (x, y offsets
# inside the 34 px icon cell, as in BILANZ_INFO_PAGE)
ICONS = [
    [("Pr2_MiniIcon_3xGold", 9, 0)],                                   # taxes
    [("Pr2_Symbol_Wareneinkauf", 11, 0)],                              # import tariffs
    [("Pr2_Symbol_Schaedel", 14, 0)],                                  # privateering
    [("Pr2_Symbol_Entermesser", 13, 0)],                               # plunder
    [("Pr2_Symbol_Plus_pfeil", 10, 0)],                                # donations
    [("Pr2_Symbol_Papier_a", 10, 0)],                                  # administration
    [("Pr2_Symbol_Konvois", 9, 0)],                                    # fleet upkeep
    [("Pr2_Symbol_Kanonen", 9, 0)],                                    # tower upkeep
    [("Pr2_Symbol_Schiffe", 12, 0)],                                   # new fleets
    [("Pr2_Symbol_Garde", 10, 0)],                                     # soldiers
    [("Pr2_Symbol_Kanonen", 7, 0), ("Pr2_MiniIcon_Hammer", 24, 1)],    # cannon towers
    [("Pr2_Symbol_Stadt_AH", 10, 0)],                                  # towns bought
    [("Pr2_Symbol_Minus_pfeil", 10, 0)],                               # withdrawals
]
ROWS = len(ICONS)
SEL = [("Tax", 58), ("Tariff", 148), ("Amount", 238)]   # the three value rows of mode 2: caption y


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def anim_sizes():
    """w, h of every symbol as the vanilla screens draw it (first CStatic that uses it)."""
    sizes = {}
    for p in sorted(SCRIPTS.glob("*.screen")):
        for n in Screen.load(p).walk():
            if n.cls == "CStatic" and n.has("anim"):
                a = Path(str(n.get("anim")).replace("\\", "/")).stem
                sizes.setdefault(a, (n.get("w"), n.get("h")))
    return sizes


def main():
    sizes = anim_sizes()
    page = load("BILANZ_PAGE")
    info = load("BILANZ_INFO_PAGE")
    ope, wkr = load("OPTIONEN_GAMEPLAYEINSTELLUNGEN"), load("WERFT_RENAME_INFO")
    ahs = load("AUTOHANDEL_SPEICHERN_LADEN")
    root = page.root
    root.rename("FNN_TREASURY")
    root.remove("S0000_Kopie11Auf_TAB_BG")                 # a design-time copy of the background
    root.remove("LOB_Posider")
    root.rename_children("LOB_", "FNT_")
    root.find("FNT_Cap_01").set("x", 50).set("w", 340)          # room for "Taxes and Finances"

    # mode 1: everything of the balance table goes into one group, shown or hidden as a whole
    bal = info.root.clone("FNT_Balance")
    bal.children = []
    bal.set("x", 0).set("y", 0).set("w", 440).set("h", 400)
    keep = []
    for c in root.children:
        if c.name in ("FNT_Cap_00", "FNT_Cap_01", "FNT_kredite"):
            keep.append(c)                                  # the title bar and the button stay
        else:
            bal.children.append(c)
    cap_t, c1_t, c2_t = info.find("LOB_LineCap__00"), info.find("LOB_Row1_00"), info.find("LOB_Row2_00")
    for i, icons in enumerate(ICONS):
        y = 111 + 1 + 20 * i
        for k, (anim, dx, dy) in enumerate(icons):
            ic = info.find("LON_Noname_002").clone(f"FNT_Icon_{i:02d}_{k}")
            w, h = sizes.get(anim, (18, 14))
            ic.set("anim", f"scripts\\{anim}.anim").set("x", 21 + dx).set("y", y + dy + (18 - h) // 2)
            ic.set("w", w).set("h", h)
            bal.children.append(ic)
        bal.children.append(cap_t.clone(f"FNT_Line_{i:02d}").set("x", 21 + 43).set("y", y).set("w", 104))
        bal.children.append(c1_t.clone(f"FNT_Row1_{i:02d}").set("x", 21 + 149).set("y", y))
        bal.children.append(c2_t.clone(f"FNT_Row2_{i:02d}").set("x", 21 + 271).set("y", y))
    for n in bal.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")

    # mode 2: taxes and finances
    fin = bal.clone("FNT_Finance")
    fin.children = []

    def add(src, name, new, x, y, w=None, h=None):
        n = src.find(name).clone(new)
        n.set("x", x).set("y", y)
        if w is not None:
            n.set("w", w)
        if h is not None:
            n.set("h", h)
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
        fin.children.append(n)
        return n

    for key, y in SEL:
        add(wkr, "WKR_Cap", f"FNT_{key}Cap", 70, y, 300, 22)
        add(ope, "OPE_BgValue_Level", f"FNT_{key}Bg", 112, y + 22)
        add(ope, "OPE_TbValue_Level", f"FNT_{key}Value", 120, y + 27, 200, 21)
        add(ope, "OPE_Btn_logo_dec", f"FNT_{key}Prev", 81, y + 25)
        add(ope, "OPE_Btn_logo_inc", f"FNT_{key}Next", 331, y + 25)
        note = add(info, "LOB_LineCap__00", f"FNT_{key}Note", 30, y + 56, 380, 30)
        note.set_text_id("text", "ID_NONE")
    add(ahs, "AHS_ActionBtn", "FNT_Donate", 55, 330)
    add(ahs, "AHS_ActionBtn", "FNT_Withdraw", 228, 330)
    add(info, "LOB_LineCap__00", "FNT_Status", 30, 362, 380, 36).set_text_id("text", "ID_NONE")
    fin.set("flags", 1)                                     # hidden until the button switches modes

    root.children = [bal, fin] + keep
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page.save(OUT)
    back = Screen.load(OUT)
    names = [n.name for n in back.walk()]
    assert len(names) == len(set(names)), "duplicate control names"
    assert not any(n.startswith(("LOB_", "LON_", "OPE_", "WKR_", "AHS_", "S0000")) for n in names), names
    print(f"{OUT}: {len(names)} controls, {ROWS} rows")


if __name__ == "__main__":
    main()
