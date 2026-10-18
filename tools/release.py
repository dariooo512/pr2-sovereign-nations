"""Build the public release: the setup program and the mod files, no game file (the player setup).

    python tools/release.py [--dgvoodoo DIR] [--no-check]

Writes dist/release/SovereignNations_v<date>-<commit>/ and a zip of it:
  Sovereign Nations Setup.exe   the setup program (installer/sn_setup.py, frozen with PyInstaller
                                when it is installed; otherwise sn_setup.py + "Sovereign Nations
                                Setup.bat", which need Python 3)
  mod/                          version.dll (the loader), PR2Nation.dll, PR2Nation.patches and the
                                loose data files, MANIFEST.json (sha256 of each)
  HOW TO INSTALL.txt, HOW TO INSTALL.html (the same text under the mod's banner), FEATURES.md,
  CHANGELOG.md, PLAYER_GUIDE.md, VERSION.txt, docs/banner.jpg (the banner the guide and the .html show)
--dgvoodoo DIR adds dgVoodoo2's unmodified D3D8.dll / D3DImm.dll / DDraw.dll and dgVoodoo.conf from
an official dgVoodoo2 release folder (its licence lets a game mod ship them unmodified); the setup
installs them only when the player ticks the box.
The check (default on) hashes every file of the test install's game folder and refuses to build if
any release file equals a game file, or if the release contains an .exe / .cpr of the game.
"""
import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402

DIST = env.HERE / "dist" / "release"
DGV_FILES = ("D3D8.dll", "D3DImm.dll", "DDraw.dll", "dgVoodoo.conf")

HOW_TO = r"""PORT ROYALE 2 - SOVEREIGN NATIONS {version}
HOW TO INSTALL
==============================================

WHAT YOU NEED
- Port Royale 2 from Steam, installed (version 1.1.2.3, the one Steam sells).
- Windows 10 or 11.

INSTALL
1. Extract this zip to any folder (right-click -> Extract All...).
2. Double-click "Sovereign Nations Setup".
3. The setup finds your Steam copy of Port Royale 2 by itself (or click Browse and pick the
   folder that contains PR2.exe). Click "Install / Update".
4. Start Port Royale 2 from Steam as always. The nation button (a flag) is in the top bar.

The mod does not change PR2.exe or your saves. If Steam updates the game to a build the mod
does not know, the game simply starts without the mod.

BLACK SCREEN OR HANG ON START (some Intel graphics)
Run the setup again, tick "Also install dgVoodoo2" and click "Install / Update".

UPDATE
Run the setup of the new version and click "Install / Update". No need to uninstall first.

UNINSTALL
Run the setup and click "Uninstall". The game folder is put back exactly as it was; saves stay.

REPAIR
If a mod file was deleted or changed, run the setup and click "Repair".

Logs, if something goes wrong: PR2Loader.log and PR2Nation.log in the game folder.
"""

HOW_TO_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sovereign Nations: how to install</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:1200px;margin:0 auto;padding:16px;background:#fff;color:#111}}
img{{width:100%;height:auto}} pre{{white-space:pre-wrap;font:15px/1.5 Segoe UI,Arial,sans-serif}}</style></head>
<body><img src="docs/banner.jpg" alt="Sovereign Nations, a Port Royale 2 mod">
<pre>{text}</pre></body></html>
"""

SETUP_BAT = r"""@echo off
rem Sovereign Nations setup (needs Python 3 from python.org when there is no Setup.exe)
python "%~dp0sn_setup.py" %*
if errorlevel 9009 echo Python 3 is needed: https://www.python.org/downloads/ & pause
"""


def git(*args):
    return subprocess.run(["git", "-C", str(env.HERE), *args], capture_output=True, text=True).stdout.strip()


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_parts():
    for script in (env.HERE / "dll" / "build.py", env.HERE / "loader" / "build.py"):
        subprocess.run([sys.executable, str(script)], check=True)
    subprocess.run([sys.executable, str(HERE / "export_patches.py"), "--check"], check=True)
    if not (env.HERE / "data" / "nation_flags" / "flag_000.bmp").exists():
        subprocess.run([sys.executable, str(env.HERE / "art" / "make_logos.py")], check=True)


def mod_files() -> dict:
    files = {"version.dll": env.HERE / "_build" / "loader" / "version.dll",
             "PR2Nation.dll": env.HERE / "_build" / "dll" / "PR2Nation.dll",
             "PR2Nation.patches": env.HERE / "_build" / "loader" / "PR2Nation.patches"}
    data = env.HERE / "data"
    for f in sorted(data.rglob("*")):
        if f.is_file() and f.name != "README.md":
            files[str(f.relative_to(data)).replace("/", "\\")] = f
    return files


def game_hashes(mod_rel) -> dict:
    """sha256 -> name of every file of the game: the test install's folder without what the mod
    puts there (its files, the patched PR2_nation.exe, logs) and the contents of the game's
    archives (extracted to reverse-engineering/_workdir, setting SN_WORKDIR)."""
    ours = {r.lower() for r in mod_rel} | {"pr2_nation.exe", "pr2nation.dll", "pr2nation.ini", "pr2nation.log",
                                            "pr2nation.dev", "pr2nation.cmd", "pr2loader.log", "version.dll",
                                            "pr2nation.patches"}
    out = {}
    for f in env.ENV.rglob("*"):
        rel = str(f.relative_to(env.ENV))
        if not f.is_file() or f.stat().st_size == 0 or "_parked" in f.parts or rel.lower() in ours or                 rel.lower().startswith("nation_flags"):
            continue
        out.setdefault(sha256(f), rel)
    work = env.WORKDIR
    for f in work.rglob("*") if work.exists() else []:
        if f.is_file() and f.stat().st_size > 0:
            out.setdefault(sha256(f), "archive: " + str(f.relative_to(work)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dgvoodoo", type=Path, help="folder of an official dgVoodoo2 release (MS\\x86 files)")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    build_parts()
    commit = git("log", "-1", "--format=%h", "--abbrev=8") or "nogit"
    version = f"v{time.strftime('%Y.%m.%d')}-{commit}"
    out = DIST / f"SovereignNations_{version}"
    shutil.rmtree(out, ignore_errors=True)
    mod = out / "mod"
    files = mod_files()
    man = {"version": version, "files": {}, "dgvoodoo": {}}
    for rel, src in files.items():
        dst = mod / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        man["files"][rel] = sha256(dst)
    if a.dgvoodoo:
        for n in DGV_FILES:
            src = next(iter(a.dgvoodoo.rglob(n)), None)
            if src:
                shutil.copy2(src, mod / n)
                man["dgvoodoo"][n] = sha256(mod / n)
    (mod / "MANIFEST.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    setup = env.HERE / "installer" / "sn_setup.py"
    frozen = False
    try:
        import PyInstaller  # noqa: F401
        work = env.HERE / "_build" / "pyinstaller"
        header = setup.parent / "header.png"          # the window's header image (art/make_banner.py)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--name",
                        "Sovereign Nations Setup", "--distpath", str(out), "--workpath", str(work),
                        "--specpath", str(work), "--add-data", f"{header}{os.pathsep}.", str(setup)], check=True)
        frozen = True
    except ImportError:
        shutil.copy2(setup, out / "sn_setup.py")
        shutil.copy2(setup.parent / "header.png", out / "header.png")
        (out / "Sovereign Nations Setup.bat").write_text(SETUP_BAT, encoding="ascii")
    how_to = HOW_TO.format(version=version)
    (out / "HOW TO INSTALL.txt").write_text(how_to.replace("\n", "\r\n"), encoding="utf-8")
    (out / "HOW TO INSTALL.html").write_text(HOW_TO_HTML.format(text=html.escape(how_to)), encoding="utf-8")
    (out / "docs").mkdir()
    shutil.copy2(env.HERE / "docs" / "banner.jpg", out / "docs" / "banner.jpg")
    for doc in ("FEATURES.md", "CHANGELOG.md", "PLAYER_GUIDE.md"):
        shutil.copy2(env.HERE / doc, out / doc)
    (out / "VERSION.txt").write_text(f"Sovereign Nations {version}\r\n", encoding="ascii")

    if not a.no_check:
        game = game_hashes(files)
        bad = []
        for f in out.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() in (".cpr", ".pr2") or (f.suffix.lower() == ".exe" and not frozen) or f.name.lower() == "pr2.exe":
                bad.append(f"{f.relative_to(out)}: a game file type")
            h = sha256(f)
            if h in game:
                bad.append(f"{f.relative_to(out)} == game file {game[h]}")
        if bad:
            raise SystemExit("release refused, it contains game files:\n  " + "\n  ".join(bad))
        print(f"check: none of {sum(1 for f in out.rglob('*') if f.is_file())} release files is one of the "
              f"game's {len(game)} files")
    z = out.parent / (out.name + ".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out.parent))
    print(f"{z} ({z.stat().st_size // 1024} KB), setup {'exe' if frozen else 'script (no PyInstaller)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
