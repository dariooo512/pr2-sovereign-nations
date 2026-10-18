"""Static self-check for the nation UI (dll/strings.c, dll/ui.c, data/.../include.ini).

    python tools/check_ui_static.py        -> exit code = failures

No game is started. What it checks:
  1. The .res string-table format and id hash, against the game's own table
     (PR2.exe resource BINARY #167, XOR-chain decoded like 0x404794..0x4047AC)
     and the UI table global.res: known ids resolve to the expected text with
     A2dLib's exact binary search (0x10025C90).
  2. Every byte signature ui.c / strings.c rely on, in PR2.exe.unpacked.exe and
     A2dLib-2.20A.dll (the same facts are cited in the C comments).
  3. A host harness (mingw32 gcc) links the real strings.c + ui.c glue + lua.c,
     loads the pristine game lua.dll (Lua 4.1 ASCARON) and
       - dumps the "FNN" blob -> parsed + looked up here like the engine does;
       - runs data/lua/config/default/include.ini against engine stubs and
         drives every remaining popup flow (menu event ->
         panel hand-off, current town, conquest + its notification, guard fallback), validating each OnPopupText
         result (header string, body/button tables, <=3 buttons, ids exist).
  4. include.ini starts with the vanilla file byte for byte; no Lua-5-only syntax.
"""
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sn_paths import BASE_EXE, MINGW32_BIN, PRISTINE, WORKDIR  # noqa: E402

FNN = Path(__file__).resolve().parents[1]
DLL = FNN / "dll"
INCLUDE = FNN / "data" / "lua" / "config" / "default" / "include.ini"
VANILLA_INCLUDE = WORKDIR / "arcs" / "lua" / "config" / "default" / "include.ini"
EXE = BASE_EXE
A2D = PRISTINE / "A2dLib-2.20A.dll"
LUADLL = PRISTINE / "lua.dll"
GLOBAL_RES = WORKDIR / "arcd" / "strings" / "Original" / "global" / "global.res"
OUT = FNN / "_build" / "check_ui"
GCC_BIN = MINGW32_BIN

fails = 0


def check(cond, what):
    global fails
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails += 1
    return cond


# ---------------------------------------------------------------- .res format
def res_hash(name: str) -> int:
    h = 0
    for ch in name.encode("latin-1"):
        c = ch - 256 if ch >= 128 else ch                    # movsx
        m = (h * 0x71 + c) & 0xFFFFFFFF                      # imul/add wrap
        m = m - (1 << 32) if m >= 1 << 31 else m
        h = abs(m) % 999999991 * (1 if m >= 0 else -1)       # idiv 0x3B9AC9F7: truncating remainder
    return h


def parse_res(blob: bytes):
    n = struct.unpack_from("<I", blob, 0)[0]
    ents = [struct.unpack_from("<iIII", blob, 4 + 16 * i) for i in range(n)]
    return n, ents


def res_lookup(blob: bytes, name: str):
    """A2dLib 0x10025C90: lo=0, hi=count, mid=hi>>1, signed compare."""
    key = res_hash(name)
    if key == -1:
        return None
    n = struct.unpack_from("<I", blob, 0)[0]
    lo, hi = 0, n
    mid = hi >> 1
    while lo <= hi:
        if mid >= n:                     # engine would read past the table; treat as miss
            break
        h = struct.unpack_from("<i", blob, 4 + 16 * mid)[0]
        if key == h:
            break
        if key < h:
            hi = mid - 1
        else:
            lo = mid + 1
        mid = (hi + lo) >> 1
    if mid < 0 or mid >= n:
        return None
    h, off, _nargs, ln = struct.unpack_from("<iIII", blob, 4 + 16 * mid)
    if h != key:
        return None
    return blob[4 + off: 4 + off + ln].decode("utf-16-le")


def check_table_layout(blob: bytes, label: str):
    n, ents = parse_res(blob)
    hashes = [e[0] for e in ents]
    check(hashes == sorted(hashes), f"{label}: {n} entries sorted by signed hash")
    end = 4 + 16 * n
    ok = all(end <= 4 + off and 4 + off + ln <= len(blob) and ln % 2 == 0 for _, off, _, ln in ents)
    check(ok, f"{label}: every text lies inside the blob (offset counted from byte 4)")
    return n, ents


def exe_mission_table() -> bytes:
    import pefile
    pe = pefile.PE(str(EXE))
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if t.name and str(t.name) == "BINARY":
            for e in t.directory.entries:
                if e.id == 167:
                    d = e.directory.entries[0].data.struct
                    raw = pe.get_memory_mapped_image()[d.OffsetToData:d.OffsetToData + d.Size]
                    w = struct.unpack(f"<{len(raw) // 2}H", raw[: len(raw) // 2 * 2])
                    out = [0] * len(w)
                    for i in range(len(w) - 1, 0, -1):      # out[i] = in[i-1] ^ in[i]
                        out[i] = w[i - 1] ^ w[i]
                    out[0] = w[0] ^ 0x45AD
                    return struct.pack(f"<{len(out)}H", *out)
    raise RuntimeError("BINARY #167 not found")


def part1():
    print("[1] .res format + hash against the game's tables")
    check(res_hash("IDA_ALLESTAEDTE") & 0xFFFFFFFF == 0xE6550853, "hash(IDA_ALLESTAEDTE) == 0xE6550853")
    mt = exe_mission_table()
    check_table_layout(mt, "PR2.exe BINARY #167")
    check(res_lookup(mt, "ID_NATION_0") == "England", "mission table: ID_NATION_0 -> 'England'")
    check(res_lookup(mt, "ID_NPC_VICEROY_HDR") == "Viceroy of %1", "mission table: ID_NPC_VICEROY_HDR -> 'Viceroy of %1'")
    check(res_lookup(mt, "IDM_FNN_NO_SUCH_ID") is None, "mission table: unknown id misses")
    mb = WORKDIR / "arcs" / "lua" / "data" / "missions.bin"
    if mb.exists():
        ids = set(x.decode() for x in re.findall(rb"\bIDM?_[A-Z0-9_]{3,}", mb.read_bytes()))
        keys = {e[0] for e in parse_res(mt)[1]}
        hits = sum(res_hash(i) in keys for i in ids)
        check(hits > len(ids) // 2, f"mission table: {hits}/{len(ids)} ids named in missions.bin resolve")
    tables = {"mission": mt}
    if GLOBAL_RES.exists():
        g = GLOBAL_RES.read_bytes()
        try:
            check_table_layout(g, "global.res")
            tables["global"] = g
        except struct.error:
            check(False, "global.res parses")
    return tables


# ---------------------------------------------------------------- byte facts
def part2():
    print("[2] verified byte signatures")
    import pefile
    pe = pefile.PE(str(EXE))
    img = pe.get_memory_mapped_image()
    base = pe.OPTIONAL_HEADER.ImageBase

    def at(va, hx, what):
        b = bytes.fromhex(hx)
        check(img[va - base: va - base + len(b)] == b, f"PR2 {va:08X} {what}")

    at(0x44DE70, "8B5424088BC1", "GameMenuEvent ctor")
    at(0x44DE96, "C70030956800", "GameMenuEvent vtbl 0x689530")
    at(0x44DEA2, "C21400", "GameMenuEvent ctor ret 0x14")
    at(0x450090, "64A1000000006AFF", "CEventDispatcher::Post")
    at(0x450164, "C20400", "Post ret 4")
    at(0x510EEF, "6AFF6AFF6A016A006A06", "vanilla post: push -1,-1,1,0,6")
    at(0x510F06, "B90C2B7000", "vanilla post: mov ecx,0x702B0C")
    at(0x42F850, "6AFF68D9176500", "MessageSystem singleton")
    at(0x5B7FF0, "6AFF688BFF6600", "MessageSystem::AddText")
    at(0x5B80BC, "C20800", "AddText ret 8")
    at(0x430739, "6A00", "Global_AddMessage passes flag 0")
    at(0x4047B0, "8B15D0F467008B0A", "string table Add site: mov edx,[g_pStringMgr]; mov ecx,[edx]")
    at(0x4047BF, "FF15CCF46700", "call [IAT Add]")
    at(0x57F28E, "8A86440E0000", "sim running flag read [esi+0xE44]")
    at(0x433939, "6A016A01", "OnInit lua_call(1 arg, 1 result)")
    at(0x41C4A8, "7510", "OnInit result must be a number (lua_error otherwise)")
    at(0x41D27C, "B801000000", "Script_Register returns 1 value (the vtb table)")
    imports = {i.address: (i.name or b"").decode() for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports}
    for va, nm in [(0x67F4CC, "?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z"),
                   (0x67F4C4, "?Remove@CStringManager@NA2dLib@@QAEXPBD@Z"),
                   (0x67F4D0, "?g_pStringMgr@NA2dLib@@3PAVCStringManager@1@A"),
                   (0x67FA18, "??0?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@QAE@PBGABV?$allocator@G@1@@Z"),
                   (0x67FA04, "??1?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@QAE@XZ")]:
        check(imports.get(va) == nm, f"IAT {va:08X} = {nm[:48]}")
    a = pefile.PE(str(A2D))
    aimg = a.get_memory_mapped_image()
    abase = a.OPTIONAL_HEADER.ImageBase

    def aat(va, hx, what):
        b = bytes.fromhex(hx)
        check(aimg[va - abase: va - abase + len(b)] == b, f"A2d {va:08X} {what}")

    aat(0x1002BB45, "6BC0710FBEC903C199B9F7C99A3BF7F9", "hash loop imul 0x71 / movsx / idiv 0x3B9AC9F7 = 999999991")
    aat(0x10026C58, "FF504C", "Add -> vfunc +0x4C")
    aat(0x10026C6C, "C20C00", "Add ret 0xC")
    aat(0x10026DAD, "C20400", "Remove ret 4")
    aat(0x10025E97, "F3A5", "LoadBuffer copies the data (rep movsd)")
    aat(0x10025C9A, "83FBFF", "lookup rejects hash -1")
    exports = {abase + e.address: (e.name or b"").decode() for e in a.DIRECTORY_ENTRY_EXPORT.symbols}
    check(exports.get(0x10005A51, "").startswith("?Add@CStringManager"), "A2d export Add @10005A51")
    check(exports.get(0x10001FC8, "").startswith("?Remove@CStringManager"), "A2d export Remove @10001FC8")


# ---------------------------------------------------------------- harness
HARNESS_C = r'''
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lua.h"
#include "strings.h"

int ui_register_glue(lua_State *L);
unsigned ui_guard_failures(void);
const char *ui_guard_last_error(void);

/* stubs for the game-side symbols ui.c links against */
int adapter_world_ready(void) { return 0; }
void panel_toggle(void) {}
void panel_request_close(void) {}
int sight_cycle(void) { return 0; }
void *adapter_state(void) { static unsigned char state[65536]; return state; }   /* zeroed: not founded */
const char *eng_town_name(int idx)
{
    switch (idx) { case 47: return "PortRoyale"; case 31: return "PortauPrince";
                   case 17: return "StAugustine"; case 25: return "Havana"; }
    return "?";
}

typedef lua_State *(__cdecl *open_t)(int);
typedef int (__cdecl *dobuf_t)(lua_State *, const char *, size_t, const char *);
typedef int (__cdecl *L_i)(lua_State *, int);
typedef const char *(__cdecl *L_s)(lua_State *, int);
typedef void (__cdecl *L_v)(lua_State *, int);
typedef void (__cdecl *L_vii)(lua_State *, int, int);
typedef void (__cdecl *L_cf)(lua_State *, lua_CFunction, int);
typedef void (__cdecl *L_name)(lua_State *, const char *);
typedef int (__cdecl *L_top)(lua_State *);

static open_t l_open; static dobuf_t l_dobuffer; static L_i l_type; static L_s l_tostring;
static L_vii l_rawgeti; static L_cf l_pushcclosure; static L_name l_setglobal; static L_top l_gettop;
static L_v l_settop;
static int failures, popups;
static char errmsg[1024];

static int __cdecl h_errmsg(lua_State *L) { snprintf(errmsg, sizeof errmsg, "%s", l_tostring(L, 1)); return 0; }

static int __cdecl h_check(lua_State *L)
{
    const char *what = l_gettop(L) >= 2 ? l_tostring(L, 2) : "?";
    int ok = l_gettop(L) >= 1 && l_type(L, 1) != 1;   /* not nil */
    printf("  %s  lua: %s\n", ok ? "ok   " : "FAIL ", what);
    if (!ok) failures++;
    return 0;
}

static int __cdecl h_contains(lua_State *L)
{
    const char *s = l_tostring(L, 1), *t = l_tostring(L, 2);
    if (s && t && strstr(s, t)) { plua_push_int(L, 1); return 1; }
    return 0;
}

static int __cdecl h_guard_fails(lua_State *L) { plua_push_int(L, (int)ui_guard_failures()); return 1; }

static int __cdecl h_text(lua_State *L)
{
    const char *t = strings_get(plua_str(L, 1, ""));
    if (!t) return 0;
    plua_push_str(L, t);
    return 1;
}

/* POPUP(h, b, k): validate an OnPopupText result like 0x44EE90 consumes it */
static int check_ids(lua_State *L, int idx, const char *what, int max)
{
    if (l_type(L, idx) != 5) { printf("  FAIL  popup %s is not a table\n", what); failures++; return 0; }
    int n = 0;
    for (int i = 1; i <= 8; i++) {
        l_rawgeti(L, idx, i);
        int ty = l_type(L, -1);
        if (ty == 1) { l_settop(L, -2); break; }
        const char *id = ty == 4 ? l_tostring(L, -1) : NULL;
        if (!id || !strings_get(id)) { printf("  FAIL  popup %s[%d] id '%s' unknown\n", what, i, id ? id : "(non-string)"); failures++; }
        else printf("          %s[%d] %s = \"%.90s\"\n", what, i, id, strings_get(id));
        l_settop(L, -2);
        n++;
    }
    if (n > max) { printf("  FAIL  popup has %d %s (max %d)\n", n, what, max); failures++; }
    if (n == 0) { printf("  FAIL  popup has no %s\n", what); failures++; }
    return n;
}

static int __cdecl h_popup(lua_State *L)
{
    popups++;
    const char *h = l_type(L, 1) == 4 ? l_tostring(L, 1) : NULL;
    if (!h || !strings_get(h)) { printf("  FAIL  popup header '%s' unknown\n", h ? h : "(non-string)"); failures++; }
    else printf("        popup \"%s\"\n", strings_get(h));
    check_ids(L, 2, "body", 4);
    int nb = check_ids(L, 3, "button", 3);
    plua_push_int(L, nb);
    return 1;
}

static char *slurp(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc(sz + 1); *n = fread(b, 1, sz, f); b[*n] = 0; fclose(f);
    return b;
}

int main(int argc, char **argv)
{
    if (argc < 6) return 99;
    /* 1. the default FNN blob */
    uint32_t size; uint8_t *blob = strings_build_blob(&size);
    FILE *o = fopen(argv[1], "wb"); fwrite(blob, 1, size, o); fclose(o); free(blob);

    /* 2. Lua flows */
    HMODULE m = LoadLibraryA(argv[2]);
    if (!m) { printf("  FAIL  cannot load %s\n", argv[2]); return 98; }
    l_open = (open_t)(void *)GetProcAddress(m, "lua_open");
    l_dobuffer = (dobuf_t)(void *)GetProcAddress(m, "lua_dobuffer");
    l_type = (L_i)(void *)GetProcAddress(m, "lua_type");
    l_tostring = (L_s)(void *)GetProcAddress(m, "lua_tostring");
    l_rawgeti = (L_vii)(void *)GetProcAddress(m, "lua_rawgeti");
    l_pushcclosure = (L_cf)(void *)GetProcAddress(m, "lua_pushcclosure");
    l_setglobal = (L_name)(void *)GetProcAddress(m, "lua_setglobal");
    l_gettop = (L_top)(void *)GetProcAddress(m, "lua_gettop");
    l_settop = (L_v)(void *)GetProcAddress(m, "lua_settop");
    plua_init();
    lua_State *L = l_open(1000);
    struct { const char *n; lua_CFunction f; } fns[] = {
        {"_ERRORMESSAGE", h_errmsg}, {"CHECK", h_check}, {"POPUP", h_popup},
        {"TEXT", h_text}, {"CONTAINS", h_contains}, {"GUARD_FAILS", h_guard_fails}};
    for (unsigned i = 0; i < sizeof fns / sizeof *fns; i++) { l_pushcclosure(L, fns[i].f, 0); l_setglobal(L, fns[i].n); }
    if (!ui_register_glue(L)) { printf("  FAIL  ui_register_glue\n"); return 97; }
    for (int a = 3; a <= 5; a++) {
        size_t n; char *src = slurp(argv[a], &n);
        if (!src) { printf("  FAIL  cannot read %s\n", argv[a]); return 96; }
        errmsg[0] = 0;
        int st = l_dobuffer(L, src, n, argv[a]);
        l_settop(L, 0);
        printf("  %s  lua_dobuffer(%s) = %d %s\n", st == 0 ? "ok   " : "FAIL ", strrchr(argv[a], '\\') ? strrchr(argv[a], '\\') + 1 : argv[a], st, errmsg);
        if (st) failures++;
        free(src);
    }
    /* exactly the 2 deliberate failures of the negative test in flows.lua */
    if (ui_guard_failures() != 2) { printf("  FAIL  FNN_Guard caught %u script errors, expected 2 (last: %s)\n", ui_guard_failures(), ui_guard_last_error()); failures++; }
    else printf("  ok    no unexpected script error inside FNN_Guard\n");
    printf("  %d popups validated\n", popups);
    return failures;
}
'''

PRELUDE_LUA = r'''
-- engine stubs (values verified in PR2.exe: MTYPE_GLOBAL 1, MEVENT_GAME_MENU 0x40000,
-- MEVENT_TOWNBATTLE_END 0x8000000; Script_Register returns SCRIPT_TABLE[name])
SCRIPT_TABLE = {}
MTYPE_GLOBAL = 1
MSTATE_OFFERING = 1
MEVENT_GAME_MENU = 262144
MEVENT_TOWNBATTLE_END = 134217728
T = { popups = 0, filter = 0, view = -1, convoy = -1, convoy_town = -1, player = 131072,
      founded = 0, name = "", tax = 10, can = 1, why = "", rel = { 0, 0, 0, 0 }, cap = -1,
      treasury = 1234567, stab = 60, tariff = 0, gold = 0, ships = 2 }
function Script_Register(name, group, typ)
  local t = { TYPE = typ, GROUP = group, T_COUNT = 0, M_COUNT = 1, I_COUNT = 0 }
  SCRIPT_TABLE[name] = t
  return t
end
function Global_InstallEventFilter(m) T.filter = m end
function Global_CreatePopup() T.popups = T.popups + 1 end
function Global_GetViewTown() return T.view end
function Global_GetSelectedConvoy() return T.convoy end
function Convoy_GetTown(c) return T.convoy_town end
function Global_GetPlayer() return T.player end
function Nation_Log(a, b, c) end
function Nation_TownIndex(h) return h - 65536 end
function Nation_CanFound(i) return T.can, T.why end
function Nation_Found(i, name, adj, title, flag)
  T.found_flag = flag
  T.found_name = name
  T.found_title = title
  T.founded = 1
  T.name = name
  T.cap = i
  return 1, ""
end
function Nation_PanelOpen(p) T.panel = p return 1 end
function Nation_GetInfo() return T.founded, T.name, T.name, T.cap, T.treasury, T.stab, 1, T.tax, T.tariff end
function Nation_GetFinance() return T.treasury, 7087, 2000, 150, 60, 7200, 75, 6000 end
function Nation_Donate(a)
  if T.founded ~= 1 or a <= 0 or a > T.gold then return 0 end
  T.gold = T.gold - a T.treasury = T.treasury + a return 1
end
function Nation_Withdraw(a)
  if T.founded ~= 1 or a <= 0 or a * 2 > T.treasury or T.stab < 25 then return 0 end
  T.gold = T.gold + a T.treasury = T.treasury - a T.stab = T.stab - 2 return 1
end
function Nation_SetTariff(p)
  if p == 5 or p == 10 or p == 20 then T.tariff = p else T.tariff = 0 end
end
function Nation_NationalConvoys(n) return 0 end   -- national convoys are off in this version
function Nation_GetRelation(p) return T.rel[p + 1], -12, 1, 40 end
function Nation_DeclareWar(p) T.rel[p + 1] = 4 T.war = p return 1 end
function Nation_Propose(p, t)
  if t == 5 then T.rel[p + 1] = 5 T.ceasefire = p else T.rel[p + 1] = 0 T.peace = p end
  return 1, ""
end
function Nation_SetTax(t, pct) T.tax = pct end
function Nation_GetTown(i) if T.member == i then return 1, 50, 10, 0 end return 0, 50, 10, 0 end
function Nation_Annex(i, r) T.annexed = i T.member = i return 1 end
function Nation_ResolveConquest(a, i) T.resolved = a T.resolved_town = i return 0 end
function Nation_FlagCount() return 100 end
function Nation_FlagName(i) return "Flag " .. i, "Group" end
function Nation_GetGovernment() return T.gov or 0, "x", T.gov_cool or 0 end
T.fleets = 0 T.order = 0 T.rank = 2
function Nation_NavyInfo()
  return 1, T.fleets, 6, T.rank, "Naval power", T.order, "Order " .. T.order, T.fleets, 6000 * T.fleets, 1234, 120000, 6000
end
function Nation_NavyCommission()
  if T.treasury < 120000 then return 0, "A new fleet costs 120000 gold." end
  T.fleets = T.fleets + 1 return 1, ""
end
function Nation_NavyDecommission()
  if T.fleets == 0 then return 0, "The nation has no fleet to pay off." end
  T.fleets = T.fleets - 1 return 1, ""
end
function Nation_NavySetOrder(o)
  if (o == 1 and T.rank < 2) or (o == 2 and T.rank < 3) then return 0, "rank" end
  T.order = o return 1, ""
end
function Nation_NavyReinforce(t) T.reinforced = t return 1, "" end
function Nation_NavyBuildTower(t) T.tower = t return 1, "" end
function Nation_TownDefence(t) return 321, 3, 5000, 1 end
function Nation_SetGovernment(g)
  if (T.gov_cool or 0) > 0 then return 0, "cooldown" end
  T.gov = g T.gov_cool = 25 return 1, ""
end
'''

FLOWS_LUA = r'''
V = SCRIPT_TABLE.fnn_nation
CHECK(V ~= nil, "Script_Register result holds the callbacks")
CHECK(USE_GROUPS[5] == "fnn" and USE_GROUPS[1] == "tavern", "USE_GROUPS keeps vanilla entries and appends fnn")
CHECK(fnn_nation == V, "fnn_nation is the registered vtb table")
inst = { STATE = 1 }
CHECK(V.OnInit(inst) == 1, "OnInit returns 1 (creation requires a non-zero number)")
V.OnCreate(inst)
CHECK(T.filter == MEVENT_GAME_MENU + MEVENT_TOWNBATTLE_END, "OnCreate installs the event filter")
CHECK(V.OnDestroy ~= nil and V.OnTimer ~= nil, "OnDestroy/OnTimer defined")

function show()
  local h, b, k = V.OnPopupText(inst, 0)
  POPUP(h, b, k)
  return h, b, k
end
function click(btn) V.OnPopupClose(inst, 0, btn) end

-- vanilla menus are ignored
T.popups = 0
V.OnGameMenu(inst, 6, 0, 1, -1, -1)
CHECK(T.popups == 0 and T.panel == nil, "governor menu event does not open anything")

-- the nation's own menu event opens the panel, never a dialog
V.OnGameMenu(inst, 20033, 0, 1, -1, -1)
CHECK(T.popups == 0 and T.panel == -1, "nation menu event -> Nation_PanelOpen(-1), no popup")

-- the panel's founding page asks for the current town: town view first, then the selected convoy's town
T.view = 65536 + 47
CHECK(fnn_current_town() == 47, "fnn_current_town: the open town view")
T.view = -1
T.convoy = 777
T.convoy_town = 65536 + 31
CHECK(fnn_current_town() == 31, "fnn_current_town: the selected convoy's town")
T.convoy = -1
CHECK(fnn_current_town() == -1, "fnn_current_town: none")
T.founded = 1
T.name = "Kingdom of Port Royale"

-- conquest
T.popups = 0
V.OnTownBattleEnd(inst, { attacker = T.player, town = 65536 + 25, land_attack = 1, attacker_wins = 1, annexation = 0 })
CHECK(T.popups == 0, "town-battle-end event opens nothing (the DLL decides)")
-- the DLL posts the menu event with sub = 1000 + town once a war conquest is ready
V.OnGameMenu(inst, 20033, 1000 + 25, 1, -1, -1)
CHECK(T.popups == 1 and inst.FnnConquest == 25, "menu event sub 1025 -> conquest popup for town 25")
h, b, k = show()
CHECK(h == "IDM_FNN_HDR_CONQUEST" and k[1] == "IDM_FNN_BTN_ANNEX" and k[2] == "IDM_FNN_BTN_WITHDRAW" and k[3] == nil,
      "conquest -> two buttons: annex / withdraw")
CHECK(CONTAINS(TEXT("IDM_FNN_BODY"), "Kingdom of Port Royale"), "conquest text names the nation")
T.member = 25
click(0)
CHECK(T.resolved == 1 and T.resolved_town == 25, "Nation_ResolveConquest(1, 25)")
CHECK(T.annexed == nil, "no Nation_Annex fallback (a peacetime victory is no conquest)")
h, b, k = show()
CHECK(h == "IDM_FNN_HDR_INFO" and k[1] == "IDM_FNN_BTN_CLOSE" and k[2] == nil and
      CONTAINS(TEXT("IDM_FNN_INFO_BODY"), "now belongs to the Kingdom of Port Royale"),
      "annexed -> a notification with one button")
T.popups = 0
click(0)
CHECK(T.popups == 0, "closing the notification opens nothing else")
V.OnGameMenu(inst, 20033, 1000 + 25, 1, -1, -1)
show()
click(1)
CHECK(T.resolved == 0, "withdraw -> Nation_ResolveConquest(0, 25)")

-- helpers
CHECK(FNN_Num(-1234567) == "-1,234,567" and FNN_Num(999) == "999", "FNN_Num")
CHECK(FNN_TownLabel(17) == "St. Augustine" and FNN_TownLabel(47) == "Port Royale", "FNN_TownLabel")

-- without the DLL glue the callbacks stay harmless
g = FNN_Guard
FNN_Guard = nil
h, b, k = V.OnPopupText(inst, 0)
POPUP(h, b, k)
CHECK(h == "IDM_FNN_HDR_INFO", "OnPopupText fallback without FNN_Guard")
V.OnGameMenu(inst, 20033, 0, 1, -1, -1)
V.OnPopupClose(inst, 0, 0)
FNN_Guard = g

-- a script error inside FNN_Guard is contained and the handler restored
function fnn_test_boom(self) local x = nil
  return x .. "boom"
end
em = _ERRORMESSAGE
n0 = GUARD_FAILS()
r = FNN_Guard("fnn_test_boom", inst)
CHECK(r == nil and GUARD_FAILS() == n0 + 1, "script error inside FNN_Guard is caught")
CHECK(_ERRORMESSAGE == em, "_ERRORMESSAGE restored after a caught error")
r = FNN_Guard("fnn_no_such_function", inst)
CHECK(r == nil and GUARD_FAILS() == n0 + 2, "unknown function is refused")
'''


def part3(tables):
    print("[3] host harness: FNN blob + include.ini flows in the real lua.dll")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "harness.c").write_text(HARNESS_C, encoding="utf-8")
    (OUT / "prelude.lua").write_text(PRELUDE_LUA, encoding="utf-8")
    (OUT / "flows.lua").write_text(FLOWS_LUA, encoding="utf-8")
    exe = OUT / "harness.exe"
    cmd = [str(GCC_BIN / "gcc.exe"), "-m32", "-std=gnu11", "-O1", "-Wall", "-I", str(DLL),
           "-o", str(exe), str(OUT / "harness.c"), str(DLL / "strings.c"), str(DLL / "ui.c"),
           str(DLL / "lua.c"), str(DLL / "log.c"), "-luser32"]
    env = dict(os.environ, PATH=str(GCC_BIN) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if not check(r.returncode == 0, "harness builds"):
        print(r.stdout + r.stderr)
        return
    blob_path = OUT / "fnn.res"
    r = subprocess.run([str(exe), str(blob_path), str(LUADLL), str(OUT / "prelude.lua"), str(INCLUDE),
                        str(OUT / "flows.lua")], env=env, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    global fails
    if r.returncode:
        print(f"  FAIL  harness reported {r.returncode} failure(s)")
        fails += r.returncode

    blob = blob_path.read_bytes()
    n, ents = check_table_layout(blob, "FNN blob")
    defaults = parse_defaults()
    bad = [i for i, t in defaults if res_lookup(blob, i) != t]
    check(not bad, f"FNN blob: all {len(defaults)} default ids resolve to their text via the engine search"
                   + (f" (bad: {bad[:3]})" if bad else ""))
    used = sorted(set(re.findall(r'"(IDM_FNN_[A-Z0-9_]+)"', INCLUDE.read_text(encoding="latin-1"))))
    missing = [u for u in used if res_lookup(blob, u) is None]
    check(not missing, f"every id used by include.ini ({len(used)}) has a default" + (f" (missing {missing})" if missing else ""))
    clash = []
    for name, t in tables.items():
        hs = {e[0] for e in parse_res(t)[1]}
        clash += [f"{i}~{name}" for i, _ in defaults if res_hash(i) in hs]
    check(not clash, "no FNN id hash collides with a vanilla table (FNN sorts first and would shadow it)"
                     + (f": {clash}" if clash else ""))


def parse_defaults():
    src = (DLL / "strings.c").read_text(encoding="utf-8")
    block = src[src.index("k_defaults[][2] = {"): src.index("};", src.index("k_defaults[][2] = {"))]
    out = []
    for m in re.finditer(r"\{\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+),\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\}", block):
        lits = lambda s: "".join(re.findall(r"\"((?:[^\"\\]|\\.)*)\"", s))
        out.append((lits(m.group(1)), lits(m.group(2))))
    return out


# ---------------------------------------------------------------- include.ini
def part4():
    print("[4] include.ini")
    van = VANILLA_INCLUDE.read_bytes()
    mod = INCLUDE.read_bytes()
    check(mod.startswith(van), f"starts with the vanilla file byte for byte ({len(van)} bytes)")
    check(mod[len(van):len(van) + 1] in (b"\n", b"\r"), "vanilla line is terminated before the additions")
    body = mod[len(van):].decode("latin-1")
    code = "\n".join(l.split("--", 1)[0] for l in body.splitlines())
    for pat, what in [(r"#", "'#' length operator"), (r"\bpairs\s*\(", "pairs()"), (r"\bipairs\s*\(", "ipairs()"),
                      (r"\blocal\s+function\b", "'local function'"), (r"\bstring\.", "string.* library"),
                      (r"\btable\.", "table.* library"), (r"\bformat\s*\(", "format()"),
                      (r"\.\.\.", "varargs '...'"), (r"\[\[", "long strings"), (r"\bgoto\b", "goto")]:
        check(not re.search(pat, code), f"no Lua-5-only / library construct: {what}")
    check("@" not in body and "$" not in body, "no '@'/'$' (mission-text placeholder syntax) in literals")


def main():
    tables = part1()
    part2()
    part3(tables)
    part4()
    print(f"\n{'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECK(S) FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
