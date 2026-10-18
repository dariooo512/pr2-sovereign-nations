"""Open the nation panel in a test game and screenshot every page.

    python tools/panel_probe.py [--save "FNN 10 - Nation founded"] [--keep]

Loads the save in the corner window, opens the panel (Nation_PanelOpen) on each
of its six pages, logs the cards (Nation_PanelInfo / Nation_PanelCard) and takes
a screenshot of each: _build/shots/panel_<n>.png. Then presses Ctrl+N-equivalents:
closes the panel. Saves and settings are restored afterwards.
"""
import argparse
import shutil
import sys
import time

import env
import session
import feature_suite as F


def lua(code):
    return F.lua(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 10 - Nation founded")
    ap.add_argument("--keep", action="store_true", help="leave the game running")
    ap.add_argument("--tax-xy", default="", help="x,y of the tax card's button to click")
    a = ap.parse_args()
    backup = env.backup_saves()
    try:
        session.load(a.save, [], "PR2_nation.exe")
        import screen
        for page in range(6):
            r = lua(f'Nation_Log("o", Nation_PanelOpen({page}))')
            time.sleep(2.5)
            info = lua('Nation_Log("i", Nation_PanelInfo())').get("i", [])
            print(f"page {page}: open {r.get('o')} info {info} {r.get('__error__', '')}", flush=True)
            n = int(info[2]) if len(info) > 2 and info[2].isdigit() else 0
            for i in range(min(n, 4)):
                c = lua(f'Nation_Log("c", Nation_PanelCard({i}))').get("c", [])
                print(f"   card {i}: {c[:1]} {(c[1][:120] if len(c) > 1 else '')!r}", flush=True)
            screen.shot(f"panel_{page}")
        # real mouse clicks (window coordinates of the 1280x800 test window)
        def treasury():
            return int(lua('Nation_Log("t", Nation_GetInfo())').get("t", ["0"] * 5)[4])
        lua("Nation_PanelOpen(1)")
        time.sleep(2.5)
        t0 = treasury()
        session.cmd("click", 765, 111)                       # title-bar button 1: Donate 10,000
        time.sleep(2.5)
        t1 = treasury()
        c0 = lua('Nation_Log("c", Nation_PanelCard(0))').get("c", [])
        print(f"CLICK donate: treasury {t0} -> {t1}; first card {c0[:1]}", flush=True)
        screen.shot("panel_click_donate")
        tax0 = lua('Nation_Log("t", Nation_GetInfo())').get("t", ["0"] * 8)[7]
        n = int(lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0", "0", "0"])[2])
        print("cards now", n, flush=True)
        screen.shot("panel_before_tax")
        if a.tax_xy:
            x, y = map(int, a.tax_xy.split(","))
            session.cmd("click", x, y)
            time.sleep(2.5)
            tax1 = lua('Nation_Log("t", Nation_GetInfo())').get("t", ["0"] * 8)[7]
            print(f"CLICK tax: {tax0} -> {tax1}", flush=True)
        session.cmd("click", 899, 100)                       # the close X
        time.sleep(2.5)
        print("after X:", lua('Nation_Log("i", Nation_PanelInfo())').get("i"), flush=True)
        lua("Nation_PanelClose()")
        time.sleep(2)
        print("after close:", lua('Nation_Log("i", Nation_PanelInfo())').get("i"), flush=True)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
