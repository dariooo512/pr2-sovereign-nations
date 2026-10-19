/* National ships on the sea map (the national-ships-on-the-sea-map change).
 *
 * Fog of war (research/sea_map_sight.md). Every map object (convoy, town, sea
 * marker) is a node of one list sorted by x: +0x0E x, +0x12 y, +0x14 next, +0x18
 * previous, +0x1C visible now, +0x1D visible in the last pass. The visibility pass
 * 0x62C3A0 first moves +0x1C to +0x1D and clears it on every node, then, for each
 * convoy of the local player with +0x3B set, calls RevealAround(convoy, 100)
 * 0x62C760: the convoy and every node within 100 map units get vfunc+8 =
 * SetVisible (convoy: 0x5B2CA0, +0x1C = 1 and, if it was hidden before, the
 * "convoy appeared" signal 0x701EE4 that makes the sea map create its marker
 * CSeekarteSchiff and the minimap its dot). The sea map drops the marker of every
 * convoy whose +0x1C is 0 (0x5A37F0). A national fleet is not the player's, so
 * vanilla never shows it unless a player convoy is near.
 *
 * Hook R (0x62C3E7, inside the pass, after the reset loops and before the player's
 * convoys): the same RevealAround(ship, 100) for every national ship at sea. The
 * ship becomes visible itself and shows what is around it -- display only: what
 * the player may do with a visible ship (attack it with an own convoy nearby,
 * open its info) is unchanged, since every such command is issued by an own convoy.
 *
 * Go to = the game's own "jump to convoy" (pressing a convoy group key twice,
 * 0x51DCD0): view controller VC = *(app 0x6E58E4 + 0xF0); in the town view (VC+0x6C
 * = 2) SetView(1) 0x51CAA0 leaves for the sea map, then CenterOnConvoy 0x516E30
 * (VC, handle) centres the sea map (VC+0x4C, scroll at +0x7C/+0x80) on the ship.
 *
 * National convoys: the spec's MVP (§7.1 "national designation on regular convoys")
 * -- a national convoy is one of the player's own convoys, chosen by handle, paid
 * from the treasury and renamed "National convoy N" while it serves (its own name
 * comes back on release). Autonomous national traders would need a nation-5 trader
 * owner (a CPlayer), which the game does not support (research/conquest_transfer.md).
 *
 * Switched off in this version (NATION_CONVOYS 0, core.h; the removal of national convoys):
 * nothing can be designated, so only the fleets are national ships (map label, flag, minimap
 * dot, Ctrl+Shift+N). A save's PNCV block is still read, but only to undo it once the world is
 * loaded: each convoy gets its old name back and, being the player's again, the player's flag;
 * natc_save writes nothing, so the next save has no PNCV block.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "sight.h"
#include "navy.h"
#include "hook.h"
#include "log.h"
#include "lua.h"
#include "adapter.h"
#include "engine.h"
#include "game.h"
#include "flag.h"

#define TC __attribute__((thiscall))

#define CONVOY_TABLE     0x00701EE8u   /* {u32 *slots, ?, u16 count} */
#define APP_PTR          0x006E58E4u   /* the application singleton */
#define APP_VIEWCTL      0xF0
#define VC_SEAMAP        0x4C
#define VC_VIEW          0x6C          /* 1 sea map, 2 town, 3 sea battle, 4 harbour battle, 5 town battle */
#define SM_SCROLL_X      0x7C
#define SM_SCROLL_Y      0x80
#define SM_VIEW_W        0x84
#define SM_VIEW_H        0x88
#define VIEW_SEAMAP      1
#define VIEW_TOWN        2

#define K_X              0x0E
#define K_Y              0x12
#define K_VISIBLE        0x1C
#define K_AT_SEA         0x3B          /* the visibility pass reveals only around convoys with this set */
#define K_STATE          0x90
#define K_SHIPS          0x95
#define K_TOWN           0x9C
#define K_HANDLE         0xA8
#define K_OWNER          0xB0          /* group (+0x4C) + 0x64: the owning player's handle */
#define K_TYPE           0xB4
#define K_NATION         0xB8
#define K_NAME           0x194         /* u16 id in the name table */
#define K_DEST           0x1B0
#define KT_PLAYER        1
#define KT_MILITARY      4
#define KT_WAR_MISSION   9
#define SIGHT_RADIUS     100           /* vanilla's radius for the player's convoys (0x62C455 push 0x64) */

#define NAMES_TABLE      0x00702CB8u   /* kind 2 = convoy names: wchar[21] at +0x5CC, count at +0x872 */

typedef void (TC *Reveal_t)(void *obj, uint32_t radius);
typedef void (TC *Center_t)(void *vc, uint32_t convoy_h);
typedef void (TC *SetView_t)(void *vc, int view);
#define RevealAround     ((Reveal_t)0x0062C760)          /* ret 4 */
#define CenterOnConvoy   ((Center_t)0x00516E30)          /* ret 4 */
#define SetView          ((SetView_t)0x0051CAA0)         /* ret 4 */

static int g_ready, g_reveal = 1;

/* ---- the convoy pool --------------------------------------------------------------- */
static uint32_t *pool(int *n)
{
    uint32_t *hdr = (uint32_t *)(uintptr_t)CONVOY_TABLE;
    *n = (int)(hdr[2] & 0xFFFF);
    return (uint32_t *)(uintptr_t)hdr[0];
}

/* the pool handle the game's functions expect: convoy type 2 in bits 16..20 (navy.c) */
static uint32_t pool_handle(const uint8_t *k)
{
    return (*(const uint32_t *)(k + K_HANDLE) & ~(0x1Fu << 16)) | (2u << 16);
}

static int is_fleet(const uint8_t *k)
{
    uint32_t t = *(const uint32_t *)(k + K_TYPE);
    return k[K_NATION] == 5 && (t == KT_MILITARY || t == KT_WAR_MISSION);
}

static int is_players(const uint8_t *k)
{
    uint32_t h = eng_human_handle();          /* 0 while there is no player: 0x0009FFFF owns nothing */
    return h && *(const uint32_t *)(k + K_TYPE) == KT_PLAYER && *(const uint32_t *)(k + K_OWNER) == h;
}

static uint8_t *by_handle(uint32_t h)
{
    int n;
    uint32_t *s = pool(&n);
    for (int i = 0; s && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)s[i];
        if (k && *(uint32_t *)(k + K_HANDLE) == h) return k;
    }
    return NULL;
}

static int town_of(uint32_t th) { return (th & 0xFFFF) < 0xFFFF && (int)(th & 0xFFFF) < eng_town_count() ? (int)(th & 0xFFFF) : -1; }

static uint8_t *view_controller(void);

/* ---- national convoys ---------------------------------------------------------------- */
#define MAX_NATC 16
typedef struct { uint32_t handle; uint16_t old_name, pad; } Desig;
static Desig g_nc[MAX_NATC];
static int g_nc_n;
#if !NATION_CONVOYS
static Desig g_old[MAX_NATC];     /* a loaded save's designations, undone at world ready */
static int g_old_n;
#endif

static const wchar_t *name_of(const uint8_t *k)
{
    uint8_t *t = (uint8_t *)(uintptr_t)NAMES_TABLE;
    uint16_t id = *(const uint16_t *)(k + K_NAME), count = *(uint16_t *)(t + 0x872);
    const wchar_t *names = *(const wchar_t **)(t + 0x5CC);
    return names && id < count ? names + id * 21 : NULL;
}

static void name_ascii(const uint8_t *k, char *out, int cap)
{
    const wchar_t *w = name_of(k);
    int o = 0;
    for (int i = 0; w && i < 21 && w[i] && o < cap - 1; i++) out[o++] = w[i] < 0x100 ? (char)w[i] : '?';
    out[o] = 0;
}

/* AddName 0x5D8210 (thiscall on the name table, kind, const wchar_t *; ret 8) appends the text and
   returns its id -- what Lua's Convoy_SetName does after looking the text up as a text id. */
typedef uint16_t (TC *AddName_t)(void *table, int kind, const wchar_t *text);
#define AddName ((AddName_t)0x005D8210)

static void rename_convoy(uint8_t *k, const char *name)
{
    wchar_t w[21];
    int i = 0;
    for (; name[i] && i < 20; i++) w[i] = (unsigned char)name[i];
    w[i] = 0;
    *(uint16_t *)(k + K_NAME) = AddName((void *)(uintptr_t)NAMES_TABLE, 2, w);
}

/* the label on the map: fleets are "Fleet N" (as on their Navy-tab cards, pool order), national
   convoys "National convoy N"; the game shows the name with the flag when the ship is pointed at */
static void relabel(void)
{
    int n, f = 0;
    uint32_t *s = pool(&n);
    for (int i = 0; s && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)s[i];
        if (!k || !is_fleet(k)) continue;
        char want[24], have[24];
        snprintf(want, sizeof want, "Fleet %d", ++f);
        name_ascii(k, have, sizeof have);
        if (strcmp(want, have)) rename_convoy(k, want);
    }
    for (int i = 0; i < g_nc_n; i++) {
        uint8_t *k = by_handle(g_nc[i].handle);
        if (!k) continue;
        char want[24], have[24];
        snprintf(want, sizeof want, "National convoy %d", i + 1);
        name_ascii(k, have, sizeof have);
        if (strcmp(want, have)) rename_convoy(k, want);
    }
}

/* drop convoys that were sold, sunk or captured; the treasury pays for the rest */
static void natc_refresh(void)
{
    int o = 0;
    for (int i = 0; i < g_nc_n; i++) {
        uint8_t *k = by_handle(g_nc[i].handle);
        if (k && is_players(k)) g_nc[o++] = g_nc[i];
        else log_line("SIGHT: national convoy %08X is gone", g_nc[i].handle);
    }
    g_nc_n = o;
    if (adapter_state()->founded) relabel();          /* cheap when the names are right */
    NationState *s = adapter_state();
    if (s->founded && s->national_convoys != g_nc_n) s->national_convoys = (uint8_t)g_nc_n;
}

int natc_count(void) { return g_nc_n; }

static int designated(uint32_t h)
{
    for (int i = 0; i < g_nc_n; i++)
        if (g_nc[i].handle == h) return 1;
    return 0;
}

static int designate(uint8_t *k)
{
    if (g_nc_n >= MAX_NATC) return 0;
    Desig *d = &g_nc[g_nc_n++];
    d->handle = *(uint32_t *)(k + K_HANDLE);
    d->old_name = *(uint16_t *)(k + K_NAME);
    d->pad = 0;
    char was[24];
    name_ascii(k, was, sizeof was);
    relabel();
    flag_convoy_changed(k);                        /* its ships in port take the nation's flag */
    log_line("SIGHT: convoy %08X ('%s') is national convoy %d", d->handle, was, g_nc_n);
    return 1;
}

int natc_designate(char *why, int why_len)
{
#if !NATION_CONVOYS
    snprintf(why, why_len, "National convoys are not part of this version.");
    return 0;
#endif
    if (g_nc_n >= MAX_NATC) { snprintf(why, why_len, "The nation keeps at most %d national convoys.", MAX_NATC); return 0; }
    /* the selected convoy: the view controller's selection (+0x7C) keeps its handles in a vector at +0x20
       (Global_GetSelectedConvoy 0x42DB10 reads the first one) */
    uint32_t sel = 0xFFFFFFFFu;
    uint8_t *vc = view_controller(), *sl = vc ? *(uint8_t **)(vc + 0x7C) : NULL;
    if (sl && *(uint32_t *)(sl + 0x20) && *(uint32_t *)(sl + 0x20) != *(uint32_t *)(sl + 0x24))
        sel = **(uint32_t **)(sl + 0x20);
    uint8_t *pick = NULL;
    if (sel != 0xFFFFFFFFu) {
        int n;
        uint32_t *s = pool(&n);
        for (int i = 0; s && i < n && !pick; i++) {
            uint8_t *k = (uint8_t *)(uintptr_t)s[i];
            if (k && pool_handle(k) == ((((uint32_t)sel) & ~(0x1Fu << 16)) | (2u << 16))
                && is_players(k) && !designated(*(uint32_t *)(k + K_HANDLE)))
                pick = k;
        }
    }
    if (!pick) {
        int n;
        uint32_t *s = pool(&n);
        for (int i = 0; s && i < n && !pick; i++) {
            uint8_t *k = (uint8_t *)(uintptr_t)s[i];
            if (k && is_players(k) && !designated(*(uint32_t *)(k + K_HANDLE))) pick = k;
        }
    }
    log_line("SIGHT: designate: selected %08X, pick %p", sel, (void *)pick);
    if (!pick) { snprintf(why, why_len, "All of your convoys already serve as national convoys."); return 0; }
    designate(pick);
    adapter_state()->national_convoys = (uint8_t)g_nc_n;
    return 1;
}

int natc_release(uint32_t h)
{
    if (!g_nc_n) return 0;
    int i = g_nc_n - 1;
    if (h) {
        for (i = 0; i < g_nc_n && g_nc[i].handle != h; i++) {}
        if (i == g_nc_n) return 0;
    }
    uint8_t *k = by_handle(g_nc[i].handle);
    if (k) *(uint16_t *)(k + K_NAME) = g_nc[i].old_name;    /* the id it had, even "no name" (out of the table) */
    log_line("SIGHT: convoy %08X released from national service", g_nc[i].handle);
    memmove(&g_nc[i], &g_nc[i + 1], (size_t)(g_nc_n - i - 1) * sizeof g_nc[0]);
    g_nc_n--;
    relabel();
    if (k) flag_convoy_changed(k);                 /* back to the player's flag */
    adapter_state()->national_convoys = (uint8_t)g_nc_n;
    return 1;
}

int natc_set_count(int n)
{
    char why[160];
    while (g_nc_n > n && natc_release(0)) {}
    while (g_nc_n < n && natc_designate(why, sizeof why)) {}
    return g_nc_n;
}

int natc_list(NatConvoy *out, int max)
{
    int c = 0;
    for (int i = 0; i < g_nc_n && c < max; i++) {
        uint8_t *k = by_handle(g_nc[i].handle);
        if (!k) continue;
        NatConvoy *o = &out[c++];
        memset(o, 0, sizeof *o);
        o->handle = g_nc[i].handle;
        o->ships = k[K_SHIPS];
        o->state = (int)*(uint32_t *)(k + K_STATE);
        o->town = town_of(*(uint32_t *)(k + K_TOWN));
        o->dest = town_of(*(uint32_t *)(k + K_DEST));
        uint8_t *t = (uint8_t *)(uintptr_t)NAMES_TABLE;   /* the convoy's own name, shown on its card */
        const wchar_t *names = *(const wchar_t **)(t + 0x5CC);
        int oi = 0;
        if (names && g_nc[i].old_name < *(uint16_t *)(t + 0x872))
            for (const wchar_t *w = names + g_nc[i].old_name * 21; oi < 20 && *w; w++) o->name[oi++] = *w < 0x100 ? (char)*w : '?';
        o->name[oi] = 0;
    }
    return c;
}

/* 'PNCV' block body: {u32 handle, u16 old name id, u16 0} per convoy */
int natc_save(uint8_t *buf, int cap)
{
    int n = 0;
#if !NATION_CONVOYS
    return 0;                                      /* no PNCV block */
#endif
    for (int i = 0; i < g_nc_n && n + 8 <= cap; i++, n += 8) memcpy(buf + n, &g_nc[i], 8);
    return n;
}

void natc_load(const uint8_t *buf, int len)
{
    g_nc_n = 0;
#if !NATION_CONVOYS
    g_old_n = 0;
    for (int o = 0; buf && o + 8 <= len && g_old_n < MAX_NATC; o += 8) memcpy(&g_old[g_old_n++], buf + o, 8);
    if (g_old_n) log_line("SIGHT: the save has %d national convoy(s); national convoys are off: releasing them", g_old_n);
    return;
#endif
    for (int o = 0; buf && o + 8 <= len && g_nc_n < MAX_NATC; o += 8) memcpy(&g_nc[g_nc_n++], buf + o, 8);
    if (g_nc_n) log_line("SIGHT: %d national convoy(s) restored", g_nc_n);
}

/* ---- the national ships, in a fixed order: fleets (pool order), then national convoys ---- */
#define MAX_SHIPS 32
static uint8_t *g_ship[MAX_SHIPS];
static int g_nship;

static void collect(void)
{
    g_nship = 0;
    int n;
    uint32_t *s = pool(&n);
    for (int i = 0; s && i < n && g_nship < MAX_SHIPS; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)s[i];
        if (k && is_fleet(k)) g_ship[g_nship++] = k;
    }
    for (int i = 0; i < g_nc_n && g_nship < MAX_SHIPS; i++) {
        uint8_t *k = by_handle(g_nc[i].handle);
        if (k) g_ship[g_nship++] = k;
    }
}

/* ---- hook R: national ships reveal the sea around them --------------------------------- */
static unsigned long g_passes, g_reveals;

static void on_visibility_pass(Regs *r)
{
    (void)r;
    g_passes++;
    if (!g_reveal || !adapter_state()->founded) return;
    int n;
    uint32_t *s = pool(&n);
    for (int i = 0; s && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)s[i];
        if (!k || !is_fleet(k) || !k[K_AT_SEA]) continue;
        RevealAround(k, SIGHT_RADIUS);
        g_reveals++;
    }
}

/* ---- hook M: a national ship's minimap dot -------------------------------------------
   The sea map's minimap (interface +0xA0) adds a dot for a visible convoy in 0x4803D0 (edi = convoy,
   kind in eax at 0x480504): 1 own (blue), 2/3 by the relation to its nation. Flag 0x2000 paints the
   dot cyan (0x587918).
   National ships get kind 1 + 0x2000: friendly, and told apart from the player's own convoys. */
#define MM_NATIONAL      (1 | 0x2000)
static unsigned long g_dots;

static int is_national(const uint8_t *k)
{
    return is_fleet(k) || designated(*(const uint32_t *)(k + K_HANDLE));
}

int sight_is_national(const void *k) { return k && is_national((const uint8_t *)k); }

static void on_minimap_dot(Regs *r)
{
    const uint8_t *k = (const uint8_t *)(uintptr_t)r->edi;
    if (!k || !adapter_state()->founded || !is_national(k)) return;
    r->eax = MM_NATIONAL;
    g_dots++;
}

/* ---- Go to ------------------------------------------------------------------------- */
static uint8_t *view_controller(void)
{
    uint8_t *app = *(uint8_t **)(uintptr_t)APP_PTR;
    return app ? *(uint8_t **)(app + APP_VIEWCTL) : NULL;
}

static uint32_t g_goto, g_last_goto;
static int g_goto_frames, g_last_x, g_last_y, g_last_view;

int sight_goto(uint32_t h, char *why, int why_len)
{
    uint8_t *k = by_handle(h);
    if (!k) { snprintf(why, why_len, "That ship is no longer in service."); return 0; }
    uint8_t *vc = view_controller();
    int view = vc ? *(int *)(vc + VC_VIEW) : 0;
    if (view != VIEW_SEAMAP && view != VIEW_TOWN) {
        snprintf(why, why_len, "Not during a battle.");
        return 0;
    }
    g_goto = h;
    g_goto_frames = 0;
    return 1;
}

static void run_goto(void)
{
    if (!g_goto) return;
    if (++g_goto_frames < 2) return;          /* one frame for the panel to close */
    uint32_t h = g_goto;
    uint8_t *k = by_handle(h), *vc = view_controller();
    if (!k || !vc) { g_goto = 0; return; }
    int view = *(int *)(vc + VC_VIEW);
    if (view == VIEW_TOWN) {                   /* like the convoy keys: leave the town first */
        log_line("SIGHT: go to %08X: leaving the town view", h);
        SetView(vc, VIEW_SEAMAP);
        view = *(int *)(vc + VC_VIEW);
    }
    g_goto = 0;
    if (view != VIEW_SEAMAP) { log_line("SIGHT: go to %08X: view %d, not the sea map", h, view); return; }
    CenterOnConvoy(vc, pool_handle(k));
    g_last_goto = h;
    g_last_x = *(int16_t *)(k + K_X);
    g_last_y = *(int16_t *)(k + K_Y);
    g_last_view = view;
    uint8_t *sm = *(uint8_t **)(vc + VC_SEAMAP);
    log_line("SIGHT: go to %08X at %d,%d: sea map scroll %d,%d", h, g_last_x, g_last_y,
             sm ? *(int *)(sm + SM_SCROLL_X) : -1, sm ? *(int *)(sm + SM_SCROLL_Y) : -1);
}

static int g_cycle;

int sight_cycle(void)
{
    collect();
    if (!g_nship) return 0;
    g_cycle = (g_cycle + 1) % g_nship;
    char why[96];
    return sight_goto(*(uint32_t *)(g_ship[g_cycle] + K_HANDLE), why, sizeof why);
}

/* ---- lifecycle --------------------------------------------------------------------- */
void sight_frame(void)
{
    if (!g_ready) return;
    run_goto();
    static int ticks;
    if (++ticks % 60 == 0 && adapter_world_ready()) natc_refresh();
}

void sight_reset(void)
{
    g_goto = 0;
    g_nc_n = 0;
#if !NATION_CONVOYS
    g_old_n = 0;
#endif
    g_cycle = -1;
}

void sight_world_ready(void)
{
#if !NATION_CONVOYS
    /* a save's national convoys: their old names back, and the player's flag (they are no longer
       national ships, so flag.c draws the player's logo; flag_convoy_changed re-flags them in port) */
    for (int i = 0; i < g_old_n; i++) {
        uint8_t *k = by_handle(g_old[i].handle);
        if (!k) { log_line("SIGHT: former national convoy %08X is gone", g_old[i].handle); continue; }
        char was[24], now[24];
        name_ascii(k, was, sizeof was);
        *(uint16_t *)(k + K_NAME) = g_old[i].old_name;   /* the id it had before, also a "no name" id past the table */
        name_ascii(k, now, sizeof now);
        flag_convoy_changed(k);
        log_line("SIGHT: convoy %08X released from national service: '%s' -> '%s' (name id %u)", g_old[i].handle, was, now,
                 g_old[i].old_name);
    }
    g_old_n = 0;
    adapter_state()->national_convoys = 0;
#else
    /* an older save counted national convoys without naming them: designate that many */
    NationState *s = adapter_state();
    if (s->founded && s->national_convoys > g_nc_n) {
        int want = s->national_convoys;
        log_line("SIGHT: the save counts %d national convoys, %d designated: designating the rest", want, g_nc_n);
        natc_set_count(want);
    }
#endif
    relabel();
}

void sight_install(void)
{
    static const uint8_t hr[] = {0x8D, 0x44, 0x24, 0x08, 0x50};   /* lea eax,[esp+8]; push eax */
    g_ready = hook_install("sight.VisibilityPass", 0x0062C3E7, hr, sizeof hr, on_visibility_pass);
    static const uint8_t hm[] = {0x0F, 0xBF, 0x57, 0x12, 0x50};   /* movsx edx,word [edi+0x12]; push eax (eax = dot kind) */
    hook_install("sight.MinimapDot", 0x00480504, hm, sizeof hm, on_minimap_dot);
    g_cycle = -1;
}

/* ---- tests ------------------------------------------------------------------------- */
int sight_reveal_enabled(int on)
{
    if (on >= 0) g_reveal = on != 0;
    return g_reveal;
}

int sight_last_goto(uint32_t *h, int *x, int *y, int *view)
{
    *h = g_last_goto;
    *x = g_last_x;
    *y = g_last_y;
    *view = g_last_view;
    return g_last_goto != 0;
}

int sight_ship_count(void) { collect(); return g_nship; }

int sight_ship_info(int i, uint32_t *h, int *x, int *y, int *visible, int *at_sea, int *fleet)
{
    collect();
    if (i < 0 || i >= g_nship) return 0;
    uint8_t *k = g_ship[i];
    *h = *(uint32_t *)(k + K_HANDLE);
    *x = *(int16_t *)(k + K_X);
    *y = *(int16_t *)(k + K_Y);
    *visible = k[K_VISIBLE];
    *at_sea = k[K_AT_SEA];
    *fleet = is_fleet(k);
    return 1;
}

int sight_visible_near(int x, int y, int radius, int *total, int *own)
{
    int n, vis = 0, all = 0;
    *own = 0;
    uint32_t *s = pool(&n);
    for (int i = 0; s && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)s[i];
        if (!k || is_fleet(k)) continue;
        int dx = *(int16_t *)(k + K_X) - x, dy = *(int16_t *)(k + K_Y) - y;
        int r2 = radius + SIGHT_RADIUS;                      /* an own convoy this close would reveal the spot */
        if (is_players(k) && k[K_AT_SEA] && dx * dx + dy * dy <= r2 * r2) (*own)++;
        if (dx * dx + dy * dy > radius * radius || !k[K_AT_SEA]) continue;
        all++;
        if (k[K_VISIBLE]) vis++;
    }
    *total = all;
    return vis;
}

int sight_view(int *sx, int *sy)
{
    uint8_t *vc = view_controller();
    uint8_t *sm = vc ? *(uint8_t **)(vc + VC_SEAMAP) : NULL;
    *sx = sm ? *(int *)(sm + SM_SCROLL_X) + *(int *)(sm + SM_VIEW_W) / 2 : -1;
    *sy = sm ? *(int *)(sm + SM_SCROLL_Y) + *(int *)(sm + SM_VIEW_H) / 2 : -1;
    return vc ? *(int *)(vc + VC_VIEW) : -1;
}
