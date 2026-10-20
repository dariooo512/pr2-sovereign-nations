"""Build the public release with the modding kit's release builder and the mod's install.json.

    python tools/release.py [--dgvoodoo DIR] [--no-check]

The builder is the kit's tools/release/build_release.py (the kit is found through the setting
PR2_KIT, default: a checkout named pr2-modkit next to this mod's folder, or in the workspace).
install.json says what goes in. Writes dist/release/SovereignNations_v<date>-<commit>/
and a zip of it:
  Sovereign Nations Setup.exe   the kit's setup program (tools/release/mod_setup.py) frozen with
                                PyInstaller when it is installed, with installer/header.png in its
                                window; otherwise mod_setup.py + "Sovereign Nations Setup.bat",
                                which need Python 3
  mod/                          version.dll (the kit's loader), PR2Nation.dll, PR2Nation.patches and
                                the loose data files, MANIFEST.json (the mod's name, the PR2.exe
                                builds it is made for, sha256 of each file)
  HOW TO INSTALL.txt (installer/HOW_TO_INSTALL.txt), HOW TO INSTALL.html (the same text under the
  mod's banner), FEATURES.md, CHANGELOG.md, PLAYER_GUIDE.md, VERSION.txt, docs/banner.jpg
--dgvoodoo DIR adds dgVoodoo2's unmodified D3D8.dll / D3DImm.dll / DDraw.dll and dgVoodoo.conf from
an official dgVoodoo2 release folder (its licence lets a game mod ship them unmodified); the setup
installs them only when the player ticks the box.
The check (default on) hashes every file of the test install's game folder and of the extracted
archives and refuses to build if any release file equals a game file, or if the release contains
an .exe / .cpr of the game.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_paths  # noqa: E402  (the settings: SN_/PR2_ names)

MOD = sn_paths.MOD
INSTALL_JSON = MOD / "install.json"


def kit_dir() -> Path:
    """The modding kit's checkout: sn_paths.KIT when it has one, else PR2_KIT, else pr2-modkit next
    to the mod's folder or in the workspace."""
    k = getattr(sn_paths, "KIT", None)
    cands = [Path(k)] if k else []
    if os.environ.get("PR2_KIT"):
        cands.insert(0, Path(os.environ["PR2_KIT"]).expanduser())
    cands += [MOD.parent / "pr2-modkit", sn_paths.WORKSPACE / "pr2-modkit"]
    for c in cands:
        if (c / "tools" / "release" / "build_release.py").exists():
            return c
    raise SystemExit("the modding kit (pr2-modkit) was not found: clone https://github.com/dariooo512/pr2-modkit "
                     "next to this folder or set PR2_KIT to its folder")


def kit_release():
    """The kit's tools/release package (build_release, export_patches, mod_setup, install_json)."""
    d = str(kit_dir() / "tools" / "release")
    if d not in sys.path:
        sys.path.insert(0, d)
    os.environ.setdefault("PR2_BASE_EXE", str(sn_paths.BASE_EXE))    # the mod's settings for the kit's tools
    os.environ.setdefault("MINGW32_BIN", str(sn_paths.MINGW32_BIN))
    import build_release
    return build_release


def config():
    kit_release()
    from install_json import Config
    return Config(INSTALL_JSON)


def game_hashes(mod_rel) -> dict:
    """sha256 -> name of every file of the game: the test install's folder without what the mod
    puts there (its files, the patched PR2_nation.exe, logs, install.json check_ignore) and the
    contents of the game's archives (extracted to reverse-engineering/_workdir, setting SN_WORKDIR)."""
    b = kit_release()
    return b.game_hashes([sn_paths.TEST_ENV], sn_paths.WORKDIR, mod_rel, config().check_ignore)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dgvoodoo", type=Path, help="folder of an official dgVoodoo2 release (MS\\x86 files)")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    b = kit_release()
    if not (MOD / "data" / "nation_flags" / "flag_000.bmp").exists():
        subprocess.run([sys.executable, str(MOD / "art" / "make_logos.py")], check=True)
    out = b.build(config(), a.dgvoodoo, check=not a.no_check, game_dirs=[sn_paths.TEST_ENV], workdir=sn_paths.WORKDIR,
                  base=sn_paths.BASE_EXE)
    print(f"release: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
