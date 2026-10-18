"""Screenshot every vanilla PR2 window and tab (and the mod's nation panel) for the UI design work.

    python tools/ui_gallery.py [--save NAME] [--only PREFIX ...] [--hold]

Takes the shared test-install lock (env.LOCK, %USERPROFILE%\\PR2-nation-env.lock) like sight_probe.py,
deploys this worktree's PR2Nation.dll + data/ into the env, loads a save in the small corner
window (gamehost: no focus, no real mouse) and opens each window in turn with the dev-only
Lua functions Nation_DevMenu / Nation_DevTabs / Nation_DevSelectTab (dll/api.c), which call
the game's own CGameMenu::Open* functions (this = *(app+0xEC)) and CTabControl::SelectTab.
Each window/tab is saved as docs/ui_gallery/<window>__<page>.jpg (1280x800 client, q85) and
docs/ui_gallery/INDEX.md lists them. Saves, settings.cfg and the Run logos are restored after.

--hold   load the save, then keep the game (and the lock) until _build/ui_gallery.stop appears
         (for exploring with console.py / cmd.py by hand)
--only   only the steps whose window name starts with one of these prefixes
"""
import argparse
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402
import session  # noqa: E402
import feature_suite as F  # noqa: E402

LOCK = env.LOCK                      # the shared test-install lock (setting SN_TEST_LOCK)
OUT = env.HERE / "docs" / "ui_gallery"
STOP = env.HERE / "_build" / "ui_gallery.stop"
DEFAULT_SAVE = "FNN 46 - Navy - Great power with a fleet"
captured = []          # (file, window, page, how, screen)
missed = []            # (window, page, why)


def L(code):
    return F.lua(code)


def ints(v):
    return [int(x) for x in v if re.fullmatch(r"-?\d+", x)]


# ---- CGameMenu (gm) windows: name, Open* VA, args, gm field of the window, tab ids, main .screen ----
# All found statically in PR2_target.exe (each Open* starts with `if (gm+field) return;
# CloseAllMenus(0)`, see the INDEX for how each was found).
LOG_TABS = [(0x111, "messages"), (0x222, "missions"), (0x333, "company"), (0x444, "balance"),
            (0x555, "problems"), (0x666, "successes"), (0x777, "trade_route"), (0x888, "map_pieces")]
CHRONICLE_TABS = [(0x99, "events"), (0xAA, "nations"), (0xBB, "pirates"), (0xFF, "town_list"),
                  (0xCC, "town_statistics"), (0xDD, "population_statistics"), (0xEE, "goods_statistics")]


def ensure_dirs():
    OUT.mkdir(parents=True, exist_ok=True)


def shot(window, page, how, screen=""):
    """Capture the game window into docs/ui_gallery/<window>__<page>.jpg."""
    import screen as S
    from PIL import Image
    session.cmd("move", 5, 595)                             # park the cursor: no hover tooltips
    time.sleep(0.8)
    try:
        png = S.shot(f"gallery_{window}__{page}")
    except Exception as e:
        missed.append((window, page, f"screenshot failed: {e}"))
        return None
    dst = OUT / f"{window}__{page}.jpg"
    Image.open(png).convert("RGB").save(dst, "JPEG", quality=85)
    captured.append((dst.name, window, page, how, screen))
    print(f"  shot {dst.name}", flush=True)
    return dst


def gm_fields():
    """All CGameMenu window slots gm+0x40..gm+0x1A0 in one console run: {offset: pointer}."""
    r = L('local s = "" for o = 64, 416, 4 do s = s .. Nation_DevMenuField(o) .. "," end Nation_Log("g", s)')
    v = (r.get("g") or [""])[0].split(",")
    return {64 + 4 * i: int(x) for i, x in enumerate(v) if re.fullmatch(r"-?\d+", x)}


def new_window(before):
    """The gm slot that went from 0 to a window since `before` (the window just opened)."""
    after = gm_fields()
    new = [o for o, p in after.items() if p and not before.get(o) and o != 0x14C]
    return new[0] if new else None


def field(off):
    v = ints(L(f'Nation_Log("f", Nation_DevMenuField({off}))').get("f", []))
    return v[0] if v else 0


def close_all():
    L("Nation_DevCloseMenus()")
    time.sleep(1.0)


def open_menu(va, args=(), on_vc=0, wait=2.5):
    a = list(args) + [0] * (3 - len(args))
    L(f"Nation_DevMenu({va}, {len(args)}, {a[0]}, {a[1]}, {a[2]}, {on_vc})")
    time.sleep(wait)


def tabs(off):
    v = ints(L(f'Nation_Log("t", Nation_DevTabs({off}))').get("t", []))
    if len(v) < 2:
        return -1, []
    n, cur = v[0], v[1]
    return cur, [(v[2 + 2 * i], v[3 + 2 * i]) for i in range(n)]


def select_tab(off, tid, wait=2.0):
    L(f"Nation_DevSelectTab({off}, {tid})")
    time.sleep(wait)


def tabbed(window, va, off, names=None, args=(), screen="", how=None, on_vc=0, sub=None):
    """Open a tabbed window and shoot every radio tab."""
    close_all()
    before = gm_fields() if off is None else None
    open_menu(va, args, on_vc)
    if off is None:
        off = new_window(before)
        if off is None:
            shot(window, "main", how or f"Nation_DevMenu({va:#x})", screen)
            return
        print(f"  {window}: window at gm+{off:#x}", flush=True)
    if not field(off):
        missed.append((window, "*", f"did not open (gm+{off:#x} stays 0 after {va:#x})"))
        return
    cur, tl = tabs(off)
    print(f"{window}: tabs {[(hex(i), r) for i, r in tl]} current {cur:#x}", flush=True)
    if names and not isinstance(names[0], tuple):          # positional labels, in tab order
        names = list(zip([i for i, r in tl if r], names))
    names = dict(names or [])
    how = how or f"Nation_DevMenu({va:#x}) = CGameMenu::Open*; tabs via CTabControl::SelectTab (gm+{off:#x})"
    radio = [i for i, r in tl if r] or [cur]
    for i, tid in enumerate(radio):
        if tid != cur:
            select_tab(off, tid)
            cur = tid
        page = names.get(tid, f"tab{i + 1}_{tid:#x}")
        shot(window, page, how + f", tab {i + 1} (id {tid:#x})", screen)
        if sub and page in sub:                             # a sub-view reached by a click on this tab
            sub[page]()
    actions = [i for i, r in tl if not r]
    if actions:
        print(f"  {window}: action tabs not clicked: {[hex(a) for a in actions]}", flush=True)


def single(window, page, va, off, args=(), screen="", on_vc=0, how=None):
    close_all()
    open_menu(va, args, on_vc)
    if off is not None and not field(off):
        missed.append((window, page, f"did not open (gm+{off:#x} stays 0 after {va:#x})"))
        return False
    shot(window, page, how or f"Nation_DevMenu({va:#x})", screen)
    return True


def click(x, y, wait=2.0):
    """A click posted to the game window by gamehost (client pixels of the 1280x800 shot)."""
    session.cmd("click", x, y)
    time.sleep(wait)


def click_control(name, wait=2.0):
    """Click a named UI control (CWindowManager::FindDrawable) through gamehost."""
    ok, x, y = F.gui_center(name)
    if ok:
        click(x, y, wait)
    return ok


def vc_building(kind, handle):
    """The town view's building-click dispatcher 0x516AA0(kind, handle): what a click on a building does."""
    return dict(va=0x516AA0, args=(kind, handle), on_vc=1)


# ---- the gallery ----------------------------------------------------------------------------
# Building kinds (low byte of the dispatcher's first argument) and the handles of buildings in
# Margarita in the default save, found by click-scanning the town view with a breakpoint on
# 0x516AA0 (tools/ui_gallery.py --hold + gamehost `bp 0x516AA0=esp+4:4,esp+8:4`).
HOUSE, FACTORY = (0x13, 0x2E001D), (0x09, 0x2E0013)   # also seen: 0x15 house 0x2E0017, 0x1A 0x2E0008 (town info)
WAREHOUSE_KIND, PALACE_KIND = 22, 35        # Global_CreateBuilding kinds (0x16 warehouse, 0x23 palace)
CAPITAL = 56                                 # Margarita

# window -> main .screen files (scripts/*.screen; from the strings each Open*/page Create loads)
SCREENS = {
    "log": "TAB_CONTROL; pages NACHRICHTEN_LISTE+NACHRICHTEN_EINTRAG (messages, missions), UNTERNEHMEN_PAGE, "
           "BILANZ_PAGE (+BILANZ_INFO_PAGE, BILANZ_KREDITE/BILANZ_KREDIT_ZEILE), PRODUKTION_PAGE+PRODUKTIONS_EINTRAG, "
           "ERFOLGSPAGE (+ERFOLGSPAGE_ARTEFAKTE), HANDELSROUTEN_PAGE, SCHATZKARTEN_PAGE",
    "chronicle": "TAB_CONTROL; pages CHRONIK_ENTRIES+CHRONIK_EINTRAG, NATION_PAGE, CHRONIK_PIRATEN+PIRATEN_EINTRAG, "
                 "STATISTIC_PAGE (3 tabs), STAEDTE_PAGE+STADT_ENTRY",
    "convoy_list": "TAB_CONTROL_WIDE + KONVOI_LISTE/KONVOILISTEN_EINTRAG",
    "trade_route_library": "TAB_CONTROL + AUTOHANDEL_SPEICHERN_LADEN/AUTOHANDEL_SAVE_EINTRAG",
    "political_map": "POLITISCHE_KARTE",
    "town_info": "STADT_INFO_DIALOG / STADT_INFO",
    "town_population": "STADTINFO_EINWOHNER_INFO",
    "market": "INTERFACE_TAB_WINDOW + INTERFACE_BUTTON_PANEL (TMPL_Market); page NPC_FESTGROESSE",
    "tavern": "INTERFACE_TAB_WINDOW + INTERFACE_BUTTON_PANEL (TMPL_Pub); KNEIPE_GLUECKSSPIEL(_REGELN), NPC_CAPTAIN_*",
    "governor": "INTERFACE_TAB_WINDOW + INTERFACE_BUTTON_PANEL (TMPL_Gouverneur); NPC_* pages (NPC_KARTE, NPC_NATIONEN, ...)",
    "church": "INTERFACE_TAB_WINDOW + INTERFACE_BUTTON_PANEL (TMPL_Church); NPC_GOLD_EINGABE",
    "shipyard": "INTERFACE_TAB_WINDOW + INTERFACE_BUTTON_PANEL (TMPL_WerftTabCtrl); WERFT, WERFT_KAUFEN_INFO, "
                "WERFT_RENAME_INFO, WERFT_REPAIR(_INFO)",
    "construction": "INTERFACE_TAB_WINDOW (TMPL_ConstructionMenu); BAUMENU, BAUMENU_GEBAUDEINFO, BAUMMENU_INFO",
    "warehouse": "INTERFACE_TAB_WINDOW (TMPL_WarehouseTabCtrl); LAGER_UEBERSICHT, LAGERHAUS_WARENBESTAND, "
                 "LAGER_VERWALTER, LAGERHAUS_PRODUKTION",
    "palace": "INTERFACE_TAB_WINDOW (TMPL_WarehouseTabCtrl); SPIELER_PALAST, LAGERHAUS_WARENBESTAND, LAGER_VERWALTER",
    "trade": "INTERFACE_TAB_WINDOW (TMPL_HandelsScreen); HANDELSFENSTER, HANDELSFENSTER_CARGO, WARENTRANSFER",
    "house": "INTERFACE_TAB_WINDOW (TMPL_ControlInterface); WOHNGEBIET_INFO / WOHNGEBIET_GEGNER",
    "factory": "INTERFACE_TAB_WINDOW (TMPL_ControlInterface); BETRIEB_INFO_SPIELER / BETRIEB_INFO_GEGNER",
    "ingame_menu": "MENU_AUSWAHL_TAFEL / OPTIONENSCREEN",
    "interface": "INTERFACE_TAB_WINDOW + INTERFACEBAR; INTERFACE_WAREN, INTERFACE_SCHIFFE, INTERFACE_CREW_FRACHT, "
                 "INTERFACE_KONVOI_INFO, INTERFACE_AUTOHANDEL",
    "sea_map": "SEEKARTE_NEU, SIDEMENU_MINIMAP, TOPMENUBAR",
    "town_view": "TOPMENUBAR, INTERFACEBAR, SIDEMENU_MINIMAP",
    "nation_panel": "TAB_CONTROL + NACHRICHTEN_LISTE + FNN_CARD (the mod)",
}
PANEL_PAGES = ["overview", "treasury", "towns", "diplomacy", "government", "navy_defence", "found"]
INTERFACE_BUTTONS = [("goods_list", (917, 618)), ("ships_list", (917, 655)), ("overview_costs", (917, 692)),
                     ("trade_route", (917, 730)), ("attack_mode", (917, 767))]   # right edge of the lower panel
DIALOG_BUTTON = (600, 760)       # the one text button of a building dialog page (Continue, Grant loan, ...)
INGAME_MENU = {"options": (1040, 230), "load_save": (1040, 146), "return": (1040, 494)}
OPTIONS = [("graphic", (1045, 62)), ("sound", (1045, 143)), ("gameplay", (1045, 226)), ("keyboard", (1045, 308))]
OPTIONS_OK, OPTIONS_BACK, LOAD_SAVE_BACK = (1040, 162), (1045, 407), (1040, 326)


def run_days(n):
    if n <= 0:
        return
    print(f"running {n} game days first", flush=True)
    F.run_days(n)
    for _ in range(6):                               # back down from 20x
        session.cmd("click", 395, 13)
    time.sleep(2)


def sub_click(window, page, xy, how, screen, wait=2.5):
    """A sub-view of the current page reached with one click (posted by gamehost)."""
    def go():
        click(*xy, wait)
        shot(window, page, how, screen)
    return go


def plan_town(only):
    """Everything that needs the player in a town: Margarita, the player's convoy at anchor."""
    enter_town(CAPITAL)
    close_all()
    if want(only, "town_view"):
        shot("town_view", "margarita", "Nation_DevView(2, Margarita) (tests: enter a town)", SCREENS["town_view"])
    if want(only, "interface"):
        for name, (x, y) in INTERFACE_BUTTONS:
            close_all()
            click(x, y)
            shot("interface", name, f"gamehost click on the lower panel's button at {x},{y}", SCREENS["interface"])
        click(*INTERFACE_BUTTONS[1][1])
        click(398, 693)                                       # the first ship in the ships list
        shot("interface", "ship_selected", "ships list, then a click on the first ship", SCREENS["interface"])
        click(*INTERFACE_BUTTONS[0][1])
    if want(only, "chronicle"):
        tabbed("chronicle", 0x509990, 0x7C, CHRONICLE_TABS, screen=SCREENS["chronicle"])
    if want(only, "convoy_list"):
        tabbed("convoy_list", 0x5090E0, 0x78, ["sort_name", "sort_ships", "sort_cannons", "sort_crew",
                                              "sort_capacity", "captains"], screen=SCREENS["convoy_list"])
    if want(only, "trade_route_library"):
        tabbed("trade_route_library", 0x50C940, 0xBC, ["save", "load", "delete"],
               screen=SCREENS["trade_route_library"])
    if want(only, "town_info"):
        b = vc_building(0x24, -1)
        single("town_info", "margarita", b["va"], 0x120, b["args"], SCREENS["town_info"], 1,
               "town view building dispatcher 0x516AA0(0x24, -1) -> CGameMenu 0x50B8F0 (town info)")
    if want(only, "town_goods"):
        single("town_goods", "margarita", 0x50A3E0, 0x148, (), SCREENS["town_population"],
               how="Nation_DevMenu(0x50A3E0) (town info's goods/consumption window)")
    if want(only, "market"):
        tabbed("market", 0x511630, 0xA8, ["feast"], screen=SCREENS["market"])
    if want(only, "tavern"):
        tabbed("tavern", 0x50FB90, 0x9C, ["gambling"], screen=SCREENS["tavern"], sub={
            "gambling": sub_click("tavern", "gambling_rules", (490, 766), "Tavern, then the Rules button",
                                  SCREENS["tavern"])})
    if want(only, "governor"):
        tabbed("governor", 0x510520, 0xA4, ["governor", "treasurer", "general"], screen=SCREENS["governor"], sub={
            "governor": sub_click("governor", "governor_continue", DIALOG_BUTTON, "Governor, then Continue",
                                  SCREENS["governor"]),
            "treasurer": sub_click("governor", "treasurer_loan_granted", DIALOG_BUTTON,
                                   "Treasurer, then Grant loan (gives the Balance tab a loan)", SCREENS["governor"])})
    if want(only, "church"):
        tabbed("church", 0x510F40, 0xA0, ["pray", "bless", "donate"], screen=SCREENS["church"])
    if want(only, "shipyard"):
        tabbed("shipyard", 0x50F160, 0x98, ["buy", "sell", "rename", "repair"], screen=SCREENS["shipyard"])
    if want(only, "construction"):
        tabbed("construction", 0x5121D0, None, ["buildings", "businesses", "special", "master_builder"], args=(0,),
               screen=SCREENS["construction"])
    if want(only, "warehouse"):
        L(f"Global_CreateBuilding({player_handle()}, Global_GetViewTown(), {WAREHOUSE_KIND})")
        time.sleep(1)
        tabbed("warehouse", 0x50EAD0, 0x84, ["overview", "stock", "goods_bought", "goods_sold"], args=(0,),
               screen=SCREENS["warehouse"],
               how="Global_CreateBuilding(player, town, 22) then Nation_DevMenu(0x50EAD0) (own warehouse)")
    if want(only, "palace"):
        L(f"Global_CreateBuilding({player_handle()}, Global_GetViewTown(), {PALACE_KIND})")
        time.sleep(1)
        tabbed("palace", 0x50BA90, 0xAC, ["palace", "stock", "goods_bought", "goods_sold"], screen=SCREENS["palace"],
               how="Global_CreateBuilding(player, town, 35) then Nation_DevMenu(0x50BA90) (player palace)")
    if want(only, "trade"):
        b = vc_building(0x22, -1)
        tabbed("trade", b["va"], 0x80, ["town_warehouse", "town_convoy", "warehouse_convoy"], args=b["args"],
               on_vc=1, screen=SCREENS["trade"],
               how="town view building dispatcher 0x516AA0(0x22, -1) -> 0x508930 (trade window)")
    for name, (kind, h) in (("house", HOUSE), ("factory", FACTORY)):
        if want(only, name):
            b = vc_building(kind, h)
            tabbed(name, b["va"], None, ["info", "buy"], args=b["args"], on_vc=1, screen=SCREENS[name],
                   how=f"town view building dispatcher 0x516AA0({kind:#x}, {h:#x}) (a building of a local trader)")
    if want(only, "log"):                                     # after the treasurer: the Balance tab has a loan
        tabbed("log", 0x507ED0, 0x74, LOG_TABS, screen=SCREENS["log"], sub={
            "missions": lambda: click_control("LON_BtnMissonsDone") and shot(
                "log", "missions_done", "Log, Missions tab, then the 'done' button LON_BtnMissonsDone", SCREENS["log"]),
            "balance": lambda: click_control("LOB_kredite") and shot(
                "log", "balance_loans", "Log, Balance tab, then the Loans button LOB_kredite", SCREENS["log"]),
        })
    if want(only, "nation_panel"):
        close_all()
        founded = (L('Nation_Log("i", Nation_GetInfo())').get("i") or ["0"])[0] == "1"
        for i, page in enumerate(PANEL_PAGES[:6] if founded else PANEL_PAGES[:1] + PANEL_PAGES[6:]):
            k = PANEL_PAGES.index(page)
            L(f"Nation_PanelOpen({k})")
            time.sleep(2.5)
            shot("nation_panel", f"{k}_{page}", f"Nation_PanelOpen({k}) (the mod's panel, Ctrl+N)",
                 SCREENS["nation_panel"])
        L("Nation_PanelClose()")
    if want(only, "ingame_menu"):
        plan_ingame_menu()
    close_all()


def plan_ingame_menu():
    s = SCREENS["ingame_menu"]
    if not single("ingame_menu", "main", 0x507DD0, 0x5C, (), s, how="Nation_DevMenu(0x507DD0) (Esc menu)"):
        return
    click(*INGAME_MENU["options"])
    shot("ingame_menu", "options", "Esc menu, then Options", "OPTIONENSCREEN")
    for name, xy in OPTIONS:
        click(*xy, 3)
        shot("ingame_menu", f"options_{name}", f"Esc menu, Options, then {name.title()}",
             f"OPTIONEN_{dict(graphic='GRAFIK', sound='SOUND', gameplay='GAMEPLAY', keyboard='EINGABE')[name]}"
             "EINSTELLUNGEN")
        click(*OPTIONS_OK)
    click(*OPTIONS_BACK)
    click(*INGAME_MENU["load_save"], 3)
    shot("ingame_menu", "load_save", "Esc menu, then Load/Save", "SPIELSTANDLADENMENU + SPIELSTANDLISTEN_EINTRAG")
    click(*LOAD_SAVE_BACK)
    click(*INGAME_MENU["return"])


MINIMAP_MARGARITA = (1226, 744)          # sea-map minimap: centre the view on Margarita


def plan_sea(only):
    sea_map()
    close_all()
    click(*MINIMAP_MARGARITA, 3)
    if want(only, "sea_map"):
        shot("sea_map", "plain", "Nation_DevView(1, 0) (tests: back to the sea map)", SCREENS["sea_map"])
    if want(only, "political_map"):
        single("political_map", "sea", 0x50B720, 0x154, (), SCREENS["political_map"],
               how="Nation_DevMenu(0x50B720) (the top bar's globe button)")
    close_all()


def player_handle():
    out = session.cmd("read", "0x701ED0", "4")
    m = re.search(r"0x701ed0: ((?:[0-9a-f]{2} ?){4})", out)
    return int.from_bytes(bytes.fromhex(m.group(1).replace(" ", "")), "little") if m else 0


def want(only, name):
    return not only or any(name.startswith(p) for p in only)


def run_plan(a):
    if not a.attach or a.days:
        run_days(a.days)
    plan_town(a.only)
    plan_sea(a.only)


NOT_CAPTURED = [
    "Tavern: the captain and pirate tabs (CGameMenu 0x50FB90 adds them only when a captain / pirate sits in the "
    "tavern; none in Margarita in this save), so only Gambling (+ its Rules) is shown.",
    "Trade route editor (AUTOHANDEL_* screens): the convoy's captain needs 4 experience points (see "
    "interface__trade_route.jpg); the Log's Trade routes page and the trade route library (save/load/delete) are shown.",
    "Missions: the save has no open or finished missions, so both mission views are the empty page.",
    "Generic question/message dialogs (PERGAMENT_ALLGEMEIN*, CGameMenu 0x5078B0..0x507C70 at gm+0x48/+0x4C): "
    "they need a caller (mission, event) and arguments.",
    "Goods/ship transfer between two convoys (0x50A570, 0x50A9F0, 0x50D0D0, TRANSFER_SCHIFF / WARENTRANSFER): "
    "needs two own convoys in one place.",
    "Enemy warehouse (0x50E3E0, LAGERHAUS_GEGNER) and special buildings (0x50C030, SPEZIALGEBAEUDE_INFO): no such "
    "building found in Margarita by the click scan.",
    "Battle screens (sea battle, town battle, fencing), the in-game help window (0x5065F0), the main menu and the "
    "new-game screens: not part of the in-game windows.",
    "The nation panel's 'Found a nation' page: it exists only before founding; this save already has a nation.",
    "Harbour master, moneylender, town hall: PR2 has no separate windows for them (loans are the governor's "
    "Treasurer tab, ships are the shipyard, the town hall is the town info).",
    "Top bar buttons 'convoys without / with a mission': they jump to the next such convoy, no window.",
]


def write_index():
    """docs/ui_gallery/INDEX.md from index.json (kept across --only runs)."""
    import json
    idx_file = OUT / "index.json"
    idx = json.loads(idx_file.read_text()) if idx_file.exists() else {}
    for f, w, p, how, scr in captured:
        idx[f] = {"window": w, "page": p, "how": how, "screen": scr}
    idx = {k: v for k, v in idx.items() if (OUT / k).exists()}
    idx_file.write_text(json.dumps(idx, indent=1, sort_keys=True))
    lines = ["# Vanilla UI gallery", "",
             "Every vanilla Port Royale 2 window and tab, captured in-game (1280x800, the test install) by "
             "`tools/ui_gallery.py`, to pick the vanilla look for each page of the nation panel. Windows are "
             "opened with the dev-only Lua functions `Nation_DevMenu` / `Nation_DevTabs` / `Nation_DevSelectTab` "
             "(dll/api.c), which call the game's own `CGameMenu::Open*` (this = `*(app+0xEC)`), the town view's "
             "building-click dispatcher `0x516AA0` (this = `*(app+0xF0)`) and `CTabControl::SelectTab 0x4DCC70`. "
             "Save: `FNN 46 - Navy - Great power with a fleet`, player in Margarita.", "",
             "| Image | Window | Page | How it was opened | Main .screen |", "|---|---|---|---|---|"]
    for f in sorted(idx, key=lambda k: (idx[k]["window"], k)):
        v = idx[f]
        lines.append(f"| [{f}]({f}) | {v['window']} | {v['page']} | {v['how']} | {v['screen']} |")
    lines += ["", "## Not captured (and why)", ""] + [f"- {s}" for s in NOT_CAPTURED]
    if missed:
        lines += ["", "## Failed in the last run", ""] + [f"- {w} / {p}: {why}" for w, p, why in missed]
    (OUT / "INDEX.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------------------------
def view():
    return L('Nation_Log("v", Global_GetView(), Global_GetViewTown())').get("v", [])


def enter_town(idx):
    h = ints(L(f'Nation_Log("h", Nation_TownHandle({idx}))').get("h", ["-1"]))[0]
    L(f"Nation_DevView(2, {h})")
    time.sleep(7)
    return h


def sea_map():
    L("Nation_DevView(1, 0)")
    time.sleep(5)


def acquire():
    while True:
        try:
            LOCK.mkdir()
            (LOCK / "owner.txt").write_text(f"agent ui-gallery (vanilla window screenshots, worktree "
                                            f"agent-aa79e3d1819ef1192): tools/ui_gallery.py, {time.ctime()}\n")
            return
        except FileExistsError:
            try:
                print("lock held by:", (LOCK / "owner.txt").read_text().strip(), flush=True)
            except OSError:
                pass
            time.sleep(60)


def release():
    shutil.rmtree(LOCK, ignore_errors=True)


def deploy():
    shutil.copy2(env.HERE / "_build" / "dll" / "PR2Nation.dll", env.ENV / "PR2Nation.dll")
    (env.ENV / "PR2Nation.dev").write_text("test install: enables Nation_Dev* and the PR2Nation.cmd console\n")
    data = env.HERE / "data"
    for f in list((data / "scripts").glob("*")) + [data / "lua" / "config" / "default" / "include.ini"]:
        if f.is_file():
            dst = env.ENV / f.relative_to(data)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)


def wait_desktop():
    while session.input_desktop() != "Default":
        print("input desktop is", session.input_desktop(), "- waiting 2 min", flush=True)
        time.sleep(120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=DEFAULT_SAVE)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--hold", action="store_true")
    ap.add_argument("--attach", action="store_true",
                    help="use the game a --hold run of this tool already loaded (it holds the lock)")
    ap.add_argument("--days", type=int, default=21, help="game days to run first (fills messages, balance)")
    a = ap.parse_args()
    ensure_dirs()
    if a.attach:
        if not (LOCK / "owner.txt").exists() or "ui-gallery" not in (LOCK / "owner.txt").read_text():
            sys.exit("--attach needs a running `ui_gallery.py --hold` (it holds the lock)")
        try:
            run_plan(a)
        finally:
            write_index()
            print(f"captured {len(captured)}; missed {len(missed)}", flush=True)
            for m in missed:
                print("  MISSED", m, flush=True)
        return 0
    wait_desktop()
    acquire()
    backup = None
    try:
        deploy()
        backup = env.backup_saves()
        wait_desktop()
        session.load(a.save, [], "PR2_nation.exe")
        time.sleep(3)
        if a.hold:
            STOP.unlink(missing_ok=True)
            print("holding the game; create", STOP, "to stop", flush=True)
            while not STOP.exists() and F.M.game_alive():
                time.sleep(2)
            STOP.unlink(missing_ok=True)
        else:
            run_plan(a)
    finally:
        F.M.kill_game()
        if backup:
            for f in backup.iterdir():
                if f.is_file():
                    shutil.copy2(f, env.SAVE_DIR / f.name)
            env.restore_run(backup)
            orig = env.BACKUPS / "settings.cfg.orig"
            if orig.exists():
                shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
        release()
        if not a.hold:
            write_index()
        print(f"captured {len(captured)}; missed {len(missed)}", flush=True)
        for m in missed:
            print("  MISSED", m, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
