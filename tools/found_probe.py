"""Found a nation through the panel's founding page in a test game (the founding-page change).

    python tools/found_probe.py [--save "FNN 02 - Rich - ready to found"] [--keep]

Loads the save in the corner window and opens the nation panel (the founding page before
founding). Then:
- steps the form of state and checks that the suggested name follows it;
- steps the flags forward, back and around the end;
- clicks into the name box and types through the game's input (gamehost), past the length
  limit, checking that typing stops at the limit;
- founds the nation with the typed name and checks the name, title and flag;
- saves, reloads and checks the name again.
Screenshots go to _build/shots/found_*.png (and screenshots/found/). Saves and settings are
restored afterwards.
"""
import argparse
import shutil
import sys
import time

import sn_env as env
import sn_session as session
import feature_suite as F

RESULTS = []


def lua(code):
    return F.lua(code)


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:12s} {detail}", flush=True)


def found_info():
    r = lua('Nation_Log("f", Nation_DevFoundInfo())').get("f", [])
    keys = ("shown", "title", "flag", "name", "x", "y", "w", "h")
    d = dict(zip(keys, r))
    for k in ("shown", "title", "flag", "x", "y", "w", "h"):
        d[k] = int(d.get(k, "0") or 0)
    return d


def nation():
    r = lua('Nation_Log("n", Nation_GetInfo())').get("n", [])
    return {"founded": r[0] if r else "?", "name": r[1] if len(r) > 1 else ""}


def press(key, wait=0.6):
    lua(f"Nation_PanelClick({key})")
    time.sleep(wait)


def shot(name):
    import screen
    screen.shot(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 02 - Rich - ready to found")
    ap.add_argument("--keep", action="store_true", help="leave the game running")
    a = ap.parse_args()
    backup = env.backup_saves()
    try:
        session.load(a.save, [], "PR2_nation.exe")
        town = lua('Nation_Log("t", fnn_current_town())').get("t", ["-1"])[0]
        print(f"current town {town}", flush=True)
        lua("Nation_PanelOpen(-1)")
        time.sleep(3)
        info = lua('Nation_Log("i", Nation_PanelInfo())').get("i", [])
        fi = found_info()
        record("open", fi["shown"] == 1 and info[1:2] == ["6"], f"panel {info}; founding card {fi}")
        shot("found_open")
        first = fi["name"]

        press(101)                                        # next form of state
        fi = found_info()
        record("title", fi["title"] == 1 and fi["name"].startswith("Kingdom of "), f"{fi['title']} {fi['name']!r}")
        for _ in range(7):                                # all the way round: back to Republic
            press(101, 0.3)
        fi = found_info()
        record("titles", fi["title"] == 0 and fi["name"] == first, f"after 8 steps: {fi['title']} {fi['name']!r}")

        for _ in range(3):
            press(103, 0.4)
        f3 = found_info()["flag"]
        press(102)
        f2 = found_info()["flag"]
        for _ in range(3):
            press(102, 0.3)
        fl = found_info()["flag"]
        n = int(lua('Nation_Log("c", Nation_FlagCount())').get("c", ["100"])[0])
        record("flags", f2 == f3 - 1 and fl == (f2 - 3) % n, f"next x3 -> {f3}, prev -> {f2}, prev x3 -> {fl} of {n}")
        press(103)
        press(103)
        shot("found_flag")

        # type into the box through the game's own input: click it, clear it, type past the limit
        fi = found_info()
        import screen                                      # layout pixels (1024x768) -> window pixels
        cw, ch = screen.client_size(screen.game_window())
        cx = int((fi["x"] + fi["w"] // 2) * cw / 1024)
        cy = int((fi["y"] + fi["h"] // 2) * ch / 768)
        session.cmd("click", str(cx), str(cy))
        time.sleep(1.5)
        fi = found_info()
        record("focus", fi["shown"] == 2, f"clicked {cx},{cy}: {fi}")
        session.cmd("key", "0x57", "1")                    # one W
        time.sleep(2)
        print("after one W:", found_info(), flush=True)
        session.cmd("key", "0x08", "1")                    # one Backspace
        time.sleep(2)
        print("after one Backspace:", found_info(), flush=True)
        session.cmd("key", "0x23", "1")                    # End (a game hotkey too: must not fire)
        session.cmd("key", "0x08", "40")                   # Backspace
        time.sleep(4)
        fi = found_info()
        record("cleared", fi["shown"] >= 1 and fi["name"] == "", f"after Backspace: {fi}")
        session.cmd("key", "0x57", "45")                   # W, the widest letter
        time.sleep(5)
        fi = found_info()
        print("after typing:", fi, flush=True)
        record("limit", fi["shown"] >= 1 and 0 < len(fi["name"]) <= 28, f"45 keys -> {len(fi['name'])} letters {fi['name']!r}")
        shot("found_typed")
        typed = fi["name"]
        flag = fi["flag"]

        press(104, 2.5)                                    # Found the nation
        nat = nation()
        record("founded", nat["founded"] == "1" and nat["name"] == typed, f"{nat}")
        info = lua('Nation_Log("i", Nation_PanelInfo())').get("i", [])
        card = lua('Nation_Log("c", Nation_PanelCard(0))').get("c", [])
        record("panel", info[1:2] == ["0"], f"panel {info}; first card {card[:2]}")
        got_flag = lua('Nation_Log("g", Nation_GetFlag())').get("g", ["-1"])[0]
        record("flag", got_flag == str(flag), f"Nation_GetFlag {got_flag}, chosen {flag}")
        shot("found_done")
        lua("Nation_PanelOpen(0)")
        time.sleep(2.5)
        shot("found_overview")
        lua("Nation_PanelClose()")

        session.cmd("call", "0x57EE90", "0x700500")       # QuickSave
        time.sleep(8)
        F.M.kill_game()
        if any(n == "founded" and ok for n, ok, _ in RESULTS):
            session.load("Quick Save", [], "PR2_nation.exe")
            nat2 = nation()
            record("reload", nat2["founded"] == "1" and nat2["name"] == typed, f"after reload {nat2}")
            print("alive:", F.M.game_alive(), "crashes:", F.M.crashes(), flush=True)
    finally:
        if not a.keep:
            F.M.kill_game()
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig = env.BACKUPS / "settings.cfg.orig"
        if orig.exists() and not a.keep:
            shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
    fails = [n for n, ok, _ in RESULTS if not ok]
    print("ALL PASS" if not fails else f"FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
