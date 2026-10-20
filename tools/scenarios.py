"""Scenario saves: prepared game states to load and test one action each.

    python tools/scenarios.py --make [--only 13,21]   build the saves
    python tools/scenarios.py --run  [--only 13,21]   load each save, do the action, check
    python tools/scenarios.py --doc                   write SCENARIOS.md only

--make starts from a new game (or from another scenario's save), puts the game
into the scenario's state with the Nation_* / Nation_Dev* API and the harness,
QuickSaves and copies the save to "<Save folder>/FNN <id> - <title>.pr2".
Those saves stay in the Save folder on purpose: load them from the game's
Load menu to try the same action by hand (SCENARIOS.md says what to do and
what should happen). --run loads each save in the test install, performs
the action like a player (menu clicks) or through the API, and checks the
result in game memory and the API. Reports: SCENARIO_RESULTS.md.

Everything runs in the corner window (tools/session.py). The user's own saves
and settings.cfg are backed up first and restored afterwards; the FNN saves
are left in place.
"""
import argparse
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_env as env  # noqa: E402
import sn_session as session  # noqa: E402
import m0_suite as M  # noqa: E402
import feature_suite as F  # noqa: E402
import conquest_test as C  # noqa: E402

EXE = "PR2_nation.exe"
SAVES_OUT = env.HERE / "_build" / "scenario_saves"
DOC = env.HERE / "SCENARIOS.md"
REPORT = env.HERE / "SCENARIO_RESULTS.md"
CAPITAL, CORO, SPAIN, ENGLAND = 56, 52, 3, 0
# menu pages (include.ini FNN_P_*) and their button counts
PANEL_FOUND = 6                                       # the founding page (before founding)
# Pauses after UI actions. A Nation_* call runs in the DLL's console, which takes a script only every 30
# frames, and the panel API acts at once (refreshes on the next frame), so consecutive Lua calls need no
# pause between them. A gamehost click is injected over the next 3 frames after cmd() returns.
UI = 0.3                                              # after a panel API call
CLICK = 0.6                                           # after a click injected by gamehost

results = []
current = {"id": "?"}


class Fail(Exception):
    pass


# ---------------------------------------------------------------- helpers --
def record(check, ok, detail):
    name = f"S{current['id']}/{check}"
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<22} {detail}", flush=True)
    return ok


def lua(code):
    r = F.lua(code)
    if "__error__" in r:
        print("  LUA error:", r["__error__"][0][-300:])
    return r


def info():
    r = lua('Nation_Log("i", Nation_GetInfo())')
    v = r.get("i", [])
    keys = ["founded", "name", "adj", "capital", "treasury", "stability", "towns", "tax", "tariff"]
    return dict(zip(keys, v))


def finance():
    v = lua('Nation_Log("f", Nation_GetFinance())').get("f", [])
    keys = ["treasury", "tax", "upkeep", "tariff", "month_day", "estimate", "today", "military"]
    return {k: int(x) for k, x in zip(keys, v) if re.fullmatch(r"-?\d+", x)}


def navy():
    v = lua('Nation_Log("n", Nation_NavyInfo())').get("n", [])
    keys = ["ready", "fleets", "cap", "rank", "rank_name", "order", "order_name", "target", "military",
            "plunder", "cost", "upkeep"]
    return {k: (int(x) if re.fullmatch(r"-?\d+", x) else x) for k, x in zip(keys, v)}


def defence(t):
    v = lua(f'Nation_Log("d", Nation_TownDefence({t}))').get("d", [])
    return dict(zip(["soldiers", "towers", "budget", "bought"], [int(x) for x in v if re.fullmatch(r"-?\d+", x)]))


def wait_fleets(n, limit=20):
    t0 = time.time()
    while time.time() - t0 < limit:
        if navy().get("fleets") == n:
            return True
        time.sleep(0.5)
    return False


def relation(p):
    v = lua(f'Nation_Log("r", Nation_GetRelation({p}))').get("r", [])
    return dict(zip(["status", "score", "recognized", "chance"], [int(x) for x in v if re.fullmatch(r"-?\d+", x)]))


def town(t):
    v = lua(f'Nation_Log("t", Nation_GetTown({t}))').get("t", [])
    return dict(zip(["member", "loyalty", "tax", "unrest"], [int(x) for x in v if re.fullmatch(r"-?\d+", x)]))


def gold():
    return int(lua('Nation_Log("g", Nation_GetGold())').get("g", ["-1"])[0])


def gov():
    v = lua('Nation_Log("g", Nation_GetGovernment())').get("g", [])
    return {"gov": int(v[0]), "name": v[1], "cooldown": int(v[2])} if len(v) >= 3 else {}


def owner_byte(t):
    rows = C.towns()
    return C.u8(rows[t][1] + C.L_NATION) if t in rows else None


def war_table(p):
    return C.u8(0x9F7000 + p)


def dev(*args):
    a = ", ".join(f'"{x}"' if isinstance(x, str) else str(x) for x in args)
    r = lua(f'Nation_Log("d", Nation_DevSet({a}))')
    if r.get("d", ["0"])[0] != "1":
        raise Fail(f"Nation_DevSet({a}) refused")


CONQ = 10                                             # the conquest popup's page (include.ini)


def popup_press(btn, page, shot):
    """The conquest popup (Annex / Withdraw), the one dialog left: screenshot it, find its buttons, click
    button `btn` (0-based) and check that the script logged closing page `page` with it."""
    import screen
    from buttons import find_buttons_n
    name = f"s{current['id']}_{shot}"
    screen.shot(name)
    found = find_buttons_n(screen.SHOTS / f"{name}.png", 2)
    if btn >= len(found):
        raise Fail(f"popup: only {len(found)} buttons found")
    for _ in range(2):                                # a popup that just opened can miss the first click
        pos = F.LOG.stat().st_size
        session.cmd("click", *found[btn])
        m = wait_log(r"FNN popup close \| (\S+) \| (\S+)", pos, 4)
        if m:
            break
    if not m or m.groups() != (str(page), str(btn)):
        raise Fail(f"popup click {btn} on page {page} did not register ({m.groups() if m else 'nothing logged'})")


def confirm():
    """Answer the page's question (Withdraw on the Treasury, Declare war on Diplomacy) with yes."""
    page = (lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0", "-1"]) + ["-1"])[1]
    lua(f"Nation_PanelClick({3007 if page == '1' else 3200})")
    time.sleep(UI)
    return panel_result()


def refresh_towns():
    """A loaded save has new town objects: rebuild _build/towns.tsv (conquest_test reads it)."""
    lagers = session.scan_towns()
    names = session.town_names()
    if len(lagers) != len(names):
        raise Fail(f"town scan found {len(lagers)} towns, expected {len(names)}")
    (env.HERE / "_build" / "towns.tsv").write_text("idx\tname\tlager\tnation\tdisplay\n" + "".join(
        f"{i}\t{n}\t{a}\t{nat}\t{d}\n" for i, (n, (a, nat, d)) in enumerate(zip(names, lagers))))


def fast(on):
    session.cmd("call", "0x57F570", "0x700500", "1" if on else "0")


def day_of_month():
    out = session.cmd("read", "0x702c1c", "1")
    m = re.search(r": ([0-9a-f]{2})", out)
    return int(m.group(1), 16) if m else None


def run_to_day(day, limit=300):
    """Fast-forward until the day-of-month byte reaches `day` (before a month end)."""
    M.speed_up()
    fast(True)
    t0 = time.time()
    try:
        while time.time() - t0 < limit:
            d = day_of_month()
            if d is not None and d >= day:
                return d
            time.sleep(0.5)
        raise Fail(f"day {day} not reached in {limit}s (last {day_of_month()})")
    finally:
        fast(False)
        session.cmd("call", "0x57F550", "0x700500", "1")    # normal speed: the save starts calm


def run_to_day_offset(days, limit=240):
    """Fast-forward `days` game days from now."""
    start = finance().get("today", 0)
    M.speed_up()
    fast(True)
    t0 = time.time()
    try:
        while time.time() - t0 < limit:
            time.sleep(0.5)
            if not M.game_alive():
                raise Fail("game exited")
            if finance().get("today", start) - start >= days:
                return
        raise Fail(f"{days} days did not pass within {limit}s")
    finally:
        fast(False)


def run_to_month_end(limit=300):
    """Fast-forward until the nation's monthly settlement has happened; returns (before, after)."""
    before = finance()
    M.speed_up()
    fast(True)
    t0 = time.time()
    try:
        while time.time() - t0 < limit:
            time.sleep(0.5)
            if not M.game_alive():
                raise Fail("game exited during the month")
            now = finance()
            if now.get("month_day", before.get("month_day")) != before.get("month_day"):
                return before, now
        raise Fail(f"no monthly settlement within {limit}s")
    finally:
        fast(False)
        session.cmd("call", "0x57F550", "0x700500", "1")


def logo_is(index):
    """The nation's flag file Run\\7.bmp (the two-flags change: national ships and towns draw it) is nation flag `index`,
    and the player's own logo Run\\0.bmp is not (the mod never writes it)."""
    nat, own = env.RUN_DIR / "7.bmp", env.RUN_DIR / "0.bmp"
    flag = env.ENV / "nation_flags" / f"flag_{index:03d}.bmp"
    if not (nat.exists() and flag.exists()):
        return False
    return nat.read_bytes() == flag.read_bytes() and not (own.exists() and own.read_bytes() == flag.read_bytes())


def shot(name):
    try:
        import screen
        screen.shot(f"s{current['id']}_{name}")
    except Exception as e:                        # informational only
        print("screenshot failed:", e)


def log_mark():
    return F.LOG.stat().st_size if F.LOG.exists() else 0


def found_nation():
    r = lua(f'''Nation_DevSetRequirements(10000, 1, 0)
local ok, why = Nation_Found({CAPITAL}, "Free Republic of Margarita", "Margaritan", 0, 0)
Nation_Log("f", ok, why)''')
    if r.get("f", ["0"])[0] != "1":
        raise Fail(f"founding failed: {r}")


def annex_coro():
    r = lua(f'Nation_Log("a", Nation_Annex({CORO}, 1))')          # 1 = treaty (no war needed)
    if r.get("a", ["0"])[0] != "1":
        raise Fail(f"annexing Coro failed: {r}")


def troops_off_coro():
    """Arm the player's convoy and sail it to Coro (no battle)."""
    refresh_towns()
    c, _ = C.pick_convoy()
    C.grant_troops(c)
    target = C.pick_town(CORO)
    M.speed_up()
    C.sail(c, target, "B")
    session.cmd("call", "0x57F550", "0x700500", "1")


def conquest_battle(expect_conquest):
    """Fight the land battle at Coro (defenders emptied: a deterministic win)."""
    refresh_towns()
    C.ZERO_DEFENDERS, C.ATTACK_CLICKS = True, False
    c, _ = C.pick_convoy()
    target = C.pick_town(CORO)
    try:
        C.drive(c, target, "B", False)
        return True
    except C.Stall as e:
        if not expect_conquest and "conquest_applies() said no" in str(e):
            return False
        raise Fail(f"battle: {e}")


def wait_log(pattern, mark, limit=30):
    t0 = time.time()
    while True:
        m = re.search(pattern, F.log_since(mark))
        if m or time.time() - t0 >= limit:
            return m
        time.sleep(0.25)


# -------------------------------------------------------------- registry --
class Sc:
    def __init__(self, id, title, base, state, manual, expect, setup=None, test=None, save=True):
        self.id, self.title, self.base, self.state = id, title, base, state
        self.manual, self.expect, self.test, self.save = manual, expect, test, save

    @property
    def setup(self):                   # attached to the test function by @setup_of (after registration)
        return getattr(self.test, "setup", None)

    @property
    def save_name(self):
        return f"FNN {self.id} - {self.title}"


REG = []


def scenario(id, title, base, state, manual, expect, save=True):
    def deco(fn):
        sc = Sc(id, title, base, state, manual, expect, save=save)
        sc.test = fn
        REG.append(sc)
        return fn
    return deco


def setup_of(fn):
    def deco(s):
        fn.setup = s
        return s
    return deco


def by_id(i):
    return next(s for s in REG if s.id == i)


# ------------------------------------------------------------- scenarios --
# Each test function runs right after its save has been loaded.

@scenario("01", "No nation yet", "new",
          "A fresh game: Pedro Ruiz at Margarita with 30,000 gold, no nation.",
          "Click the nation button in the top bar (or Ctrl+N): the *Found a Nation* page; press *Found the nation*.",
          "The founding is refused with the missing requirement (5,000,000 gold), shown in red on the card. "
          "Nothing changes.")
def s01():
    lua("Nation_PanelOpen(-1)")
    time.sleep(UI)
    page = lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0", "-1"])
    lua("Nation_PanelClick(104)")                     # Found the nation
    time.sleep(UI)
    i = info()
    body = lua('Nation_Log("c", Nation_PanelCard(0))').get("c", ["", ""])[1]
    record("refused", page[1:2] == [str(PANEL_FOUND)] and i.get("founded") == "0" and "gold" in body,
           f"founding page {page}; founded={i.get('founded')}; card: {body[:120]!r}")
    lua("Nation_PanelClose()")


@scenario("02", "Rich - ready to found", "01",
          "No nation; about 5,030,000 gold. PR2Nation.ini in the test install lowers the ship requirement "
          "to 1 ship (the starting convoy).",
          "Nation button (or Ctrl+N) -> the *Found a Nation* page: form *Republic*, keep the suggested name, "
          "flag arrows to No. 38 of 100 (Calico Jack) -> *Found the nation*.",
          "The Republic of Margarita is founded with Margarita as capital under Calico Jack's flag; Spain loses "
          "Margarita; a message appears and the panel opens on the Overview.")
def s02():
    spain0 = int(lua('Nation_Log("n", Nation_GetNumTowns(3))')["n"][0])
    lua("Nation_PanelOpen(-1)")
    time.sleep(UI)
    lua("for i = 1, 37 do Nation_PanelClick(103) end")   # flag 0 -> 37 (No. 38 of 100): 37 presses of the arrow
    time.sleep(UI)
    lua("Nation_PanelClick(104)")                     # Found the nation
    time.sleep(UI)
    i = info()
    spain1 = int(lua('Nation_Log("n", Nation_GetNumTowns(3))')["n"][0])
    record("founded", i.get("founded") == "1" and i.get("name") == "Republic of Margarita"
           and i.get("capital") == str(CAPITAL), f"info {i}")
    record("spain-lost-town", spain1 == spain0 - 1, f"Spanish towns {spain0} -> {spain1}")
    record("owner-byte", owner_byte(CAPITAL) == 5, f"Margarita owner byte {owner_byte(CAPITAL)} (5 = nation)")
    fl = lua('Nation_Log("f", Nation_GetFlag(), Nation_FlagName(Nation_GetFlag()))').get("f", [])
    record("flag", fl[:1] == ["37"], f"flag {fl}")
    record("logo", logo_is(37), "Run\\7.bmp (the nation's flag) is flag No. 37; the player's logo Run\\0.bmp is kept")
    time.sleep(1.5)                                   # the founding message and the panel drawn for the screenshot
    shot("after_founding")


@setup_of(s02)
def _s02_setup():
    lua("Nation_DevGrantGold(5000000)")


@scenario("10", "Nation founded", "new",
          "Free Republic of Margarita founded at Margarita; 50,000 in the national treasury, "
          "about 150,000 personal gold; at peace with everyone.",
          "Load it and click the nation button: the panel's Overview and Diplomacy tabs.",
          "The panel shows the nation, treasury 50,000, 1 town, peace with all four powers.")
def s10():
    i = info()
    record("loaded", i.get("founded") == "1" and i.get("treasury") == "50000" and i.get("capital") == str(CAPITAL),
           f"nation state after load: {i}")
    record("owner-byte", owner_byte(CAPITAL) == 5, f"Margarita owner byte {owner_byte(CAPITAL)}")
    record("war-table", all(war_table(p) == 0 for p in range(4)), "player_rel all 0 (peace)")
    record("logo", logo_is(0), "after loading, Run\\7.bmp is the nation's flag No. 0 (Venice); Run\\0.bmp stays the player's")
    shot("loaded")


@setup_of(s10)
def _s10_setup():
    found_nation()
    r = lua('Nation_Log("g", Nation_DevGrantGold(200000))\nNation_Log("d", Nation_Donate(50000))')
    if r.get("d", ["0"])[0] != "1":
        raise Fail(f"donation failed: {r}")


@scenario("11", "Treasury actions", "10",
          "Same as 10.",
          "Nation button -> Treasury tab -> *Donate 10,000* on the Accounts card; *Apply* on 'Import tariff 5%'; "
          "open the Navy and defence tab.",
          "Treasury +10,000 (personal gold -10,000), tariff 5%; the Navy and defence tab has no national convoys "
          "(removed in this version).", save=False)
def s11():
    t0 = int(info()["treasury"])
    panel_press(1, "Accounts", 0)                     # Donate 10,000
    t1 = int(info()["treasury"])
    record("donate", t1 == t0 + 10000, f"treasury {t0} -> {t1}")
    panel_press(1, "Import tariff 5%", 0)              # Apply
    record("tariff", info().get("tariff") == "5", f"tariff {info().get('tariff')}%")
    lua("Nation_PanelOpen(5)")                        # Navy and defence: no national convoys any more
    time.sleep(UI)
    panel_mode(NAVY_FLEETS)
    rows = [name for _, name, _ in panel_rows()]
    lua("Nation_PanelClose()")
    n = lua('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["?"])[0]
    record("no-convoys", n == "0" and not any("National convoy" in r for r in rows),
           f"Nation_NationalConvoys(1) -> {n}; Navy tab rows {rows}")


@scenario("12", "Month end in 2 days", "10",
          "Nation of 10, two days before the end of the month.",
          "Load, unpause and let 3 days pass.",
          "Monthly accounts message: taxes in, upkeep 2,000 out; treasury = old + tax + tariff - upkeep.")
def s12():
    before, after = run_to_month_end()
    expect = before["treasury"] + after["tax"] + after["tariff"] - after["upkeep"]
    record("settled", after["tax"] > 0 and after["upkeep"] == 2000, f"tax {after['tax']} tariff {after['tariff']} "
           f"upkeep {after['upkeep']}")
    record("exact", after["treasury"] == expect, f"treasury {before['treasury']} -> {after['treasury']} (expected {expect})")


@setup_of(s12)
def _s12_setup():
    run_to_day(27)


@scenario("13", "Insolvent at month end", "12",
          "Nation two days before month end with an empty treasury and 0% tax (upkeep 2,000 a month).",
          "Load and let 3 days pass.",
          "The treasury goes negative; message 'The national treasury is insolvent'; stability -3 or more.")
def s13():
    s0 = int(info()["stability"])
    mark = log_mark()
    before, after = run_to_month_end()
    s1 = int(info()["stability"])
    msg = re.search(r"MSG The national treasury is insolvent.*", F.log_since(mark))
    record("negative", after["treasury"] < 0, f"treasury {before['treasury']} -> {after['treasury']}")
    record("message", msg is not None, msg.group(0) if msg else "no insolvency message")
    record("stability", s1 <= s0 - 3, f"stability {s0} -> {s1}")


@setup_of(s13)
def _s13_setup():
    lua("Nation_SetTax(-1, 0)")
    dev("treasury", 0)


@scenario("14", "Unrest about to break out", "12",
          "Coro joined the nation by treaty; Coro has loyalty 12 and has been below 20 for a month; "
          "Coro's tax is 50%; month end in 2 days.",
          "Load and let 3 days pass.",
          "Message 'Unrest has broken out in Coro'; Coro goes on strike (production stops).")
def s14():
    mark = log_mark()
    run_to_month_end()
    out = F.log_since(mark)
    msg = re.search(r"MSG Unrest has broken out in Coro.*", out)
    fx = re.search(rf"FX unrest town {CORO} start", out)
    t = town(CORO)
    record("message", msg is not None, msg.group(0) if msg else "no unrest message")
    record("strike", fx is not None, "eng_town_unrest(Coro) applied" if fx else "no FX unrest start")
    record("in-unrest", t.get("unrest") == 1, f"Coro {t} (Nation_GetTown's 4th value is the in-unrest flag)")


@setup_of(s14)
def _s14_setup():
    annex_coro()
    lua(f"Nation_SetTax({CORO}, 50)")
    dev("loyalty", CORO, 12)
    dev("unrest", CORO, 1)


@scenario("15", "Coro about to secede", "12",
          "Coro has been in open unrest for 4 months (loyalty 5); month end in 2 days.",
          "Load and let 3 days pass.",
          "Message 'After 4 months of unrest, Coro secedes ... returns to Spanish rule'; "
          "Coro is Spanish again; stability -10.")
def s15():
    s0 = int(info()["stability"])
    mark = log_mark()
    run_to_month_end()
    msg = re.search(r"MSG After \d+ months of unrest, Coro secedes.*", F.log_since(mark))
    t = town(CORO)
    record("message", msg is not None, msg.group(0) if msg else "no secession message")
    record("seceded", t.get("member") == 0 and owner_byte(CORO) == SPAIN,
           f"Coro member {t.get('member')} owner byte {owner_byte(CORO)}")
    record("stability", int(info()["stability"]) <= s0 - 10, f"stability {s0} -> {info()['stability']}")


@setup_of(s15)
def _s15_setup():
    annex_coro()
    dev("loyalty", CORO, 5)
    dev("unrest", CORO, 5)


@scenario("16", "Capital about to fall", "10",
          "Nation with two towns: Margarita (capital) and Coro (joined by treaty).",
          "(Needs an AI attack to happen by hand.) The automated test simulates Spain retaking Margarita.",
          "The capital moves to Coro; message 'The capital ... has fallen! The government relocates to Coro'; "
          "Margarita is Spanish again.")
def s16():
    mark = log_mark()
    r = lua(f'Nation_Log("rel", Nation_ReleaseTown({CAPITAL}, 3))')
    msg = re.search(r"MSG The capital of .* relocates to Coro.*", F.log_since(mark))
    i = info()
    record("released", r.get("rel", ["0"])[0] == "1", f"Nation_ReleaseTown -> {r.get('rel')}")
    record("relocated", i.get("capital") == str(CORO), f"capital {i.get('capital')}")
    record("message", msg is not None, msg.group(0) if msg else "no relocation message")
    record("owner-byte", owner_byte(CAPITAL) == SPAIN, f"Margarita owner byte {owner_byte(CAPITAL)}")


@setup_of(s16)
def _s16_setup():
    annex_coro()


@scenario("17", "Reform available", "10",
          "Nation of 10 (Sovereign Nation, no reform cooldown).",
          "Nation button -> Government tab -> *Adopt* on the Pirate Republic card.",
          "The nation becomes a Pirate Republic; stability -10; relations with all powers -10; "
          "a 25-month cooldown starts.", save=False)
def s17():
    s0 = int(info()["stability"])
    r0 = [relation(p).get("score") for p in range(4)]
    panel_press(4, "Pirate Republic", 0)              # Adopt
    lua("Nation_PanelClose()")
    g = gov()
    r1 = [relation(p).get("score") for p in range(4)]
    record("adopted", g.get("gov") == 3 and g.get("cooldown") == 25, f"government {g}")
    record("stability", int(info()["stability"]) == s0 - 10, f"stability {s0} -> {info()['stability']}")
    record("relations", all(b is not None and a is not None and b <= a - 10 + 0 for a, b in zip(r0, r1)),
           f"relations {r0} -> {r1}")


@scenario("18", "Reform on cooldown", "10",
          "The nation adopted the Merchant Republic this month (25-month cooldown).",
          "Nation button -> Government tab -> *Adopt* on the Colonial Monarchy card.",
          "Refused: 'Another constitutional reform is possible in 25 months.' (shown on the first card)")
def s18():
    first = panel_press(4, "Colonial Monarchy", 0)    # Adopt
    lua("Nation_PanelClose()")
    g = gov()
    record("refused", g.get("gov") == 1, f"government stays {g}")
    record("ui", first[0] == "Not possible" and "25 months" in first[1], f"first card {first}")


@setup_of(s18)
def _s18_setup():
    r = lua('Nation_Log("g", Nation_SetGovernment(1))')
    if r.get("g", ["0"])[0] != "1":
        raise Fail(f"Merchant Republic not adopted: {r}")


@scenario("19", "Declare war via the menu", "10",
          "Nation of 10, at peace.",
          "Nation button -> Diplomacy tab -> Spain -> *Declare war* -> *Confirm*.",
          "At war with Spain: Spanish ships and towns treat you as an enemy; the Overview shows 'AT WAR'.",
          save=False)
def s19():
    first = panel_press(3, "Spain", 1)                # Declare war (asks first)
    if first[0] != "Please confirm":
        raise Fail(f"no confirmation card: {first}")
    confirm()
    lua("Nation_PanelClose()")
    r = relation(SPAIN)
    record("war", r.get("status") == 4 and war_table(SPAIN) == 1, f"Spain {r}, player_rel {war_table(SPAIN)}")
    record("others-peace", all(relation(p).get("status") == 0 for p in (0, 1, 2)), "England/France/Holland at peace")


@scenario("20", "Exhausted war with Spain", "10",
          "At war with Spain for 200 days: Spain's war exhaustion 90, relation -10.",
          "Nation button -> Diplomacy tab -> Spain -> *Offer ceasefire*.",
          "The page shows a high ceasefire chance; Spain accepts if the roll is under it. In a ceasefire "
          "the war table is cleared (Spanish ships stop attacking) and the button becomes *Propose peace*.")
def s20():
    r0 = relation(SPAIN)
    panel_press(3, "Spain", 0)                        # Offer ceasefire
    lua("Nation_PanelClose()")
    r1 = relation(SPAIN)
    consistent = (r1.get("status") == 4 and war_table(SPAIN) == 1) or (r1.get("status") in (0, 5) and war_table(SPAIN) == 0)
    record("consistent", consistent, f"before {r0}, after {r1}, player_rel {war_table(SPAIN)}")
    # the chance includes the AI strategy's modifier, which follows live vanilla conditions (e.g. whether
    # Spain is at war with another power), so it varies between loads; before the fix it was always 0
    strat = lua(f'Nation_Log("s", Nation_GetStrategy({SPAIN}))').get("s", ["?", "?"])[-1]
    record("chance", r0.get("chance", 0) >= 25,
           f"ceasefire chance with an exhausted Spain: {r0.get('chance')}% (Spain's strategy: {strat})")


@setup_of(s20)
def _s20_setup():
    lua(f"Nation_DeclareWar({SPAIN})")
    dev("exhaustion", SPAIN, 90)
    dev("score", SPAIN, -10)
    dev("lastchange", SPAIN, 200)                 # a long war: no "declared this month" malus


@scenario("21", "Friendly England", "10",
          "England loves the nation (relation 100) and recognizes it.",
          "Console/API: Nation_Propose(0, 1) (trade agreement), then Nation_Propose(0, 3) (alliance).",
          "A high chance for the trade agreement (shown in the answer); the answer is a roll against it. "
          "An accepted treaty shows up in the Overview; a rejected one changes nothing.")
def s21():
    for t, name in ((1, "trade"), (3, "alliance")):
        before = relation(ENGLAND).get("status")
        r = lua(f'local ok, why = Nation_Propose({ENGLAND}, {t})\nNation_Log("p", ok, why)')
        ok, why = (r.get("p", ["?", ""]) + [""])[:2]
        after = relation(ENGLAND).get("status")
        m = re.search(r"chance was (\d+)%", why)
        chance = int(m.group(1)) if m else (100 if ok == "1" else None)
        consistent = (ok == "1" and after == t) or (ok == "0" and after == before)
        record(f"{name}-consistent", consistent, f"Nation_Propose -> {ok} '{why}'; status {before} -> {after}")
        if name == "trade":
            strat = lua(f'Nation_Log("s", Nation_GetStrategy({ENGLAND}))').get("s", ["?", "?"])[-1]
            record("trade-chance", chance is not None and chance >= 60,
                   f"trade agreement chance {chance}% (England's strategy: {strat})")


@setup_of(s21)
def _s21_setup():
    dev("score", ENGLAND, 100)
    dev("recognized", ENGLAND, 1)


@scenario("22", "At war - troops off Coro", "10",
          "At war with Spain; the player's convoy (40 sailors, 200 cutlasses, 200 muskets) lies at Coro.",
          "Select the convoy, attack Coro (land assault) and win the battle.",
          "After the battle: popup 'Town Conquered' -> *Annex*: Coro joins the nation; Spain has one town less.")
def s22():
    spain0 = int(lua('Nation_Log("n", Nation_GetNumTowns(3))')["n"][0])
    mark = log_mark()
    conquest_battle(True)
    if not wait_log(rf"UI: conquest popup for town {CORO}", mark):
        raise Fail("the conquest popup was not opened")
    time.sleep(2)                                     # drawn before the screenshot looks for its buttons
    popup_press(0, CONQ, "annex")
    spain1 = int(lua('Nation_Log("n", Nation_GetNumTowns(3))')["n"][0])
    record("annexed", town(CORO).get("member") == 1 and owner_byte(CORO) == 5,
           f"Coro member {town(CORO).get('member')} owner byte {owner_byte(CORO)}")
    record("spain", spain1 == spain0 - 1, f"Spanish towns {spain0} -> {spain1}")


@setup_of(s22)
def _s22_setup():
    troops_off_coro()                             # sail first: at war, Spanish fleets intercept at sea
    lua(f"Nation_DeclareWar({SPAIN})")


@scenario("23", "Conquest - withdraw", "22",
          "Same save as 22.",
          "Win the battle at Coro, then press *Withdraw* in the popup.",
          "Coro stays Spanish; no pending conquest remains.", save=False)
def s23():
    mark = log_mark()
    conquest_battle(True)
    if not wait_log(rf"UI: conquest popup for town {CORO}", mark):
        raise Fail("the conquest popup was not opened")
    time.sleep(2)
    popup_press(1, CONQ, "withdraw")
    w = wait_log(rf"WAR conquest of town {CORO} \(Coro\): WITHDRAW", mark, 10)
    pend = lua('Nation_Log("p", Nation_PendingConquest())').get("p", ["?"])[0]
    record("withdrawn", w is not None and town(CORO).get("member") == 0 and owner_byte(CORO) == SPAIN,
           f"WITHDRAW logged={w is not None}, Coro member {town(CORO).get('member')} owner {owner_byte(CORO)}")
    record("no-pending", pend == "-1", f"Nation_PendingConquest() -> {pend}")


@scenario("24", "At peace - troops off Coro", "10",
          "At PEACE with Spain; the armed convoy lies at Coro.",
          "Attack Coro anyway and win.",
          "No 'Town Conquered' popup: a peacetime victory gives no title. Coro stays Spanish.")
def s24():
    mark = log_mark()
    conquered = conquest_battle(False)
    popup = wait_log(rf"UI: conquest popup for town {CORO}", mark, 8)
    record("no-conquest", not conquered and popup is None and town(CORO).get("member") == 0,
           f"conquest recorded={conquered}, popup={popup is not None}, Coro member {town(CORO).get('member')}")


@setup_of(s24)
def _s24_setup():
    troops_off_coro()


@scenario("25", "Attack own capital", "10",
          "Nation of 10.",
          "Order the convoy at Margarita to attack Margarita.",
          "Refused: the game does not start a battle against your own nation's town.", save=False)
def s25():
    refresh_towns()
    c, _ = C.pick_convoy()
    C.results.clear()
    C.con02(c, CAPITAL)
    ok = any(t == "CON-02" and ok for t, ok, _ in C.results)
    record("refused", ok, next((d for t, _, d in C.results if t == "CON-02"), "no CON-02 result"))


@scenario("26", "Complex nation - save round trip", "10",
          "Two towns (Coro by treaty), Merchant Republic, at war with Spain, tax 20%, tariff 10%, "
          "treasury 123,456.",
          "Load, QuickSave, quit, load the Quick Save.",
          "Everything identical after the reload: towns, government, war, taxes, treasury.")
def s26():
    def snap():
        return (info(), gov(), [relation(p) for p in range(4)], town(CORO), town(CAPITAL),
                [war_table(p) for p in range(4)])
    a = snap()
    session.quicksave()
    M.kill_game()
    session.load("Quick Save", [], EXE)
    b = snap()
    for k, (x, y) in enumerate(zip(a, b)):
        record(f"same{k}", x == y, f"{x} | {y}" if x != y else str(x)[:150])


@setup_of(s26)
def _s26_setup():
    annex_coro()
    lua(f"Nation_SetGovernment(1)\nNation_DeclareWar({SPAIN})\nNation_SetTax(-1, 20)\nNation_SetTariff(10)")
    dev("treasury", 123456)


@scenario("27", "Weak and broke", "10",
          "Treasury -20,000 (insolvent), stability 20.",
          "Nation button -> Diplomacy tab: look at the powers.",
          "The powers turn opportunistic (they smell weakness); Nation_GetStrategy shows it.")
def s27():
    st = [lua(f'Nation_Log("s", Nation_GetStrategy({p}))').get("s", ["?", "?"]) for p in range(4)]
    record("opportunistic", any(s[0] == "3" for s in st), f"strategies {[s[-1] for s in st]}")


@setup_of(s27)
def _s27_setup():
    dev("treasury", -20000)
    dev("stability", 20)


@scenario("28", "Order about to be restored", "12",
          "Coro (joined by treaty) has been in unrest for a month but its loyalty is back to 45; "
          "month end in 2 days.",
          "Load and let 3 days pass.",
          "Message 'Order has been restored in Coro'; the strike ends; Coro is no longer in unrest.")
def s28():
    mark = log_mark()
    run_to_month_end()
    out = F.log_since(mark)
    msg = re.search(r"MSG Order has been restored in Coro.*", out)
    fx = re.search(rf"FX unrest town {CORO} end", out)
    t = town(CORO)
    record("message", msg is not None, msg.group(0) if msg else "no 'order restored' message")
    record("strike-ended", fx is not None, "eng_town_unrest(Coro, off) applied" if fx else "no FX unrest end")
    record("calm", t.get("unrest") == 0 and t.get("member") == 1, f"Coro {t}")


@setup_of(s28)
def _s28_setup():
    annex_coro()
    dev("loyalty", CORO, 45)
    dev("unrest", CORO, 3)


@scenario("29", "Capital in revolt", "12",
          "The capital Margarita has been in open unrest for 4 months (loyalty 5); month end in 2 days.",
          "Load and let 3 days pass.",
          "Message 'Riots paralyse the capital (Margarita)'; stability -20; the capital never secedes.")
def s29():
    s0 = int(info()["stability"])
    mark = log_mark()
    run_to_month_end()
    msg = re.search(r"MSG Riots paralyse the capital \(Margarita\).*", F.log_since(mark))
    i = info()
    record("message", msg is not None, msg.group(0) if msg else "no riot message")
    record("stability", int(i["stability"]) <= s0 - 20, f"stability {s0} -> {i['stability']}")
    record("no-secession", i.get("capital") == str(CAPITAL) and town(CAPITAL).get("member") == 1
           and owner_byte(CAPITAL) == 5, f"capital {i.get('capital')}, Margarita owner byte {owner_byte(CAPITAL)}")


@setup_of(s29)
def _s29_setup():
    dev("loyalty", CAPITAL, 5)
    dev("unrest", CAPITAL, 5)


@scenario("30", "Ceasefire with Spain", "10",
          "War with Spain ended in a ceasefire 200 days ago; Spain's relation +30, exhaustion 60.",
          "Nation button -> Diplomacy tab -> Spain -> *Propose peace*.",
          "During the ceasefire Spanish ships are not hostile (war table off). The page offers *Propose "
          "peace* with its chance; if Spain accepts, the status becomes peace.")
def s30():
    r0 = relation(SPAIN)
    record("ceasefire-not-hostile", r0.get("status") == 5 and war_table(SPAIN) == 0,
           f"Spain {r0}, player_rel {war_table(SPAIN)}")
    panel_press(3, "Spain", 0)                        # Propose peace
    lua("Nation_PanelClose()")
    r1 = relation(SPAIN)
    record("consistent", r1.get("status") in (0, 5) and war_table(SPAIN) == 0,
           f"after proposing peace: Spain {r1}, player_rel {war_table(SPAIN)}")
    record("chance", r0.get("chance", 0) > 0, f"peace chance during the ceasefire: {r0.get('chance')}%")


@setup_of(s30)
def _s30_setup():
    lua(f"Nation_DeclareWar({SPAIN})")
    dev("status", SPAIN, 5)
    dev("score", SPAIN, 30)
    dev("exhaustion", SPAIN, 60)
    dev("lastchange", SPAIN, 200)


@scenario("31", "Taxes via the menu", "10",
          "Nation of 10 (national tax 10%).",
          "Nation button -> Treasury tab -> National tax card: *Raise to 15%*, then *Lower to ...* twice (5%).",
          "The national tax follows each click: 15%, 10%, 5%.", save=False)
def s31():
    panel_press(1, "National tax", 0)                 # Raise to 15%
    t1 = info().get("tax")
    panel_press(1, "National tax", 1)                 # Lower to 10%
    panel_press(1, "National tax", 1)                 # Lower to 5%
    t2 = info().get("tax")
    lua("Nation_PanelClose()")
    record("raise", t1 == "15", f"after Raise: {t1}%")
    record("lower", t2 == "5", f"after Lower x2: {t2}%")


@scenario("32", "Withdraw from the treasury", "10",
          "Treasury 100,000, stability 60.",
          "Nation button -> Treasury tab -> Accounts -> *Withdraw 10,000* -> *Confirm*.",
          "Treasury 90,000, your personal gold +10,000, stability drops a little (withdrawals are unpopular).")
def s32():
    t0, s0 = int(info()["treasury"]), int(info()["stability"])
    g0 = gold()
    panel_press(1, "Accounts", 1)                     # Withdraw 10,000 (asks first)
    confirm()
    lua("Nation_PanelClose()")
    i = info()
    record("treasury", int(i["treasury"]) == t0 - 10000, f"treasury {t0} -> {i['treasury']}")
    record("stability", int(i["stability"]) < s0, f"stability {s0} -> {i['stability']}")
    record("purse", gold() == g0 + 10000, f"personal gold {g0} -> {gold()}")


@setup_of(s32)
def _s32_setup():
    dev("treasury", 100000)
    dev("stability", 60)


@scenario("33", "Withdraw refused - unstable", "10",
          "Treasury 100,000 but stability only 20.",
          "Nation button -> Treasury tab -> Accounts -> *Withdraw 10,000* -> *Confirm*.",
          "Refused (stability below 25): the treasury and your gold stay as they are.")
def s33():
    t0 = int(info()["treasury"])
    panel_press(1, "Accounts", 1)                     # Withdraw 10,000 (asks first)
    first = confirm()
    lua("Nation_PanelClose()")
    t1 = int(info()["treasury"])
    record("refused", t1 == t0 and first[0] == "Not possible", f"treasury {t0} -> {t1}; first card {first}")


@setup_of(s33)
def _s33_setup():
    dev("treasury", 100000)
    dev("stability", 20)


@scenario("34", "Donation refused - too poor", "10",
          "You have only about 5,000 gold of your own.",
          "Nation button -> Treasury tab -> Accounts -> *Donate 10,000*.",
          "Refused ('you do not have 10,000 gold of your own'); the treasury is unchanged.")
def s34():
    t0, g0 = int(info()["treasury"]), gold()
    first = panel_press(1, "Accounts", 0)             # Donate 10,000
    lua("Nation_PanelClose()")
    t1 = int(info()["treasury"])
    record("refused", t1 == t0 and gold() == g0 and first[0] == "Not possible",
           f"treasury {t0} -> {t1}, purse {g0} -> {gold()}; first card {first}")


@setup_of(s34)
def _s34_setup():
    lua(f"Nation_DevGrantGold({5000 - gold()})")    # spend the purse down to 5,000
    if gold() != 5000:
        raise Fail(f"purse is {gold()}, wanted 5,000")


@scenario("35", "Landless nation", "16",
          "Same save as 16 (Margarita capital + Coro).",
          "(Automated) Spain retakes both towns, then the nation gains Coro back by treaty.",
          "After losing everything: message 'governs in exile', the nation still exists without a capital; "
          "its next town becomes the capital.", save=False)
def s35():
    mark = log_mark()
    lua(f"Nation_ReleaseTown({CORO}, 3)\nNation_ReleaseTown({CAPITAL}, 3)")
    i = info()
    msg = re.search(r"MSG .* governs in exile.*", F.log_since(mark))
    record("exile", i.get("founded") == "1" and i.get("towns") == "0" and msg is not None,
           f"info {i}; {msg.group(0) if msg else 'no exile message'}")
    annex_coro()
    i = info()
    record("new-capital", i.get("capital") == str(CORO) and owner_byte(CORO) == 5,
           f"capital {i.get('capital')}, Coro owner byte {owner_byte(CORO)}")


@scenario("36", "Federation keeps calm", "12",
          "Maritime Federation; Coro joined by treaty with loyalty 17, below 20 for a month; "
          "month end in 2 days. (Compare with 14: same town, other government.)",
          "Load and let 3 days pass.",
          "No unrest: a Federation only riots below loyalty 15.")
def s36():
    mark = log_mark()
    run_to_month_end()
    out = F.log_since(mark)
    t = town(CORO)
    record("no-unrest", "Unrest has broken out in Coro" not in out and t.get("unrest") == 0,
           f"Coro {t}")


@setup_of(s36)
def _s36_setup():
    r = lua('Nation_Log("g", Nation_SetGovernment(4))')
    if r.get("g", ["0"])[0] != "1":
        raise Fail(f"Maritime Federation not adopted: {r}")
    annex_coro()
    dev("loyalty", CORO, 17)
    dev("unrest", CORO, 1)


@scenario("37", "Colonial Monarchy upkeep", "12",
          "Colonial Monarchy with one town; month end in 2 days.",
          "Load and let 3 days pass; read the monthly accounts message.",
          "Upkeep is 2,500 instead of 2,000 (a monarchy pays +25% for court and garrisons); the "
          "treasury changes by exactly tax + tariff - 2,500.")
def s37():
    before, after = run_to_month_end()
    expect = before["treasury"] + after["tax"] + after["tariff"] - after["upkeep"]
    record("upkeep", after["upkeep"] == 2500, f"upkeep {after['upkeep']}")
    record("exact", after["treasury"] == expect, f"treasury {before['treasury']} -> {after['treasury']} "
           f"(expected {expect})")


@setup_of(s37)
def _s37_setup():
    r = lua('Nation_Log("g", Nation_SetGovernment(2))')
    if r.get("g", ["0"])[0] != "1":
        raise Fail(f"Colonial Monarchy not adopted: {r}")


@scenario("38", "Upkeep without national convoys", "12",
          "One town, no fleets or towers; month end in 2 days. A convoy could not be made national "
          "(national convoys are removed in this version).",
          "Load and let 3 days pass.",
          "Upkeep exactly 2,000 (the town; no convoy upkeep), navy and forts 0; the treasury changes by exactly "
          "tax + tariff - 2,000.")
def s38():
    n = lua('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["?"])[0]
    record("no-convoys", n == "0", f"Nation_NationalConvoys(1) -> {n}")
    before, after = run_to_month_end()
    expect = before["treasury"] + after["tax"] + after["tariff"] - after["upkeep"]
    record("upkeep", after["upkeep"] == 2000 and after.get("military", 0) == 0,
           f"upkeep {after['upkeep']}, navy and forts {after.get('military')}")
    record("exact", after["treasury"] == expect, f"treasury {before['treasury']} -> {after['treasury']} "
           f"(expected {expect})")


@setup_of(s38)
def _s38_setup():
    n = lua('Nation_Log("c", Nation_NationalConvoys(1))').get("c", ["?"])[0]
    if n != "0":
        raise Fail(f"a national convoy was designated: {n}")


@scenario("39", "Menu while paused", "10",
          "Nation of 10.",
          "Pause the game, press Ctrl+N; unpause, press Ctrl+N again.",
          "While paused nothing opens; after unpausing the nation panel opens normally.", save=False)
def s39():
    session.cmd("call", "0x57EDF0", "0x700500")         # pause
    time.sleep(CLICK)                                   # the call runs on the UI thread's next frame
    mark = log_mark()
    lua("Nation_DevOpenMenu()")
    wait_log(r"DEVMENU|menu event posted", mark, 6)     # the request is taken on the next frame
    time.sleep(1)                                       # ... and nothing opens after it
    out = F.log_since(mark)
    record("paused-ignored", "DEVMENU: ignored" in out and "menu event posted" not in out,
           "menu request ignored while paused" if "DEVMENU: ignored" in out else out[-200:])
    session.cmd("call", "0x57EFD0", "0x700500")         # unpause
    time.sleep(CLICK)
    mark = log_mark()
    lua("Nation_DevOpenMenu()")
    wait_log(r"menu event posted \(handled\)", mark, 6)
    info_ = lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0"])
    record("unpaused-opens", "menu event posted (handled)" in F.log_since(mark) and info_[:1] == ["1"],
           f"after unpausing the menu event opens the panel {info_}")
    lua("Nation_PanelClose()")


@scenario("40", "Two months of accounts", "12",
          "Nation two days before month end with a 10% tariff.",
          "Let about 33 days pass.",
          "Two monthly settlements, each exact: treasury = previous + tax + tariff - upkeep, once per month.")
def s40():
    b1, a1 = run_to_month_end()
    e1 = b1["treasury"] + a1["tax"] + a1["tariff"] - a1["upkeep"]
    b2, a2 = run_to_month_end(limit=420)
    e2 = b2["treasury"] + a2["tax"] + a2["tariff"] - a2["upkeep"]
    record("month1", a1["treasury"] == e1, f"{b1['treasury']} -> {a1['treasury']} (expected {e1}; "
           f"tax {a1['tax']} tariff {a1['tariff']} upkeep {a1['upkeep']})")
    record("month2", a2["treasury"] == e2, f"{b2['treasury']} -> {a2['treasury']} (expected {e2}; "
           f"tax {a2['tax']} tariff {a2['tariff']} upkeep {a2['upkeep']})")
    record("two-settlements", a2["month_day"] != a1["month_day"], f"settlement days {a1['month_day']}, {a2['month_day']}")


@setup_of(s40)
def _s40_setup():
    lua("Nation_SetTariff(10)")


# ------------------------------------------------------- play checkpoints --
# Longer starting points for playing by hand rather than one checked action.
# Their tests only confirm the state survived the save + load.

CARACAS = 55


@scenario("P1", "Young republic", "10",
          "Free Republic of Margarita with two towns (Coro joined by treaty), 300,000 in the treasury, "
          "1,500,000 gold of your own, at peace with everyone.",
          "Free play: trade, set taxes and tariff, commission fleets, court the powers in Diplomacy. "
          "Watch the monthly accounts and the towns' loyalty.",
          "Month by month the treasury follows taxes + tariff - upkeep; low taxes keep loyalty up.")
def sP1():
    i = info()
    record("state", i.get("founded") == "1" and i.get("towns") == "2" and i.get("treasury") == "300000",
           f"nation {i}")
    record("gold", gold() >= 1500000, f"personal gold {gold()}")


@setup_of(sP1)
def _sP1_setup():
    annex_coro()
    dev("treasury", 300000)
    lua("Nation_DevGrantGold(1500000)")


@scenario("P2", "War for Coro", "10",
          "At war with Spain. Your convoy lies in Margarita's harbour with 40 sailors, 200 cutlasses and "
          "200 muskets; you have 2,000,000 gold to buy warships and hire more men.",
          "Strengthen the convoy (shipyard, tavern, weapons dealer), sail west to Coro, attack the town and "
          "win the land battle. Spanish fleets hunt you at sea.",
          "After a victory: popup 'Town Conquered' -> *Annex* makes Coro a town of your nation; "
          "*Withdraw* leaves it Spanish.")
def sP2():
    r = relation(SPAIN)
    record("war", r.get("status") == 4 and war_table(SPAIN) == 1, f"Spain {r}, player_rel {war_table(SPAIN)}")
    record("gold", gold() >= 2000000, f"personal gold {gold()}")


@setup_of(sP2)
def _sP2_setup():
    refresh_towns()
    c, _ = C.pick_convoy()
    C.grant_troops(c)
    lua("Nation_DevGrantGold(2000000)")
    lua(f"Nation_DeclareWar({SPAIN})")


@scenario("P3", "Nation in crisis", "10",
          "Three towns (Margarita, Coro, Caracas), at war with Spain for 120 days, treasury -10,000, "
          "stability 30, Coro restless (loyalty 15, 50% tax); Spain is tired of the war (exhaustion 60). "
          "500,000 gold of your own.",
          "Save the nation: donate to the treasury, cut taxes, offer Spain a ceasefire, then peace.",
          "Without action Coro breaks into unrest at the month end and the treasury sinks further; "
          "a ceasefire stops the Spanish attacks.")
def sP3():
    i = info()
    record("state", i.get("towns") == "3" and i.get("treasury") == "-10000" and i.get("stability") == "30",
           f"nation {i}")
    r = relation(SPAIN)
    record("war", r.get("status") == 4 and war_table(SPAIN) == 1, f"Spain {r}, player_rel {war_table(SPAIN)}")
    record("coro", town(CORO).get("loyalty") == 15, f"Coro {town(CORO)}")


@setup_of(sP3)
def _sP3_setup():
    annex_coro()
    r = lua(f'Nation_Log("a", Nation_Annex({CARACAS}, 1))')
    if r.get("a", ["0"])[0] != "1":
        raise Fail(f"annexing Caracas failed: {r}")
    lua(f"Nation_SetTax({CORO}, 50)")
    dev("loyalty", CORO, 15)
    lua(f"Nation_DeclareWar({SPAIN})")
    dev("exhaustion", SPAIN, 60)
    dev("lastchange", SPAIN, 120)
    dev("treasury", -10000)
    dev("stability", 30)
    lua("Nation_DevGrantGold(500000)")


# ------------------------------------------------------------------ navy --
@scenario("41", "Navy - ready to commission", "10",
          "Nation of 10 with 600,000 in the treasury (a Regional power: 3 fleets).",
          "Nation button -> Navy and defence tab -> National navy -> *Commission fleet*; commission more until refused.",
          "A fleet of the nation is fitted out at Margarita: 120,000 leave the treasury and a military convoy "
          "under your flag lies in Margarita's harbour. More fleets are refused once the rank's limit is reached "
          "('A Regional power can keep at most 3 fleets').")
def s41():
    n0, t0 = navy(), int(info()["treasury"])
    panel_press(5, "National navy", 0)                # Commission fleet
    lua("Nation_PanelClose()")
    ok = wait_fleets(1)
    n1, t1 = navy(), int(info()["treasury"])
    record("commissioned", ok and n1.get("fleets") == 1, f"navy {n0.get('fleets')} -> {n1.get('fleets')} fleets")
    record("paid", t1 == t0 - 120000, f"treasury {t0} -> {t1}")
    while navy().get("fleets", 99) < navy().get("cap", 0):          # fill up to the rank's limit
        lua("Nation_NavyCommission()")
        wait_fleets(navy().get("fleets", 0) + 1, 10)
    n2, t2 = navy(), int(info()["treasury"])
    r = lua('local ok, why = Nation_NavyCommission()\nNation_Log("c", ok, why)').get("c", ["?", ""])
    n3, t3 = navy(), int(info()["treasury"])
    record("limit", r[0] == "0" and "at most" in r[1] and n3.get("fleets") == n2.get("fleets") and t3 == t2,
           f"{n2.get('rank_name')}: {n2.get('fleets')} of {n2.get('cap')} fleets; one more -> {r}; treasury {t2} -> {t3}")
    shot("navy")


@setup_of(s41)
def _s41_setup():
    dev("treasury", 600000)


@scenario("42", "Navy - fleet at month end", "12",
          "Nation two days before month end with one fleet in service and 600,000 in the treasury.",
          "Load and let 3 days pass; read the monthly accounts message.",
          "The accounts list 'navy and forts -6,000'; the treasury changes by exactly tax + tariff - upkeep - 6,000.")
def s42():
    record("fleet", wait_fleets(1, 10), f"navy {navy()}")
    before, after = run_to_month_end()
    expect = before["treasury"] + after["tax"] + after["tariff"] - after["upkeep"] - after.get("military", -1)
    record("military", after.get("military") == 6000, f"navy and forts {after.get('military')}")
    record("exact", after["treasury"] == expect, f"treasury {before['treasury']} -> {after['treasury']} (expected {expect})")


@setup_of(s42)
def _s42_setup():
    dev("treasury", 600000)
    r = lua('local ok, why = Nation_NavyCommission()\nNation_Log("c", ok, why)')
    if r.get("c", ["0"])[0] != "1" or not wait_fleets(1):
        raise Fail(f"commissioning failed: {r}")


@scenario("43", "Navy - recruit and fortify", "10",
          "Nation of 10 with 300,000 in the treasury.",
          "Nation button -> Navy and defence tab -> Defence of Margarita -> *Recruit soldiers*, then *Build tower*.",
          "Recruiting books up to 20,000 gold for soldiers at Margarita (any part the town cannot house is "
          "refunded); a cannon tower is built for 50,000 (or the money comes back if the town cannot build one).")
def s43():
    d0, t0 = defence(CAPITAL), int(info()["treasury"])
    panel_press(5, "Defence of Margarita", 0)         # Recruit soldiers
    d1, t1 = defence(CAPITAL), int(info()["treasury"])
    spent = t0 - t1
    record("recruit", 0 <= spent <= 20000 and d1["budget"] - d0["budget"] == spent,
           f"treasury -{spent}, soldier budget {d0['budget']} -> {d1['budget']} (soldiers {d0['soldiers']})")
    panel_press(5, "Defence of Margarita", 1)         # Build tower
    lua("Nation_PanelClose()")
    d2, t2 = defence(CAPITAL), int(info()["treasury"])
    built = d2["towers"] == d1["towers"] + 1 and t2 == t1 - 50000 and d2["bought"] == d1["bought"] + 1
    refunded = d2["towers"] == d1["towers"] and t2 == t1 and d2["bought"] == d1["bought"]
    record("tower", built or refunded, f"towers {d1['towers']} -> {d2['towers']}, treasury {t1} -> {t2}, "
           f"bought {d1['bought']} -> {d2['bought']} ({'built' if built else 'refunded' if refunded else 'INCONSISTENT'})")
    shot("defence")


@setup_of(s43)
def _s43_setup():
    dev("treasury", 300000)


@scenario("44", "Navy - fleet after reload", "42",
          "Same as 42 (one fleet), saved and loaded again.",
          "Load the save and open Navy & defence.",
          "The fleet is still in service (1 of 1) under the nation's flag.", save=False)
def s44():
    ok = wait_fleets(1, 20)
    raw = lua('Nation_Log("n", Nation_NavyInfo())')
    record("kept", ok, f"navy after load: {navy()} (raw {str(raw)[:200]})")
    log = F.log_since(0)
    record("registered", "re-registered" in log, "the nation's fleet was re-registered after loading")


@scenario("45", "Navy - Spain sends a war fleet", "10",
          "Nation of 10; you declare war on Spain.",
          "Nation button -> Diplomacy tab -> Spain -> *Declare war* -> *Confirm*, then let a few days pass.",
          "Message 'A Spanish war fleet has put to sea against your nation'; one Spanish fleet takes a war "
          "mission against the nation (it sails home, then to one of your towns to besiege it).", save=False)
def s45():
    import milprobe as P
    mark = log_mark()
    lua(f"Nation_DeclareWar({SPAIN})")
    run_to_day_offset(3)
    sent = wait_log(r"NAVY: Spanish fleet ([0-9A-F]+) sent against the nation", mark, 5)
    refused = re.search(r"NAVY: Spanish war mission against the nation refused[^\n]*", F.log_since(mark))
    missions = [r for _, p, r in ((i, p, P.dump(p)) for i, p in P.convoys())
                if r and r["type"] == 9 and r["nation"] == SPAIN and bytes.fromhex(r["raw"])[0x172] == 5]
    record("assigned", sent is not None and len(missions) == 1,
           f"log: {sent.group(0) if sent else refused.group(0) if refused else 'nothing'}; "
           f"Spanish type-9 fleets aimed at the nation: {len(missions)}")
    record("message", "put to sea against your nation" in F.log_since(mark) or sent is not None,
           "the player is warned")


@scenario("46", "Navy - Great power with a fleet", "10",
          "A Great power (Margarita plus towns joined by treaty, 2,000,000 in the treasury) with one fleet. "
          "In the test: order 'War campaign', war with Spain, Coro's garrison down to 20 soldiers.",
          "Nation button -> Navy and defence tab -> *Give this order* on the War campaign card; declare war on Spain; "
          "sail with the fleet to Coro (automated in the test).",
          "The fleet attacks Coro by itself; after the won land assault Coro joins the nation "
          "('The navy of ... has stormed Coro!').")
def s46():
    mark = log_mark()
    r = lua('local ok, why = Nation_NavySetOrder(2)\nNation_Log("o", ok, why)').get("o", ["?"])
    record("order", r[0] == "1", f"Nation_NavySetOrder(war campaign) -> {r}; navy {navy()}")
    lua(f"Nation_DeclareWar({SPAIN})")
    dev("soldiers", CORO, 20)
    r = lua(f'Nation_Log("s", Nation_DevFleetSail({CORO}))').get("s", ["0"])[0]
    record("sails", r == "1", f"Nation_DevFleetSail(Coro) -> {r}")
    attack = conquest = None
    t0 = time.time()
    M.speed_up()
    fast(True)
    import milprobe as P
    try:
        sent = time.time()
        while time.time() - t0 < 420 and not conquest:
            time.sleep(3)
            if attack and time.time() - sent > 75:          # lost (towers): the fleet went home; try again
                lua(f'Nation_Log("s", Nation_DevFleetSail({CORO}))')
                dev("soldiers", CORO, 20)
                sent = time.time()
            if not M.game_alive():
                raise Fail("game exited")
            for _, p in P.convoys():
                d = P.dump(p)
                if d and d["nation"] == 5 and d["type"] in (4, 9):
                    raw = bytes.fromhex(d["raw"])
                    print(f"  [46] t={time.time() - t0:5.0f}s state {d['state']} type {d['type']} town {d['town']:#x} "
                          f"dest {int.from_bytes(raw[0x1B0:0x1B4], 'little'):#x} mask {d['mask']:#x} sailors {d['sailors']}",
                          flush=True)
            out = F.log_since(mark)
            attack = attack or re.search(r"NAVY: fleet [0-9A-F]+ attacks an? Spanish town[^\n]*", out)
            conquest = re.search(r"WAR navy conquest of town 52[^\n]*", out)
    finally:
        fast(False)
    record("attack", attack is not None, attack.group(0) if attack else "the fleet never attacked")
    record("annexed", conquest is not None and "annexed" in conquest.group(0) and town(CORO).get("member") == 1,
           conquest.group(0) if conquest else f"no conquest; log tail: {F.log_since(mark)[-300:]}")
    # the Holland war fix: the fleet's assault is the nation's, not the player's: it costs the player no reputation
    loss = re.findall(r"REP \w+ -[\d.]+ by SubReputation[^\n]*", F.log_since(mark))
    record("no-rep-loss", not loss, f"reputation losses of the player during the assault: {loss[:3] or 'none'}")


@setup_of(s46)
def _s46_setup():
    dev("treasury", 2000000)
    joined = []
    for t in range(60):                              # towns join by treaty until the nation is a Great power
        if navy().get("rank") == 3:
            break
        if t in (CAPITAL, CORO):
            continue
        r = lua(f'Nation_Log("a", Nation_Annex({t}, 1))')
        if r.get("a", ["0"])[0] == "1":
            joined.append(t)
    if navy().get("rank") != 3:
        raise Fail(f"could not reach Great power: {navy()} after annexing {joined}")
    r = lua('local ok, why = Nation_NavyCommission()\nNation_Log("c", ok, why)')
    if r.get("c", ["0"])[0] != "1" or not wait_fleets(1):
        raise Fail(f"commissioning failed: {r}")
    print(f"Great power with towns {joined} and one fleet", flush=True)


@scenario("47", "Navy - raiding order", "46",
          "One fleet under the order 'Raid enemy trade', at war with Spain.",
          "(Automated) Let a few days pass.",
          "The docked fleet is sent to circle a Spanish port and attack Spanish convoys "
          "(log 'raids Spanish shipping'); captured cargo is credited to the treasury when it docks.", save=False)
def s47():
    mark = log_mark()
    r = lua('local ok, why = Nation_NavySetOrder(1)\nNation_Log("o", ok, why)').get("o", ["?"])
    record("order", r[0] == "1", f"Nation_NavySetOrder(raid) -> {r}")
    lua(f"Nation_DeclareWar({SPAIN})")
    run_to_day_offset(2)
    m = re.search(r"NAVY: fleet [0-9A-F]+ raids Spanish shipping[^\n]*", F.log_since(mark))
    record("raid", m is not None, m.group(0) if m else "no raid task issued")
    record("alive", M.game_alive() and not M.crashes(), "the game runs on with the raid task")


@scenario("48", "Navy - pay off a fleet", "46",
          "One fleet in service.",
          "Nation button -> Navy and defence tab -> National navy -> *Pay off a fleet*.",
          "The fleet leaves service: 0 fleets, no more fleet upkeep.", save=False)
def s48():
    record("before", wait_fleets(1, 10), f"navy {navy()}")
    panel_press(5, "National navy", 1)                # Pay off a fleet
    lua("Nation_PanelClose()")
    ok = wait_fleets(0, 30)
    record("paid-off", ok, f"navy after paying off: {navy()}")


@scenario("49", "Navy - Spain retakes a town", "46",
          "A Great power at war with Spain; every town's garrison is down to 15 soldiers.",
          "(Automated) Let Spain's war fleet sail against the nation.",
          "A Spanish war fleet besieges a town of the nation; after its won land assault the town goes back to "
          "Spain ('WAR AI conquest: town ... -> Spain: transferred') and the game runs on.", save=False)
def s49():
    mark = log_mark()
    members = [t for t in range(60) if town(t).get("member") == 1]
    for t in members:
        dev("soldiers", t, 15)
    lua(f"Nation_DeclareWar({SPAIN})")
    sent = won = moved = None
    t0 = time.time()
    M.speed_up()
    fast(True)
    try:
        while time.time() - t0 < 420 and not moved:
            time.sleep(4)
            if not M.game_alive():
                raise Fail("game exited")
            out = F.log_since(mark)
            sent = sent or re.search(r"NAVY: Spanish fleet [0-9A-F]+ sent against the nation[^\n]*", out)
            won = won or re.search(r"WAR AI land assault won at nation town (\d+)[^\n]*", out)
            moved = re.search(r"WAR AI conquest: town (\d+) \([^)]*\) -> Spain: transferred", out)
            if int(time.time() - t0) % 60 < 4:
                for t in members:
                    dev("soldiers", t, 15)              # vanilla keeps recruiting; keep the town weak
    finally:
        fast(False)
    record("mission", sent is not None, sent.group(0) if sent else "no Spanish war fleet sent")
    record("assault", won is not None, won.group(0) if won else "no won land assault within the time")
    if moved:
        t = int(moved.group(1))
        record("transferred", town(t).get("member") == 0 and owner_byte(t) == SPAIN,
               f"{moved.group(0)}; member {town(t).get('member')}, owner byte {owner_byte(t)}")
    else:
        record("transferred", False, "no transfer seen")


def panel_cards():
    n = int((lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0", "0", "0"]) + ["0"])[2] or 0)
    return [lua(f'Nation_Log("c", Nation_PanelCard({i}))').get("c", ["", ""])[0] for i in range(n)]


def panel_rows():
    """The visible list page's rows (Towns, Diplomacy, Navy): [(key, name, [cell1..cell4])]."""
    n = int((lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["0", "0", "0"]) + ["0"])[2] or 0)
    rows = []
    for i in range(n):
        v = lua(f'Nation_Log("r", Nation_PanelRow({i}))').get("r", [])
        if len(v) >= 2 and v[0] != "-1":
            rows.append((int(v[0]), v[1], (v[2:] + [""] * 4)[:4]))
    return rows


def panel_result():
    """The panel's answer to the last press, shaped like the old result card: (caption, text)."""
    v = lua('Nation_Log("f", Nation_PanelFeedback())').get("f", ["0", ""])
    ok, text = v[0], (v[1] if len(v) > 1 else "")
    return ("Please confirm" if ok == "2" else "Done" if ok == "1" and text else "Not possible" if text else "", text)


def panel_key(key, wait=UI):
    lua(f"Nation_PanelClick({key})")
    time.sleep(wait)


def panel_mode(mode):
    lua(f"Nation_PanelMode({mode})")
    time.sleep(UI)


def panel_select_row(match):
    """Select the first row whose name contains match (or whose key satisfies match, if callable)."""
    rows = panel_rows()
    row = next((r for r in rows if (match(r) if callable(match) else match in r[1])), None)
    if row is None:
        raise Fail(f"no row {match!r}: {[(k, n) for k, n, _ in rows]}")
    lua(f"Nation_PanelSelect({row[0]})")
    time.sleep(UI)
    return row


GOV_INDEX = {"Sovereign": 0, "Merchant Republic": 1, "Colonial Monarchy": 2, "Pirate Republic": 3, "Federation": 4}
TREASURY_FINANCE, TOWNS_FOR_SALE, NAVY_FLEETS, NAVY_COMMAND, NAVY_DEFENCE = 1, 1, 0, 1, 2


def panel_press(page, what, slot=0):
    """Open a panel page and do what a player does there for `what` (the old card captions):
    Treasury 'Accounts' (Donate / Withdraw 10,000), 'National tax' (+/-), 'Import tariff' (next);
    Towns 'Buy <town>', 'asks to join'; Diplomacy '<power>' (button 1 / 2); Government '<form>' (Adopt);
    Navy 'National navy' (Commission / Pay off), 'Fleet N' (Next order / Next target),
    'Defence of <town>' (Recruit / Build tower). Returns panel_result()."""
    lua(f"Nation_PanelOpen({page})")
    time.sleep(UI)
    if page == 1:
        panel_mode(TREASURY_FINANCE)
        key = {"Accounts": (3007, 3008), "National tax": (3002, 3001), "Import tariff": (3004, 3003)}
        k = next((v for c, v in key.items() if what.startswith(c)), None)
        if k is None:
            raise Fail(f"no treasury control for {what!r}")
        panel_key(k[slot])
    elif page == 2:
        panel_mode(TOWNS_FOR_SALE)
        if what.startswith("Buy "):
            panel_select_row(what[4:])
        else:
            panel_select_row(lambda r: r[0] >= 100)              # the petitioning town
        panel_key(3102 + slot)
    elif page == 3:
        panel_select_row(what)
        panel_key(3200 + slot)
    elif page == 4:
        g = next((v for c, v in GOV_INDEX.items() if c in what), None)
        if g is None:
            raise Fail(f"no form of government {what!r}")
        lua(f"Nation_PanelMode({g})")
        time.sleep(UI)
        panel_key(3402)                                         # Adopt ...
        panel_key(3402)                                         # ... Confirm reform
    elif page == 5:
        if what == "National navy":
            panel_mode(NAVY_COMMAND)
        elif what.startswith("Defence of "):
            panel_mode(NAVY_DEFENCE)
            panel_select_row(what[len("Defence of "):])
        else:
            panel_mode(NAVY_FLEETS)
            n = int(what.split()[-1])
            rows = panel_rows()
            if len(rows) < n:
                raise Fail(f"no {what}: {rows}")
            lua(f"Nation_PanelSelect({rows[n - 1][0]})")
            time.sleep(UI)
        panel_key(3300 + slot)
    else:
        raise Fail(f"panel_press: page {page}")
    return panel_result()


def fleet_order(n=1):
    """The order shown on fleet n's row of the Navy page (lower case), e.g. 'campaign: coro'."""
    lua("Nation_PanelOpen(5)")
    time.sleep(UI)
    panel_mode(NAVY_FLEETS)
    rows = panel_rows()
    return rows[n - 1][2][0].lower() if len(rows) >= n else ""


@scenario("50", "Peaceful growth - buy, petition, offer", "46",
          "A Great power at peace with Spain (relation 100, recognized), owning property in Coro; Caracas asks to "
          "join; Spain offers a trade agreement.",
          "Panel: Towns -> *Offer ...* on 'Buy Coro'; Towns -> *Accept* on the petition; Diplomacy -> Spain -> "
          "*Accept offer*.",
          "Coro is bought for its price from the treasury (if Spain's roll allows; retried over a few days); the "
          "petitioning town joins with loyalty 70; the trade agreement with Spain is in force.", save=False)
def s50():
    dev("score", SPAIN, 100)
    dev("recognized", SPAIN, 1)
    dev("property", CORO, 1)
    bought = None
    for attempt in range(6):
        t0 = int(info()["treasury"])
        r = panel_press(2, "Buy Coro")
        if town(CORO).get("member") == 1:
            bought = (t0, int(info()["treasury"]), r)
            break
        run_to_day_offset(1)
    record("buy", bought is not None, f"Coro member {town(CORO).get('member')}; treasury {bought[0]} -> {bought[1]}; "
           f"card {bought[2][:1]}" if bought else f"Spain never sold Coro in 6 tries (last card {r[:2]})")

    cand = next((t for t in (55, 50, 53, 26) if town(t).get("member") == 0), None)
    dev("petition", cand)
    r = panel_press(2, "asks to join")
    t = town(cand)
    record("petition", t.get("member") == 1 and t.get("loyalty") == 70, f"town {cand}: {t}; card {r[:1]}")

    dev("offer", ENGLAND)
    r = panel_press(3, "England", 0)
    rel = relation(ENGLAND)
    record("offer", rel.get("status") == 1, f"England {rel}; card {r[:2]}")
    shot("peaceful")


@scenario("51", "Navy - a fleet with its own orders", "46",
          "A Great power with one fleet, at war with Spain; Coro's garrison is down to 5 soldiers.",
          "Navy and defence tab -> Fleet 1 -> *Next order* (guard a town) ... until *War campaign against Coro* "
          "(*Next target* chooses the town).",
          "The fleet takes its own order (shown on its card), sails for Coro by itself and storms it; the order "
          "survives a save and reload.", save=False)
def s51():
    lua(f"Nation_DeclareWar({SPAIN})")
    dev("soldiers", CORO, 5)
    panel_press(5, "Fleet 1", 0)                      # standing -> guard
    b = fleet_order()
    record("guard", "guard" in b, b[:120])
    for _ in range(4):                                # -> raid -> campaign (first enemy town)
        if "campaign" in fleet_order():
            break
        panel_press(5, "Fleet 1", 0)
    for _ in range(40):                               # Next target until Coro
        if "campaign: coro" in fleet_order():
            break
        panel_press(5, "Fleet 1", 1)
    b = fleet_order()
    record("campaign", "campaign: coro" in b, b[:120])
    lua("Nation_PanelClose()")
    mark = log_mark()
    t0 = time.time()
    M.speed_up()
    fast(True)
    conquest = None
    try:
        while time.time() - t0 < 480 and not conquest:
            time.sleep(4)
            if not M.game_alive():
                raise Fail("game exited")
            conquest = re.search(r"WAR navy conquest of town 52[^\n]*", F.log_since(mark))
            if int(time.time() - t0) % 40 < 4:
                dev("soldiers", CORO, 5)              # vanilla keeps recruiting
    finally:
        fast(False)
    attacks = re.findall(r"NAVY: fleet [0-9A-F]+ attacks an? Spanish town[^\n]*", F.log_since(mark))
    days = {}                                         # fleet -> game days of its attacks
    for a in attacks:
        m = re.search(r"fleet ([0-9A-F]+) .*day (\d+)\)", a)
        if m:
            days.setdefault(m.group(1), []).append(int(m.group(2)))
    gaps = [b - a for d in days.values() for a, b in zip(d, d[1:])]
    record("attacks", bool(attacks) and all(g >= 7 for g in gaps),
           f"no fleet attacks twice within 7 days (a beaten fleet goes home first): days {days}")
    adopted = re.findall(r"NAVY: fleet [0-9A-F]+ takes over the order of lost fleet[^\n]*", F.log_since(mark))
    if adopted:
        print(f"  [51] replacement fleets kept the order: {len(adopted)}", flush=True)
    record("stormed", conquest is not None and town(CORO).get("member") == 1,
           conquest.group(0) if conquest else "Coro not taken in time")
    shutil.copy2(env.ENV / "PR2Nation.log", env.HERE / "_build" / "s51_campaign.log")
    # give the fleet a guard order, then save and reload
    for _ in range(4):
        if "guard" in fleet_order():
            break
        panel_press(5, "Fleet 1", 0)
    lua("Nation_PanelClose()")
    session.quicksave()
    M.kill_game()
    session.load("Quick Save", [], EXE)
    log = F.log_since(0)
    found = re.findall(r"NAVY: (\d+) fleet order\(s\) restored", log)
    record("restored", bool(found) and int(found[-1]) >= 1, f"fleet orders restored after loading: {found}")


@scenario("53", "Navy - five new fleets raid at once", "46",
          "A Great power at war with Spain, standing order 'Raid enemy trade', 2,000,000 in the treasury.",
          "Navy and defence tab -> National navy -> *Commission fleet* five times in a row; let a few days pass "
          "and watch the capital's harbour and the sea map.",
          "Each new fleet puts to sea within a few days (log 'NAVY: fleet ... leaves port at Margarita (raid task)') "
          "and circles a Spanish port; none of them stays in the harbour.", save=False)
def s53():
    import milprobe as P
    dev("treasury", 2000000)
    r = lua('local ok, why = Nation_NavySetOrder(1)\nNation_Log("o", ok, why)').get("o", ["?"])
    record("order", r[0] == "1", f"Nation_NavySetOrder(raid) -> {r}")
    lua(f"Nation_DeclareWar({SPAIN})")
    before = navy().get("fleets", 0)
    mark = log_mark()
    lua("for i = 1, 5 do Nation_NavyCommission() end")    # five in a row, as in the report
    ok = wait_fleets(before + 5, 20)
    record("commissioned", ok, f"navy {before} -> {navy().get('fleets')} fleets")

    def ours():
        out = {}
        for _, p in P.convoys():
            d = P.dump(p)
            if d and d["nation"] == 5 and d["type"] in (4, 9):
                raw = bytes.fromhex(d["raw"])
                out[int.from_bytes(raw[0xA8:0xAC], "little")] = raw[0x1C]
        return out
    at_sea = {h: bool(m) for h, m in ours().items()}
    start = finance().get("today", 0)
    M.speed_up()
    fast(True)
    t0 = time.time()
    try:
        while time.time() - t0 < 240 and not all(at_sea.values()):
            time.sleep(3)
            if not M.game_alive():
                raise Fail("game exited")
            for h, m in ours().items():
                at_sea[h] = at_sea.get(h, False) or bool(m)
    finally:
        fast(False)
    days = finance().get("today", start) - start
    log = F.log_since(mark)
    left = set(re.findall(r"NAVY: fleet ([0-9A-F]+) leaves port", log))
    record("at-sea", len(at_sea) >= before + 5 and all(at_sea.values()),
           f"{sum(at_sea.values())}/{len(at_sea)} fleets were at sea within {days} days")
    record("logged", len(left) >= 5, f"'leaves port' logged for {len(left)} fleets")
    trapped = re.findall(r"NAVY: fleet [0-9A-F]+ held in port by a task[^\n]*", log)
    record("no-trap", not trapped, f"tasks cancelled in port: {len(trapped)}")
    shot("raiders")


OFFICIALS = {0: "treasurer", 1: "commander", 2: "building master"}
REFUSED = {0: (1,), 1: (1,), 2: (1, 2)}          # dialog states that mean "reputation too low"


def official(t, kind):
    """Run the official's real enter-dialog code (Nation_DevOfficial) -> (state, npc nation, vanilla tier)."""
    v = lua(f'Nation_Log("o", Nation_DevOfficial({t}, {kind}))').get("o", [])
    v = [int(x) for x in v if re.fullmatch(r"-?\d+", x)]
    if len(v) < 4 or v[0] != 1:
        raise Fail(f"Nation_DevOfficial({t}, {kind}) failed: {v}")
    return v[1], v[2], v[3]


def check_officials(tag, own, foreign):
    names = session.town_names()
    for t in own:
        for k, name in OFFICIALS.items():
            st, nat, tier = official(t, k)
            record(f"{tag}-own-{t}-{k}", st not in REFUSED[k],
                   f"{names[t]} {name}: dialog state {st} (refused = {REFUSED[k]}), asks nation {nat}, "
                   f"vanilla tier {tier}")
    for t in foreign:
        for k, name in OFFICIALS.items():
            st, nat, tier = official(t, k)
            record(f"{tag}-foreign-{t}-{k}", st in REFUSED[k] and tier == 0,
                   f"{names[t]} (Spanish) {name}: dialog state {st}, nation {nat}, tier {tier}: "
                   "still refuses, as in vanilla")


@scenario("52", "Officials serve the sovereign", "10",
          "Nation of Margarita; Coro conquered in a war with Spain and annexed, two more Spanish towns bought / "
          "joined by petition; reputation with Spain 0.",
          "In Coro (or Margarita) visit the treasurer, the commander and the building master; then visit them in "
          "a Spanish town.",
          "In the nation's own towns they serve the player (no 'reputation with Spain too low'); in Spanish towns "
          "they still refuse; the same after a save and reload.", save=False)
def s52():
    lua(f"Nation_DeclareWar({SPAIN})")
    r = lua(f'Nation_Log("a", Nation_Annex({CORO}, 0))')            # 0 = conquest (needs the war)
    if r.get("a", ["0"])[0] != "1":
        raise Fail(f"annexing Coro by conquest failed: {r}")
    spanish = [t for t in (55, 54, 50, 51, 26, 25, 48, 49) if
               lua(f'Nation_Log("n", Town_GetNation(Nation_TownHandle({t})))').get("n", ["-1"])[0] == "3"]
    joined = []
    for t in spanish:                                              # 1 = treaty / purchase, 2 = petition
        if len(joined) < 2 and lua(f'Nation_Log("a", Nation_Annex({t}, {len(joined) + 1}))').get("a", ["0"])[0] == "1":
            joined.append(t)
    foreign = [t for t in spanish if t not in joined][:1]
    if len(joined) < 2 or not foreign:
        raise Fail(f"could not set up the towns: Spanish {spanish}, joined {joined}")
    dev("rep", SPAIN, 0)
    own = [CAPITAL, CORO] + joined
    record("setup", all(town(t).get("member") == 1 for t in own) and owner_byte(CORO) == 5,
           f"own towns {own} (capital, conquest, purchase, petition), Spanish {foreign}, reputation with Spain 0")
    check_officials("live", own, foreign)
    log = F.log_since(0)
    record("hook", "OFFICIALS" in log and "sovereign, full access" in log,
           "; ".join(sorted(set(re.findall(r"OFFICIALS ([^\n]*?) in ", log))))[:250])
    session.quicksave()                                             # QuickSave, then cold reload
    M.kill_game()
    session.load("Quick Save", [], EXE)
    refresh_towns()
    check_officials("reload", own, foreign)


@scenario("54", "Spain threatens war", "10",
          "Margarita's nation at war with England; Spain, the capital's former sovereign, at peace with a relation "
          "of -38 that has not changed for 385 days, reputation 90 (as Holland in the player's game, the Holland war fix).",
          "Let a week pass; open Nation button -> Diplomacy -> Spain. Then make peace with England (here: a "
          "ceasefire) and let another week pass.",
          "Spain does not declare war out of nowhere: first the messages 'Spain may declare war on ...: relations "
          "are unfriendly (-38), and it sees the nation tied up in its war with England' and what its relations drift "
          "towards; the Diplomacy row says 'threat!' and the footer why. No war for at least a month after the "
          "warning. After the ceasefire with England: 'Tension with Spain eases'.")
def s54():
    mark = log_mark()
    run_to_day_offset(8)
    log = F.log_since(mark)
    warn = re.search(r"MSG Spain may declare war on [^\n]*", log)
    why = re.search(r"MSG Improve relations within a month[^\n]*", log)
    r = relation(SPAIN)
    rv = [int(x) for x in lua(f'Nation_Log("r", Nation_GetRelation({SPAIN}))').get("r", []) if re.fullmatch(r"-?\d+", x)]
    record("warning", warn is not None and "tied up in its war with England" in warn.group(0),
           warn.group(0) if warn else f"no warning; log {log[-300:]!r}")
    record("why", why is not None and "former sovereign of the capital -20" in why.group(0),
           why.group(0) if why else "no cause message")
    ai = re.search(r"AI Spain \([^)]*\): [^\n]*-> WARNING[^\n]*", log)
    rel = re.search(r"REL Spain: [^\n]*", F.log_since(0))             # the load's summary line
    record("trace", ai is not None and rel is not None,
           f"{ai.group(0)[:160] if ai else 'no AI line'} / {rel.group(0)[:120] if rel else 'no REL line'}")
    record("still-peace", r.get("status") == 0 and len(rv) >= 5 and rv[4] >= 1 and war_table(SPAIN) == 0,
           f"Spain {r}, threat {rv[4] if len(rv) >= 5 else '?'}, player_rel {war_table(SPAIN)}")
    lua("Nation_PanelOpen(3)")
    time.sleep(UI)
    lua(f"Nation_PanelSelect({SPAIN})")
    time.sleep(1.5)                                   # drawn for the screenshot below
    row = lua(f'Nation_Log("w", Nation_PanelRow({SPAIN}))').get("w", [])
    shot("diplomacy_threat")
    lua("Nation_PanelClose()")
    record("row", any("threat!" in c for c in row), f"Diplomacy row of Spain: {row}")
    mark = log_mark()
    run_to_day_offset(14)
    record("no-war-yet", relation(SPAIN).get("status") == 0 and "Spain has declared war" not in F.log_since(mark),
           f"two weeks after the warning: Spain {relation(SPAIN)}")
    dev("status", ENGLAND, 5)                         # a ceasefire with England: Spain is Commercial again
    mark = log_mark()
    run_to_day_offset(8)
    log = F.log_since(mark)
    eased = re.search(r"MSG Tension with Spain eases[^\n]*", log)
    rv = [int(x) for x in lua(f'Nation_Log("r", Nation_GetRelation({SPAIN}))').get("r", []) if re.fullmatch(r"-?\d+", x)]
    record("eased", eased is not None and len(rv) >= 5 and rv[4] == 0 and relation(SPAIN).get("status") == 0,
           eased.group(0) if eased else f"no 'eases' message; relation {rv}")


@setup_of(s54)
def _s54_setup():
    lua(f"Nation_DeclareWar({ENGLAND})")
    dev("status", SPAIN, 0)
    dev("score", SPAIN, -38)
    dev("recognized", SPAIN, 0)
    dev("rep", SPAIN, 90)
    dev("lastchange", SPAIN, 385)


@scenario("55", "Navy - raids stop at peace", "46",
          "A Great power with a fleet under the order 'Raid enemy trade', at war with Spain; the fleet circles a "
          "Spanish port. In the test a ceasefire with Spain follows.",
          "Raid order, war with Spain, wait until the fleet raids; then agree a ceasefire with Spain "
          "(Diplomacy -> Spain -> Offer ceasefire) and watch the fleet.",
          "The fleet breaks off the raid at once ('Your fleets break off their raids on Spanish shipping: the nation "
          "is not at war with Spain'); its raid task is gone and it attacks no Spanish ship while the ceasefire "
          "lasts (no 'BATTLE national ... AT PEACE' line).", save=False)
def s55():
    import milprobe as P
    r = lua('local ok, why = Nation_NavySetOrder(1)\nNation_Log("o", ok, why)').get("o", ["?"])
    record("order", r[0] == "1", f"Nation_NavySetOrder(raid) -> {r}")
    lua(f"Nation_DeclareWar({SPAIN})")
    mark = log_mark()
    for _ in range(6):
        run_to_day_offset(2)
        if re.search(r"NAVY: fleet [0-9A-F]+ raids Spanish shipping", F.log_since(mark)):
            break
    raid = re.search(r"NAVY: fleet [0-9A-F]+ raids Spanish shipping[^\n]*", F.log_since(mark))
    record("raid", raid is not None, raid.group(0) if raid else "no raid task issued")

    def tasks():
        """the nation's fleets: handle -> (MTask +0x1B8, its target nation +0x1C0)"""
        out = {}
        for _, p in P.convoys():
            d = P.dump(p)
            t = C.mem(p + 0x1B8, 12)
            if d and t and d["nation"] == 5 and d["type"] in (4, 9):
                raw = bytes.fromhex(d["raw"])
                out[int.from_bytes(raw[0xA8:0xAC], "little")] = (int.from_bytes(t[0:4], "little"), t[8])
        return out
    before = tasks()
    mark = log_mark()
    dev("status", SPAIN, 5)                           # ceasefire: player_rel[Spain] = 0
    wait_log(r"MSG Your fleets break off their raids on Spanish shipping", mark, 8)
    time.sleep(1)                                     # the fleets' tasks are cleared on the same pass
    log = F.log_since(mark)
    after = tasks()
    stopped = re.search(r"NAVY: fleet [0-9A-F]+ stops raiding Spanish shipping[^\n]*", log)
    told = re.search(r"MSG Your fleets break off their raids on Spanish shipping[^\n]*", log)
    record("stopped", stopped is not None and told is not None and
           not any(t in (2, 3) and n == SPAIN for t, n in after.values()),
           f"tasks before {before}, after {after}; {stopped.group(0) if stopped else 'no stop line'}; "
           f"{told.group(0) if told else 'no message'}")
    mark = log_mark()
    run_to_day_offset(6)
    log = F.log_since(mark)
    peace = re.findall(r"BATTLE national [^\n]* attacks [^\n]*AT PEACE[^\n]*", log)
    again = re.findall(r"NAVY: fleet [0-9A-F]+ raids Spanish shipping[^\n]*", log)
    record("no-attack", not peace and not again, f"6 days of ceasefire: {len(peace)} attacks on a power at peace "
           f"{peace[:2]}, {len(again)} new raids on Spain")


# ------------------------------------------------------------------ driver --
def quicksave_as(sc):
    qs = session.quicksave()
    SAVES_OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(qs, env.SAVE_DIR / f"{sc.save_name}.pr2")
    shutil.copy2(qs, SAVES_OUT / f"{sc.save_name}.pr2")
    print(f"saved {sc.save_name}.pr2", flush=True)


def start_from(base):
    M.kill_game()
    if base == "new":
        session.newgame([], EXE)
    else:
        b = by_id(base)
        if not (env.SAVE_DIR / f"{b.save_name}.pr2").exists():
            shutil.copy2(SAVES_OUT / f"{b.save_name}.pr2", env.SAVE_DIR / f"{b.save_name}.pr2")
        session.load(b.save_name, [], EXE)
        if not M.game_alive():
            raise Fail(f"loading '{b.save_name}' failed")


def make(sc):
    current["id"] = sc.id
    start_from(sc.base)
    if sc.setup:
        sc.setup()
    quicksave_as(sc)
    record("make", True, f"'{sc.save_name}.pr2'")


def run(sc):
    current["id"] = sc.id
    start_from(sc.id if sc.save else sc.base)
    refresh_towns()                               # town objects moved: owner-byte checks need fresh addresses
    sc.test()
    record("alive", M.game_alive() and not M.crashes(), "no unhandled exception")


def write_ini():
    """Test install only: founding needs 1 ship instead of 10 (scenario 02, manual play)."""
    (env.ENV / "PR2Nation.ini").write_text(
        "; tools/scenarios.py: lower ship requirements so scenario 02 can be founded by hand\n"
        "[Requirements]\nMinGold=5000000\nMinShips=1\nMinWarships=0\n")


# Rows for checks run by other tools (tools/permit_probe.py), listed in SCENARIOS.md with the scenarios.
EXTRA_ROWS = [
    "| NC1 | (a save made with v2026.10.18-79816ea1 that has a national convoy; `tools/t09_probe.py` makes one "
    "from `FNN 12 - Month end in 2 days`) | One town, a convoy of yours designated \"National convoy 1\" by the "
    "older build, month end in 2 days. | Load it with this version; look at the convoy in port and at sea; let "
    "3 days pass. | The convoy has its old name and flies your own flag, in port and at sea; the Navy tab has no "
    "national convoys; the month's upkeep is 2,000 (nothing for the convoy); the next save no longer holds it. "
    "`tools/t09_probe.py`. |",
    "| BP1 | (uses `FNN 22 - At war - troops off Coro`) | At war with Spain, troops off Coro; no building permit in Coro. | Conquer Coro and *Annex* it, enter Coro and open the town info, then the build menu. Let a day pass after selling the permit at the master builder (it pays nothing). | The join message ends 'You may now build there.'; the town info shows the permit as held and building works without buying one; a sold permit is back the next day. `tools/permit_probe.py --part annex` automates the permit checks. |",
    '| BP2 | (uses `FNN 46 - Navy - Great power with a fleet`) | A Great power saved before the permit feature; its towns joined by treaty without a permit. | Load it and open the town info of a member town; release a town (Lua `Nation_ReleaseTown(t, 3)`). | Every member town has the building permit right after loading; a released town goes back to no permit, its buildings stay. `tools/permit_probe.py --part oldsave`. |',
]


def write_doc():
    lines = ["# Scenario saves",
             "",
             "Each scenario is a save in your Save folder named `FNN <id> - <title>`. To play one by hand:",
             "",
             "1. Start the game with the desktop shortcut *Port Royale 2 - Nation (test)* "
             "(`%USERPROFILE%\\PR2-nation-env\\PR2_nation.exe`).",
             "2. Open **Load game** and pick the save.",
             "3. Do what the *Try* column says.",
             "4. Compare what happens with the *Expected* column.",
             "",
             "Saves `FNN 01` to `FNN 40` each test one action. The play checkpoints `FNN P1` to `FNN P3` at the "
             "end of the table are longer starting points to play from: a growing two-town republic, "
             "a war to conquer Coro, and a nation in crisis.",
             "",
             "Load these saves only with `PR2_nation.exe`; the Steam game does not know the fifth nation.",
             "",
             "The automated version of every scenario is `python tools/scenarios.py --run` "
             "(`--only 13,22` runs just those). Rebuild the saves with `--make`. Latest results are in "
             "`SCENARIO_RESULTS.md`.",
             "",
             "| # | Save | State | Try | Expected |",
             "|---|---|---|---|---|"]
    for s in REG:
        save = f"`{s.save_name}`" if s.save else f"(uses `{by_id(s.base).save_name}`)"
        lines.append(f"| {s.id} | {save} | {s.state} | {s.manual} | {s.expect} |")
    lines += EXTRA_ROWS
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--doc", action="store_true")
    ap.add_argument("--build", action="store_true", help="build + deploy first (feature_suite.build)")
    ap.add_argument("--only", help="comma-separated scenario ids")
    a = ap.parse_args()
    write_doc()
    if a.doc and not (a.make or a.run):
        print(f"wrote {DOC}")
        return 0
    only = set(a.only.split(",")) if a.only else None
    backup = env.backup_saves()
    try:
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        if a.build:
            F.build()
        write_ini()
        (env.ENV / "PR2Nation.dev").write_text("test install\n")
        if a.make:
            for sc in REG:
                if sc.save and (only is None or sc.id in only):
                    try:
                        make(sc)
                    except (Fail, C.Stall, SystemExit) as e:
                        record("make", False, f"{type(e).__name__}: {e}")
                    except Exception:
                        record("make", False, traceback.format_exc(limit=3).replace("\n", " "))
        if a.run:
            for sc in REG:
                if only is None or sc.id in only:
                    try:
                        run(sc)
                    except (Fail, C.Stall, SystemExit) as e:
                        current["id"] = sc.id
                        record("run", False, f"{type(e).__name__}: {e}")
                    except Exception:
                        current["id"] = sc.id
                        record("run", False, traceback.format_exc(limit=3).replace("\n", " "))
    finally:
        M.kill_game()
        session.restore_options()
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig_cfg = env.BACKUPS / "settings.cfg.orig"
        if orig_cfg.exists():
            shutil.copy2(orig_cfg, env.SAVE_DIR / "settings.cfg")
        print(f"restored your saves from {backup} (FNN scenario saves left in place)")
    REPORT.write_text("# Scenario run " + time.strftime("%Y-%m-%d %H:%M")
                      + f"\n\nArgs: `{' '.join(sys.argv[1:])}`\n\n| Check | Result | Detail |\n|---|---|---|\n"
                      + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {str(d).replace('|', '/')[:300]} |\n"
                                for t, ok, d in results), encoding="utf-8")
    failed = [t for t, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
