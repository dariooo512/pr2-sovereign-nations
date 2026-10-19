"""Clean, disposable test install for found-new-nation experiments.

Builds a game install from the pristine copy (original-game/original, setting SN_PRISTINE),
outside any synced folder and separate from the Steam install, so no other mod leaks into a
test. Paths are settings with defaults: tools/sn_paths.py.

    python tools/env.py setup          # create/verify the env
    python tools/env.py status         # report drift from pristine
    python tools/env.py backup-saves   # snapshot the shared Save dir
    python tools/env.py windowed on|off
    python tools/env.py fast-boot on|off  # park/restore intro videos
    python tools/env.py dpi-aware on|off  # no 2x window scaling (test exes only)
    python tools/env.py deploy <built.exe> # install a patched build as PR2_nation.exe

The game always writes saves and settings to the user's Documents folder, which
is shared with the Steam install -- hence backup-saves before every experiment.
"""
import hashlib
import os
import subprocess
import shutil
import sys
import time
from pathlib import Path

import sn_paths

REPO = sn_paths.WORKSPACE
HERE = sn_paths.MOD                  # the mod's folder
PRISTINE = sn_paths.PRISTINE
TARGET_EXE = sn_paths.BASE_EXE
WORKDIR = sn_paths.WORKDIR           # the game's archives, extracted
TARGET_SHA = "9c9250bc2b7a8068f658c0d9935bf2e7d8f9865bc31b875d9fb3b220d01cf448"
RETAIL_SHA = "5295c06689147f7565f72510aeb686719cf0ae38aa581a6df3e4d61d0cf76264"

ENV = sn_paths.TEST_ENV
LOCK = sn_paths.TEST_LOCK           # shared by every test run of ENV
ENV_EXE = ENV / "PR2_target.exe"
MOD_EXE = ENV / "PR2_nation.exe"     # patched build deployed by `env.py deploy`
MOD_DLL = ENV / "PR2Nation.dll"      # nation logic, loaded by patch P06
MOD_LOG = ENV / "PR2Nation.log"
SAVE_DIR = sn_paths.SAVE_DIR
BACKUPS = HERE / "_backup"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_files(root):
    return {p.relative_to(root).as_posix(): p.stat().st_size for p in root.rglob("*") if p.is_file()}


INTRO_VIDEOS = ["Videos/ascaron.wmv", "Videos/nvidia.wmv", "Videos/intro.wmv"]
PARKED = ENV / "_parked"   # files moved aside by a profile, restorable


def fast_boot(on):
    """Skip the startup videos by parking them (they are pure presentation)."""
    for rel in INTRO_VIDEOS:
        live, parked = ENV / rel, PARKED / rel
        src, dst = (live, parked) if on else (parked, live)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
    print(f"fast boot {'on' if on else 'off'} (intro videos {'parked' if on else 'restored'})")


def dpi_aware(on):
    """Windows compatibility flag for the test exe only: without it, a 200%-scaled
    display doubles the (DPI-unaware) game window to fill the whole screen."""
    import winreg
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers")
    for exe in (ENV_EXE, MOD_EXE):
        if on:
            winreg.SetValueEx(key, str(exe), 0, winreg.REG_SZ, "~ HIGHDPIAWARE")
        else:
            try:
                winreg.DeleteValue(key, str(exe))
            except FileNotFoundError:
                pass
    print(f"HIGHDPIAWARE {'set' if on else 'cleared'} for {ENV_EXE.name}, {MOD_EXE.name}")


def drift():
    """Files in ENV that differ from the pristine copy (besides our target exe
    and anything a profile parked)."""
    want, have = rel_files(PRISTINE), rel_files(ENV)
    parked = {p.relative_to(PARKED).as_posix() for p in PARKED.rglob("*") if p.is_file()} \
        if PARKED.exists() else set()
    if parked:
        print(f"parked:    {sorted(parked)}")
    have = {f: s for f, s in have.items() if not f.startswith("_parked/")}
    extra = sorted(set(have) - set(want) - {ENV_EXE.name, MOD_EXE.name, MOD_DLL.name, MOD_LOG.name})
    missing = sorted(set(want) - set(have) - parked)
    resized = sorted(f for f in set(want) & set(have) if want[f] != have[f])
    return extra, missing, resized


def setup():
    if sha256(PRISTINE / "PR2.exe") != RETAIL_SHA:
        sys.exit(f"pristine copy is not retail 1.1.2.3: {PRISTINE / 'PR2.exe'}")
    if sha256(TARGET_EXE) != TARGET_SHA:
        sys.exit(f"target exe hash mismatch: {TARGET_EXE}")
    if not ENV.exists():
        print(f"copying {PRISTINE} -> {ENV} ...")
        shutil.copytree(PRISTINE, ENV)
    shutil.copy2(TARGET_EXE, ENV_EXE)
    status()


def status():
    if not ENV.exists():
        sys.exit(f"no env at {ENV}; run setup")
    extra, missing, resized = drift()
    exe_ok = ENV_EXE.exists() and sha256(ENV_EXE) == TARGET_SHA
    print(f"env:       {ENV}")
    print(f"target:    {ENV_EXE.name} {'OK (unmodified unpacked 1.1.2.3)' if exe_ok else 'MISSING/MODIFIED'}")
    print(f"extra:     {extra or 'none'}")
    print(f"missing:   {missing or 'none'}")
    print(f"resized:   {resized or 'none'}")
    clean = exe_ok and not (extra or missing or resized)
    print("VERDICT:  ", "CLEAN" if clean else "DIRTY")
    return clean


def deploy(built):
    """Copy a pe_patch.py build (with its manifest) into the env as PR2_nation.exe."""
    built = Path(built)
    shutil.copy2(built, MOD_EXE)
    print(f"deployed {built} -> {MOD_EXE} sha256 {sha256(MOD_EXE)}")
    dll = HERE / "_build" / "dll" / MOD_DLL.name
    if dll.exists():
        shutil.copy2(dll, MOD_DLL)
        print(f"deployed {dll} -> {MOD_DLL}")


RUN_DIR = Path(os.environ.get("APPDATA", "")) / "Ascaron Entertainment" / "Port Royale 2" / "Run"
RUN_FILES = ("0.bmp", "Player0.aim", "0_company_logo.bmp", "7.bmp", "Player7.aim")   # 7 = the nation's flag


def backup_saves():
    """Save folder + the player logo files (the mod writes the nation flag into Run\0.bmp)."""
    dest = BACKUPS / time.strftime("saves-%Y%m%d-%H%M%S")
    shutil.copytree(SAVE_DIR, dest)
    run = dest / "_run"
    run.mkdir()
    for n in RUN_FILES:
        if (RUN_DIR / n).exists():
            shutil.copy2(RUN_DIR / n, run / n)
    print(f"saves backed up -> {dest}")
    return dest


def restore_run(backup):
    """Put the player logo files back as they were before the test run."""
    run = Path(backup) / "_run"
    if not run.exists():
        return
    for n in RUN_FILES:
        if (run / n).exists():
            shutil.copy2(run / n, RUN_DIR / n)
        elif (RUN_DIR / n).exists():
            (RUN_DIR / n).unlink()


def windowed(on):
    cfg = SAVE_DIR / "settings.cfg"
    orig = BACKUPS / "settings.cfg.orig"
    text = cfg.read_text()
    if not orig.exists() or "FULLSCREEN : 0" not in text:   # an orig from an older run would undo later changes
        BACKUPS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg, orig)
    lines = text.splitlines()
    lines = [f"FULLSCREEN : {0 if on else 1}" if l.startswith("FULLSCREEN") else l for l in lines]
    cfg.write_text("\n".join(lines) + "\n")
    print(f"{cfg}: FULLSCREEN = {0 if on else 1}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        setup()
    elif cmd == "status":
        sys.exit(0 if status() else 1)
    elif cmd == "backup-saves":
        backup_saves()
    elif cmd == "windowed":
        windowed(sys.argv[2] == "on")
    elif cmd == "deploy":
        deploy(sys.argv[2])
    elif cmd == "dpi-aware":
        dpi_aware(sys.argv[2] == "on")
    elif cmd == "fast-boot":
        fast_boot(sys.argv[2] == "on")
    else:
        sys.exit(__doc__)


def mute_sound():
    """Keep the test game silent: start tools/mute_game.ps1 -Watch (the volume mixer's mute for
    PR2_nation.exe / PR2_target.exe) unless one is already running; it stops by itself after
    10 minutes without a test game. Works whatever DLL is installed (the DLL also mutes itself
    in a test install, dll/mute.c)."""
    pid_file = HERE / "_build" / "mute_watch.pid"
    try:
        pid = int(pid_file.read_text())
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        if str(pid) in out:
            return
    except (OSError, ValueError):
        pass
    p = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(HERE / "tools" / "mute_game.ps1"), "-Watch", "-IdleMinutes", "10"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x08000000)              # CREATE_NO_WINDOW
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(p.pid))
