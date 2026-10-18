"""In-game checks of the in-memory loader (the player setup, loader/loader.c).

    python tools/loader_probe.py [--save "FNN 10 - Nation founded"]

Run inside the test-install lock (scratch locked_run.sh, or after taking it yourself). Puts the
loader (version.dll) and PR2Nation.patches next to the test install's exes, then:
  LDR-01  PR2_target.exe (the DRM-free original, no patches on disk) + loader: the loader applies
          every patch in memory and loads PR2Nation.dll; the save loads with its nation, the
          Lua API answers (the full mod without a patched exe)
  LDR-02  PR2_nation.exe (patched on disk) + loader: the loader stays idle, the mod runs once
  LDR-03  patch data with one wrong original byte: nothing is patched, PR2Nation.dll is not
          loaded, the game still reaches its main menu (it starts without the mod)
Never starts PR2.exe: the Steam-wrapped exe relaunches through the user's Steam install.
Removes the loader files again afterwards; saves and settings are restored.
"""
import argparse
import hashlib
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402
import session  # noqa: E402
import feature_suite as F  # noqa: E402

LOADER = env.HERE / "_build" / "loader"
FILES = ("version.dll", "PR2Nation.patches")
results = []


def record(test, ok, detail):
    results.append((test, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<7} {detail}", flush=True)


def loader_log():
    p = env.ENV / "PR2Loader.log"
    return p.read_text(encoding="latin-1", errors="replace") if p.exists() else ""


def mod_log():
    p = env.ENV / "PR2Nation.log"
    return p.read_text(encoding="latin-1", errors="replace") if p.exists() else ""


def fresh_logs():
    for n in ("PR2Loader.log", "PR2Nation.log"):
        try:
            (env.ENV / n).unlink()
        except OSError:
            pass


def broken_patches(src: Path, dst: Path):
    """The same patch data with the first patch's expected bytes changed (and a valid checksum)."""
    lines = src.read_text(encoding="ascii").splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("patch "):
            f = ln.split()
            f[2] = ("00" if f[2][:2] != "00" else "11") + f[2][2:]
            lines[i] = " ".join(f)
            break
    body = "\n".join(lines[:-1]) + "\n"
    dst.write_text(body + "end " + hashlib.sha256(body.encode("ascii")).hexdigest() + "\n", encoding="ascii")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 10 - Nation founded")
    a = ap.parse_args()
    for f in FILES:
        if not (LOADER / f).exists():
            raise SystemExit(f"{LOADER / f} missing: python loader/build.py; python tools/export_patches.py")
    backup = env.backup_saves()
    try:
        for f in FILES:
            shutil.copy2(LOADER / f, env.ENV / f)

        fresh_logs()
        session.load(a.save, [], "PR2_target.exe")
        time.sleep(3)
        info = F.lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        lg, ml = loader_log(), mod_log()
        m = re.search(r"(\d+) patches applied in memory, section at ([0-9A-F]+); PR2Nation.dll loaded", lg)
        record("LDR-01", m and "PR2Nation.dll loaded" in ml and info[:1] == ["1"],
               f"loader: {m.group(0) if m else lg.strip()[-200:]!r}; nation {info[:3]}")
        F.M.kill_game()
        time.sleep(3)

        fresh_logs()
        session.load(a.save, [], "PR2_nation.exe")
        time.sleep(3)
        info = F.lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        lg, ml = loader_log(), mod_log()
        record("LDR-02", "file route" in lg and ml.count("PR2Nation.dll loaded") == 1 and info[:1] == ["1"],
               f"loader: {lg.strip()[-120:]!r}; DLL loaded {ml.count('PR2Nation.dll loaded')}x; nation {info[:2]}")
        F.M.kill_game()
        time.sleep(3)

        fresh_logs()
        broken_patches(LOADER / "PR2Nation.patches", env.ENV / "PR2Nation.patches")
        host = session.launch([], "PR2_target.exe")          # up to the main menu
        time.sleep(5)
        lg, ml = loader_log(), mod_log()
        record("LDR-03", "original bytes differ" in lg and "PR2Nation.dll loaded" not in ml and host.poll() is None,
               f"loader: {lg.strip()[-160:]!r}; mod log {'empty' if not ml else 'written'}; game running {host.poll() is None}")
        F.M.kill_game()
    finally:
        F.M.kill_game()
        for f in FILES + ("PR2Loader.log",):
            try:
                (env.ENV / f).unlink()
            except OSError:
                pass
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig = env.BACKUPS / "settings.cfg.orig"
        if orig.exists():
            shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
    n = sum(ok for _, ok, _ in results)
    print(f"loader probe: {n} pass, {len(results) - n} fail")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
