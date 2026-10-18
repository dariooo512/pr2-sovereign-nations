"""Navy spike: one nation-5 military convoy driven by the game's military AI.

    python tools/navy_spike.py [--days 10] [--town 56]

Loads 'FNN 10 - Nation founded' in the corner window, spawns a military convoy
at a nation town through the game's own builder (Lua Global_CreateMilitaryConvoy),
then checks: type 4 / nation 5, registered in the nation's CNation, the game
keeps running for --days game days while the convoy changes state; save + reload
keeps it; a war with Spain sets Spain's bit in its attack mask.
Report: NAVY_SPIKE.md.
"""
import argparse
import shutil
import sys
import time

import env
import session
import conquest_test as C
import feature_suite as F
import milprobe as P

REPORT = env.HERE / "NAVY_SPIKE.md"
SAVE = "FNN 10 - Nation founded"
results = []


def record(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<12} {detail}", flush=True)


def lua(code):
    return F.lua(code)


def navy_info():
    v = lua('Nation_Log("n", Nation_NavyInfo())').get("n", ["?", "?"])
    return v


def nation5_fleets():
    out = []
    for i, p in P.convoys():
        r = P.dump(p)
        if r and r["type"] in (4, 9) and r["nation"] == 5:
            out.append((i, p, r))
    return out


def show(tag):
    fl = nation5_fleets()
    for i, p, r in fl:
        print(f"  [{tag}] slot {i} {p:#x} type {r['type']} nation {r['nation']} state {r['state']:#x} "
              f"town {r['town']:#x} mask {r['mask']:#x} sailors {r['sailors']}/{r['maxs']}", flush=True)
    return fl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--town", type=int, default=56)
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    backup = env.backup_saves()
    try:
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        if a.build:
            F.build()
        session.load(SAVE, [], "PR2_nation.exe")
        log = (env.ENV / "PR2Nation.log").read_text(errors="replace")
        record("patches", "NAVY: ready" in log, next((l for l in log.splitlines() if "NAVY:" in l), "no NAVY line"))
        record("info0", navy_info()[:2] == ["1", "0"], f"Nation_NavyInfo before spawn: {navy_info()}")

        r = lua(f'local h = Global_CreateMilitaryConvoy(0, Nation_TownHandle({a.town}))\nNation_Log("c", h)')
        record("spawn", "__error__" not in r and r.get("c"), f"Global_CreateMilitaryConvoy -> {r}")
        time.sleep(2)
        fl = show("spawned")
        info = navy_info()
        record("nation5", len(fl) == 1 and fl[0][2]["type"] == 4, f"{len(fl)} nation-5 military convoy(s)")
        record("registered", info[1] == "1", f"Nation_NavyInfo after spawn: {info}")
        if not fl:
            raise SystemExit("no fleet")
        ptr = fl[0][1]

        states = set()
        for d in range(a.days):
            if not F.run_days(1):
                record("alive", False, f"game stopped or crashed on day {d}")
                raise SystemExit("crash")
            r = P.dump(ptr)
            states.add((r["state"], r["town"]))
            print(f"  day {d + 1}: state {r['state']:#x} town {r['town']:#x} mask {r['mask']:#x}", flush=True)
        record("alive", F.M.game_alive() and not F.M.crashes(), f"{a.days} days with the fleet, no exception")
        record("moves", len(states) > 1, f"(state, town) seen: {sorted(states)}")

        lua("Nation_DeclareWar(3)")
        masks = set()                                  # the mask is rebuilt in port and cleared at sea
        for _ in range(6):
            F.run_days(1)
            masks.add(P.dump(ptr)["mask"])
        record("war-mask", any(m & (1 << 3) for m in masks),
               f"attack masks after war with Spain: {sorted(hex(m) for m in masks)} (Spain = bit 3, 0x400 when stronger)")

        C.session.cmd("call", "0x57EE90", "0x700500")      # QuickSave
        time.sleep(8)
        F.M.kill_game()
        session.load("Quick Save", [], "PR2_nation.exe")
        fl = show("reloaded")
        info = navy_info()
        record("reload", len(fl) == 1 and info[1] == "1", f"after reload: {len(fl)} fleet(s), Nation_NavyInfo {info}")
        F.run_days(2)
        record("alive2", F.M.game_alive() and not F.M.crashes(), "2 more days after reload")
    except SystemExit as e:
        print("stopped:", e)
    finally:
        F.M.kill_game()
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig = env.BACKUPS / "settings.cfg.orig"
        if orig.exists():
            shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
    REPORT.write_text("# Navy spike " + time.strftime("%Y-%m-%d %H:%M") + "\n\n| Check | Result | Detail |\n|---|---|---|\n"
                      + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {str(d).replace('|', '/')[:300]} |\n"
                                for t, ok, d in results), encoding="utf-8")
    failed = [t for t, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
