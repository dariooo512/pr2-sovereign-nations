/* "FNN" string table registered with the game's string manager.
 *
 * Verified static facts (original-game/game/A2dLib-2.20A.dll, ImageBase
 * 0x10000000; reverse-engineering/_re/PR2.exe.unpacked.exe, ImageBase 0x400000):
 *  - PR2.exe registers its own table the same way: 0x4047B0 mov edx,[0x67F4D0]
 *    (IAT g_pStringMgr); mov ecx,[edx]; push size; push buf; push name;
 *    0x4047BF call [0x67F4CC] (IAT ?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z).
 *  - Add (export 0x10005A51 -> 0x10026C20) is thiscall, ret 0xC, and forwards to
 *    vfunc +0x4C AddStringRes (vtbl 0x100F48E8, slot -> 0x1002C9C0), which hands
 *    the buffer to CScreenStrings::LoadBuffer (0x10025E60): malloc + rep movsd,
 *    i.e. the data is COPIED; then map insert at this+0x10 -- inserting a name
 *    that already exists fails (logged, no crash), hence Remove before Add.
 *  - Remove (export 0x10001FC8 -> 0x10026D00) is thiscall, ret 4: vfunc +0x50
 *    (0x1002C7C0) finds the name in the map, deletes the CScreenStrings, erases.
 *  - Lookup by name (vfunc +8, 0x1002BB30): h=(h*0x71+movsx c) idiv 0x3B9AC9F7
 *    (remainder); then every table in the map is asked (0x1002C510 loop), each
 *    one binary-searches its entries (0x10025C90): count at blob+0, entries of
 *    16 bytes from blob+4, signed compare (jge), text at blob+4+offset with
 *    offset/len in BYTES (sar 1 -> wchar units, 0x10025CF0..0x10025D07).
 *    A hash of -1 is rejected (0x10025C9A).
 */
#include <windows.h>
#include <stdlib.h>
#include <string.h>
#include "strings.h"
#include "log.h"

typedef void (__attribute__((thiscall)) *SM_Add_t)(void *mgr, const char *name, const void *data, unsigned size);
typedef void (__attribute__((thiscall)) *SM_Remove_t)(void *mgr, const char *name);

#define A2D_DLL        "A2dLib-2.20A.dll"
#define A2D_G_STRMGR   "?g_pStringMgr@NA2dLib@@3PAVCStringManager@1@A"
#define A2D_SM_ADD     "?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z"
#define A2D_SM_REMOVE  "?Remove@CStringManager@NA2dLib@@QAEXPBD@Z"

typedef struct { char *id; char *text; int32_t hash; } Entry;

static Entry *g_e;
static int g_n, g_cap;
static int g_defaults_loaded;
static int g_dirty = 1;
static int g_registered;          /* our table is currently in the manager */
static int g_resolve_failed;

static void **g_ppmgr;            /* &NA2dLib::g_pStringMgr */
static SM_Add_t g_add;
static SM_Remove_t g_remove;

/* English defaults for every static UI text. Dynamic bodies (IDM_FNN_BODY,
   IDM_FNN_INFO_BODY, ...) are overwritten at runtime by the mission script
   through Nation_SetText. Keep '@' and '$' out of texts (mission placeholder
   syntax, resolver 0x436980). '<n>' = line break. */
static const char *const k_defaults[][2] = {
    /* headers */
    {"IDM_FNN_HDR_MAIN",      "Your Nation"},
    {"IDM_FNN_HDR_OVERVIEW",  "Nation Overview"},
    {"IDM_FNN_HDR_FOUND",     "Found a Nation"},
    {"IDM_FNN_HDR_DIPLO",     "Diplomacy"},
    {"IDM_FNN_HDR_WAR",       "Declaration of War"},
    {"IDM_FNN_HDR_TAXES",     "Taxes and Treasury"},
    {"IDM_FNN_HDR_GOV",       "Form of Government"},
    {"IDM_FNN_HDR_CONQUEST",  "Town Conquered"},
    {"IDM_FNN_HDR_INFO",      "Your Nation"},
    {"IDM_FNN_HDR_FINANCE",   "Treasury and Trade"},
    {"IDM_FNN_HDR_TREASURY",  "National Treasury"},
    {"IDM_FNN_HDR_WITHDRAW",  "Withdraw from the Treasury"},
    {"IDM_FNN_HDR_TARIFF",    "Import Tariff"},
    {"IDM_FNN_HDR_CONVOYS",   "National Convoys"},
    {"IDM_FNN_HDR_NAVY",      "National Navy"},
    {"IDM_FNN_HDR_DEFENCE",   "Town Defence"},
    /* buttons (at most 3 per popup: builder 0x57BEF1..0x57BF99) */
    {"IDM_FNN_BTN_FOUND",     "Found nation"},
    {"IDM_FNN_BTN_OVERVIEW",  "Overview"},
    {"IDM_FNN_BTN_DIPLO",     "Diplomacy"},
    {"IDM_FNN_BTN_MORE",      "More..."},
    {"IDM_FNN_BTN_TAXES",     "Taxes & treasury"},
    {"IDM_FNN_BTN_GOV",       "Government"},
    {"IDM_FNN_BTN_ADOPT",     "Adopt"},
    {"IDM_FNN_BTN_NEXTGOV",   "Next form"},
    {"IDM_FNN_BTN_BACK",      "Back"},
    {"IDM_FNN_BTN_CLOSE",     "Close"},
    {"IDM_FNN_BTN_OK",        "OK"},
    {"IDM_FNN_BTN_REPUBLIC",  "Republic"},
    {"IDM_FNN_BTN_KINGDOM",   "Kingdom"},
    {"IDM_FNN_BTN_FREESTATE", "Free State"},
    {"IDM_FNN_BTN_CONFIRM",   "Found it"},
    {"IDM_FNN_BTN_CANCEL",    "Cancel"},
    {"IDM_FNN_BTN_WAR",       "Declare war"},
    {"IDM_FNN_BTN_PEACE",     "Propose peace"},
    {"IDM_FNN_BTN_CEASEFIRE", "Offer ceasefire"},
    {"IDM_FNN_BTN_FLAGNEXT",  "Next flag"},
    {"IDM_FNN_BTN_FLAGSKIP",  "Skip 10"},
    {"IDM_FNN_BTN_FLAGTAKE",  "Fly this flag"},
    {"IDM_FNN_HDR_FLAG",      "Choose Your Colours"},
    {"IDM_FNN_BTN_NEXT",      "Next power"},
    {"IDM_FNN_BTN_LOWER",     "Lower 5%"},
    {"IDM_FNN_BTN_RAISE",     "Raise 5%"},
    {"IDM_FNN_BTN_DONE",      "Done"},
    {"IDM_FNN_BTN_ANNEX",     "Annex"},
    {"IDM_FNN_BTN_WITHDRAW",  "Withdraw"},
    {"IDM_FNN_BTN_TREASURY",  "Treasury"},
    {"IDM_FNN_BTN_TARIFF",    "Tariff"},
    {"IDM_FNN_BTN_CONVOYS",   "National convoys"},
    {"IDM_FNN_BTN_DONATE",    "Donate 10,000"},
    {"IDM_FNN_BTN_WITHDRAW_10K", "Withdraw 10,000"},
    {"IDM_FNN_BTN_APPLY",     "Apply"},
    {"IDM_FNN_BTN_NEXTPRESET", "Next preset"},
    {"IDM_FNN_BTN_CONVOY_ADD", "Add one"},
    {"IDM_FNN_BTN_CONVOY_REMOVE", "Remove one"},
    {"IDM_FNN_BTN_NAVY",      "Navy & defence"},
    {"IDM_FNN_BTN_FLEET_ADD", "Commission fleet"},
    {"IDM_FNN_BTN_ORDER",     "Change orders"},
    {"IDM_FNN_BTN_FLEET_REMOVE", "Pay off a fleet"},
    {"IDM_FNN_BTN_DEFENCE",   "Town defence"},
    {"IDM_FNN_BTN_REINFORCE", "Recruit soldiers"},
    {"IDM_FNN_BTN_TOWER",     "Build cannon tower"},
    /* static bodies */
    {"IDM_FNN_TXT_MAIN_NONE",
     "You do not lead a nation yet.<n><n>To found one, open the town that should become "
     "your capital (you must own property there), press Ctrl+N and choose Found nation."},
    {"IDM_FNN_TXT_NO_TOWN",
     "No town selected. Open the town view of the town that should become your capital "
     "(or select a convoy lying in its harbour), then press Ctrl+N again."},
    {"IDM_FNN_TXT_MORE",        "Further affairs of state."},
    {"IDM_FNN_TXT_MORE3",       "The form of government."},
    {"IDM_FNN_TXT_MORE2",
     "The national treasury and the import tariff; More... leads to the government.<n><n>"
     "Each page closes with Done; press Ctrl+N to return to the nation menu."},
    {"IDM_FNN_TXT_NOT_FOUNDED", "You do not lead a nation yet."},
    {"IDM_FNN_TXT_ERROR",       "The nation menu is not available right now."},
    /* dynamic placeholders (rewritten by the script before use) */
    {"IDM_FNN_BODY",            "..."},
    {"IDM_FNN_INFO_BODY",       "..."},
    {"IDM_FNN_HDR_DYN",         "Your Nation"},
};

int32_t strings_hash(const char *id)
{
    int32_t h = 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; p++) {
        uint32_t m = (uint32_t)h * 0x71u + (uint32_t)(int32_t)(signed char)*p;  /* imul/add wrap */
        h = (int32_t)m % 999999991;   /* idiv 0x3B9AC9F7 = 999999991 (NOT 1000000503 as research/ui_entry.md says) */
    }
    return h;
}

static char *dupstr(const char *s)
{
    size_t n = strlen(s) + 1;
    char *d = malloc(n);
    if (d) memcpy(d, s, n);
    return d;
}

static Entry *find(const char *id)
{
    for (int i = 0; i < g_n; i++)
        if (strcmp(g_e[i].id, id) == 0) return &g_e[i];
    return NULL;
}

static int put(const char *id, const char *text)
{
    if (!id || !id[0]) return 0;
    if (!text) text = "";
    Entry *e = find(id);
    if (e) {
        if (strcmp(e->text, text) == 0) return 1;
        char *t = dupstr(text);
        if (!t) return 0;
        free(e->text);
        e->text = t;
        g_dirty = 1;
        return 1;
    }
    int32_t h = strings_hash(id);
    if (h == -1) { log_line("STRINGS: id %s hashes to -1 (unusable)", id); return 0; }
    for (int i = 0; i < g_n; i++)
        if (g_e[i].hash == h) {
            log_line("STRINGS: hash collision %s vs %s; %s ignored", id, g_e[i].id, id);
            return 0;
        }
    if (g_n == g_cap) {
        int nc = g_cap ? g_cap * 2 : 64;
        Entry *ne = realloc(g_e, (size_t)nc * sizeof *ne);
        if (!ne) return 0;
        g_e = ne;
        g_cap = nc;
    }
    e = &g_e[g_n];
    e->id = dupstr(id);
    e->text = dupstr(text);
    if (!e->id || !e->text) { free(e->id); free(e->text); return 0; }
    e->hash = h;
    g_n++;
    g_dirty = 1;
    return 1;
}

static void load_defaults(void)
{
    if (g_defaults_loaded) return;
    g_defaults_loaded = 1;
    for (unsigned i = 0; i < sizeof k_defaults / sizeof *k_defaults; i++)
        put(k_defaults[i][0], k_defaults[i][1]);
}

static int cmp_hash(const void *a, const void *b)
{
    int32_t x = ((const Entry *)a)->hash, y = ((const Entry *)b)->hash;
    return x < y ? -1 : x > y;
}

uint8_t *strings_build_blob(uint32_t *size_out)
{
    load_defaults();
    *size_out = 0;
    qsort(g_e, (size_t)g_n, sizeof *g_e, cmp_hash);   /* signed ascending: 0x10025CBF jge */
    /* UTF-16 length of every text */
    uint32_t total = 0;
    int *wl = calloc((size_t)(g_n ? g_n : 1), sizeof *wl);
    if (!wl) return NULL;
    for (int i = 0; i < g_n; i++) {
        int n = g_e[i].text[0] ? MultiByteToWideChar(CP_UTF8, 0, g_e[i].text, -1, NULL, 0) - 1 : 0;
        wl[i] = n < 0 ? 0 : n;
        total += (uint32_t)wl[i] * 2;
    }
    uint32_t hdr = 4 + 16u * (uint32_t)g_n;
    uint32_t size = hdr + total;
    uint8_t *blob = calloc(1, size + 2);
    if (!blob) { free(wl); return NULL; }
    uint32_t *u = (uint32_t *)blob;
    u[0] = (uint32_t)g_n;
    uint32_t off = 16u * (uint32_t)g_n;               /* text offset counted from byte 4 */
    for (int i = 0; i < g_n; i++) {
        uint32_t *rec = u + 1 + 4 * i;
        rec[0] = (uint32_t)g_e[i].hash;
        rec[1] = off;
        rec[2] = 0;                                    /* nargs: we use no %n arguments */
        rec[3] = (uint32_t)wl[i] * 2;
        if (wl[i]) {
            wchar_t *dst = (wchar_t *)(blob + 4 + off);
            MultiByteToWideChar(CP_UTF8, 0, g_e[i].text, -1, dst, wl[i] + 1);
            /* the terminator lands on the next text (overwritten next) or the pad */
        }
        off += (uint32_t)wl[i] * 2;
    }
    free(wl);
    *size_out = size;
    return blob;
}

static int resolve(void)
{
    if (g_add && g_remove && g_ppmgr) return 1;
    if (g_resolve_failed) return 0;
    HMODULE a2d = GetModuleHandleA(A2D_DLL);
    if (!a2d) return 0;                              /* host test / too early */
    g_ppmgr = (void **)GetProcAddress(a2d, A2D_G_STRMGR);
    g_add = (SM_Add_t)(void *)GetProcAddress(a2d, A2D_SM_ADD);
    g_remove = (SM_Remove_t)(void *)GetProcAddress(a2d, A2D_SM_REMOVE);
    if (!g_ppmgr || !g_add || !g_remove) {
        log_line("STRINGS: A2dLib exports missing (mgr %p add %p remove %p); table disabled",
                 (void *)g_ppmgr, (void *)g_add, (void *)g_remove);
        g_resolve_failed = 1;
        return 0;
    }
    return 1;
}

int strings_flush(void)
{
    load_defaults();
    if (!g_dirty && g_registered) return 1;
    if (!resolve()) return 0;
    void *mgr = *g_ppmgr;
    if (!mgr) return 0;                              /* manager not constructed yet */
    uint32_t size;
    uint8_t *blob = strings_build_blob(&size);
    if (!blob) return 0;
    if (g_registered)
        g_remove(mgr, FNN_STRING_TABLE);
    g_add(mgr, FNN_STRING_TABLE, blob, size);        /* copies the buffer (LoadBuffer) */
    free(blob);
    if (!g_registered)
        log_line("STRINGS: table '%s' registered (%d strings, %u bytes)", FNN_STRING_TABLE, g_n, size);
    g_registered = 1;
    g_dirty = 0;
    return 1;
}

int strings_registered(void) { return g_registered && !g_dirty; }

int strings_set(const char *id, const char *utf8_text)
{
    load_defaults();
    if (!put(id, utf8_text)) return 0;
    if (g_dirty) strings_flush();
    return 1;
}

const char *strings_get(const char *id)
{
    load_defaults();
    Entry *e = find(id);
    return e ? e->text : NULL;
}
