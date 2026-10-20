"""National ships on the sea map (the national-ships-on-the-sea-map change): in-game check, in the background.

    python tools/sight_probe.py [--save "FNN 46 - Navy - Great power with a fleet"] [--keep]

Takes the shared test-install lock (env.LOCK, %USERPROFILE%\\PR2-nation-env.lock), deploys this
worktree's PR2Nation.dll, loads the save in the corner window and checks:
  SEE-01  the nation's fleet at sea is marked visible (+0x1C) with no own convoy near
  SEE-02  ships around the fleet are revealed (A/B: reveal off -> on)
  SEE-03  Go to centres the sea map on the fleet; again after it sailed on
  SEE-04  national convoys are removed: none can be designated, only fleets are listed
  SEE-05  Ctrl+Shift+N (Nation_DevCycle) walks through the national ships
  SEE-06  the Navy tab shows Fleet cards (no National convoy card) with an eye button that jumps
  SEE-07  after QuickSave + reload: still no national convoy, Go to works for the fleet
  SEE-08  frame time with the reveal on vs off (10 fleets if --fleets 10)
Screenshots: _build/shots/sight_*.png. Saves and settings are restored afterwards.
"""
import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_env as env  # noqa: E402
import sn_session as session  # noqa: E402
import feature_suite as F  # noqa: E402

LOCK = env.LOCK                      # the shared test-install lock (setting PR2_TEST_LOCK)
results = []


def record(test, ok, detail):
    results.append((test, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<7} {detail}", flush=True)


def ints(v):
    return [int(x) for x in v if re.fullmatch(r"-?\d+", x)]


def L(code):
    return F.lua(code)


def ship_list():
    n = ints(L('Nation_Log("n", Nation_ShipCount())').get("n", ["0"]))
    out = []
    for i in range(n[0] if n else 0):
        v = ints(L(f'Nation_Log("s", Nation_ShipInfo({i}))').get("s", []))
        if len(v) == 6:
            out.append(dict(zip(["handle", "x", "y", "visible", "at_sea", "fleet"], v)))
    return out


def sight(reveal=-1):
    v = ints(L(f'Nation_Log("v", Nation_DevSight({reveal}))').get("v", []))
    return dict(zip(["reveal", "view", "cx", "cy", "goto", "gx", "gy"], v)) if len(v) == 7 else {}


def near(x, y, r=100):
    v = ints(L(f'Nation_Log("w", Nation_DevVisibleNear({x}, {y}, {r}))').get("w", []))
    return (v[0], v[1], v[2]) if len(v) == 3 else (None, None, None)


def shot(name):
    import screen
    try:
        return screen.shot(f"sight_{name}")
    except Exception as e:
        print("screenshot failed:", e)


def cyan_dots(png):
    """pixels of the national ships' cyan minimap dots (0xFF00FFFF) in the minimap's corner"""
    if not png:
        return -1
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    box = im.crop((int(w * 0.75), int(h * 0.75), w, h))
    return sum(1 for r, g, b in box.getdata() if r < 60 and g > 200 and b > 200)


def goto_ok(i, tol=40):
    r = L(f'Nation_Log("g", Nation_ShipGoto({i}))').get("g", ["0"])
    time.sleep(1.5)
    s = sight()
    sh = ship_list()
    ship = sh[i] if i < len(sh) else {}
    dx, dy = s.get("cx", -9999) - s.get("gx", 0), s.get("cy", -9999) - s.get("gy", 0)
    ok = r[0] == "1" and s.get("view") == 1 and abs(dx) <= tol and abs(dy) <= tol
    return ok, f"goto {r} view {s.get('view')} centre {s.get('cx')},{s.get('cy')} ship at {s.get('gx')},{s.get('gy')} " \
               f"(now {ship.get('x')},{ship.get('y')})"


def acquire():
    while True:
        try:
            LOCK.mkdir()
            (LOCK / "owner.txt").write_text(f"agent (national ships on the sea map, worktree "
                                            f"agent-a4a21622d2697b310): tools/sight_probe.py, {time.ctime()}\n")
            return
        except FileExistsError:
            try:
                print("lock held by:", (LOCK / "owner.txt").read_text().strip(), flush=True)
            except OSError:
                pass
            time.sleep(60)


def release():
    shutil.rmtree(LOCK, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 46 - Navy - Great power with a fleet")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--fleets", type=int, default=0, help="commission up to this many fleets for the timing test")
    a = ap.parse_args()
    acquire()
    backup = None
    try:
        dll = env.HERE / "_build" / "dll" / "PR2Nation.dll"
        shutil.copy2(dll, env.ENV / "PR2Nation.dll")
        (env.ENV / "PR2Nation.dev").touch()
        backup = env.backup_saves()
        session.load(a.save, [], "PR2_nation.exe")
        time.sleep(3)
        run_checks(a)
    finally:
        if not a.keep:
            F.M.kill_game()
        try:
            shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "sight_probe_PR2Nation.log")
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


def run_checks(a):
    sh = ship_list()
    print("ships:", sh, "sight:", sight(), flush=True)
    fleets = [s for s in sh if s["fleet"]]
    if not fleets:
        record("SEE-00", False, "no national fleet in this save")
        return
    shot("00_loaded")
    # send the fleet out to sea (dev: sails to Coro) and let time run
    L("Nation_DevFleetSail(52)")
    F.M.speed_up()
    t0 = time.time()
    while time.time() - t0 < 90:
        time.sleep(3)
        f = ship_list()[0]
        if f["at_sea"]:
            break
    time.sleep(6)
    f = ship_list()[0]
    print("fleet:", f, flush=True)
    record("SEE-01", f["at_sea"] and f["visible"], f"fleet at {f['x']},{f['y']} at sea {f['at_sea']} visible {f['visible']}")
    ok, d = goto_ok(0)
    record("SEE-03a", ok, d)
    shot("01_goto_fleet")
    # A/B: reveal off, then on
    sight(0)
    time.sleep(2)
    f = ship_list()[0]
    off = near(f["x"], f["y"])
    vis_off = f["visible"]
    shot("02_reveal_off")
    sight(1)
    time.sleep(2)
    f = ship_list()[0]
    on = near(f["x"], f["y"])
    shot("03_reveal_on")
    record("SEE-02", on[2] == 0 and (on[0] or 0) >= (off[0] or 0) and on[0] == on[1] and f["visible"],
           f"near the fleet ({on[2]} own convoys near): reveal off {off[0]} of {off[1]} convoys visible "
           f"(fleet visible {vis_off}), reveal on {on[0]} of {on[1]} (fleet visible {f['visible']})")
    # the fleet sails on: Go to follows it
    time.sleep(15)
    ok, d = goto_ok(0)
    record("SEE-03b", ok, "after sailing on: " + d)
    shot("04_goto_fleet_later")
    # national convoys are removed: designating one does nothing, only fleets are national ships
    n = ints(L('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["?"]))
    sh = ship_list()
    conv = [i for i, s in enumerate(sh) if not s["fleet"]]
    record("SEE-04", n == [0] and not conv, f"Nation_NationalConvoys(1) -> {n}, ships {sh}")
    # cycle
    seen = set()
    for _ in range(len(sh) + 1):
        L("Nation_DevCycle()")
        time.sleep(1.5)
        seen.add(sight().get("goto"))
    record("SEE-05", len(seen) >= min(2, len(sh)), f"cycle visited {len(seen)} ships of {len(sh)}")
    # the Navy tab: one row per fleet (the convoy-list look); select it, then the eye (Go to)
    L("Nation_PanelOpen(5)")
    time.sleep(2)
    L("Nation_PanelMode(0)")
    time.sleep(2)
    info = L('Nation_Log("i", Nation_PanelInfo())').get("i", [])
    rows = []
    for i in range(int(info[2]) if len(info) > 2 and info[2].isdigit() else 0):
        r = L(f'Nation_Log("r", Nation_PanelRow({i}))').get("r", [])
        rows.append((int(r[0]) if r and r[0].lstrip("-").isdigit() else -1, r[1] if len(r) > 1 else ""))
    print("rows:", rows, flush=True)
    shot("06_navy_tab")
    fleet = next((k for k, name in rows if name.startswith("Fleet")), None)
    conv = next((k for k, name in rows if name.startswith("National convoy ")), None)
    if fleet is not None:
        L(f"Nation_PanelSelect({fleet})")
        time.sleep(2)
        L("Nation_PanelClick(3303)")                    # the eye: Go to
        time.sleep(3)
        s = sight()
        f = ship_list()[0]
        pinfo = L('Nation_Log("i", Nation_PanelInfo())').get("i", [])
        ok_click = s.get("goto") == f["handle"] and abs(s.get("cx", 0) - s.get("gx", 0)) <= 40
        png = shot("07_eye_fleet")
        record("SEE-09", cyan_dots(png) > 0, f"cyan national-ship pixels on the minimap: {cyan_dots(png)}")
        record("SEE-06", ok_click and conv is None,
               f"fleet row {fleet}, convoy row {conv}; eye -> goto {s.get('goto')} centre "
               f"{s.get('cx')},{s.get('cy')} ship {s.get('gx')},{s.get('gy')}; panel {pinfo}")
    else:
        record("SEE-06", False, f"no fleet row: {rows}")
    # save and reload
    qs = env.SAVE_DIR / "Quick Save.pr2"
    t0 = qs.stat().st_mtime if qs.exists() else 0
    session.cmd("call", "0x57EE90", "0x700500")
    for _ in range(30):
        time.sleep(1)
        if qs.exists() and qs.stat().st_mtime != t0:
            break
    time.sleep(3)
    F.M.kill_game()
    session.load("Quick Save", [], "PR2_nation.exe")
    time.sleep(3)
    sh2 = ship_list()
    n2 = ints(L('Nation_Log("c", Nation_NationalConvoys())').get("c", ["0"]))
    conv2 = [i for i, s in enumerate(sh2) if not s["fleet"]]
    ok0, d0 = goto_ok(0)
    shot("08_reload_goto_fleet")
    record("SEE-07", n2 == [0] and not conv2 and ok0, f"after reload: national convoys {n2}; fleet {d0}")
    # timing: frames per second with the reveal on / off
    if a.fleets:
        for _ in range(a.fleets):
            L('Nation_DevSet("treasury", 5000000)\nNation_NavyCommission()')
            time.sleep(2)
        time.sleep(40)                          # let the patrols put to sea
        print("ships for timing:", ship_list(), flush=True)
        shot("10_many_fleets")
    t = timing()
    fps = [float(x) for x in re.findall(r"([\d.]+) fps", t)]
    off, on = fps[0::2], fps[1::2]
    record("SEE-08", len(fps) == 4 and min(on) > 0.8 * max(off), t)
    record("alive", F.M.game_alive() and not F.M.crashes(), "no unhandled exception")


def timing():
    import ctypes
    out = []
    for on in (0, 1, 0, 1):
        sight(on)
        log = env.ENV / "PR2Nation.log"
        a = frames()
        t = time.time()
        time.sleep(8)
        b = frames()
        out.append(f"reveal {on}: {(b - a) / (time.time() - t):.1f} fps" if a is not None and b is not None else f"reveal {on}: ?")
    return "; ".join(out) + f"; {len(ship_list())} national ships"


def frames():
    v = ints(L('Nation_Log("f", Nation_DevFrames())').get("f", []))
    return v[0] if v else None


if __name__ == "__main__":
    sys.exit(main())
