/* Two flags, kept apart (the two-flags change, research/flags.md section 8).
 *
 * The player's own flag is the game's company logo %APPDATA%\Ascaron
 * Entertainment\Port Royale 2\Run\0.bmp (chosen at New Game, saved inside the
 * savegame). The mod never writes it. The nation's flag is a second file in the
 * same folder, Run\7.bmp, copied from <exe dir>\nation_flags\flag_NNN.bmp on
 * founding, on a flag change and on every load.
 *
 * Vanilla draws Run\0.bmp for every convoy of nation 5 -- the player's convoys
 * and, in this mod, the nation's fleets too -- and for nation-5 towns. Each of
 * those sites is told apart here:
 *   convoys: national = a fleet of the nation (nation 5, military type 4/9) or a
 *     player convoy designated national (sight_is_national). At the string sites
 *     the pushed "0.bmp" becomes "7.bmp", so the game builds Run\7.bmp itself:
 *       0x50C7CE convoy flag name (convoy lists, port, info bar, battle dialogs)
 *       0x485C5E selection panel     0x47D4A0/0x47D62B interface bar (own convoy)
 *       0x596721 sea-map ship marker (fed by 0x5A2EE9; per-marker reload)
 *     3D sails and mast flags: the sail index (0 = Run\Player0.aim, composited
 *     by WalExtPR2 from Run\0.bmp) becomes 7 (Run\Player7.aim from Run\7.bmp):
 *       0x63DEF5 (port scene re-flag), 0x570EED (port scene ship created; the convoy
 *       handle is taken at the entry 0x570D40).
 *     0x4FAB85 battle dialog: nation-icon slot 5 is the nation's flag (towns),
 *     so a player convoy there gets "-userflag-" (= Run\0.bmp) back.
 *   towns: nation-icon slot 5 (0x6E1300) -> Run\7.bmp (top bar, town list,
 *     selection panel, town info and siege dialogs); the sea-map town marker
 *     0x590289 loads 7.bmp; the trade window 0x594A0F shows 7.bmp for a nation-5
 *     town (0x46314B). The town info dialog of a vanilla player town (bit 22)
 *     keeps the player's logo (0x4A40E8, 0x4A4143, 0x4A41C4).
 *
 * WalExtPR2 composites Run\Player<k>.aim once and caches it (0x1000BDA0). Its
 * entry is hooked: when Run\<k>.bmp was rewritten since the cached copy was made,
 * the cache slot is dropped and the texture is composited again.
 *
 * Designating or releasing a national convoy re-flags its ships in port and redraws
 * the interface bar at once (flag_convoy_changed). With NATION_CONVOYS 0 (this version)
 * no player convoy is national, so every player convoy flies the player's logo; a
 * loaded save's former national convoys are re-flagged once at world ready (sight.c).
 *
 * Saves from before this change carry the nation's flag as the player logo (the
 * old flag_apply copied it over Run\0.bmp). After such a load, Run\0.bmp is put
 * back from Run\0_company_logo.bmp (the player's own logo, kept once before the
 * first overwrite) when that copy exists; otherwise what is there stays.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "flag.h"
#include "hook.h"
#include "log.h"
#include "adapter.h"
#include "sight.h"

#define TC __attribute__((thiscall))

#define ICON_TABLE_SLOT5 ((const char **)0x006E1300)
#define USERFLAG_STR     ((const char *)0x00689970)   /* "-userflag-": CFlag turns it into Run\0.bmp */
#define LOGO_NAME_STR    ((const char *)0x0068DB0C)   /* "0.bmp" */
#define NATION_SLOT      7                            /* Run\7.bmp, Run\Player7.aim */
static const char k_nation_name[] = "7.bmp";

#define CONVOY_TABLE     0x00701EE8u   /* {u32 *slots, u16 *gen (+2 per slot), u16 count} */
#define K_TYPE           0xB4
#define K_NATION         0xB8
#define K_HANDLE         0xA8
#define K_GROUP          0x4C
#define T_FLAGS          0x40          /* CStadt+0x40 bit 22: a vanilla player town */
#define SEAMAP_HOLDER    0x00701424u   /* +0x268: the nation-5 town marker image (loaded once) */

#define PATHBUF (MAX_PATH * 2)
static char g_logo[PATHBUF];           /* Run\0.bmp */
static char g_nation[PATHBUF];         /* Run\7.bmp */
static char g_keep[PATHBUF];           /* Run\0_company_logo.bmp */
static int g_ready;                    /* Run\7.bmp holds the nation's flag of the current game */
static int g_pending;                  /* frames until the after-load step (0 = none) */
static int g_ui_live;                  /* the world is up: the interface bar may be redrawn */
static unsigned g_gen[8];              /* bumped whenever Run\<k>.bmp is rewritten */
static unsigned g_seen[8];             /* g_gen[k] when WalExtPR2 last composited Player<k>.aim */
static unsigned long g_hits[16];       /* per site: how often a national ship got the nation's flag */
enum { S_NAME, S_SEL, S_IFB, S_TRADE, S_SEA, S_SAIL, S_BATTLE_PLAYER, S_TINFO, S_MARK, S_WALEXT, S_RELOAD,
       S_SEA_ALL, S_SEA_AGAIN };

static void refresh_infobar(void);

static int run_dir(char *out, int cap)
{
    char app[MAX_PATH];
    DWORD n = GetEnvironmentVariableA("APPDATA", app, sizeof app);
    if (!n || n >= sizeof app) return 0;
    snprintf(out, cap, "%s\\Ascaron Entertainment\\Port Royale 2\\Run", app);
    return 1;
}

static int paths(void)
{
    if (g_logo[0]) return 1;
    char dir[MAX_PATH + 64];
    if (!run_dir(dir, sizeof dir)) return 0;
    snprintf(g_logo, sizeof g_logo, "%s\\0.bmp", dir);
    snprintf(g_nation, sizeof g_nation, "%s\\%s", dir, k_nation_name);
    snprintf(g_keep, sizeof g_keep, "%s\\0_company_logo.bmp", dir);
    return 1;
}

const char *flag_logo_path(void) { paths(); return g_logo; }

/* <game>\nation_flags\flag_NNN.bmp */
const char *flag_bmp_path(int index)
{
    static char src[PATHBUF];
    DWORD n = GetModuleFileNameA(NULL, src, MAX_PATH);
    while (n && src[n - 1] != '\\') n--;
    snprintf(src + n, MAX_PATH - n, "nation_flags\\flag_%03d.bmp", index);
    return src;
}

const char *flag_nation_path(void)
{
    paths();
    return g_ready ? g_nation : flag_bmp_path(adapter_state()->flag);
}

int flag_nation_ready(void) { return g_ready; }

static int same_file(const char *a, const char *b)
{
    HANDLE fa = CreateFileA(a, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    HANDLE fb = CreateFileA(b, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    int same = 0;
    if (fa != INVALID_HANDLE_VALUE && fb != INVALID_HANDLE_VALUE) {
        DWORD sa = GetFileSize(fa, NULL), sb = GetFileSize(fb, NULL);
        if (sa == sb && sa != INVALID_FILE_SIZE && sa < (1u << 22)) {
            static char ba[1u << 16], bb[1u << 16];
            same = 1;
            for (DWORD left = sa; left && same; ) {
                DWORD want = left < sizeof ba ? left : sizeof ba, ra = 0, rb = 0;
                if (!ReadFile(fa, ba, want, &ra, NULL) || !ReadFile(fb, bb, want, &rb, NULL) ||
                    ra != want || rb != want || memcmp(ba, bb, want))
                    same = 0;
                left -= want;
            }
        }
    }
    if (fa != INVALID_HANDLE_VALUE) CloseHandle(fa);
    if (fb != INVALID_HANDLE_VALUE) CloseHandle(fb);
    return same;
}

static void make_dirs(void)
{
    char dir[MAX_PATH + 64];
    if (!run_dir(dir, sizeof dir)) return;
    for (char *p = strchr(dir + 3, '\\'); ; p = strchr(p + 1, '\\')) {   /* every level: a fresh PC has none */
        if (p) *p = '\0';
        CreateDirectoryA(dir, NULL);
        if (!p) break;
        *p = '\\';
    }
}

/* the sea-map town marker keeps the first image it loaded: drop it (a 96x64 image is
   left behind) so the next draw loads the new Run\7.bmp */
static void drop_town_marker(void)
{
    uint8_t *holder = *(uint8_t **)(uintptr_t)SEAMAP_HOLDER;
    if (holder && !IsBadWritePtr(holder + 0x268, 4) && *(void **)(holder + 0x268)) {
        *(void **)(holder + 0x268) = NULL;
        log_line("FLAG: sea-map town marker image dropped (reloads with the new flag)");
    }
}

int flag_apply(int index)
{
    char src[PATHBUF];
    snprintf(src, sizeof src, "%s", flag_bmp_path(index));
    if (GetFileAttributesA(src) == INVALID_FILE_ATTRIBUTES) {
        log_line("FLAG %d: %s missing (install the mod's nation_flags folder)", index, src);
        g_ready = 0;
        return 0;
    }
    if (!paths()) return 0;
    make_dirs();
    int changed = !same_file(src, g_nation);
    if (changed && !CopyFileA(src, g_nation, FALSE)) {
        log_line("FLAG %d: copy to %s failed (%lu)", index, g_nation, GetLastError());
        g_ready = 0;
        return 0;
    }
    if (changed || !g_ready) {
        g_gen[NATION_SLOT]++;
        drop_town_marker();
    }
    g_ready = 1;
    log_line("FLAG %d -> %s%s", index, g_nation, changed ? "" : " (unchanged)");
    return 1;
}

void flag_reset(void)
{
    g_ready = 0;
    g_pending = 0;
    g_ui_live = 0;
}

void flag_world_ready(int founded, int index)
{
    if (!founded) { g_ready = 0; g_ui_live = 1; return; }
    flag_apply(index);
    g_ui_live = 0;                     /* load-time designations: the after-load step redraws */
    g_pending = 3;                     /* the load copies the save's logo to Run\0.bmp after this */
}

/* ---- the convoy pool ----------------------------------------------------------------- */
static uint8_t *convoy_by_handle(uint32_t h)
{
    uint32_t *hdr = (uint32_t *)(uintptr_t)CONVOY_TABLE;
    uint32_t idx = h & 0xFFFF, n = hdr[2] & 0xFFFF;
    if (idx >= n || !hdr[0] || !hdr[1]) return NULL;
    uint16_t gen = *(uint16_t *)(uintptr_t)(hdr[1] + idx * 4 + 2);
    if ((gen ^ (h >> 21)) & 0x7FF) return NULL;
    return *(uint8_t **)(uintptr_t)(hdr[0] + idx * 4);
}

static int national(const uint8_t *k)
{
    return g_ready && k && k[K_NATION] == 5 && sight_is_national(k);
}

static uint32_t pool_handle(const uint8_t *k)
{
    return (*(const uint32_t *)(k + K_HANDLE) & ~(0x1Fu << 16)) | (2u << 16);
}

/* ---- string sites: "0.bmp" was just pushed as the name to build Run\<name> from ---- */
static void swap_name(Regs *r, int site)
{
    uint32_t *sp = (uint32_t *)(uintptr_t)r->esp;
    if (sp[0] == (uint32_t)(uintptr_t)LOGO_NAME_STR) {
        sp[0] = (uint32_t)(uintptr_t)k_nation_name;
        g_hits[site]++;
    }
}

static void on_convoy_name(Regs *r) { if (national((uint8_t *)(uintptr_t)r->esi)) swap_name(r, S_NAME); }
static void on_selection(Regs *r)   { if (national((uint8_t *)(uintptr_t)r->esi)) swap_name(r, S_SEL); }

/* interface bar (fn 0x47C930, esi = the bar): the shown convoy is the handle at +0x1AC; the
   player's own convoy shows Run\0.bmp in the logo image (+0x2C4) */
static void on_ifb(Regs *r)
{
    uint8_t *bar = (uint8_t *)(uintptr_t)r->esi;
    if (g_ready && bar && national(convoy_by_handle(*(uint32_t *)(bar + 0x1AC)))) swap_name(r, S_IFB);
}

/* trade window: 0x463120 the caller starts, 0x46314B a town's own flag (eax = town lager),
   0x594A0F the flag widget builds Run\0.bmp */
static int g_trade_town5;
static void on_trade_start(Regs *r) { (void)r; g_trade_town5 = 0; }
static void on_trade_town(Regs *r)  { g_trade_town5 = *(uint8_t *)(uintptr_t)(r->eax + 0x358) == 5; }
static void on_trade_flag(Regs *r)
{
    if (g_ready && g_trade_town5) swap_name(r, S_TRADE);
    g_trade_town5 = 0;
}

/* sea-map ship marker: 0x5A2EE9 (esi = convoy, edi = marker) feeds 0x5966C0(nation), which
   loads Run\0.bmp for nation 5 once per marker (+0x141 loaded, +0xA0 cached nation). A
   marker whose image is of the other kind is reset so it loads again. */
#define NMARK 512
static struct { void *m; unsigned gen; uint8_t nat; } g_mark[NMARK];
static int g_icon_nat;

static int mark_slot(void *m, int add)
{
    unsigned h = ((uint32_t)(uintptr_t)m >> 4) % NMARK;
    for (int i = 0; i < NMARK; i++, h = (h + 1) % NMARK) {
        if (g_mark[h].m == m) return (int)h;
        if (!g_mark[h].m) {
            if (!add) return -1;
            g_mark[h].m = m;
            return (int)h;
        }
    }
    if (add) { memset(g_mark, 0, sizeof g_mark); return mark_slot(m, 1); }
    return -1;
}

static void on_sea_marker_feed(Regs *r)
{
    uint8_t *k = (uint8_t *)(uintptr_t)r->esi, *m = (uint8_t *)(uintptr_t)r->edi;
    g_icon_nat = national(k);
    if (!k || !m || k[K_NATION] != 5 || *(uint32_t *)(m + 0xA0) != 5 || !m[0x141]) return;
    int s = mark_slot(m, 0);
    unsigned gen = g_icon_nat ? g_gen[NATION_SLOT] : g_gen[0];
    if (s < 0 ? g_icon_nat || g_gen[0] : (g_mark[s].nat != g_icon_nat || g_mark[s].gen != gen)) {
        *(uint32_t *)(m + 0xA0) = 0xFFFFFFFFu;     /* forget the cached nation ... */
        m[0x141] = 0;                              /* ... and the loaded logo */
        g_hits[S_RELOAD]++;
    }
}

static void on_sea_marker_load(Regs *r)
{
    uint8_t *m = (uint8_t *)(uintptr_t)r->esi;
    g_hits[S_SEA_ALL]++;                           /* every nation-5 marker logo load */
    if (g_icon_nat) swap_name(r, S_SEA);
    if (mark_slot(m, 0) >= 0) g_hits[S_SEA_AGAIN]++;   /* the same marker loads again */
    int s = mark_slot(m, 1);
    g_mark[s].nat = (uint8_t)g_icon_nat;
    g_mark[s].gen = g_icon_nat ? g_gen[NATION_SLOT] : g_gen[0];
}

/* 3D sails: 0x63DEF5 (edi = convoy, cl = nation) and 0x570EED (bl = nation; the convoy
   handle was argument 2 of 0x570D40) compute the sail index, 0 for nation 5 */
static uint32_t on_sail_scene(Regs *r)
{
    if ((r->ecx & 0xFF) != 5 || !national((uint8_t *)(uintptr_t)r->edi)) return 0;
    r->edx = NATION_SLOT;
    r->ecx = 5;
    g_hits[S_SAIL]++;
    return 0x0063DF04;                 /* push edx; push ecx; mov ecx,eax; call SetSail 0x56FE60 */
}

/* 0x570D40(type, convoy handle, nation, ...) reuses the handle's stack slot for the new ship
   object (0x570DCD), so the handle is taken at the entry */
static uint32_t g_new_ship_convoy;
static void on_ship_new_entry(Regs *r) { g_new_ship_convoy = stack_arg(r, 2); }

static uint32_t on_sail_new(Regs *r)
{
    if ((r->ebx & 0xFF) != 5 || !national(convoy_by_handle(g_new_ship_convoy))) return 0;
    r->ecx = NATION_SLOT;
    g_hits[S_SAIL]++;
    return 0x00570EF9;                 /* push ecx; movzx ecx,bl; push ecx; ...; call 0x56FE60 */
}

/* battle dialogs 0x4FAA60 (esi = convoy): nation <4 or 5 -> nation-icon table -> CFlag */
static void on_battle_flag(Regs *r)
{
    const uint8_t *k = (const uint8_t *)(uintptr_t)r->esi;
    if (k && k[K_NATION] == 5 && r->edx == (uint32_t)(uintptr_t)*ICON_TABLE_SLOT5 &&
        *ICON_TABLE_SLOT5 != USERFLAG_STR && !national(k)) {
        r->edx = (uint32_t)(uintptr_t)USERFLAG_STR;
        g_hits[S_BATTLE_PLAYER]++;
    }
}

/* town info dialog 0x4A3610: a vanilla player town (bit 22) takes index 5 too */
static int g_tinfo_user;
static void on_tinfo_index(Regs *r)
{
    const uint8_t *t = *(const uint8_t **)(uintptr_t)(r->esp + 0x1C);
    g_tinfo_user = r->eax == 5 && t && ((*(const uint32_t *)(t + T_FLAGS) >> 22) & 1);
}
static void on_tinfo_flag(Regs *r)
{
    if (g_tinfo_user && r->eax == (uint32_t)(uintptr_t)*ICON_TABLE_SLOT5 && *ICON_TABLE_SLOT5 != USERFLAG_STR) {
        r->eax = (uint32_t)(uintptr_t)USERFLAG_STR;
        g_hits[S_TINFO]++;
    }
}

/* sea-map town marker of a nation-5 town (CSeekarteStadt index 4) */
static void on_town_marker(Regs *r) { if (g_ready) swap_name(r, S_MARK); }

/* ---- WalExtPR2 0x1000BDA0(this = sail cache, k): Player<k>.aim, composited when the slot is empty */
#define WALEXT_GET_SAIL_RVA 0xBDA0
static void on_walext_sail(Regs *r)
{
    uint32_t k = stack_arg(r, 1);
    uint8_t *cache = (uint8_t *)(uintptr_t)r->ecx;
    if (k >= 8 || !cache) return;
    void **slot = (void **)(cache + 0x14 + 4 * k);
    if (*slot && g_seen[k] != g_gen[k]) {
        *slot = NULL;                  /* left to the engine: ships built with it keep it */
        g_hits[S_WALEXT]++;
        log_line("FLAG: sail texture Player%u.aim made again (Run\\%u.bmp changed)", k, k);
    }
    if (!*slot) g_seen[k] = g_gen[k];
}

/* ---- port scenes: re-flag a convoy's ships (vanilla does this on owner changes) ----- */
typedef uint8_t *(TC *TownOf_t)(void *group);
typedef void (TC *SetSails_t)(void *scene, uint32_t convoy_h);
#define ConvoyTown ((TownOf_t)0x00635C40)      /* ecx = convoy+0x4C; the town it lies in, or 0 */
#define SceneFlag  ((SetSails_t)0x0063DE20)    /* ecx = town+0x20; ret 4 */

void flag_convoy_changed(void *convoy)
{
    uint8_t *k = (uint8_t *)convoy;
    if (!k || k[K_NATION] != 5) return;
    uint8_t *t = ConvoyTown(k + K_GROUP);
    if (t) SceneFlag(t + 0x20, pool_handle(k));
    refresh_infobar();
}

static void reflag_all(void)
{
    uint32_t *hdr = (uint32_t *)(uintptr_t)CONVOY_TABLE;
    uint32_t *slots = (uint32_t *)(uintptr_t)hdr[0];
    int n = (int)(hdr[2] & 0xFFFF);
    for (int i = 0; slots && i < n; i++)
        if (slots[i]) flag_convoy_changed((void *)(uintptr_t)slots[i]);
}

/* the interface bar reloads the player's logo (what the game does after a load / logo change) */
typedef void **(*GetApp_t)(void);
typedef void (TC *Refresh_t)(void *self);
#define GetApp        ((GetApp_t)0x00403360)
#define LogoRefresh   ((Refresh_t)0x005003D0)

static void refresh_logo_ui(void)
{
    void **app = GetApp();
    uint8_t *a = app ? (uint8_t *)*app : NULL;
    void *ui = a ? *(void **)(a + 0xEC) : NULL;
    if (ui) LogoRefresh(ui);
}

/* the interface bar (ui+0x54 -> +0x104; the class of 0x47C930/0x4784F0) shows the selected convoy
   (+0x1AC) in modes 0 and 4 and redraws its flag only when it changes: redraw it now */
#define InfoBarConvoy ((Refresh_t)0x0047C930)
static void refresh_infobar(void)
{
    void **app = GetApp();
    uint8_t *a = app ? (uint8_t *)*app : NULL;
    uint8_t *ui = a ? *(uint8_t **)(a + 0xEC) : NULL;
    uint8_t *x = ui ? *(uint8_t **)(ui + 0x54) : NULL;
    uint8_t *bar = x ? *(uint8_t **)(x + 0x104) : NULL;
    if (!g_ui_live || !bar || (*(uint32_t *)(bar + 0x1AC) & 0xFFFF) == 0xFFFF) return;
    uint32_t mode = *(uint32_t *)(bar + 0x2DC);
    if (mode != 0 && mode != 4) return;
    LogoRefresh(ui);                   /* forget the shown images ... */
    InfoBarConvoy(bar);                /* ... and draw the convoy's flag again */
}

/* after a load: the save's logo is in Run\0.bmp now */
static void after_load(void)
{
    NationState *s = adapter_state();
    g_ui_live = 1;
    if (!s->founded || !paths()) return;
    const char *nat = flag_bmp_path(s->flag);
    if (same_file(g_logo, nat)) {
        if (GetFileAttributesA(g_keep) != INVALID_FILE_ATTRIBUTES && !same_file(g_keep, nat) &&
            CopyFileA(g_keep, g_logo, FALSE)) {
            log_line("FLAG: this save had the nation's flag as the player logo; your own logo is back (from %s)", g_keep);
            adapter_message("Your own flag is back on your ships. The nation's flag now flies on its fleets and towns.");
        } else {
            log_line("FLAG: this save has the nation's flag as the player logo and no earlier logo is kept; left as it is");
        }
    }
    g_gen[0]++;                        /* the load wrote the save's logo: composite Player0.aim again */
    refresh_logo_ui();
    reflag_all();
    refresh_infobar();
}

static void dev_view_tick(void);

/* WalExtPR2 may load after this DLL: hooked from the frame tick once it is there */
static void install_walext(void)
{
    static int tries;
    if (tries < 0 || ++tries > 600) return;
    HMODULE wx = GetModuleHandleA("WalExtPR2.dll");
    if (!wx) {
        if (tries == 600) log_line("FLAG: WalExtPR2.dll not found; sail textures are not re-made on a flag change");
        return;
    }
    tries = -1;
    uint32_t at = (uint32_t)(uintptr_t)wx + WALEXT_GET_SAIL_RVA, eh = (uint32_t)(uintptr_t)wx + 0x24F91;
    uint8_t b[7] = {0x6A, 0xFF, 0x68};                     /* push -1; push <EH handler> */
    memcpy(b + 3, &eh, 4);
    hook_install("flag.WalExtSail", at, b, sizeof b, on_walext_sail);
}

void flag_init(void)
{
    static int done;
    install_walext();
    dev_view_tick();
    if (g_pending && --g_pending == 0) after_load();
    if (done) return;
    done = 1;
    const char *cur = *ICON_TABLE_SLOT5;
    if (IsBadReadPtr(cur, 11) || memcmp(cur, "-userflag-", 11) != 0) {
        log_line("FLAG: nation-icon slot 5 is not \"-userflag-\"; left alone");
        return;
    }
    if (!paths()) return;
    *ICON_TABLE_SLOT5 = g_nation;
    log_line("FLAG: nation-icon slot 5 -> %s", g_nation);
}

void flag_install(void)
{
    static const uint8_t name_b[]  = {0x8D, 0x4C, 0x24, 0x40, 0xC6, 0x44, 0x24, 0x54, 0x02};
    static const uint8_t sel_b[]   = {0x8D, 0x4C, 0x24, 0x38, 0xC6, 0x44, 0x24, 0x4C, 0x02};
    static const uint8_t ifb1_b[]  = {0x8D, 0x4C, 0x24, 0x5C, 0xC7, 0x44, 0x24, 0x7C, 0x15, 0x00, 0x00, 0x00};
    static const uint8_t ifb2_b[]  = {0x8D, 0x4C, 0x24, 0x44, 0xC7, 0x44, 0x24, 0x7C, 0x1B, 0x00, 0x00, 0x00};
    static const uint8_t tr0_b[]   = {0x8B, 0x46, 0x6C, 0x85, 0xC0};
    static const uint8_t tr1_b[]   = {0x33, 0xC9, 0x8A, 0x88, 0x58, 0x03, 0x00, 0x00};
    static const uint8_t tr2_b[]   = {0x8D, 0x4C, 0x24, 0x30, 0xC6, 0x44, 0x24, 0x44, 0x01};
    static const uint8_t seaf_b[]  = {0x0F, 0xB6, 0x96, 0xB8, 0x00, 0x00, 0x00};
    static const uint8_t seal_b[]  = {0x8D, 0x4C, 0x24, 0x40, 0xC7, 0x44, 0x24, 0x54, 0x01, 0x00, 0x00, 0x00};
    static const uint8_t sail1_b[] = {0x33, 0xD2, 0x80, 0xF9, 0x05, 0x0F, 0x94, 0xC2};
    static const uint8_t sail2_b[] = {0x33, 0xC9, 0x80, 0xFB, 0x05, 0x0F, 0x94, 0xC1};
    static const uint8_t bat_b[]   = {0xC7, 0x44, 0x24, 0x28, 0x00, 0x00, 0x00, 0x00};
    static const uint8_t ti0_b[]   = {0x99, 0xB9, 0x06, 0x00, 0x00, 0x00};
    static const uint8_t ti1_b[]   = {0x83, 0xEC, 0x0C, 0x8B, 0xCC};
    static const uint8_t mark_b[]  = {0x8D, 0x4C, 0x24, 0x28, 0xC7, 0x44, 0x24, 0x68, 0x01, 0x00, 0x00, 0x00};
    hook_install("flag.ConvoyName", 0x0050C7CE, name_b, sizeof name_b, on_convoy_name);
    hook_install("flag.Selection", 0x00485C5E, sel_b, sizeof sel_b, on_selection);
    hook_install("flag.InfoBarLogo", 0x0047D4A0, ifb1_b, sizeof ifb1_b, on_ifb);
    hook_install("flag.InfoBarLogoLoad", 0x0047D62B, ifb2_b, sizeof ifb2_b, on_ifb);
    hook_install("flag.TradeStart", 0x00463120, tr0_b, sizeof tr0_b, on_trade_start);
    hook_install("flag.TradeTown", 0x0046314B, tr1_b, sizeof tr1_b, on_trade_town);
    hook_install("flag.TradeFlag", 0x00594A0F, tr2_b, sizeof tr2_b, on_trade_flag);
    hook_install("flag.SeaMarkerFeed", 0x005A2EE9, seaf_b, sizeof seaf_b, on_sea_marker_feed);
    hook_install("flag.SeaMarkerLoad", 0x00596721, seal_b, sizeof seal_b, on_sea_marker_load);
    hook_install_jmp("flag.SailScene", 0x0063DEF5, sail1_b, sizeof sail1_b, on_sail_scene);
    static const uint8_t ship_b[]  = {0x6A, 0xFF, 0x68, 0x5B, 0xAB, 0x66, 0x00};   /* push -1; push 0x66AB5B */
    if (hook_install("flag.ShipNew", 0x00570D40, ship_b, sizeof ship_b, on_ship_new_entry))
        hook_install_jmp("flag.SailNew", 0x00570EED, sail2_b, sizeof sail2_b, on_sail_new);
    hook_install("flag.BattleConvoy", 0x004FAB85, bat_b, sizeof bat_b, on_battle_flag);
    hook_install("flag.TownInfoIndex", 0x004A40E8, ti0_b, sizeof ti0_b, on_tinfo_index);
    hook_install("flag.TownInfoFlagL", 0x004A4143, ti1_b, sizeof ti1_b, on_tinfo_flag);
    hook_install("flag.TownInfoFlagR", 0x004A41C4, ti1_b, sizeof ti1_b, on_tinfo_flag);
    hook_install("flag.TownMarker", 0x00590289, mark_b, sizeof mark_b, on_town_marker);

}

/* tests: enter a town view (VC+0x54 = town handle, SetView 2) or the sea map (1), next frame */
typedef void (TC *SetView_t)(void *vc, int view);
#define SetView ((SetView_t)0x0051CAA0)
static int g_view_req;
static uint32_t g_view_town;

int flag_dev_view(int view, uint32_t town_h)
{
    if (view != 1 && view != 2) return 0;
    g_view_req = view;
    g_view_town = town_h;
    return 1;
}

static void dev_view_tick(void)
{
    if (!g_view_req) return;
    int v = g_view_req;
    g_view_req = 0;
    void **app = GetApp();
    uint8_t *a = app ? (uint8_t *)*app : NULL, *vc = a ? *(uint8_t **)(a + 0xF0) : NULL;
    if (!vc) return;
    if (v == 2) *(uint32_t *)(vc + 0x54) = g_view_town;
    log_line("FLAG(dev): view %d (town %08X)", v, g_view_town);
    SetView(vc, v);
}

int flag_dev(unsigned long *hits, int n)
{
    for (int i = 0; i < n && i < 16; i++) hits[i] = g_hits[i];
    return g_ready;
}
