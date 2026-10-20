"""Building permit in the nation's own towns (the automatic building permit change).

    python tools/permit_probe.py [--part found|annex|oldsave|all] [--deploy] [--keep]

Runs in the corner window with the dev console (PR2Nation.dev). Every check reads the
game's own permit flag through vanilla Lua Player_HasLicence(town) (0x4233F0, reads
CStadt+0x91B0) next to Nation_GetTown(t) -> member, loyalty, tax, unrest, permit, before.

  found   FNN 02: the permit in Margarita is taken away first (Nation_DevPermit), then the
          nation is founded there: the capital has the permit at once, recorded as "had
          none". QuickSave + reload keeps it. Releasing Margarita to Spain takes it away
          again; the player's buildings there stay. No other town changes.
  annex   FNN 22: Coro is annexed (conquest; at war with Spain): permit at once, the join
          message says so. Given up (as at the master builder) it comes back the next day.
          Lost again: no permit, as before. Caracas, where the player had earned the permit,
          keeps it after joining and leaving. No other town changes.
  oldsave FNN 46 (made before this feature, towns joined by treaty without a permit): on
          load every member town has the permit and its earlier state is recorded.
Screenshots go to _build/shots/permit_*.png. Saves, settings and the player logo are
restored afterwards.
"""
import argparse
import re
import shutil
import sys
import time

import sn_env as env
import sn_session as session
import feature_suite as F

RESULTS = []
CORO, CARACAS, MARGARITA, SPAIN = 52, 55, 56, 3

PERMITS_LUA = """
local g = 0
while g < 6 do
  local s = ""
  local t = g * 10
  while t < g * 10 + 10 do
    local m, l, x, u, p, b = Nation_GetTown(t)
    local v = Player_HasLicence(Nation_TownHandle(t))
    if v == nil then v = 9 end
    if p == nil or p < 0 then p = 9 end
    s = s .. (m or 0) .. p .. (b or 0) .. v .. ","
    t = t + 1
  end
  Nation_Log("p" .. g, s)
  g = g + 1
end
"""


def lua(code):
    return F.lua(code)


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:14s} {detail}", flush=True)


def permits():
    """{town: (member, permit, before, vanilla Player_HasLicence)}; 9 = no answer"""
    r = lua(PERMITS_LUA)
    out = {}
    for g in range(6):
        cells = [x for x in r.get(f"p{g}", [""])[0].split(",") if x]
        for i, cell in enumerate(cells):
            out[g * 10 + i] = tuple(int(c) for c in cell)
    if len(out) != 60:
        print("permits: incomplete answer", r, flush=True)
    return out


def build_check(t):
    """The game's own build check Licence::Check 0x61B4C0 (ecx = Lager+0x9174) for town t:
    3 = may build, 2 = not enough trading record, 1/0 = permit for sale / too expensive."""
    lagers = session.scan_towns()
    if t >= len(lagers):
        return -1
    out = session.cmd("call", "0x61B4C0", f"{int(lagers[t][0], 16) + 0x9174:#x}", "0")
    m = re.search(r"returned eax=0x([0-9a-f]+)", out)
    return int(m.group(1), 16) & 0xFF if m else -1


def buildings(t):
    r = lua(f'Nation_Log("b", Player_GetNumBuildings(Global_GetPlayer(), Nation_TownHandle({t})) or -1)')
    return int(r.get("b", ["-1"])[0] or -1)


def others_same(a, b, skip):
    diff = [t for t in a if t not in skip and (a[t][1], a[t][3]) != (b.get(t, (0, 8, 0, 8))[1], b.get(t, (0, 8, 0, 8))[3])]
    return not diff, diff


def log_pos():
    return F.LOG.stat().st_size if F.LOG.exists() else 0


def shot(name):
    import screen
    try:
        screen.shot(name)
    except Exception as e:                         # a missing screenshot never fails the test
        print("screenshot failed:", e)


def town_info_shot(name):
    """The town info window of the town the player is in (click on the town name in the
    top bar): with the permit it lists 'Your buildings', without it 'Your trading record'
    (the permit progress, 0x4A5119)."""
    session.cmd("click", "650", "24")
    time.sleep(2.5)
    shot(name)
    session.cmd("key", "0x1B", "1")                # Escape closes it
    time.sleep(1)


def part_found():
    print("== found: FNN 02, capital Margarita", flush=True)
    session.load("FNN 02 - Rich - ready to found", [], "PR2_nation.exe")
    p0 = permits()
    print("Margarita before:", p0.get(MARGARITA), flush=True)
    lua(f"Nation_DevPermit({MARGARITA}, 0)")       # as if the player had no permit there
    p1 = permits()
    record("found-setup", p1[MARGARITA][1] == 0 and p1[MARGARITA][3] == 0, f"Margarita without permit: {p1[MARGARITA]}")
    b0 = buildings(MARGARITA)
    pos = log_pos()
    r = lua(f'local ok, why = Nation_Found({MARGARITA}, "Free Republic of Margarita", "Margaritan", 0, 0) '
            f'Nation_Log("f", ok, why)')
    time.sleep(2)
    p2 = permits()
    log = F.log_since(pos)
    record("found-capital", r.get("f", ["0"])[0] == "1" and p2[MARGARITA] == (1, 1, 1, 1),
           f"Nation_Found -> {r.get('f')}; Margarita (member, permit, before, vanilla) {p2[MARGARITA]}")
    chk = build_check(MARGARITA)
    record("found-buildcheck", chk == 3, f"game's build check 0x61B4C0 for Margarita -> {chk} (3 = may build)")
    record("found-message", "You may build there without a permit" in log,
           next((l for l in log.splitlines() if "independence" in l), "no founding message")[:160])
    ok, diff = others_same(p1, p2, {MARGARITA})
    record("found-others", ok, f"towns that changed besides the capital: {diff}")
    town_info_shot("permit_found_capital")

    session.cmd("call", "0x57EE90", "0x700500")    # QuickSave
    time.sleep(8)
    F.M.kill_game()
    session.load("Quick Save", [], "PR2_nation.exe")
    p3 = permits()
    record("found-reload", p3[MARGARITA] == (1, 1, 1, 1), f"after reload {p3[MARGARITA]}")
    town_info_shot("permit_found_reload")

    pos = log_pos()
    r = lua(f'Nation_Log("r", Nation_ReleaseTown({MARGARITA}, {SPAIN}))')
    time.sleep(2)
    p4 = permits()
    b1 = buildings(MARGARITA)
    record("found-release", r.get("r", ["0"])[0] == "1" and p4[MARGARITA][:2] == (0, 0) and p4[MARGARITA][3] == 0,
           f"released to Spain -> {p4[MARGARITA]} (permit back to 'none')")
    record("found-buildings", b0 == b1 and b0 >= 0, f"player buildings in Margarita {b0} -> {b1}")
    chk = build_check(MARGARITA)
    record("found-buildcheck2", chk not in (3, -1), f"build check after the release -> {chk} (not 3: needs a permit again)")
    ok, diff = others_same(p3, p4, {MARGARITA})
    record("found-others2", ok, f"towns that changed besides Margarita: {diff}")
    town_info_shot("permit_found_released")
    print(F.log_since(pos)[-600:], flush=True)
    F.M.kill_game()


def part_annex():
    print("== annex: FNN 22, Coro by conquest, Caracas with an earned permit", flush=True)
    session.load("FNN 22 - At war - troops off Coro", [], "PR2_nation.exe")
    lua(f"Nation_DevPermit({CORO}, 0)")
    lua(f"Nation_DevPermit({CARACAS}, 1)")          # earned before joining
    p0 = permits()
    print("Coro / Caracas before:", p0[CORO], p0[CARACAS], flush=True)
    pos = log_pos()
    r = lua(f'Nation_Log("a", Nation_Annex({CORO}, 0))')
    time.sleep(2)
    p1 = permits()
    log = F.log_since(pos)
    record("annex-coro", r.get("a", ["0"])[0] == "1" and p1[CORO] == (1, 1, 1, 1),
           f"Nation_Annex(Coro) -> {r.get('a')}; Coro {p1[CORO]}")
    chk = build_check(CORO)
    record("annex-buildcheck", chk == 3, f"game's build check 0x61B4C0 for Coro -> {chk} (3 = may build)")
    foreign = [t for t, v in p1.items() if v[0] == 0 and v[1] == 0][:3]
    fchk = {t: build_check(t) for t in foreign}
    record("annex-foreign", all(c not in (3, -1) for c in fchk.values()), f"build check in foreign towns without a permit {fchk}")
    msg = next((l for l in log.splitlines() if "has joined" in l), "")
    record("annex-message", "You may now build there." in msg and "Coro" in msg, msg[-120:])
    ok, diff = others_same(p0, p1, {CORO})
    record("annex-others", ok, f"towns that changed besides Coro: {diff}")
    town_info_shot("permit_annex_coro")

    lua(f"Nation_DevPermit({CORO}, 0)")              # given up at the master builder
    F.run_days(2)
    p2 = permits()
    record("annex-regrant", p2[CORO] == (1, 1, 1, 1), f"two days after giving it up: Coro {p2[CORO]}")

    r = lua(f'Nation_Log("a", Nation_Annex({CARACAS}, 0))')
    time.sleep(1)
    p3 = permits()
    record("annex-earned", r.get("a", ["0"])[0] == "1" and p3[CARACAS] == (1, 1, 2, 1),
           f"Caracas joins with its earned permit: {p3[CARACAS]}")

    r1 = lua(f'Nation_Log("r", Nation_ReleaseTown({CORO}, {SPAIN}))')
    r2 = lua(f'Nation_Log("r", Nation_ReleaseTown({CARACAS}, {SPAIN}))')
    time.sleep(2)
    p4 = permits()
    chk = build_check(CORO)
    record("annex-buildcheck2", chk not in (3, -1), f"build check in Coro after losing it -> {chk}")
    record("annex-lose", r1.get("r") == ["1"] and p4[CORO][:2] == (0, 0) and p4[CORO][3] == 0,
           f"Coro back to Spain: {p4[CORO]} (no permit, as before)")
    record("annex-lose-earned", r2.get("r") == ["1"] and p4[CARACAS][:2] == (0, 1) and p4[CARACAS][3] == 1,
           f"Caracas back to Spain: {p4[CARACAS]} (earned permit kept)")
    ok, diff = others_same(p0, p4, {CORO, CARACAS})
    record("annex-others2", ok, f"towns that changed besides Coro/Caracas: {diff}")
    F.M.kill_game()


def part_oldsave():
    print("== oldsave: FNN 46, a Great power made before this feature", flush=True)
    session.load("FNN 46 - Navy - Great power with a fleet", [], "PR2_nation.exe")
    log = F.log_since(0)                           # the game starts a new PR2Nation.log
    m = re.search(r"building permit granted in (\d+) member town", log)
    p = permits()
    members = {t: v for t, v in p.items() if v[0] == 1}
    town_info_shot("permit_oldsave")
    chks = {t: build_check(t) for t in members}
    record("oldsave-buildcheck", all(c == 3 for c in chks.values()), f"build check in member towns {chks}")
    ok = bool(members) and all(v[1] == 1 and v[3] == 1 and v[2] in (1, 2) for v in members.values())
    record("oldsave-load", ok and m is not None,
           f"log: {m.group(0) if m else 'no permit line'}; members {members}")
    granted = [l for l in log.splitlines() if "building permit granted" in l and "town " in l]
    print("\n".join(granted[:12]), flush=True)
    lose = next((t for t, v in members.items() if t != MARGARITA and v[2] == 1), None)
    if lose is not None:                           # a town that had no permit before joining leaves
        b0 = buildings(lose)
        r = lua(f'Nation_Log("r", Nation_ReleaseTown({lose}, {SPAIN}))')
        time.sleep(2)
        p2 = permits()
        b1 = buildings(lose)
        record("oldsave-lose", r.get("r") == ["1"] and p2[lose][:2] == (0, 0) and p2[lose][3] == 0 and b0 == b1,
               f"town {lose} released: {p2[lose]}, player buildings {b0} -> {b1}")
    F.M.kill_game()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all", choices=("found", "annex", "oldsave", "all"))
    ap.add_argument("--deploy", action="store_true", help="copy _build/dll/PR2Nation.dll into the test install")
    ap.add_argument("--keep", action="store_true", help="leave the game running")
    a = ap.parse_args()
    if a.deploy:
        shutil.copy2(env.HERE / "_build" / "dll" / "PR2Nation.dll", env.MOD_DLL)
        (env.ENV / "PR2Nation.dev").write_text("test install: enables Nation_Dev* and the PR2Nation.cmd console\n")
        print(f"deployed {env.MOD_DLL}", flush=True)
    backup = env.backup_saves()
    try:
        parts = ("found", "annex", "oldsave") if a.part == "all" else (a.part,)
        for part in parts:
            try:
                {"found": part_found, "annex": part_annex, "oldsave": part_oldsave}[part]()
            except SystemExit as e:
                record(part, False, f"aborted: {e}")
                F.M.kill_game()
        print("crashes:", F.M.crashes(), flush=True)
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
