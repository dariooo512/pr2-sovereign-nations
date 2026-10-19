"""Tests of the setup program (installer/sn_setup.py) on throw-away copies of a game folder.

    python tools/test_installer.py [--release DIR]

Never touches a real install: each test builds a small fake game folder in _build/installer_test
with a copy of the test install's PR2.exe (the Steam build) and a few vanilla files, then runs the
setup's install / update / repair / uninstall and compares the folder byte for byte.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402

results = []


def record(test, ok, detail):
    results.append((test, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<7} {detail}", flush=True)


def tree(d: Path) -> dict:
    return {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.rglob("*")) if f.is_file()} | \
           {str(f.relative_to(d)) + "/": "dir" for f in sorted(d.rglob("*")) if f.is_dir()}


def fake_game(root: Path, loose_include=False, towns=False) -> Path:
    g = root / "Game"
    shutil.rmtree(root, ignore_errors=True)
    (g / "scripts").mkdir(parents=True)
    shutil.copy2(env.ENV / "PR2.exe", g / "PR2.exe")
    for n in ("A2dLib-2.20A.dll", "lua.dll"):
        shutil.copy2(env.ENV / n, g / n)
    (g / "scripts" / "SOMETHING_800x600.screen").write_bytes(b"vanilla screen")
    if loose_include:
        (g / "lua" / "config" / "default").mkdir(parents=True)
        (g / "lua" / "config" / "default" / "include.ini").write_text("-- another mod's include.ini\n")
    if towns:
        (g / "towns").mkdir()
        (g / "towns" / "Tortuga.tow").write_bytes(b"4x town")
    return g


def latest_release() -> Path:
    rels = sorted((env.HERE / "dist" / "release").glob("SovereignNations_v*/mod/MANIFEST.json"), key=lambda p: p.stat().st_mtime)
    if not rels:
        raise SystemExit("no release: python tools/release.py")
    return rels[-1].parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", type=Path)
    a = ap.parse_args()
    rel = a.release or latest_release()
    sys.path.insert(0, str(env.HERE / "installer"))
    import sn_setup as S
    S.package_dir = lambda: rel / "mod"                     # the release under test
    man = json.loads((rel / "mod" / "MANIFEST.json").read_text())
    root = env.HERE / "_build" / "installer_test"
    log = []
    if not (env.ENV / "PR2.exe").exists():
        raise SystemExit(f"no test install at {env.ENV}: run python tools/env.py setup (setting SN_TEST_ENV)")

    g = fake_game(root)
    before = tree(g)
    exe0 = hashlib.sha256((g / "PR2.exe").read_bytes()).hexdigest()
    S.install(g, log=log.append)
    st = json.loads((g / S.STATE).read_text())
    ok = all((g / r).exists() for r in man["files"]) and len(st["files"]) == len(man["files"])
    record("INS-01", ok, f"install: {len(st['files'])} files, version {st['version']}, game {st['game']}")
    record("INS-02", hashlib.sha256((g / "PR2.exe").read_bytes()).hexdigest() == exe0, "PR2.exe unchanged after install")
    (g / "PR2Nation.dll").unlink()
    (g / "PR2Nation.patches").write_text("changed")
    n = S.repair(g, log=log.append)
    record("INS-03", n == 2 and "every file is in order" in (S.repair(g, log=log.append) == 0 and "every file is in order" or ""),
           f"repair put back {n} files, then nothing to do")
    # update: an older install with one file the new version no longer has
    st = json.loads((g / S.STATE).read_text())
    (g / "obsolete.txt").write_text("old version's file")
    st["files"]["obsolete.txt"] = {"replaced": False, "sha256": hashlib.sha256(b"old version's file").hexdigest()}
    st["version"] = "v2000.01.01-old"
    (g / S.STATE).write_text(json.dumps(st))
    S.install(g, log=log.append)
    st = json.loads((g / S.STATE).read_text())
    record("INS-04", not (g / "obsolete.txt").exists() and st["version"] == man["version"],
           f"update from v2000.01.01-old -> {st['version']}, the old version's extra file removed")
    (g / "PR2Loader.log").write_text("written while playing")
    S.uninstall(g, log=log.append)
    after = tree(g)
    record("INS-05", after == before, "uninstall: the folder is byte-identical to before"
           + ("" if after == before else f" (diff {set(after) ^ set(before)})"))

    g = fake_game(root, loose_include=True)
    before = tree(g)
    S.install(g, log=log.append)
    replaced = (g / "lua" / "config" / "default" / "include.ini").read_text(errors="replace") != "-- another mod's include.ini\n"
    S.uninstall(g, log=log.append)
    record("INS-06", replaced and tree(g) == before, "a loose include.ini already there: backed up, replaced, restored")

    g = fake_game(root, towns=True)
    before = tree(g)
    try:
        S.install(g, log=log.append, confirm=lambda m: False)
        refused = False
    except S.SetupError as e:
        refused = "town files" in str(e)
    record("INS-07", refused and tree(g) == before, "another mod's towns\\*.tow: asks, and a No changes nothing")

    (g / "PR2.exe").write_bytes(b"MZ" + b"\0" * 100)
    before = tree(g)
    try:
        S.install(g, force=True, log=log.append)
        refused = False
    except S.SetupError as e:
        refused = "not made for" in str(e)
    record("INS-08", refused and tree(g) == before, "an unknown PR2.exe: refused, nothing installed")

    found = S.find_game()
    record("INS-09", True, f"Steam discovery (read-only): {found or 'not found'}")
    shutil.rmtree(root, ignore_errors=True)
    n = sum(ok for _, ok, _ in results)
    print(f"installer tests: {n} pass, {len(results) - n} fail")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
