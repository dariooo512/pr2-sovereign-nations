"""The Government page: data/scripts/FNN_GOVERNMENT_800x600.screen.

    python art/make_government.py

The form of government as the new-game feature selector (the private screen catalogue: "one of 5
with a long description"), on the founding page's value row (OPTIONEN_GAMEPLAYEINSTELLUNGEN's
OPE_BgValue_Level / OPE_TbValue_Level with the round arrow buttons): the title bar, the form
in force on a light header bar, the selector, the chosen form's description in the Chronicle's
double frame, a status line and one long button (Adopt). All names FNG_*.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from screen_dump import Screen  # noqa: E402
from sn_paths import WORKDIR  # noqa: E402

SCRIPTS = WORKDIR / "arcd" / "scripts"      # vanilla screens (setting SN_WORKDIR)
OUT = HERE.parent / "data" / "scripts" / "FNN_GOVERNMENT_800x600.screen"


def load(name):
    return Screen.load(SCRIPTS / f"{name}_800x600.screen")


def main():
    p = load("BILANZ_PAGE")
    root = p.root
    root.rename("FNN_GOVERNMENT")
    bal = {c.name: c for c in root.children}
    nat, ope, wkr = load("NATION_PAGE"), load("OPTIONEN_GAMEPLAYEINSTELLUNGEN"), load("WERFT_RENAME_INFO")
    info = load("BILANZ_INFO_PAGE").find("LOB_LineCap__00")
    ahs = load("AUTOHANDEL_SPEICHERN_LADEN")
    kids = [bal["LOB_Cap_00"].rename("FNG_CaptionBg"), bal["LOB_Cap_01"].rename("FNG_Caption").set("x", 50).set("w", 340)]
    kids.append(nat.find("CHN_Bg1").clone("FNG_Bg1").set("y", 64))
    kids.append(nat.find("CHN_Txt6").clone("FNG_InForce").set_rect(45, 60, 350, 24))
    kids.append(wkr.find("WKR_Cap").clone("FNG_SelCap").set_rect(70, 96, 300, 22))
    kids.append(ope.find("OPE_BgValue_Level").clone("FNG_Bg").set("x", 112).set("y", 118))
    kids.append(ope.find("OPE_TbValue_Level").clone("FNG_Value").set_rect(120, 123, 200, 21))
    kids.append(ope.find("OPE_Btn_logo_dec").clone("FNG_Prev").set("x", 81).set("y", 121))
    kids.append(ope.find("OPE_Btn_logo_inc").clone("FNG_Next").set("x", 331).set("y", 121))
    kids.append(nat.find("CHN_Noname_05").clone("FNG_Band").set_rect(27, 162, 386, 180))
    kids.append(nat.find("CHN_Noname_00").clone("FNG_Frame").set_rect(25, 160, 390, 184))
    desc = info.clone("FNG_Desc").set_rect(38, 170, 364, 166)
    kids.append(desc)
    kids.append(bal["LOB_Stuff_00"].rename("FNG_Sep").set("y", 350))
    status = info.clone("FNG_Status").set_rect(30, 364, 380, 40)
    kids.append(status)
    kids.append(ahs.find("AHS_ActionBtn").clone("FNG_Adopt").set("x", 142).set("y", 412))
    root.children = kids
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
        if n.cls == "CTextBoxEx" and n.has("text"):
            n.set_text_id("text", "ID_NONE")
    p.save(OUT)
    names = [n.name for n in Screen.load(OUT).walk()]
    assert len(names) == len(set(names)), "duplicate control names"
    assert not any(n.startswith(("LOB_", "CHN_", "OPE_", "WKR_", "AHS_", "S0000")) for n in names), names
    print(f"{OUT}: {len(names)} controls")


if __name__ == "__main__":
    main()
