"""Look at both flags in port and at sea (the two-flags change): a screenshot run.

    python tools/flag_probe2.py [x,y]     # town-minimap point to click (Margarita's harbour)

Loads FNN 46 (Margarita: the nation's fleet and a player convoy lie in the harbour), clicks the town
minimap once (one short focus flash) to look at the harbour, designates the player's convoy national
and releases it again (same view), sends both to sea and does the same there, then makes an "older"
save whose embedded logo is the nation's flag and reloads it.
Screenshots _build/shots/flag_h*.png; counters from Nation_DevFlags.
"""
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402
import session  # noqa: E402
import screen  # noqa: E402
import flag_probe as P  # noqa: E402

CLICK = tuple(int(v) for v in sys.argv[1].split(",")) if len(sys.argv) > 1 else (1195, 690)
CORO = 52


def lua_handle(h):
    return (h & ~(0x1F << 16)) | (2 << 16)


def quicksave():
    qs = env.SAVE_DIR / "Quick Save.pr2"
    t0 = qs.stat().st_mtime if qs.exists() else 0
    session.cmd("call", "0x57EE90", "0x700500")
    for _ in range(30):
        time.sleep(1)
        if qs.exists() and qs.stat().st_mtime != t0:
            break
    time.sleep(3)


def step(name, code=None, wait=3):
    if code:
        print(name, P.L(code), flush=True)
    time.sleep(wait)
    P.shot(name)
    print(name, P.counters(), flush=True)


def main():
    P.acquire()
    backup = None
    try:
        shutil.copy2(env.HERE / "_build" / "dll" / "PR2Nation.dll", env.ENV / "PR2Nation.dll")
        backup = env.backup_saves()
        session.load("FNN 46 - Navy - Great power with a fleet", [], "PR2_nation.exe")
        time.sleep(4)
        print("view", P.view(), P.counters(), flush=True)
        screen.click(*CLICK)
        step("h1_port")
        step("h2_port_designated", 'Nation_Log("n", Nation_NationalConvoys(1))')
        step("h3_port_released", 'Nation_Log("n", Nation_NationalConvoys(0))')
        cs = P.convoys()
        player = [c for c in cs if c["nation"] == 5 and c["type"] == 1]
        far_i = P.ints(P.L('for i = 0, 120 do local n = Nation_TownName(i) if n == "Havana" or n == "Havanna" then Nation_Log("t", i) end end').get("t", [str(CORO)]))[0]
        far = P.ints(P.L(f'Nation_Log("h", Nation_TownHandle({far_i}))').get("h", ["-1"]))[0]
        print("player convoy to town", far_i, flush=True)
        P.L(f"Nation_DevFleetSail({CORO})")
        if player:
            print("player convoy out:", P.L(f'Nation_Log("m", Convoy_MoveToTown({lua_handle(player[0]["handle"])}, {far}))'))
        P.F.M.speed_up()
        time.sleep(6)
        P.sea_map()
        P.L("Nation_ShipGoto(0)")
        step("h4_sea", None, 3)
        print("at sea", [c for c in P.convoys() if c["nation"] == 5 and c["type"] in (1, 4)], flush=True)
        P.L('Nation_NationalConvoys(1)')
        time.sleep(1)
        print("goto convoy", P.L('Nation_Log("g", Nation_ShipGoto(1))'), flush=True)
        step("h5_sea_designated", None, 3)
        step("h6_sea_released", 'Nation_Log("n", Nation_NationalConvoys(0))')
        # an older save: the nation's flag as the player logo
        shutil.copy2(env.RUN_DIR / "7.bmp", env.RUN_DIR / "0.bmp")
        quicksave()
        P.F.M.kill_game()
        shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "flag_probe2_first_PR2Nation.log")
        shutil.copy2(env.RUN_DIR / "0_company_logo.bmp", env.RUN_DIR / "0.bmp")   # the PC's logo before the load
        session.load("Quick Save", [], "PR2_nation.exe")
        time.sleep(6)
        P.run_files("legacy reload")
        P.sea_map()
        P.L("Nation_ShipGoto(0)")
        step("h7_legacy_sea", None, 4)
        print("ships", P.convoys() and [c for c in P.convoys() if c["nation"] == 5 and c["type"] in (1, 4)], flush=True)
    finally:
        P.F.M.kill_game()
        try:
            shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "flag_probe2_PR2Nation.log")
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
        P.release()


if __name__ == "__main__":
    main()
