"""In-game checks of the loader (the modding kit's loader/, one version.dll for every mod).

    python tools/loader_probe.py [--save "FNN 10 - Nation founded"]
    python tools/loader_probe.py --mods [--hello DIR] [--sn DIR] [--keep]

Run inside the test-install lock (take it yourself first). Never starts PR2.exe: the
Steam-wrapped exe relaunches through the user's Steam install. Saves, settings.cfg, options.dat
and the Run folder's logo files are restored afterwards.

Default: puts the loader (version.dll) and PR2Nation.patches next to the test install's exes, then
  LDR-01  PR2_target.exe (the DRM-free original, no patches on disk) + loader: the loader applies
          every patch in memory and loads PR2Nation.dll; the save loads with its nation, the
          Lua API answers (the full mod without a patched exe)
  LDR-02  PR2_nation.exe (patched on disk) + loader: the loader stays idle, the mod runs once
  LDR-03  patch data with one wrong original byte: nothing is patched, PR2Nation.dll is not
          loaded, the game still reaches its main menu (it starts without the mod)
and removes the loader files again.

--mods: the releases end to end, in a throw-away copy of the pristine game folder
(%USERPROFILE%\\PR2-loader-e2e, with the DRM-free PR2_target.exe; deleted afterwards unless --keep),
with the setups of the releases (their frozen Setup.exe):
  MOD-01  the template's release (HelloMod, made with the kit's tools only): its setup installs it
  MOD-02  PR2_target.exe + the loader: HelloMod.dll loaded, its frame hook, its Lua API registered
          and answering through its dev console; PR2Loader.log names the mod
  MOD-03  its setup uninstalls it: the folder is byte-identical to before
  MOD-04  Sovereign Nations' release and HelloMod side by side: both DLLs load, the save loads with
          its nation, both Lua APIs answer in the same game (the frame hooks chain)
  MOD-05  a third patch file that overlaps Sovereign Nations' patches (the template's entry-point
          detour, exported as ZClash.patches): the loader refuses it by name and starts the others
  MOD-06  HelloMod uninstalled: the loader stays for Sovereign Nations, which still works alone
  MOD-07  Sovereign Nations uninstalled too: the folder is byte-identical to before
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

E2E = Path.home() / "PR2-loader-e2e"
if "--mods" in sys.argv:                 # the tools' test install is the throw-away copy
    for _v in ("PR2_TEST_ENV", "SN_TEST_ENV"):
        os.environ[_v] = str(E2E)
    os.environ.setdefault("PR2_TEST_LOCK", str(Path.home() / "PR2-nation-env.lock"))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_env as env  # noqa: E402  (first: finds the kit)
import sn_session as session  # noqa: E402
import console  # noqa: E402  (the kit's tools/test/console.py)
import feature_suite as F  # noqa: E402
import release  # noqa: E402

LOADER = env.HERE / "_build" / "loader"
FILES = ("version.dll", "PR2Nation.patches")
SAVE = "FNN 10 - Nation founded"
results = []


def record(test, ok, detail):
    results.append((test, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<7} {detail}", flush=True)


def text(p: Path) -> str:
    return p.read_text(encoding="latin-1", errors="replace") if p.exists() else ""


def loader_log():
    return text(env.ENV / "PR2Loader.log")


def mod_log():
    return text(env.ENV / "PR2Nation.log")


def fresh_logs(*names):
    for n in ("PR2Loader.log", "PR2Nation.log") + names:
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


def lua(code, mod="PR2Nation"):
    """Run Lua through `mod`'s dev console; {label: [values]} from its LUA lines."""
    out = {}
    for line in console.run(code, mod=mod).splitlines():
        m = re.search(r"LUA:? (.*)", line)
        if m:
            parts = [x.strip() for x in m.group(1).split("|")]
            out[parts[0]] = parts[1:]
    return out


def kill():
    F.M.kill_game()
    time.sleep(3)


def probe(a):
    for f in FILES:
        if not (LOADER / f).exists():
            raise SystemExit(f"{LOADER / f} missing: python loader/build.py; python tools/export_patches.py")
    for f in FILES:
        shutil.copy2(LOADER / f, env.ENV / f)
    try:
        fresh_logs()
        session.load(a.save, [], "PR2_target.exe")
        time.sleep(3)
        info = F.lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        lg, ml = loader_log(), mod_log()
        m = re.search(r"(\d+) patches applied in memory, section at ([0-9A-F]+); PR2Nation.dll loaded", lg)
        record("LDR-01", m and "PR2Nation.dll loaded" in ml and info[:1] == ["1"],
               f"loader: {m.group(0) if m else lg.strip()[-200:]!r}; nation {info[:3]}")
        kill()

        fresh_logs()
        session.load(a.save, [], "PR2_nation.exe")
        time.sleep(3)
        info = F.lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        lg, ml = loader_log(), mod_log()
        record("LDR-02", "file route" in lg and ml.count("PR2Nation.dll loaded") == 1 and info[:1] == ["1"],
               f"loader: {lg.strip()[-120:]!r}; DLL loaded {ml.count('PR2Nation.dll loaded')}x; nation {info[:2]}")
        kill()

        fresh_logs()
        broken_patches(LOADER / "PR2Nation.patches", env.ENV / "PR2Nation.patches")
        host = session.launch([], "PR2_target.exe")          # up to the main menu
        time.sleep(5)
        lg, ml = loader_log(), mod_log()
        record("LDR-03", "original bytes differ" in lg and "PR2Nation.dll loaded" not in ml and host.poll() is None,
               f"loader: {lg.strip()[-160:]!r}; mod log {'empty' if not ml else 'written'}; game running {host.poll() is None}")
        kill()
    finally:
        for f in FILES + ("PR2Loader.log",):
            try:
                (env.ENV / f).unlink()
            except OSError:
                pass


# ---- --mods ----------------------------------------------------------------------------------
def tree(d: Path) -> dict:
    return {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.rglob("*")) if f.is_file()} | \
           {str(f.relative_to(d)) + "/": "dir" for f in sorted(d.rglob("*")) if f.is_dir()}


def diff(a: dict, b: dict) -> str:
    d = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return "" if not d else f" (differs: {d[:8]}{' ...' if len(d) > 8 else ''})"


def newest(paths):
    paths = sorted(paths, key=lambda p: p.stat().st_mtime)
    return paths[-1].parent.parent if paths else None


def setup(rel: Path, action: str):
    exe = next(rel.glob("* Setup.exe"))
    r = subprocess.run([str(exe), action, "--game", str(E2E)], capture_output=True, text=True, timeout=300)
    return r.returncode


def wait_text(path: Path, pattern: str, timeout: float) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = text(path)
        if re.search(pattern, t):
            return t
        time.sleep(0.25)
    return text(path)


def zclash(kit: Path) -> str:
    """Patch data that overlaps Sovereign Nations': the template's entry-point detour (P06's 5 bytes)."""
    sys.path.insert(0, str(kit / "tools" / "release"))
    import export_patches as X
    from install_json import Config
    cfg = Config(kit / "template" / "install.json")
    cfg.patch_globs, cfg.name = ["patches/load_mod_dll.py"], "ZClash"
    return X.export(cfg, "test", Path(os.environ["PR2_BASE_EXE"]))[0]


def mods(a):
    kit = release.kit_dir()
    hello = a.hello or newest((kit / "template" / "_build" / "release").glob("HelloMod_*/mod/MANIFEST.json"))
    sn = a.sn or newest([p for p in (env.HERE / "dist" / "release").glob("SovereignNations_v*/mod/MANIFEST.json")
                         if json.loads(p.read_text()).get("format") == 2])
    if not hello or not sn:
        raise SystemExit("releases missing: python tools/release/build_release.py template/install.json (kit); "
                         "python tools/release.py")
    print(f"HelloMod release {hello.name}, Sovereign Nations release {sn.name}, folder {E2E}")
    if E2E.exists():
        shutil.rmtree(E2E)
    print(f"copying {env.PRISTINE} -> {E2E} ...", flush=True)
    shutil.copytree(env.PRISTINE, E2E)
    shutil.copy2(env.TARGET_EXE, E2E / "PR2_target.exe")
    env.fast_boot(True)                                     # before the snapshot: the tools' own change
    before = tree(E2E)
    hlog, slog = E2E / "HelloMod.log", E2E / "PR2Nation.log"
    try:
        # MOD-01..03: the template alone
        rc = setup(hello, "install")
        st = E2E / "HelloMod.install.json"
        files = json.loads((hello / "mod" / "MANIFEST.json").read_text())["files"]
        record("MOD-01", rc == 0 and st.exists() and all((E2E / r).exists() for r in files),
               f"HelloMod Setup.exe install: rc {rc}, {len(files)} files, record {st.name}")
        (E2E / "HelloMod.dev").write_bytes(b"")
        host = session.launch([], "PR2_target.exe")
        hl = wait_text(hlog, r"Hello_\* Lua API registered", 30)
        out = console.run('Hello_Log("e2e", Hello_Version())', mod="HelloMod")
        lg = loader_log()
        ok = ("HelloMod.dll loaded" in hl and re.search(r"HOOK A2d\.InputProcessor @\w+ ok", hl)
              and "Hello_* Lua API registered" in hl and "LUA e2e | HelloMod 0.1" in out
              and re.search(r"HelloMod\.patches \(HelloMod\): 0 patches applied in memory, no section; HelloMod\.dll loaded", lg)
              and host.poll() is None)
        record("MOD-02", ok, "PR2Loader.log: " + " / ".join(l[9:] for l in lg.splitlines()[-2:])
               + f"; HelloMod.log: {[l[9:] for l in hl.splitlines()[:3]]}; console: {[l[9:] for l in out.splitlines() if 'LUA' in l]}")
        kill()
        (E2E / "HelloMod.dev").unlink()
        rc = setup(hello, "uninstall")
        after = tree(E2E)
        record("MOD-03", rc == 0 and after == before, f"HelloMod Setup.exe uninstall: rc {rc}, byte-identical "
               f"{after == before}{diff(before, after)}")

        # MOD-04: Sovereign Nations and HelloMod side by side
        rc1, rc2 = setup(sn, "install"), setup(hello, "install")
        for n in ("PR2Nation.dev", "HelloMod.dev"):
            (E2E / n).write_bytes(b"")
        fresh_logs("HelloMod.log")
        session.load(a.save, [], "PR2_target.exe")
        time.sleep(3)
        info = lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        h = lua('Hello_Log("h", Hello_Version(), Hello_GetGold())', mod="HelloMod").get("h", [])
        lg, sl, hl = loader_log(), text(slog), text(hlog)
        both = re.search(r"HelloMod\.patches \(HelloMod\): .*HelloMod\.dll loaded", lg) and \
            re.search(r"PR2Nation\.patches \(Sovereign Nations\): 22 patches applied in memory, section at [0-9A-F]{8}; PR2Nation\.dll loaded", lg)
        chained = "chained behind another mod's hook" in sl + hl
        record("MOD-04", rc1 == 0 and rc2 == 0 and both and chained and info[:1] == ["1"] and h[:1] == ["HelloMod 0.1"],
               f"setups rc {rc1}/{rc2}; both DLLs loaded {bool(both)}; frame hook chained {chained}; "
               f"nation {info[:3]}; Hello {h}")
        kill()

        # MOD-05: an overlapping third patch file
        (E2E / "ZClash.patches").write_text(zclash(kit), encoding="ascii", newline="\n")
        fresh_logs("HelloMod.log")
        host = session.launch([], "PR2_target.exe")
        time.sleep(5)
        lg = loader_log()
        m = re.search(r"ZClash\.patches \(ZClash\): conflicts with PR2Nation\.patches \(Sovereign Nations\)[^;]*", lg)
        record("MOD-05", m and "HelloMod.dll loaded" in lg and "PR2Nation.dll loaded" in lg and host.poll() is None,
               f"{m.group(0) if m else lg[-300:]!r}; the other two loaded; game running {host.poll() is None}")
        kill()
        (E2E / "ZClash.patches").unlink()

        # MOD-06: HelloMod uninstalled, Sovereign Nations alone
        (E2E / "HelloMod.dev").unlink()
        rc = setup(hello, "uninstall")
        fresh_logs()
        session.load(a.save, [], "PR2_target.exe")
        time.sleep(3)
        info = lua('Nation_Log("i", Nation_GetInfo())').get("i", [])
        lg = loader_log()
        record("MOD-06", rc == 0 and (E2E / "version.dll").exists() and not hlog.exists() and "1 patch file(s)" in lg
               and "PR2Nation.dll loaded" in lg and info[:1] == ["1"],
               f"HelloMod uninstall rc {rc}; loader kept; {lg.splitlines()[0][9:] if lg else '?'}; nation {info[:3]}")
        kill()

        # MOD-07: both gone
        (E2E / "PR2Nation.dev").unlink()
        rc = setup(sn, "uninstall")
        after = tree(E2E)
        record("MOD-07", rc == 0 and after == before, f"Sovereign Nations uninstall: rc {rc}, byte-identical "
               f"{after == before}{diff(before, after)}")
    finally:
        kill()
        env.fast_boot(False)
        if not a.keep:
            shutil.rmtree(E2E, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=SAVE)
    ap.add_argument("--mods", action="store_true", help="the releases end to end (see the help above)")
    ap.add_argument("--hello", type=Path, help="the template's release folder (default: its newest)")
    ap.add_argument("--sn", type=Path, help="Sovereign Nations' release folder (default: its newest)")
    ap.add_argument("--keep", action="store_true", help="--mods: keep the throw-away folder")
    a = ap.parse_args()
    snap = env.backup_saves()
    try:
        mods(a) if a.mods else probe(a)
    finally:
        session.cleanup()
        env.restore_saves(Path(snap).parent if Path(snap).name == "Save" else snap)
        env.restore_settings()
    n = sum(ok for _, ok, _ in results)
    print(f"loader probe: {n} pass, {len(results) - n} fail")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
