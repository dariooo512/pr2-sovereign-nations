"""Sovereign Nations setup: installs the mod into the player's own Port Royale 2 (the player setup).

    sn_setup.py [--game DIR]          the setup window (DIR: preselect that folder instead of Steam's)
    sn_setup.py status  [--game DIR]
    sn_setup.py install [--game DIR] [--force] [--dgvoodoo]    (also updates an older version)
    sn_setup.py repair  [--game DIR]
    sn_setup.py uninstall [--game DIR]

What it does to the game folder:
  * adds the loader (version.dll), PR2Nation.dll, the patch data PR2Nation.patches and the mod's
    loose data files (lua\\config\\default\\include.ini, scripts\\FNN_*.screen, nation_flags\\);
    optionally dgVoodoo2's D3D8 wrapper for machines whose Direct3D 8 hangs (Intel D3D9on12);
  * never changes PR2.exe or any save; a game file it has to replace (a loose include.ini, a
    modified TOPMENUBAR screen) is backed up first to _SovereignNations_backup\\;
  * records what it did in SovereignNations.install.json, so Uninstall puts the folder back
    exactly as it was (added files removed, replaced files restored, created folders removed)
    and Install over an older version updates it in place.
The game is started as always (from Steam); the loader applies the mod in memory and leaves
the game unmodded if the game build is not the one the mod was made for (loader/loader.c).
The mod files come from the folder "mod" next to this program (MANIFEST.json lists them).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

APP = "Sovereign Nations"
STATE = "SovereignNations.install.json"
BACKUP = "_SovereignNations_backup"
STEAM_APP = "12470"
# PR2.exe builds the mod is made for (sha256): the Steam release and its DRM-free image
KNOWN_EXES = {
    "5295c06689147f7565f72510aeb686719cf0ae38aa581a6df3e4d61d0cf76264": "Port Royale 2 1.1.2.3 (Steam)",
    "9c9250bc2b7a8068f658c0d9935bf2e7d8f9865bc31b875d9fb3b220d01cf448": "Port Royale 2 1.1.2.3 (DRM-free)",
}
OTHER_MOD_HINT = ("towns", "*.tow")          # the 4x towns mod's loose files


class SetupError(Exception):
    pass


def here() -> Path:
    return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent)


def package_dir() -> Path:
    for base in (Path(sys.executable).parent if getattr(sys, "frozen", False) else None, here(), here().parent):
        if base and (base / "mod" / "MANIFEST.json").exists():
            return base / "mod"
    raise SetupError("the folder 'mod' with MANIFEST.json is missing next to the setup program")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- finding the game ------------------------------------------------------------------------
def steam_root() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                           (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                           (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                p = Path(winreg.QueryValueEx(k, val)[0])
                if p.exists():
                    return p
        except OSError:
            continue
    return None


def steam_libraries(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)
    return libs


def find_game() -> Path | None:
    """The Steam install of Port Royale 2 (app 12470), read-only."""
    root = steam_root()
    if not root:
        return None
    for lib in steam_libraries(root):
        acf = lib / "steamapps" / f"appmanifest_{STEAM_APP}.acf"
        if acf.exists():
            m = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text(encoding="utf-8", errors="replace"))
            if m:
                for d in (lib / "steamapps" / "common" / m.group(1), lib / "steamapps" / "common" / m.group(1) / "Game"):
                    if (d / "PR2.exe").exists():
                        return d
    return None


def identify(game: Path) -> str:
    exe = game / "PR2.exe"
    if not exe.exists():
        raise SetupError(f"{game} has no PR2.exe: choose the folder that contains PR2.exe")
    name = KNOWN_EXES.get(sha256(exe))
    if not name:
        raise SetupError("This PR2.exe is a game build the mod was not made for (or it was changed). "
                         "Sovereign Nations needs Port Royale 2 1.1.2.3 as sold on Steam. Nothing was installed.")
    return name


# ---- install state -------------------------------------------------------------------------------
def load_state(game: Path) -> dict | None:
    p = game / STATE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError(f"{p} is damaged; it says how to undo the installation, so fix or restore it first")


def save_state(game: Path, st: dict):
    (game / STATE).write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")


def manifest(pkg: Path, dgvoodoo: bool) -> dict:
    m = json.loads((pkg / "MANIFEST.json").read_text(encoding="utf-8"))
    files = dict(m["files"])
    if dgvoodoo:
        files.update(m.get("dgvoodoo", {}))
    for rel in files:
        if Path(rel).name.lower() == "pr2.exe" or ".." in Path(rel).parts or Path(rel).is_absolute():
            raise SetupError(f"the package lists {rel!r}: refusing")
    return {"version": m["version"], "files": files}


def other_mod_files(game: Path) -> list[Path]:
    d = game / OTHER_MOD_HINT[0]
    return sorted(d.glob(OTHER_MOD_HINT[1])) if d.exists() else []


def _remove_file(game: Path, rel: str, entry: dict, log):
    dst, bak = game / rel, game / BACKUP / rel
    if entry.get("replaced"):
        if bak.exists():
            shutil.copy2(bak, dst)
            log(f"restored {rel}")
        else:
            log(f"WARNING: the original of {rel} is missing from the backup; left as it is")
    elif dst.exists():
        dst.unlink()
        log(f"removed {rel}")


def _prune_dirs(game: Path, dirs: list[str], log):
    for rel in sorted(dirs, key=lambda d: -len(Path(d).parts)):
        d = game / rel
        try:
            d.rmdir()                                    # only if empty
            log(f"removed folder {rel}")
        except OSError:
            pass


def install(game: Path, force=False, dgvoodoo=False, log=print, confirm=None) -> str:
    name = identify(game)
    pkg = package_dir()
    man = manifest(pkg, dgvoodoo)
    towns = other_mod_files(game)
    if towns and not force:
        msg = (f"{game / OTHER_MOD_HINT[0]} has {len(towns)} loose town files from another mod (the 4x towns mod?). "
               "Sovereign Nations is made and tested with the original towns. Install anyway?")
        if not (confirm and confirm(msg)):
            raise SetupError("not installed: another mod's town files are present (use --force to install anyway)")
    st = load_state(game) or {"files": {}, "dirs": []}
    old_files = st["files"]
    # update: files of the old version that the new one no longer has
    for rel in [r for r in old_files if r not in man["files"]]:
        _remove_file(game, rel, old_files[rel], log)
        del old_files[rel]
    for rel, want in sorted(man["files"].items()):
        src, dst = pkg / rel, game / rel
        if not src.exists() or sha256(src) != want:
            raise SetupError(f"the package is damaged: {rel} is missing or changed (download it again)")
        entry = old_files.get(rel)
        if entry is None:
            entry = {"replaced": dst.exists()}
            if entry["replaced"]:
                bak = game / BACKUP / rel
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bak)
                log(f"backed up {rel}")
            parent = Path(rel).parent
            while str(parent) not in (".", ""):
                if not (game / parent).exists() and str(parent) not in st["dirs"]:
                    st["dirs"].append(str(parent))
                parent = parent.parent
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or sha256(dst) != want:
            shutil.copy2(src, dst)
        entry["sha256"] = want
        old_files[rel] = entry
    previous = st.get("version")
    st.update(version=man["version"], game=name, files=old_files)
    save_state(game, st)
    log(f"{APP} {man['version']} {'updated from ' + previous if previous and previous != man['version'] else 'installed'} "
        f"for {name}: {len(old_files)} files. Start the game from Steam as always.")
    return man["version"]


def repair(game: Path, log=print) -> int:
    st = load_state(game)
    if not st:
        raise SetupError(f"{APP} is not installed in {game}")
    identify(game)
    pkg = package_dir()
    n = 0
    for rel, entry in st["files"].items():
        dst, src = game / rel, pkg / rel
        if not dst.exists() or sha256(dst) != entry["sha256"]:
            if not src.exists() or sha256(src) != entry["sha256"]:
                raise SetupError(f"{rel} cannot be repaired from this package (version {st['version']} needed)")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log(f"repaired {rel}")
            n += 1
    log(f"repair: {n} file(s) put back" if n else "repair: every file is in order")
    return n


def uninstall(game: Path, log=print):
    st = load_state(game)
    if not st:
        raise SetupError(f"{APP} is not installed in {game}")
    for rel, entry in st["files"].items():
        _remove_file(game, rel, entry, log)
    shutil.rmtree(game / BACKUP, ignore_errors=True)
    (game / STATE).unlink()
    for extra in ("PR2Loader.log", "PR2Nation.log"):          # written by the mod while playing
        try:
            (game / extra).unlink()
        except OSError:
            pass
    _prune_dirs(game, st.get("dirs", []), log)
    log(f"{APP} removed; the game folder is as it was before.")


def status(game: Path) -> str:
    st = load_state(game)
    try:
        name = identify(game)
    except SetupError as e:
        name = str(e)
    if not st:
        return f"{game}\n{name}\n{APP} is not installed."
    bad = [r for r, e in st["files"].items() if not (game / r).exists() or sha256(game / r) != e["sha256"]]
    return (f"{game}\n{name}\n{APP} {st['version']} installed ({len(st['files'])} files)"
            + (f"; {len(bad)} file(s) changed or missing: use Repair" if bad else "."))


# ---- the window ----------------------------------------------------------------------------------
HEADER = "header.png"          # the mod's main image, 600x300 (art/make_banner.py); bundled into the exe


def gui(game_dir: Path | None = None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    root = tk.Tk()
    root.title(f"{APP} setup")
    game = tk.StringVar(value=str(game_dir or find_game() or ""))
    dgv = tk.BooleanVar(value=False)
    try:                                         # the header is decoration: the setup works without it
        root.header = tk.PhotoImage(file=str(here() / HEADER))
        tk.Label(root, image=root.header, borderwidth=0).pack(side="top", pady=(10, 0))
    except (tk.TclError, OSError):
        pass
    frm = tk.Frame(root, padx=12, pady=10)
    frm.pack(fill="both", expand=True)
    tk.Label(frm, text="Port Royale 2 folder (the one with PR2.exe):").grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Entry(frm, textvariable=game, width=70).grid(row=1, column=0, columnspan=2, sticky="we")

    def browse():
        d = filedialog.askdirectory(title="The Port Royale 2 folder (with PR2.exe)")
        if d:
            game.set(d)
            show()
    tk.Button(frm, text="Browse...", command=browse).grid(row=1, column=2, padx=6)
    tk.Checkbutton(frm, text="Also install dgVoodoo2 (only if the game hangs on start with a black screen)",
                   variable=dgv).grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
    out = scrolledtext.ScrolledText(frm, width=84, height=14)
    out.grid(row=3, column=0, columnspan=3, pady=6)

    def log(s):
        out.insert("end", s + "\n")
        out.see("end")
        root.update_idletasks()

    def show():
        out.delete("1.0", "end")
        if game.get():
            log(status(Path(game.get())))
        else:
            log("Steam's Port Royale 2 was not found: choose its folder with Browse.")

    def run(fn):
        try:
            fn()
        except SetupError as e:
            log(str(e))
            messagebox.showerror(APP, str(e))
        except OSError as e:
            log(f"error: {e}")
            messagebox.showerror(APP, f"{e}\n\nIs the game still running? Close it and try again.")
    btns = tk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=3)
    tk.Button(btns, text="Install / Update", width=16, command=lambda: run(lambda: install(
        Path(game.get()), dgvoodoo=dgv.get(), log=log, confirm=lambda m: messagebox.askyesno(APP, m)))).pack(side="left", padx=4)
    tk.Button(btns, text="Repair", width=12, command=lambda: run(lambda: repair(Path(game.get()), log=log))).pack(side="left", padx=4)
    tk.Button(btns, text="Uninstall", width=12, command=lambda: run(
        lambda: messagebox.askyesno(APP, "Remove Sovereign Nations? Your saves stay.") and uninstall(Path(game.get()), log=log))).pack(side="left", padx=4)
    tk.Button(btns, text="Close", width=10, command=root.destroy).pack(side="left", padx=4)
    show()
    root.mainloop()


def main(argv=None):
    if argv is None and len(sys.argv) == 1:
        gui()
        return 0
    ap = argparse.ArgumentParser(description=f"{APP} setup")
    ap.add_argument("action", nargs="?", choices=["status", "install", "repair", "uninstall"],
                    help="without an action: the setup window")
    ap.add_argument("--game", type=Path, help="the folder with PR2.exe (default: the Steam install)")
    ap.add_argument("--force", action="store_true", help="install even with another mod's town files present")
    ap.add_argument("--dgvoodoo", action="store_true", help="also install dgVoodoo2's D3D8 wrapper")
    a = ap.parse_args(argv)
    if a.action is None:
        gui(a.game)
        return 0
    game = a.game or find_game()
    if not game:
        print("Steam's Port Royale 2 was not found: give its folder with --game")
        return 2
    try:
        if a.action == "status":
            print(status(game))
        elif a.action == "install":
            install(game, force=a.force, dgvoodoo=a.dgvoodoo)
        elif a.action == "repair":
            repair(game)
        else:
            uninstall(game)
    except SetupError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
