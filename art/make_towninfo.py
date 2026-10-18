"""The nation's flag in the town info dialog: data/scripts/FNN_TINFO_NATION_800x600.screen.

    python art/make_towninfo.py

A town of the player's nation shows "Your nation" with the nation's flag and the town's
loyalty in the town info dialog's relationship section (the conquered-town info fix, dll/towninfo.c). The
vanilla mini flags there are CStatic animations of the four powers' `Pr2_Flagge_<N>`
parts, which cannot show a .bmp. So the DLL hides them and creates this small screen as
a child of the dialog: the flag cell of the Chronicle's town list row (STADT_ENTRY:
`LOS_Nation`, the CDynamicImg drawable the game loads nation flags into, under the
`LOS_NationFrame` frame), renamed FNI_*. The root sits where the last vanilla mini flag is
(dialog 188,345), left of the relation word.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from screen_dump import Screen  # noqa: E402

SCRIPTS = HERE.parents[1] / "reverse-engineering" / "_workdir" / "arcd" / "scripts"
if not SCRIPTS.is_dir():           # a git worktree: the extracted game data lives in the main checkout
    import subprocess
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=HERE, capture_output=True,
                            text=True).stdout.strip()
    SCRIPTS = (HERE / common).resolve().parent / "reverse-engineering" / "_workdir" / "arcd" / "scripts"
OUT = HERE.parent / "data" / "scripts" / "FNN_TINFO_NATION_800x600.screen"
ROOT_X, ROOT_Y = 181, 339          # frame (7,6) of the row -> dialog (188,345) = SID_Nat_03


def main():
    s = Screen.load(SCRIPTS / "STADT_ENTRY_800x600.screen")
    root = s.root
    root.rename("FNN_TINFO_NATION")
    for name in ("LOS_StadtName", "LOS_Einwohner", "LOS_Wohlstand", "LOS_nation_Texture"):
        root.remove(name)
    root.find("LOS_Nation").rename("FNI_Flag")
    root.find("LOS_NationFrame").rename("FNI_Frame")
    root.set_rect(ROOT_X, ROOT_Y, 34, 24)
    for n in root.walk():
        if n.has("tooltip"):
            n.set_text_id("tooltip", "")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    s.save(OUT)
    back = Screen.load(OUT)
    names = [n.name for n in back.walk()]
    assert names == ["FNN_TINFO_NATION", "FNI_Flag", "FNI_Frame"], names
    print(f"{OUT}: {', '.join(names)}")


if __name__ == "__main__":
    main()
