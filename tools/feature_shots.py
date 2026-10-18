"""Screenshots of the mod's features for the docs and every packaged version.

    python tools/feature_shots.py [--if-stale]

Plays the FNN saves in the corner test window and photographs each feature:
the founding page, a founded nation's first card, the six panel pages, the top-bar
nation button. Writes docs/screenshots/<name>.jpg, docs/screenshots/README.md (what each
shot shows) and docs/screenshots/BUILD.txt (the mod build they show). The private test-machine packager
calls this with --if-stale, so each package carries screenshots of its own build.
Saves and settings are restored afterwards.
"""
import argparse
import shutil
import subprocess
import sys
import time

from PIL import Image

import env
import session
import feature_suite as F

OUT = env.HERE / "docs" / "screenshots"
STAMP = OUT / "BUILD.txt"
CODE = ("dll", "data", "art", "patches")      # relative to the mod's folder (git runs there)

# name, caption (README order)
SHOTS = [
    ("found_page", "Founding: the *Found a Nation* page (nation button before founding): form of state, name, flag."),
    ("found_done", "Just founded: the panel opens on the Overview with the result."),
    ("topbar", "The nation button in the top bar, right of the convoy list."),
    ("panel_overview", "Overview, in the look of the Successes and Nations pages: the facts, the nation next to the four powers, what needs attention."),
    ("panel_treasury", "Treasury, in the look of the Balance page: 13 categories, last month and the forecast (Taxes and finances: tax, tariff, donations, withdrawals)."),
    ("panel_towns", "Towns, in the look of the Chronicle town list: inhabitants, loyalty, tax, garrison; the selected town's tax; towns for sale."),
    ("panel_diplomacy", "Diplomacy, in the look of the Chronicle nations page: treaty, relation and mood per power; the next step for the selected one."),
    ("panel_government", "Government: the five forms on the new-game value selector, with strengths and weaknesses."),
    ("panel_navy", "Navy and defence, in the look of the convoy list: the fleets with their orders (also naval command and town defence)."),
    ("seamap_fleet", "A national fleet on the sea map after *Go to* (the eye on the Navy tab): it flies the nation's flag, "
                     "lights up the sea around it and shows as a cyan dot on the minimap."),
]
PAGES = ["panel_overview", "panel_treasury", "panel_towns", "panel_diplomacy", "panel_government", "panel_navy"]


def git(*args):
    r = subprocess.run(["git", "-C", str(env.HERE), *args], capture_output=True, text=True)
    return r.stdout.strip()


def build_id():
    """The last commit that changed the mod itself, -dev if it has uncommitted changes."""
    commit = git("log", "-1", "--format=%h", "--abbrev=8", "--", *CODE) or "nogit"
    return commit + ("-dev" if git("status", "--porcelain", "--", *CODE) else "")


def stale():
    return not STAMP.exists() or STAMP.read_text(encoding="utf-8").split()[0] != build_id()


def lua(code):
    return F.lua(code)


def grab(name, crop=None):
    import screen
    png = screen.shot(name)
    img = Image.open(png).convert("RGB")
    if crop:
        img = img.crop(crop)
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.jpg", quality=88)
    print(f"  {name}.jpg", flush=True)


def founding():
    session.load("FNN 02 - Rich - ready to found", [], "PR2_nation.exe")
    lua("Nation_PanelOpen(-1)")
    time.sleep(3)
    for _ in range(6):                                  # a flag with some colour
        lua("Nation_PanelClick(103)")
        time.sleep(0.3)
    time.sleep(1.5)
    grab("found_page")
    lua("Nation_PanelClick(104)")                       # found it with the suggested name
    time.sleep(4)
    grab("found_done")
    F.M.kill_game()


def pages(save, names):
    session.load(save, [], "PR2_nation.exe")
    time.sleep(2)
    if "topbar" in names:
        import screen
        cw, ch = screen.client_size(screen.game_window())
        grab("topbar", (int(cw * 0.55), 0, cw, int(ch * 0.09)))
    for i, name in enumerate(PAGES):
        if name not in names:
            continue
        lua(f"Nation_PanelOpen({i})")
        time.sleep(2)
        lua(f"Nation_PanelMode({-1 if i == 4 else 0})")  # first mode; Government: the form in force
        time.sleep(2)
        grab(name)
    lua("Nation_PanelClose()")
    if "seamap_fleet" in names:                          # the national-ships-on-the-sea-map change: the fleet sails out, Go to centres on it
        lua("Nation_DevFleetSail(52)")
        for _ in range(30):
            time.sleep(3)
            v = lua('Nation_Log("s", Nation_ShipInfo(0))').get("s", [])
            if len(v) >= 5 and v[4] == "1":
                break
        time.sleep(5)
        lua("Nation_ShipGoto(0)")
        time.sleep(2)
        grab("seamap_fleet")
    F.M.kill_game()


def readme():
    lines = ["# Screenshots", "",
             f"Sovereign Nations build `{build_id()}`, taken {time.strftime('%Y-%m-%d')} in a 1280x800 window "
             "with `tools/feature_shots.py`.", ""]
    for name, caption in SHOTS:
        if (OUT / f"{name}.jpg").exists():
            lines += [f"**{caption}**", "", f"![{name}]({name}.jpg)", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    STAMP.write_text(f"{build_id()} {time.strftime('%Y-%m-%d %H:%M')}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-stale", action="store_true", help="only if the mod changed since the last shots")
    a = ap.parse_args()
    if a.if_stale and not stale():
        print(f"screenshots are current (build {build_id()})")
        return 0
    backup = env.backup_saves()
    try:
        founding()
        pages("FNN P1 - Young republic", ["topbar"] + PAGES[:-1])
        pages("FNN 46 - Navy - Great power with a fleet", ["panel_navy", "seamap_fleet"])
        readme()
        print(f"{OUT}: {len(list(OUT.glob('*.jpg')))} screenshots of build {build_id()}")
    finally:
        F.M.kill_game()
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig = env.BACKUPS / "settings.cfg.orig"
        if orig.exists():
            shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
