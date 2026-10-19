"""Feature acceptance suite (M1-M5): the spec's §15 tests, in-game, in the background.

    python tools/feature_suite.py [--days N]

Builds the DLL and the full patch set, deploys them to the test install, starts
a new game and drives the feature through the Nation_* Lua API (dev console),
checking game memory and the API's answers. The user's Save folder and
settings are backed up first and always restored. Report: FEATURE_RESULTS.md.
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import console  # noqa: E402
import env  # noqa: E402
import m0_suite as M  # noqa: E402
import session  # noqa: E402

BUILD = env.HERE / "_build" / "feature" / "PR2_nation.exe"
REPORT = env.HERE / ("UI_RESULTS.md" if "--ui-only" in sys.argv else "FEATURE_RESULTS.md")
CAPITAL = 56              # Margarita (start town, Spanish governor seat)
SPAIN = 3
UI = 0.3                  # after a panel API call (the panel acts at once and redraws on the next frame)
CLICK = 0.6               # after a click injected by gamehost (over the next 3 frames)
results = []


def record(test, ok, detail):
    results.append((test, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<8} {detail}", flush=True)


def lua(code):
    """Run Lua in the game; return {label: [values]} from Nation_Log lines."""
    text = console.run(code)                          # in-process: no Python start per call
    out = {}
    for line in text.splitlines():
        m = re.search(r"LUA: (.*)", line)
        if m:
            parts = [x.strip() for x in m.group(1).split("|")]
            out[parts[0]] = parts[1:]
    if "LUA error" in text:
        out["__error__"] = [text]
    return out


def mem_u8(addr):
    out = session.cmd("read", f"{addr:#x}", "1")
    m = re.search(r": ([0-9a-f]{2})", out)
    return int(m.group(1), 16) if m else None


def run_days(n):
    """Run the simulation at 20x until n game days have passed (or timeout)."""
    start = int(lua('Nation_Log("d", Nation_GetFinance())')["d"][6])
    M.speed_up()
    # the game's own fast-forward (0x57F570(1)): 8 ms per sim tick instead of
    # 40 ms at 20x, still capped at 8 ticks per frame -> ~5x faster again
    session.cmd("call", "0x57F570", "0x700500", "1")
    t0 = time.time()
    try:
        while time.time() - t0 < 60 * 12:
            time.sleep(1)
            if M.crashes() or not M.game_alive():
                return False
            now = int(lua('Nation_Log("d", Nation_GetFinance())').get("d", [0] * 7)[6] or start)
            if now - start >= n:
                return True
        return False
    finally:
        session.cmd("call", "0x57F570", "0x700500", "0")    # back to 20x before saving


def build():
    for cmd in ([HERE.parent / "dll" / "tests" / "run_tests.py"], [HERE.parent / "dll" / "build.py"]):
        code, tail = M.run(*cmd)
        record(Path(cmd[0]).stem, code == 0, tail[0])
    args = [HERE / "pe_patch.py", BUILD]
    for p in sorted((env.HERE / "patches").glob("p0*.py")):
        args += ["--patch-module", p]
    code, tail = M.run(*args)
    record("BUILD", code == 0, tail[0])
    env.deploy(BUILD)
    (env.ENV / "PR2Nation.dev").write_text("test install: enables Nation_Dev* and the PR2Nation.cmd console\n")
    if not (env.HERE / "data" / "nation_flags" / "flag_000.bmp").exists():
        M.run(env.HERE / "art" / "make_logos.py")
    data = env.HERE / "data"
    if data.exists():                                 # loose-file overrides (UI script)
        for f in data.rglob("*"):
            if f.is_file() and f.name != "README.md":
                dst = env.ENV / f.relative_to(data)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)


LOG = env.ENV / "PR2Nation.log"


def log_since(pos):
    data = LOG.read_bytes() if LOG.exists() else b""
    return data[pos:].decode("latin-1")


def ui_checks():
    """The nation menu is the panel: the menu event and the top-bar button open it."""
    import screen
    r = lua('Nation_Log("m", GLOBALS.FNN_MISSION, FNN_Guard ~= nil)')
    record("UI-01", r.get("m", ["?"])[0] == "1",
           f"nation mission exists after load (GLOBALS.FNN_MISSION={r.get('m')})")
    pos = LOG.stat().st_size
    lua("Nation_DevOpenMenu()")
    out = wait_log(r"menu event posted", pos, 8)
    time.sleep(UI)
    info = panel_info()
    record("UI-02", "(handled)" in out and info[:1] == ["1"],
           f"menu event {'handled' if '(handled)' in out else 'NOT handled'} -> panel open {info}")
    shot("ui_panel")
    lua("Nation_PanelClose()")
    time.sleep(UI)
    # the nation button in the top bar, clicked like a player (twice: open, then close)
    ok, x, y = gui_center("TMB_Nation")
    opened = closed = None
    if ok:
        session.cmd("click", str(x), str(y))
        opened = wait_panel("1")
        shot("ui_topbar_open")
        session.cmd("click", str(x), str(y))
        closed = wait_panel("0")
    record("UI-03", ok and opened[:1] == ["1"] and closed[:1] == ["0"],
           f"top-bar nation button at {x},{y}: open {opened}, then closed {closed}")
    r = lua('Nation_Message("Sovereign Nations: message test")\nNation_Log("msg", 1)')
    time.sleep(2)                                     # the ticker shows it, for the screenshot
    shot("ui_message")
    record("UI-04", "msg" in r, "ticker message queued (see _build/shots/ui_message.png)")


def scenario(days):
    M.kill_game()
    session.newgame([], "PR2_nation.exe")

    r = lua(f'local ok, why = Nation_CanFound({CAPITAL})\nNation_Log("can", ok, why)')
    record("FND-01", r.get("can", ["?"])[0] == "0" and "gold" in r["can"][1].lower(),
           f"default requirements block founding: {r.get('can')}")

    spain_before = lua('Nation_Log("n", Nation_GetNumTowns(3))')["n"][0]
    r = lua(f'''Nation_DevSetRequirements(10000, 1, 0)
local ok, why = Nation_Found({CAPITAL}, "Free Republic of Margarita", "Margaritan", 0, 0)
Nation_Log("found", ok, why)
Nation_Log("info", Nation_GetInfo())
Nation_Log("town", Nation_GetTown({CAPITAL}))
Nation_Log("spain", Nation_GetNumTowns(3))''')
    info = r.get("info", [])
    record("FND-02", r.get("found", ["0"])[0] == "1" and info[:2] == ["1", "Free Republic of Margarita"]
           and r["town"][0] == "1" and int(r["spain"][0]) == int(spain_before) - 1,
           f"founded={r.get('found')} info={info[:4]} Spain towns {spain_before}->{r.get('spain')}")

    r = lua(f'local ok, why = Nation_Found({CAPITAL}, "Second", "S", 0, 0)\nNation_Log("again", ok, why)')
    record("FND-03", r.get("again", ["?"])[0] == "0", f"second founding rejected: {r.get('again')}")

    r = lua(f'''local before = Nation_GetNumTowns(3)
local cand = {{ 52, 26, 0 }}   -- Spanish towns (Coro, Trinidad, Corpus Christi); viceroy seats refuse
local i = 1
local got = -1
while cand[i] ~= nil and got < 0 do
  if Nation_Annex(cand[i], 1) == 1 then got = cand[i] end   -- 1 = treaty (0 = conquest needs a war)
  i = i + 1
end
Nation_Log("annex", got, before, Nation_GetNumTowns(3), Nation_GetInfo())
if got >= 0 then
  Nation_Log("mem", Nation_GetTown(got))
  Nation_Log("rel", Nation_ReleaseTown(got, 3), Nation_GetNumTowns(3))
  Nation_Log("after", Nation_GetTown(got))
end''')
    a = r.get("annex", ["-1", "0", "0"])
    record("TER-02", a[0] != "-1" and int(a[2]) == int(a[1]) - 1 and r.get("mem", ["0"])[0] == "1" and r.get("rel", ["0"])[0] == "1"
           and r.get("after", ["1"])[0] == "0",
           f"annex town {a[0]} (Spanish towns {a[1]}->{a[2]}, nation towns {a[9] if len(a) > 9 else '?'}), "
           f"release back {r.get('rel')}, member after {r.get('after', ['?'])[0]}")

    r = lua('''Nation_DevGrantGold(20000)
Nation_Log("don", Nation_Donate(5000))
Nation_SetTax(-1, 15)
Nation_Log("fin", Nation_GetFinance())
Nation_Log("info", Nation_GetInfo())''')
    record("ECO-00", r.get("don", ["0"])[0] == "1" and r["fin"][0] == "5000" and r["info"][7] == "15",
           f"donation 5000 -> treasury {r.get('fin', ['?'])[0]}, default tax {r.get('info', ['?']*8)[7]}%")

    r = lua(f'Nation_Log("war", Nation_DeclareWar({SPAIN}))\nNation_Log("rel", Nation_GetRelation({SPAIN}))')
    table = mem_u8(0x9F7000 + SPAIN)
    record("DIP-01", r.get("war", ["0"])[0] == "1" and r["rel"][0] == "4" and table == 1,
           f"declare war on Spain: api={r.get('war')} status={r.get('rel', ['?'])[0]} player_rel[Spain]={table}")

    r = lua('''local ok, why = Nation_SetGovernment(1)
Nation_Log("gov1", ok, why)
Nation_Log("get", Nation_GetGovernment())
local ok2, why2 = Nation_SetGovernment(3)
Nation_Log("gov2", ok2, why2)''')
    record("GOV-01", r.get("gov1", ["0"])[0] == "1" and r.get("get", ["?"])[0] == "1"
           and r.get("gov2", ["1"])[0] == "0",
           f"Merchant Republic adopted {r.get('gov1')}, now {r.get('get')}, immediate re-change refused {r.get('gov2')}")

    r = lua('for p = 0, 3 do Nation_Log("s" .. p, Nation_GetStrategy(p)) end')
    strats = [r.get(f"s{p}", ["?"])[0] for p in range(4)]
    record("AI-01", all(s in ("0", "1", "2", "3") for s in strats),
           f"AI strategies per power: {[r.get(f's{p}', ['?'])[-1] for p in range(4)]}")

    fin0 = lua('Nation_Log("f", Nation_GetFinance())')["f"]
    ok = run_days(days)
    fin1 = lua('Nation_Log("f", Nation_GetFinance())')["f"]
    settled = int(fin1[4]) > int(fin0[4])
    expect = int(fin0[0]) + int(fin1[1]) + int(fin1[3]) - int(fin1[2])
    record("ECO-01", ok and settled and int(fin1[1]) > 0,
           f"{days} days: month settled={settled}, tax {fin1[1]}, tariff {fin1[3]}, upkeep {fin1[2]}")
    record("ECO-02", ok and settled and int(fin1[0]) == expect,
           f"treasury {fin0[0]} -> {fin1[0]} (expected {expect}: +tax +tariff -upkeep once)")

    r = lua(f'local ok, why = Nation_Propose({SPAIN}, 5)\nNation_Log("cf", ok, why)\nNation_Log("rel", Nation_GetRelation({SPAIN}))')
    status = r.get("rel", ["?"])[0]
    table = mem_u8(0x9F7000 + SPAIN)
    record("DIP-02", (status in ("4",) and table == 1) or (status in ("5", "0") and table == 0),
           f"ceasefire proposal {r.get('cf')}: status {status}, player_rel[Spain]={table} (consistent)")

    pre = lua('Nation_Log("info", Nation_GetInfo())\nNation_Log("rel", Nation_GetRelation(3))\nNation_Log("fin", Nation_GetFinance())')
    session.quicksave()
    M.kill_game()
    session.load("Quick Save", [], "PR2_nation.exe")
    post = lua('Nation_Log("info", Nation_GetInfo())\nNation_Log("rel", Nation_GetRelation(3))\nNation_Log("fin", Nation_GetFinance())')
    same = all(pre.get(k, [])[:4] == post.get(k, [])[:4] for k in ("info", "rel")) and \
        pre.get("fin", [None])[0] == post.get("fin", [None])[0]
    table = mem_u8(0x9F7000 + SPAIN)
    want = 1 if post.get("rel", ["?"])[0] == "4" else 0
    record("SAV-02", same and table == want,
           f"after QuickSave/restart/load: info {post.get('info', [])[:3]}, Spain status {post.get('rel', ['?'])[0]}, "
           f"player_rel restored={table == want}")
    ui_checks()
    ui_pages()
    alive = M.game_alive() and not M.crashes()
    record("REG-02", alive, "no unhandled exception during the whole run")


def info():
    r = lua('Nation_Log("i", Nation_GetInfo())\nNation_Log("c", Nation_NationalConvoys())')
    return r.get("i", ["?"] * 9), r.get("c", ["?"])[0]


def shot(name):
    import screen
    try:
        screen.shot(name)
    except Exception as e:                            # screenshots are informational
        print("screenshot failed:", e)


def panel_info():
    return lua('Nation_Log("i", Nation_PanelInfo())').get("i", ["?", "?", "0"])


def wait_panel(is_open, limit=6):
    """Nation_PanelInfo once the panel is open ("1") or closed ("0"), or after `limit` s."""
    t0 = time.time()
    time.sleep(CLICK)
    info_ = panel_info()
    while info_[:1] != [is_open] and time.time() - t0 < limit:
        time.sleep(0.3)
        info_ = panel_info()
    return info_


def wait_log(pattern, pos, limit):
    """PR2Nation.log after byte offset pos, once `pattern` is in it (or after `limit` s)."""
    t0 = time.time()
    out = log_since(pos)
    while not re.search(pattern, out) and time.time() - t0 < limit:
        time.sleep(0.25)
        out = log_since(pos)
    return out


def to_window(x, y):
    """Layout pixels (1024x768, CDrawable::AbsPos) -> the test window's client pixels."""
    import screen
    cw, ch = screen.client_size(screen.game_window())
    return int(x * cw / 1024), int(y * ch / 768)


def gui_center(name):
    r = lua(f'Nation_Log("r", Nation_DevGuiRect("{name}"))').get("r", ["0"] * 5)
    if r[0] != "1":
        return False, 0, 0
    x, y = to_window(int(r[1]) + int(r[3]) // 2, int(r[2]) + int(r[4]) // 2)
    return True, x, y


def click_ctl(name):
    """Click a named panel control like a player (gamehost click at its centre)."""
    ok, x, y = gui_center(name)
    if ok:
        session.cmd("click", str(x), str(y))
        time.sleep(CLICK)
    print(f"  click {name}: {'at %d,%d' % (x, y) if ok else 'not found'}", flush=True)
    return ok


def click_row(key):
    """Click a list row of the visible panel page (its name cell) like a player."""
    r = lua(f'Nation_Log("r", Nation_DevPanelRow({key}))').get("r", ["0"] * 5)
    if r[0] != "1":
        return False
    x, y = to_window(int(r[1]) + int(r[3]) // 2, int(r[2]) + int(r[4]) // 2)
    session.cmd("click", str(x), str(y))
    time.sleep(CLICK)
    return True


def panel_feedback():
    v = lua('Nation_Log("f", Nation_PanelFeedback())').get("f", ["0", ""])
    return v[0], (v[1] if len(v) > 1 else "")


def ui_pages():
    """UI-05..08: the Treasury and Towns pages' controls, clicked like a player; the Overview after a petition."""
    i0, _ = info()
    lua("Nation_PanelOpen(1)")
    time.sleep(UI)
    lua("Nation_PanelMode(0)")                                # start on the balance, as a player finds it
    time.sleep(UI)
    ok = click_ctl("FNT_kredite") and click_ctl("FNT_Donate")  # Taxes and finances, Donate 10,000
    i1, _ = info()
    shot("ui_donated")
    record("UI-05", ok and int(i1[4]) == int(i0[4]) + 10000,
           f"Treasury: Taxes and finances -> Donate 10,000 -> treasury {i0[4]} -> {i1[4]}")

    ok = click_ctl("FNT_TariffNext")                          # the next import tariff
    i2, _ = info()
    shot("ui_tariff")
    record("UI-06", ok and i2[8] != i1[8], f"Treasury: import tariff arrow -> tariff {i1[8]}% -> {i2[8]}%")

    lua("Nation_PanelOpen(2)")
    time.sleep(UI)
    lua("Nation_PanelMode(0)")
    time.sleep(UI)
    ok = click_row(CAPITAL) and click_ctl("FNW_TaxInc")       # select the capital, raise its tax
    fb = panel_feedback()
    shot("ui_town_tax")
    record("UI-07", ok and fb[0] == "1" and "The tax in" in fb[1], f"Towns: capital row, tax + -> {fb}")
    ui_petition_overview()
    lua("Nation_PanelClose()")


def flag_drawn(img, name):
    """the panel image control `name` shows the nation's flag Run\\7.bmp (mean pixel difference)"""
    from PIL import Image, ImageChops, ImageStat
    r = lua(f'Nation_Log("r", Nation_DevGuiRect("{name}"))').get("r", ["0"] * 5)
    if r[0] != "1":
        return False, f"{name} not found"
    x0, y0 = to_window(int(r[1]), int(r[2]))
    x1, y1 = to_window(int(r[1]) + int(r[3]), int(r[2]) + int(r[4]))
    c = img.crop((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))).convert("RGB")
    flag = Image.open(env.RUN_DIR / "7.bmp").convert("RGB").resize(c.size)
    d = sum(ImageStat.Stat(ImageChops.difference(c, flag)).mean) / 3
    return d < 45, f"{name} off the flag {d:.0f}"


def ui_petition_overview():
    """UI-08 (the overview page fix): a town asks to join, Towns -> Towns for sale -> Accept, then the Overview page
    (created anew): the nation's flag in the Name row and over its column. Probe screenshot."""
    import screen
    cand = next((t for t in (52, 55, 50, 53, 26) if lua(f'Nation_Log("t", Nation_GetTown({t}))').get("t", ["1"])[0] == "0"), None)
    lua(f'Nation_Log("d", Nation_DevSet("petition", {cand}))')
    lua("Nation_PanelOpen(2)")
    time.sleep(UI)
    lua("Nation_PanelMode(1)")                                # Towns for sale: the petition's row
    time.sleep(UI)
    lua(f"Nation_PanelSelect({100 + cand})")
    time.sleep(UI)
    lua("Nation_PanelClick(3102)")                            # Accept
    time.sleep(UI)
    joined = lua(f'Nation_Log("t", Nation_GetTown({cand}))').get("t", ["0"])[0] == "1"
    lua("Nation_PanelOpen(0)")
    time.sleep(2.5)                                           # the Overview drawn with its flags for the screenshot
    path = None
    try:
        path = screen.shot("ui_overview_after_petition")
    except Exception as e:
        print("screenshot failed:", e)
    from PIL import Image
    a = flag_drawn(Image.open(path), "FNO_Flag") if path else (False, "no screenshot")
    b = flag_drawn(Image.open(path), "FNO_ColFlag") if path else (False, "no screenshot")
    record("UI-08", joined and a[0] and b[0], f"town {cand} joined by petition: {joined}; Overview: {a[1]}, {b[1]} "
           "(_build/shots/ui_overview_after_petition.png)")


def ui_only():
    """Quick UI run: new game, found, open the menu (no month simulation)."""
    M.kill_game()
    session.newgame([], "PR2_nation.exe")
    r = lua(f'''Nation_DevSetRequirements(10000, 1, 0)
local ok, why = Nation_Found({CAPITAL}, "Free Republic of Margarita", "Margaritan", 0, 0)
Nation_Log("found", ok, why)''')
    record("FND-02", r.get("found", ["0"])[0] == "1", f"founded {r.get('found')}")
    lua("Nation_DevGrantGold(50000)")
    ui_checks()
    ui_pages()


def main():
    days = next((int(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--days"), 31)
    backup = env.backup_saves()
    try:
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        build()
        try:
            ui_only() if "--ui-only" in sys.argv else scenario(days)
        except SystemExit as e:                       # harness abort: still write the report
            record("RUN", False, f"aborted: {e}")
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
        print(f"restored the Save folder from {backup}")
    REPORT.write_text("# Feature acceptance run " + time.strftime("%Y-%m-%d %H:%M")
                      + "\n\n| Test | Result | Detail |\n|---|---|---|\n"
                      + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {d} |\n" for t, ok, d in results))
    failed = [t for t, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
