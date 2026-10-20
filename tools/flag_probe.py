"""The player's flag and the nation's flag stay apart (the two-flags change): in-game check, in the background.

    python tools/flag_probe.py [--save "FNN 46 - Navy - Great power with a fleet"] [--keep]

Takes the shared test-install lock, deploys this worktree's PR2Nation.dll, backs up the saves and the
Run logo folder, loads the save in the corner window and checks:
  FLG-01  Run\\0.bmp is the player's own logo after the load (an older save that had the nation's flag
          as its logo gets the kept logo back), Run\\7.bmp is the nation's flag
  FLG-02  the capital's port: the fleet's sails/mast flags and the town header show the nation's flag
          (screenshot), the player's convoy in port its own (screenshot); counters: sails, town header
  FLG-03  the sea map: the fleet's marker shows the nation's flag, a player convoy's its own
  FLG-04  no player convoy becomes national (national convoys are removed): designating one
          does nothing, the ship list holds only fleets, the nation's-flag counters do not move
  FLG-05  after QuickSave + reload: the same, Run\\0.bmp still the player's logo
With --found (default save FNN 02): founding with flag 12 leaves Run\\0.bmp alone and writes Run\\7.bmp
  FLG-06  0.bmp unchanged, 7.bmp = flag_012; the capital's header and sea-map marker (screenshots)
Screenshots: _build/shots/flag_*.png. Saves, settings and Run are restored afterwards.
"""
import argparse
import os
import hashlib
import os
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
import feature_suite as F  # noqa: E402
import conquest_test as C  # noqa: E402

LOCK = env.LOCK                      # the shared test-install lock (setting PR2_TEST_LOCK)
results = []
SITES = ["name", "selection", "infobar", "trade", "seamarker", "sails", "battle-player", "towninfo",
         "townmarker", "sailtex", "markerreload", "seaload-all", "seaload-again"]


def record(test, ok, detail):
    results.append((test, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<7} {detail}", flush=True)


def ints(v):
    return [int(x) for x in v if re.fullmatch(r"-?\d+", x)]


def L(code):
    return F.lua(code)


def md5(p):
    p = Path(p)
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


def counters():
    v = ints(L('Nation_Log("f", Nation_DevFlags())').get("f", []))
    return dict(zip(["ready"] + SITES, v)) if len(v) == 14 else {}


def shot(name):
    import screen
    try:
        return screen.shot(f"flag_{name}")
    except Exception as e:
        print("screenshot failed:", e)


def convoys():
    hdr = C.mem(0x701EE8, 12)
    base, _, cnt = struct.unpack("<III", hdr)
    arr = C.mem(base, 4 * (cnt & 0xFFFF)) or b""
    out = []
    for i in range(len(arr) // 4):
        p = struct.unpack_from("<I", arr, 4 * i)[0]
        d = C.mem(p, 0xC0) if p else None
        if d:
            out.append({"i": i, "p": p, "type": struct.unpack_from("<I", d, 0xB4)[0], "nation": d[0xB8],
                        "town": struct.unpack_from("<I", d, 0x9C)[0] & 0xFFFF, "handle": struct.unpack_from("<I", d, 0xA8)[0],
                        "x": struct.unpack_from("<h", d, 0x0E)[0], "y": struct.unpack_from("<h", d, 0x12)[0],
                        "ships": d[0x95]})
    return out


def view():
    return L('Nation_Log("v", Global_GetView(), Global_GetViewTown())').get("v", [])


def enter_town(t):
    h = ints(L(f'Nation_Log("h", Nation_TownHandle({t}))').get("h", ["-1"]))[0]
    L(f"Nation_DevView(2, {h})")
    time.sleep(6)
    return view()


def sea_map():
    L("Nation_DevView(1, 0)")
    time.sleep(4)


def acquire():
    while True:
        try:
            LOCK.mkdir()
            who = os.environ.get("PR2_LOCK_OWNER") or ("agent (player flag vs nation flag, worktree "
                                                       "agent-a9fb0ec1aa37e8358)")
            (LOCK / "owner.txt").write_text(f"{who}: tools/flag_probe.py, {time.ctime()}\n")
            return
        except FileExistsError:
            try:
                print("lock held by:", (LOCK / "owner.txt").read_text().strip(), flush=True)
            except OSError:
                pass
            time.sleep(60)


def release():
    shutil.rmtree(LOCK, ignore_errors=True)


def run_files(tag):
    keep, logo, nat = (md5(env.RUN_DIR / n) for n in ("0_company_logo.bmp", "0.bmp", "7.bmp"))
    flag = ints(L('Nation_Log("g", Nation_GetFlag())').get("g", ["-1"]))[0]
    src = md5(env.ENV / "nation_flags" / f"flag_{flag:03d}.bmp")
    print(f"[{tag}] Run: 0.bmp {logo} kept {keep} 7.bmp {nat}; nation flag {flag} {src}", flush=True)
    return logo, keep, nat, src


def run_checks(a):
    time.sleep(3)
    print("view:", view(), "counters:", counters(), flush=True)
    logo, keep, nat, src = run_files("load")
    record("FLG-01", nat == src and logo != src and (keep is None or logo == keep),
           f"0.bmp {'= kept player logo' if logo == keep else logo}, 7.bmp {'= nation flag' if nat == src else nat}")
    shot("00_loaded")
    info = L('Nation_Log("i", Nation_GetInfo())').get("i", [])
    capital = int(info[3]) if len(info) > 3 else 0
    cs = convoys()
    fleets = [c for c in cs if c["nation"] == 5 and c["type"] in (4, 9)]
    players = [c for c in cs if c["nation"] == 5 and c["type"] == 1]
    print("capital", capital, "fleets", fleets, "\nplayer convoys", players, flush=True)
    # the port of the town where the fleet lies (else the capital)
    town = fleets[0]["town"] if fleets and fleets[0]["town"] < 0xFFFF else capital
    c0 = counters()
    v = enter_town(town)
    c1 = counters()
    png = shot("01_fleet_port")
    record("FLG-02a", c1.get("sails", 0) >= 1,
           f"town {town} view {v}: the fleet's ships in port got sail/mast flag 7 ({c1.get('sails', 0)}x); {png}")
    for p in players:
        if p["town"] < 0xFFFF and p["town"] != town:
            enter_town(p["town"])
            shot(f"02_player_port_{p['town']}")
            break
    sea_map()
    L('Nation_ShipGoto(0)')
    time.sleep(4)
    png = shot("03_sea_fleet")
    c2 = counters()
    record("FLG-03", c2.get("seamarker", 0) >= 0, f"sea map: counters {c2}; {png}")
    # national convoys are removed: no player convoy can be designated, none flies the nation's flag
    n = ints(L('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["?"]))
    time.sleep(2)
    c3 = counters()
    print("national convoys", n, "counters", c3, flush=True)
    sh = [ints(L(f'Nation_Log("s", Nation_ShipInfo({i}))').get("s", [])) for i in range(4)]
    print("ships", sh, flush=True)
    natc = [c for c in convoys() if c["type"] == 1 and any(s and s[0] == c["handle"] for s in sh)]
    record("FLG-04", n == [0] and not natc, f"Nation_NationalConvoys(1) -> {n}; player convoys among the national "
           f"ships: {natc}; counters {c3}")
    if not a.no_reload:
        session.quicksave()                           # returns once the file is written
        F.M.kill_game()
        session.load("Quick Save", [], "PR2_nation.exe")   # returns once the world is ready
        time.sleep(1)
        logo2, keep2, nat2, src2 = run_files("reload")
        v = enter_town(town)
        png = shot("05_reload_fleet_port")
        sea_map()
        L('Nation_ShipGoto(0)')
        time.sleep(4)
        png2 = shot("06_reload_sea_fleet")
        record("FLG-05", logo2 == logo and nat2 == src2, f"after reload 0.bmp {logo2} 7.bmp {nat2}; {png} {png2}; {counters()}")
    record("alive", F.M.game_alive() and not F.M.crashes(), "no unhandled exception")


def found_checks(a):
    time.sleep(3)
    before = md5(env.RUN_DIR / "0.bmp")
    r = L('local ok, why = Nation_Found(56, "Free Republic of Margarita", "Margaritan", 0, 12)\nNation_Log("f", ok, why)')
    time.sleep(3)
    after, nat = md5(env.RUN_DIR / "0.bmp"), md5(env.RUN_DIR / "7.bmp")
    src = md5(env.ENV / "nation_flags" / "flag_012.bmp")
    v = enter_town(56)
    png = shot("10_founded_capital")
    sea_map()
    png2 = shot("11_founded_sea")
    record("FLG-06", r.get("f", ["0"])[0] == "1" and after == before and nat == src,
           f"found {r}; 0.bmp {'unchanged' if after == before else 'CHANGED'}; 7.bmp {'= flag_012' if nat == src else nat}; "
           f"view {v}; {png} {png2}; {counters()}")
    record("alive", F.M.game_alive() and not F.M.crashes(), "no unhandled exception")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 46 - Navy - Great power with a fleet")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--no-reload", action="store_true")
    ap.add_argument("--found", action="store_true", help="found a nation in FNN 02 instead")
    a = ap.parse_args()
    if a.found and a.save == ap.get_default("save"):
        a.save = "FNN 02 - Rich - ready to found"
    acquire()
    backup = None
    try:
        dll = env.HERE / "_build" / "dll" / "PR2Nation.dll"
        shutil.copy2(dll, env.ENV / "PR2Nation.dll")
        (env.ENV / "PR2Nation.dev").touch()
        backup = env.backup_saves()
        session.load(a.save, [], "PR2_nation.exe")
        found_checks(a) if a.found else run_checks(a)
    finally:
        if not a.keep:
            F.M.kill_game()
        try:
            shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "flag_probe_PR2Nation.log")
        except OSError:
            pass
        if backup:
            for f in backup.iterdir():
                if f.is_file():
                    shutil.copy2(f, env.SAVE_DIR / f.name)
            env.restore_run(backup)
            orig = env.BACKUPS / "settings.cfg.orig"
            if orig.exists() and not a.keep:
                shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
        release()
        print("\n".join(f"{'PASS' if ok else 'FAIL'}  {t:<7} {d}" for t, ok, d in results))
    return 0 if results and all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
