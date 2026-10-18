/* Player UI of the nation feature (engine.h: ui_init / ui_frame / ui_message).
 *
 *  - Messages: free text into the game's message ticker through
 *    CMessageSystem::AddText with an STLport wstring (no mission context needed).
 *  - Menu: Ctrl+N posts a synthetic OnGameMenu(0x4E41) event; the "fnn_nation"
 *    mission script (data/lua/config/default/include.ini) answers it with
 *    mission popups. The DLL creates that mission instance once per game.
 *  - Lua glue: FNN_Guard (error-isolated calls into the script), Nation_SetText
 *    (dynamic strings, strings.c), Nation_Message, FNN_Num, FNN_TownLabel.
 *
 * Verified static facts (reverse-engineering/_re/PR2.exe.unpacked.exe):
 *  - Global_AddMessage impl 0x4306A0: needs the mission context (0x43072B call
 *    0x437E40 -> 0x436980), then 0x430732 call 0x42F850; mov eax,[eax];
 *    push 0; push &wstr; mov ecx,eax; 0x430742 call 0x5B7FF0. We do the same
 *    tail without the context part.
 *  - 0x42F850: lazy singleton, returns &ptr (0x6E7380), ret (cdecl).
 *  - 0x5B7FF0 CMessageSystem::AddText(const wstring*, bool): thiscall, ret 8;
 *    copies the string (0x5B807A call [0x67FA10] wstring copy ctor); skipped
 *    unless (*0x42D990())->flags & 0x10 (0x5B8030..0x5B803F).
 *  - wstring = STLport stlport_vc745.dll basic_string<unsigned short>, 12 bytes
 *    (0x4306B9: wstring at esp+8, next local at esp+0x14). Ctor from const
 *    ushort* = IAT 0x67FA18, dtor = IAT 0x67FA04 (resolved here by name).
 *  - OnGameMenu event: ctor 0x44DE70 (thiscall, ret 0x14; +8 menu, +0xC sub,
 *    byte +0x10 opened, +0x14 p4, +0x18 p5, vtbl 0x689530, type 0x40000);
 *    vanilla site 0x510EF3..0x510F16 = push -1,-1,1,0,6; call 0x44DE70;
 *    push eax; mov ecx,0x702B0C; call 0x450090.
 *  - 0x450090 CEventDispatcher::Post(ev): thiscall ret 4, walks the filter list
 *    and calls each matching mission's vfunc+0x1C synchronously (0x450145), so
 *    a stack event is fine. Dispatcher 0x44DEB0 pushes the 5 fields as numbers.
 *  - Sim running = byte [0x700500+0xE44] (read 0x57F28E; cleared by the pause
 *    path 0x57EE08, set 0x57F00D).
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "panel.h"
#include "sight.h"
#include "adapter.h"
#include "engine.h"
#include "game.h"
#include "lua.h"
#include "log.h"
#include "strings.h"

int adapter_world_ready(void);                 /* adapter.c */

/* ---- engine ----------------------------------------------------------- */
#define FNN_MENU_ID          0x4E41            /* private OnGameMenu id (20033) */
#define GA_SIM_RUNNING       (0x700500u + 0xE44u)
#define GA_EVENT_DISPATCHER  ((void *)0x00702B0Cu)

typedef void *(__attribute__((thiscall)) *GameMenuEv_t)(void *ev, int menu, int sub, int opened, int p4, int p5);
#define PR2_GameMenuEvent ((GameMenuEv_t)0x0044DE70)
typedef void (__attribute__((thiscall)) *EvPost_t)(void *disp, void *ev);
#define PR2_EventPost     ((EvPost_t)0x00450090)
typedef void **(__cdecl *MsgSys_t)(void);
#define PR2_MsgSys        ((MsgSys_t)0x0042F850)
typedef void (__attribute__((thiscall)) *AddText_t)(void *ms, const void *wstr, int flag);
#define PR2_MsgAddText    ((AddText_t)0x005B7FF0)

typedef void *(__attribute__((thiscall)) *WStrCtor_t)(void *self, const uint16_t *s, const void *alloc);
typedef void (__attribute__((thiscall)) *WStrDtor_t)(void *self);
#define STLP_DLL        "stlport_vc745.dll"
#define STLP_WSTR_CTOR  "??0?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@QAE@PBGABV?$allocator@G@1@@Z"
#define STLP_WSTR_DTOR  "??1?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@QAE@XZ"

static const struct { uint32_t va; uint8_t n; uint8_t b[8]; const char *what; int grp; } k_code[] = {
    {0x0044DE70, 6, {0x8B, 0x54, 0x24, 0x08, 0x8B, 0xC1}, "GameMenuEvent ctor", 0},
    {0x0044DE96, 6, {0xC7, 0x00, 0x30, 0x95, 0x68, 0x00}, "GameMenuEvent vtbl 0x689530", 0},
    {0x00450090, 8, {0x64, 0xA1, 0x00, 0x00, 0x00, 0x00, 0x6A, 0xFF}, "CEventDispatcher::Post", 0},
    {0x0042F850, 7, {0x6A, 0xFF, 0x68, 0xD9, 0x17, 0x65, 0x00}, "MessageSystem singleton", 1},
    {0x005B7FF0, 7, {0x6A, 0xFF, 0x68, 0x8B, 0xFF, 0x66, 0x00}, "MessageSystem::AddText", 1},
};

/* ---- lua.dll exports we need beyond lua.h ----------------------------- */
#define LUA_TNIL       1
#define LUA_TFUNCTION  6
#define LUA_MULTRET    (-1)
static int  (__cdecl *x_gettop)(lua_State *);
static void (__cdecl *x_settop)(lua_State *, int);
static void (__cdecl *x_pushvalue)(lua_State *, int);
static void (__cdecl *x_getglobal)(lua_State *, const char *);
static void (__cdecl *x_setglobal)(lua_State *, const char *);
static void (__cdecl *x_pushcclosure)(lua_State *, lua_CFunction, int);
static int  (__cdecl *x_call)(lua_State *, int, int);     /* protected, returns status */
static const char *(__cdecl *x_tostring)(lua_State *, int);
static int  (__cdecl *x_type)(lua_State *, int);

/* ---- state ------------------------------------------------------------ */
static int g_inited;
static int g_can_menu, g_can_msg, g_lua_ok;
static WStrCtor_t g_wctor;
static WStrDtor_t g_wdtor;
static unsigned long g_frame;
static int g_mission_ok;             /* GLOBALS.FNN_MISSION == 1 in the running game */
static int g_key_down;
static DWORD g_last_post;
static unsigned g_menu_calls;        /* fnn_on_menu invocations through FNN_Guard */
static char g_guard_err[512];
static unsigned g_guard_failures;

#define MSGQ 32
static char g_msgq[MSGQ][256];
static int g_mq_head, g_mq_n;

/* ------------------------------------------------------------------------ */
static int code_matches(int grp)
{
    for (unsigned i = 0; i < sizeof k_code / sizeof *k_code; i++) {
        if (k_code[i].grp != grp) continue;
        if (memcmp((const void *)(uintptr_t)k_code[i].va, k_code[i].b, k_code[i].n) != 0) {
            log_line("UI: %s @%08X differs from the verified bytes; feature disabled",
                     k_code[i].what, k_code[i].va);
            return 0;
        }
    }
    return 1;
}

static int resolve_lua(void)
{
    if (g_lua_ok) return 1;
    HMODULE m = GetModuleHandleA("lua.dll");
    if (!m) return 0;
    g_lua_ok = 1;
#define R(var, name) var = (void *)GetProcAddress(m, name); if (!var) { log_line("UI: lua.dll missing %s", name); g_lua_ok = 0; }
    R(x_gettop, "lua_gettop"); R(x_settop, "lua_settop"); R(x_pushvalue, "lua_pushvalue");
    R(x_getglobal, "lua_getglobal"); R(x_setglobal, "lua_setglobal");
    R(x_pushcclosure, "lua_pushcclosure"); R(x_call, "lua_call");
    R(x_tostring, "lua_tostring"); R(x_type, "lua_type");
#undef R
    return g_lua_ok;
}

static void lazy_init(void)
{
    if (g_inited) return;
    g_inited = 1;
    g_can_menu = code_matches(0);
    g_can_msg = code_matches(1);
    HMODULE st = GetModuleHandleA(STLP_DLL);
    if (st) {
        g_wctor = (WStrCtor_t)(void *)GetProcAddress(st, STLP_WSTR_CTOR);
        g_wdtor = (WStrDtor_t)(void *)GetProcAddress(st, STLP_WSTR_DTOR);
    }
    if (!g_wctor || !g_wdtor) {
        log_line("UI: STLport wstring exports not found; messages go to the log only");
        g_can_msg = 0;
    }
    resolve_lua();
    log_line("UI ready: menu %d, messages %d, lua glue %d", g_can_menu, g_can_msg, g_lua_ok);
}

static int game_running(void)
{
    return adapter_world_ready() && G_U8(GA_SIM_RUNNING) == 1;
}

/* ---- messages --------------------------------------------------------- */
static void show_text(const char *utf8)
{
    uint16_t w[300];
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, (wchar_t *)w, 299);
    if (n <= 0) return;
    w[299] = 0;
    for (int i = 0; w[i]; i++)                   /* the ticker is one line */
        if (w[i] == '\n' || w[i] == '\r') w[i] = ' ';
    void **pms = PR2_MsgSys();
    if (!pms || !*pms) return;
    uint32_t wstr[8] = {0};                      /* STLport wstring is 12 bytes; spare room */
    uint8_t alloc = 0;                           /* stateless allocator<ushort> */
    g_wctor(wstr, w, &alloc);
    PR2_MsgAddText(*pms, wstr, 0);               /* 0 = Global_AddMessage's flag (0x430739) */
    g_wdtor(wstr);
}

void ui_message(const char *text)
{
    if (!text || !text[0]) return;
    log_line("MSG %s", text);
    if (g_mq_n == MSGQ) {                        /* drop the oldest */
        g_mq_head = (g_mq_head + 1) % MSGQ;
        g_mq_n--;
    }
    int slot = (g_mq_head + g_mq_n) % MSGQ;
    snprintf(g_msgq[slot], sizeof g_msgq[slot], "%s", text);
    g_mq_n++;
}

/* New Game / Load: messages queued for the old world are dropped */
static volatile int g_conquest_popup = -1;      /* town awaiting the Annex/Withdraw popup */
void ui_reset(void) { g_mq_n = 0; g_mq_head = 0; g_conquest_popup = -1; }

static void flush_messages(void)
{
    if (!g_mq_n || !game_running()) return;
    for (int k = 0; k < 3 && g_mq_n; k++) {
        if (g_can_msg) show_text(g_msgq[g_mq_head]);
        g_mq_head = (g_mq_head + 1) % MSGQ;
        g_mq_n--;
    }
}

/* ---- Lua-callable functions ------------------------------------------- */
static int __cdecl quiet_errormessage(lua_State *L)
{
    const char *m = x_tostring(L, 1);
    snprintf(g_guard_err, sizeof g_guard_err, "%s", m ? m : "?");
    return 0;
}

/* FNN_Guard(fname, ...): call global function fname(...) with a harmless
   _ERRORMESSAGE so a script error returns here instead of reaching the
   engine handler 0x438920 (which throws, lua_bridge.md §1.4). Returns the
   function's results, or nothing after an error. */
static int __cdecl l_guard(lua_State *L)
{
    int n = x_gettop(L);
    if (n < 1) return 0;
    char fname[64];
    const char *s = x_tostring(L, 1);
    snprintf(fname, sizeof fname, "%s", s ? s : "");
    if (strcmp(fname, "fnn_on_menu") == 0) g_menu_calls++;
    plua_quiet_enter(L);
    x_getglobal(L, "_ERRORMESSAGE");               /* n+1: engine handler */
    x_pushcclosure(L, quiet_errormessage, 0);
    x_setglobal(L, "_ERRORMESSAGE");
    x_getglobal(L, fname);                         /* n+2: function */
    if (x_type(L, -1) != LUA_TFUNCTION) {
        x_pushvalue(L, n + 1);
        x_setglobal(L, "_ERRORMESSAGE");
        plua_quiet_leave();
        x_settop(L, n);
        g_guard_failures++;
        log_line("FNN_Guard: %s is not a function", fname);
        return 0;
    }
    for (int i = 2; i <= n; i++) x_pushvalue(L, i);
    g_guard_err[0] = 0;
    int st = x_call(L, n - 1, LUA_MULTRET);
    x_pushvalue(L, n + 1);                         /* restore the engine handler */
    x_setglobal(L, "_ERRORMESSAGE");
    plua_quiet_leave();
    if (st != 0) {
        g_guard_failures++;
        log_line("FNN_Guard: %s failed (%d): %s", fname, st, g_guard_err);
        x_settop(L, n);
        return 0;
    }
    return x_gettop(L) - (n + 1);                  /* the results sit above the saved handler */
}

static int __cdecl l_set_text(lua_State *L)
{
    const char *id = plua_str(L, 1, NULL);
    const char *tx = plua_str(L, 2, "");
    int ok = id ? strings_set(id, tx) : 0;
    plua_push_int(L, ok);
    return 1;
}

static int __cdecl l_message(lua_State *L)
{
    ui_message(plua_str(L, 1, ""));
    return 0;
}

/* FNN_Num(n) -> "1,234,567" */
static int __cdecl l_num(lua_State *L)
{
    long long v = plua_int(L, 1, 0);
    char raw[32], out[48];
    snprintf(raw, sizeof raw, "%lld", v < 0 ? -v : v);
    int len = (int)strlen(raw), o = 0;
    if (v < 0) out[o++] = '-';
    for (int i = 0; i < len; i++) {
        out[o++] = raw[i];
        if ((len - i - 1) % 3 == 0 && i != len - 1) out[o++] = ',';
    }
    out[o] = 0;
    plua_push_str(L, out);
    return 1;
}

/* staedte.ini key -> display label: "PortRoyale" -> "Port Royale" */
void ui_town_label(int idx, char *out, int cap)
{
    static const char *const special[][2] = {
        {"NombredeDios", "Nombre de Dios"}, {"PortauPrince", "Port-au-Prince"},
        {"PortofSpain", "Port of Spain"},   {"PortStJoe", "Port St. Joe"},
    };
    const char *k = eng_town_name(idx);
    for (unsigned i = 0; i < sizeof special / sizeof *special; i++)
        if (strcmp(k, special[i][0]) == 0) { snprintf(out, cap, "%s", special[i][1]); return; }
    int o = 0;
    for (int i = 0; k[i] && o < cap - 3; i++) {
        char c = k[i];
        if (i > 0 && c >= 'A' && c <= 'Z' && k[i - 1] >= 'a' && k[i - 1] <= 'z') {
            if (i == 2 && k[0] == 'S' && k[1] == 't') out[o++] = '.';   /* St -> St. */
            out[o++] = ' ';
        }
        out[o++] = c;
    }
    out[o] = 0;
}

static int __cdecl l_town_label(lua_State *L)
{
    char buf[64];
    ui_town_label(plua_int(L, 1, -1), buf, sizeof buf);
    plua_push_str(L, buf);
    return 1;
}

/* Test hook: open the nation menu exactly as Ctrl+N does, on the next frame
   (outside the Lua call), without needing keyboard focus. */
static volatile int g_dev_menu;
static int __cdecl l_dev_open_menu(lua_State *L) { (void)L; g_dev_menu = 1; return 0; }

static const struct { const char *name; lua_CFunction f; } k_lua[] = {
    {"Nation_DevOpenMenu", l_dev_open_menu},
    {"Nation_SetText", l_set_text}, {"Nation_Message", l_message},
    {"FNN_Num", l_num}, {"FNN_TownLabel", l_town_label},
    {"FNN_Guard", l_guard},          /* last: its presence marks "all registered" */
};

/* Register the glue into L (also used by tools/check_ui_static.py's host
   harness with a stand-alone lua.dll state). */
int ui_register_glue(lua_State *L)
{
    if (!L || !resolve_lua()) return 0;
    for (unsigned i = 0; i < sizeof k_lua / sizeof *k_lua; i++) {
        x_pushcclosure(L, k_lua[i].f, 0);
        x_setglobal(L, k_lua[i].name);
    }
    return 1;
}

unsigned ui_guard_failures(void) { return g_guard_failures; }
const char *ui_guard_last_error(void) { return g_guard_err; }

static void register_lua(void)
{
    if (!g_lua_ok || !plua_state() || !plua_global_is_nil("FNN_Guard")) return;
    ui_register_glue(plua_state());
    log_line("UI Lua glue registered (%u functions)", (unsigned)(sizeof k_lua / sizeof *k_lua));
}

/* ---- the nation mission instance -------------------------------------- */
/* include.ini defines + registers the script on New Game and on Load, but
   mstart.ini (New Game only) is vanilla, so the DLL creates the one instance
   itself, guarded by GLOBALS.FNN_MISSION (saved with the game). Global_
   CreateMission (0x431B50) needs no mission context. */
static void mission_maintenance(void)
{
    static int attempts;
    if (!adapter_world_ready()) attempts = 0;      /* new world: allow a fresh try */
    if (!plua_state() || !game_running()) { g_mission_ok = 0; return; }
    int v = 0;
    if (!plua_eval_int("(FNN_SCRIPT == 1 and SCRIPT_TABLE ~= nil and SCRIPT_TABLE.fnn_nation ~= nil"
                       " and GLOBALS ~= nil) and 1 or 0", &v) || !v) {
        if (g_mission_ok) log_line("UI: nation mission script not loaded (scenario include.ini?)");
        g_mission_ok = 0;
        return;
    }
    v = 0;
    plua_eval_int("(GLOBALS.FNN_MISSION == 1) and 1 or 0", &v);
    if (!v && attempts < 3) {
        attempts++;
        int st = plua_run("Global_CreateMission(\"fnn_nation\", -1) GLOBALS.FNN_MISSION = 1");
        log_line("UI: created the nation mission (status %d)", st);
        v = st == 0;
    }
    g_mission_ok = v;
}

/* ---- hotkey ------------------------------------------------------------ */
static int foreground_is_ours(void)
{
    HWND fg = GetForegroundWindow();
    DWORD pid = 0;
    if (!fg) return 0;
    GetWindowThreadProcessId(fg, &pid);
    return pid == GetCurrentProcessId();
}

static void post_menu_event(void);

static void post_menu_event_sub(int sub)
{
    uint32_t ev[8] = {0};                          /* event is 0x1C bytes */
    unsigned before = g_menu_calls;
    PR2_GameMenuEvent(ev, FNN_MENU_ID, sub, 1, -1, -1);
    PR2_EventPost(GA_EVENT_DISPATCHER, ev);
    log_line("HOTKEY: nation menu event posted (%s)",
             g_menu_calls != before ? "handled" : "NOT handled: mission filter missing?");
}

static void poll_hotkey(void)
{
    if (!foreground_is_ours()) { g_key_down = 0; return; }
    int down = (GetAsyncKeyState(VK_CONTROL) & 0x8000) && (GetAsyncKeyState('N') & 0x8000)
               && !(GetAsyncKeyState(VK_MENU) & 0x8000);
    int edge = down && !g_key_down;
    g_key_down = down;
    if (!edge) return;
    if (!game_running()) { log_line("HOTKEY: ignored (no running game / paused)"); return; }
    DWORD t = GetTickCount();                     /* the nation panel (its founding page before founding) */
    if (t - g_last_post < 400) return;
    g_last_post = t;
    if (GetAsyncKeyState(VK_SHIFT) & 0x8000) {    /* Ctrl+Shift+N: the next national ship on the sea map */
        if (adapter_state()->founded) {
            panel_request_close();
            if (!sight_cycle()) ui_message("The nation has no fleets to show.");
        }
        return;
    }
    panel_toggle();
}

static void post_menu_event(void) { post_menu_event_sub(0); }

/* the founding dialog from the top-bar button (panel.c), with the hotkey's checks */
void ui_open_nation_menu(void)
{
    if (!game_running() || !g_can_menu || !g_mission_ok || !plua_state() || plua_global_is_nil("FNN_Guard")) {
        log_line("UI: nation menu not available (menu %d mission %d)", g_can_menu, g_mission_ok);
        return;
    }
    post_menu_event();
}

/* A conquest is ready for Annex/Withdraw: open the script's conquest popup
   (OnGameMenu sub = 1000 + town) as soon as the game is running. */
void ui_conquest_popup(int town) { g_conquest_popup = town; }

/* ---- engine.h entry points ------------------------------------------- */
void ui_init(void)
{
    /* Called from DllMain (loader lock): keep it trivial; the real setup runs
       on the first frame. */
    g_inited = 0;
}

void ui_frame(void)
{
    lazy_init();
    g_frame++;
    strings_flush();
    register_lua();
    if (g_frame % 30 == 0) mission_maintenance();
    poll_hotkey();
    if (g_conquest_popup >= 0 && game_running() && g_can_menu && g_mission_ok) {
        log_line("UI: conquest popup for town %d", g_conquest_popup);
        post_menu_event_sub(1000 + g_conquest_popup);
        g_conquest_popup = -1;
    }
    if (g_dev_menu) {
        g_dev_menu = 0;
        if (game_running() && g_can_menu && g_mission_ok) post_menu_event();
        else log_line("DEVMENU: ignored (running %d menu %d mission %d)", game_running(), g_can_menu, g_mission_ok);
    }
    flush_messages();
}
