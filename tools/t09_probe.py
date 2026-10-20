"""Probe of the removal of national convoys: national convoys are removed; a save that has one loads cleanly.

    python tools/t09_probe.py [--old-dll PATH] [--skip-make]

Takes the shared test-install lock (env.LOCK, %USERPROFILE%\\PR2-nation-env.lock), backs up the Save
folder, the Run logos and settings.cfg, and restores them at the end (also on failure).

1. make (unless --skip-make): with the DLL of build v2026.10.18-79816ea1 (--old-dll; build it with
   `git archive 79816ea1 dll` + the gcc line of dll/build.py), load
   "FNN 12 - Month end in 2 days", designate a national convoy (Nation_NationalConvoys(1)), look at it
   in port, QuickSave and keep the save as "FNN NC1 - Old national convoy" (also in
   _build/scenario_saves).
     NC1-old    the old build renamed it "National convoy 1" and drew the nation's flag for it
2. check, with this worktree's DLL:
     NC1-load   the log says the convoy was released, its name is the old one again,
                Nation_NationalConvoys() = 0, Nation_ShipCount() = 0 (no fleets in this save)
     NC1-port   in its port no site draws the nation's flag for a ship (counters stay 0; screenshot)
     NC1-sea    sent to sea (Convoy_MoveToTown) and centred on the sea map: still the old name, no
                nation's flag (counters 0; screenshot)
     NC1-panel  the Navy and defence tab has no national convoys card
     NC1-upkeep the month end books exactly 2,000 upkeep (one town, no fleets, no towers) and the
                treasury changes by exactly tax + tariff - upkeep
     NC1-resave QuickSave + reload: no national convoy block is read any more, the name stays
     alive      no unhandled exception
Report: _build/t09_results.md; screenshots _build/shots/t09_*.png.
"""
import argparse
import re
import shutil
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_env as env  # noqa: E402
import sn_session as session  # noqa: E402
import m0_suite as M  # noqa: E402
import feature_suite as F  # noqa: E402
import conquest_test as C  # noqa: E402
import scenarios as S  # noqa: E402

LOCK = env.LOCK                      # the shared test-install lock (setting PR2_TEST_LOCK)
BASE_SAVE = "FNN 12 - Month end in 2 days"
OLD_SAVE = "FNN NC1 - Old national convoy"
CORO = 52
CONVOY_SITES = {"name": 1, "selection": 2, "infobar": 3, "seamarker": 5, "sails": 6, "markerreload": 11}
results = []


def record(name, ok, detail):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<11} {detail}", flush=True)


def L(code):
    return F.lua(code)


def ints(v):
    return [int(x) for x in v if re.fullmatch(r"-?\d+", x)]


# ------------------------------------------------------------------ lock --
def acquire():
    last = None
    while True:
        try:
            LOCK.mkdir()
            break
        except FileExistsError:
            try:
                who = (LOCK / "owner.txt").read_text().strip()
            except OSError:
                who = "?"
            if who != last:
                print(f"lock held ({who}); retrying every 10 s", flush=True)
                last = who
            time.sleep(10)
    (LOCK / "owner.txt").write_text(f"agent (remove national convoys, worktree agent-a5d0ecd1f96de114b): "
                                    f"tools/t09_probe.py, {time.ctime()}\n")


def release():
    shutil.rmtree(LOCK, ignore_errors=True)


def wait_desktop():
    while session.input_desktop() != "Default":
        print("input desktop is", session.input_desktop(), "- waiting", flush=True)
        time.sleep(30)


def deploy(dll):
    M.kill_game()
    shutil.copy2(dll, env.MOD_DLL)
    (env.ENV / "PR2Nation.dev").write_text("test install: enables Nation_Dev* and the PR2Nation.cmd console\n")
    data = env.HERE / "data"
    for f in data.rglob("*"):
        if f.is_file() and f.name != "README.md":
            dst = env.ENV / f.relative_to(data)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    print("deployed", dll, flush=True)


# ------------------------------------------------------------- game state --
def counters():
    v = ints(L('Nation_Log("f", Nation_DevFlags())').get("f", []))
    return {k: v[i] for k, i in CONVOY_SITES.items()} if len(v) == 14 else {}


_ptr = {}


def same(a, b):
    return (a & ~(0x1F << 16)) == (b & ~(0x1F << 16))   # the pool handle vs +0xA8: bits 16..20 differ


def find_ptr(handle):
    """The convoy object for a handle (one pool scan, each convoy read separately: slow, so cached)."""
    key = handle & ~(0x1F << 16)
    if key in _ptr:
        return _ptr[key]
    hdr = C.mem(0x701EE8, 12)
    base, _, cnt = struct.unpack("<III", hdr)
    arr = C.mem(base, 4 * (cnt & 0xFFFF)) or b""
    for i in range(len(arr) // 4):
        p = struct.unpack_from("<I", arr, 4 * i)[0]
        h = C.u32(p + 0xA8) if p else None
        if h is not None and same(h, handle):
            _ptr[key] = p
            return p
    return None


def convoy(handle, retry=True):
    """The convoy with this handle: name, name id, town, at sea."""
    p = find_ptr(handle)
    d = C.mem(p, 0x198) if p else None
    if not d or not same(struct.unpack_from("<I", d, 0xA8)[0], handle):
        _ptr.pop(handle & ~(0x1F << 16), None)          # a stale pointer (another game process): look again
        return convoy(handle, False) if retry and p else None
    nid = struct.unpack_from("<H", d, 0x194)[0]
    t = C.mem(0x702CB8 + 0x5CC, 4)
    cnt_names = struct.unpack("<H", C.mem(0x702CB8 + 0x872, 2))[0]
    name = f"(no name, id {nid})"
    if t and nid < cnt_names:
        w = C.mem(struct.unpack("<I", t)[0] + nid * 42, 42) or b""
        name = w.decode("utf-16-le", "replace").split("\0")[0]
    return {"h": struct.unpack_from("<I", d, 0xA8)[0], "p": p, "name": name, "name_id": nid,
            "type": struct.unpack_from("<I", d, 0xB4)[0], "nation": d[0xB8],
            "town": struct.unpack_from("<I", d, 0x9C)[0] & 0xFFFF, "at_sea": d[0x3B], "visible": d[0x1C]}


def lua_handle(h):
    return (h & ~(0x1F << 16)) | (2 << 16)


def shot(name):
    import screen
    try:
        return screen.shot(f"t09_{name}")
    except Exception as e:
        print("screenshot failed:", e)


def enter_town(t):
    h = ints(L(f'Nation_Log("h", Nation_TownHandle({t}))').get("h", ["-1"]))[0]
    L(f"Nation_DevView(2, {h})")
    time.sleep(6)


def sea_map():
    L("Nation_DevView(1, 0)")
    time.sleep(4)


def centre_on(h):
    app = C.u32(0x6E58E4)
    vc = C.u32(app + 0xF0) if app else None
    if vc:
        session.cmd("call", "0x516E30", f"{vc:#x}", f"{lua_handle(h):#x}")
        time.sleep(3)


def quicksave():
    qs = env.SAVE_DIR / "Quick Save.pr2"
    t0 = qs.stat().st_mtime if qs.exists() else 0
    session.cmd("call", "0x57EE90", "0x700500")
    for _ in range(40):
        time.sleep(1)
        if qs.exists() and qs.stat().st_mtime != t0:
            break
    time.sleep(3)
    return qs


# ------------------------------------------------------------------ parts --
def make_old_save(old_dll):
    deploy(old_dll)
    wait_desktop()
    session.load(BASE_SAVE, [], "PR2_nation.exe")
    time.sleep(3)
    mark = S.log_mark()
    sel = ints(L('Nation_Log("s", Global_GetSelectedConvoy())').get("s", ["-1"]))
    before = convoy(sel[0] & 0xFFFFFFFF) if sel and sel[0] != -1 else None
    print("selected convoy before:", sel, before, flush=True)
    n = ints(L('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["0"]))
    time.sleep(3)
    m = re.search(r"SIGHT: convoy ([0-9A-F]{8}) \('([^']*)'\) is national convoy 1", F.log_since(mark))
    if not (n == [1] and m):
        record("NC1-old", False, f"old build: designation failed: {n} {F.log_since(mark)[-300:]}")
        return None
    h = int(m.group(1), 16)
    if not (before and same(before["h"], h)):
        record("NC1-old", False, f"old build designated {h:08X}, not the selected convoy {before}")
        return None
    old_id, old_name = before["name_id"], before["name"]
    k = convoy(h)
    c0 = counters()
    if k and k["town"] < 0xFFFF:
        enter_town(k["town"])
    png = shot("old_port")
    c1 = counters()
    hits = sum(c1.get(s, 0) - c0.get(s, 0) for s in CONVOY_SITES)
    record("NC1-old", k and k["name"] == "National convoy 1" and hits > 0,
           f"old build: convoy {h:08X} '{old_name}' (name id {old_id}) -> '{k and k['name']}', nation's flag drawn {hits}x "
           f"({c0} -> {c1}); {png}")
    sea_map()
    qs = quicksave()
    M.kill_game()
    dst = env.SAVE_DIR / f"{OLD_SAVE}.pr2"
    shutil.copy2(qs, dst)
    S.SAVES_OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(qs, S.SAVES_OUT / dst.name)
    (S.SAVES_OUT / f"{OLD_SAVE}.txt").write_text(f"{h:08X}\t{old_id}\t{old_name}\n", encoding="utf-8")
    print("old save ->", dst, flush=True)
    return h, old_id, old_name


def check_new(h, old_id, old_name):
    deploy(env.HERE / "_build" / "dll" / "PR2Nation.dll")
    wait_desktop()
    session.load(OLD_SAVE, [], "PR2_nation.exe")
    time.sleep(4)
    log = F.log_since(0)                               # a new game process starts a new log
    rel = re.search(rf"SIGHT: convoy {h:08X} released from national service: '([^']*)' -> '([^']*)'", log)
    k = convoy(h)
    nc = L('Nation_Log("c", Nation_NationalConvoys())').get("c", ["?"])[0]
    sc = L('Nation_Log("s", Nation_ShipCount())').get("s", ["?"])[0]
    record("NC1-load", rel is not None and k and k["name_id"] == old_id and nc == "0" and sc == "0",
           f"log {rel.group(0) if rel else 'no release line'}; name now '{k and k['name']}' id {k and k['name_id']} "
           f"(old '{old_name}' id {old_id}); "
           f"Nation_NationalConvoys() {nc}, Nation_ShipCount() {sc}")

    c0 = counters()
    if k and k["town"] < 0xFFFF:
        enter_town(k["town"])
    png = shot("new_port")
    c1 = counters()
    record("NC1-port", c1 and all(c1[s] == 0 for s in CONVOY_SITES),
           f"in port (town {k and k['town']}): nation's-flag counters {c0} -> {c1}; {png}")

    L(f"Convoy_MoveToTown({lua_handle(h)}, Nation_TownHandle({CORO}))")
    sea_map()
    S.fast(True)
    for _ in range(20):
        time.sleep(2)
        k = convoy(h)
        if k and k["at_sea"]:
            break
    S.fast(False)
    session.cmd("call", "0x57F550", "0x700500", "1")
    time.sleep(2)
    centre_on(h)
    png = shot("new_sea")
    c2 = counters()
    k = convoy(h)
    record("NC1-sea", k and k["at_sea"] and k["name_id"] == old_id and c2 and all(c2[s] == 0 for s in CONVOY_SITES),
           f"at sea {k and k['at_sea']} visible {k and k['visible']}: name '{k and k['name']}', counters {c2}; {png}")

    L("Nation_PanelOpen(5)")
    time.sleep(2.5)
    caps = S.panel_cards()
    png = shot("new_navy_tab")
    L("Nation_PanelClose()")
    record("NC1-panel", caps and not any("National convoy" in c for c in caps),
           f"Navy and defence cards {caps}; {png}")

    before, after = S.run_to_month_end()
    expect = before["treasury"] + after["tax"] + after["tariff"] - after["upkeep"]
    record("NC1-upkeep", after["upkeep"] == 2000 and after.get("military", 0) == 0 and after["treasury"] == expect,
           f"upkeep {after['upkeep']}, navy and forts {after.get('military')}; treasury {before['treasury']} -> "
           f"{after['treasury']} (expected {expect})")

    quicksave()
    M.kill_game()
    wait_desktop()
    session.load("Quick Save", [], "PR2_nation.exe")
    time.sleep(4)
    log = F.log_since(0)
    k = convoy(h)
    again = re.search(r"SIGHT: the save has \d+ national convoy", log)
    record("NC1-resave", again is None and "LOAD: nation" in log and k and k["name_id"] == old_id,
           f"after QuickSave + reload: {'PNCV read again' if again else 'no national convoy block'}; "
           f"name '{k and k['name']}'")
    record("alive", M.game_alive() and not M.crashes(), "no unhandled exception")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-dll", help="PR2Nation.dll of build 79816ea1")
    ap.add_argument("--skip-make", action="store_true", help=f"reuse '{OLD_SAVE}' from _build/scenario_saves")
    a = ap.parse_args()
    acquire()
    backup = None
    try:
        backup = env.backup_saves()
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        made = None
        if a.skip_make:
            src = S.SAVES_OUT / f"{OLD_SAVE}.pr2"
            shutil.copy2(src, env.SAVE_DIR / src.name)
            h, nid, name = (S.SAVES_OUT / f"{OLD_SAVE}.txt").read_text(encoding="utf-8").rstrip("\n").split("\t")
            made = int(h, 16), int(nid), name
        else:
            made = make_old_save(a.old_dll)
        if made:
            check_new(*made)
    finally:
        M.kill_game()
        try:
            shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "t09_PR2Nation.log")
        except OSError:
            pass
        if backup:
            for f in backup.iterdir():
                if f.is_file():
                    shutil.copy2(f, env.SAVE_DIR / f.name)
            env.restore_run(backup)
            orig = env.BACKUPS / "settings.cfg.orig"
            if orig.exists():
                shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
        release()
    (env.HERE / "_build" / "t09_results.md").write_text(
        "# Probe of the removal of national convoys " + time.strftime("%Y-%m-%d %H:%M") + "\n\n| Check | Result | Detail |\n|---|---|---|\n"
        + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {str(d).replace('|', '/')} |\n" for t, ok, d in results),
        encoding="utf-8")
    print("\n".join(f"{'PASS' if ok else 'FAIL'}  {t:<11} {d}" for t, ok, d in results))
    return 0 if results and all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
