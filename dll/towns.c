/* Town access (research/lua_bridge.md ยง5, economy_data.md ยง1).
 * Town index = slot in the town pool 0x702068 = staedte.ini order. */
#include <stdio.h>
#include <string.h>
#include "engine.h"
#include "game.h"
#include "lua.h"
#include "log.h"
#include "hook.h"

#define TOWN_PTRS   (*(uint8_t ***)0x00702068)
#define TOWN_LINKS  (*(uint16_t **)0x0070206C)     /* [2*i]=next, [2*i+1]=generation */
#define TOWN_CAP    (*(uint16_t *)0x00702070)

typedef void *(__attribute__((thiscall)) *PoolGet_t)(void *pool, uint32_t h);
#define TownFromHandle(h) (((PoolGet_t)0x0041F620)((void *)0x00702068, (h)))   /* NULL if bad */

/* CStadt offsets (economy_data.md) */
enum { T_LAGER = 0x38, T_FLAGS = 0x40, T_FLAGS2 = 0x44, T_ALQ = 0x54, T_WEALTH = 0x58,
       T_FOODMISS = 0x59, T_POP = 0x38A, T_SOLDIERS = 0x38E, T_NATION = 0x390, T_DISPNAT = 0x391 };
#define TF_STARVE      (1u << 4)
#define TF_PLAYERTOWN  (1u << 22)
uint8_t g_dev_property[64];             /* Nation_DevSet("property", town, 1) */
#define T_TOWERS       0x919C        /* u8 cannon towers (research/garrison.md) */
#define T_PERMIT       0x91B0        /* u8 the player holds the building permit (Lager+0x9174+4,
                                        research/building_permit.md) */
#define TF2_GOVSEAT    (1u << 0)
#define TF2_VICEROY    (1u << 13)      /* CStadtCreate sets mask 0x2001 for Vizekoenig */

static const char *k_names[] = {
#include "town_names.inc"
};

uint32_t eng_town_handle(int idx)
{
    if (idx < 0 || idx >= TOWN_CAP || !TOWN_LINKS) return 0;
    return (uint32_t)idx | 0x10000u | ((uint32_t)(TOWN_LINKS[2 * idx + 1] & 0x7FF) << 21);
}

uint8_t *eng_town_ptr(int idx)
{
    uint32_t h = eng_town_handle(idx);
    return h ? (uint8_t *)TownFromHandle(h) : NULL;
}

int eng_town_count(void)
{
    int n = TOWN_PTRS ? TOWN_CAP : 0;
    return n > MAX_TOWNS ? MAX_TOWNS : n;
}

const char *eng_town_name(int idx)
{
    if (idx >= 0 && idx < (int)(sizeof k_names / sizeof *k_names)) return k_names[idx];
    return "?";
}

static int player_buildings(int idx)
{
    char e[160];
    int n = 0;
    snprintf(e, sizeof e, "Player_GetNumBuildings(Global_GetPlayer(), %d) or 0", (int)eng_town_handle(idx));
    return plua_eval_int(e, &n) ? n : 0;
}

int eng_town_snapshot(int idx, TownSnap *o)
{
    memset(o, 0, sizeof *o);
    uint8_t *t = eng_town_ptr(idx);
    if (!t) return 0;
    uint32_t fl = *(uint32_t *)(t + T_FLAGS), fl2 = *(uint32_t *)(t + T_FLAGS2);
    o->exists = 1;
    o->power = t[T_NATION];
    o->display_power = t[T_DISPNAT];
    o->is_governor_seat = (fl2 & TF2_GOVSEAT) && !(fl2 & TF2_VICEROY);
    o->is_viceroy_seat = (fl2 & TF2_VICEROY) != 0;
    o->population = *(uint16_t *)(t + T_POP);
    /* wealth: level 0..7 (from living quality + population) scaled to money-ish units */
    o->wealth = (int32_t)t[T_WEALTH] * 25000 + (*(int16_t *)(t + T_ALQ) >> 8) * 500;
    o->essential_shortage = (fl & TF_STARVE) || t[T_FOODMISS] >= 2;
    o->garrison = *(uint16_t *)(t + T_SOLDIERS);
    o->player_property = (fl & TF_PLAYERTOWN) || player_buildings(idx) > 0 ||
                         (idx >= 0 && idx < 64 && g_dev_property[idx]);   /* test install only */
    o->cannons = t[T_TOWERS];
    o->permit = t[T_PERMIT] != 0;
    return 1;
}

/* Building permit (research/building_permit.md): vanilla keeps one licence
   record per town at Lager+0x9174 {i32 progress; u8 granted; ...}; the build
   checks (0x61B4C0, the master builder 0x410A2B) read only the granted byte.
   We write that byte directly: vanilla's own grant 0x6211A0 would also post a
   "new licence" message and chronicle entry, its sale 0x61B770 pays the player. */
int eng_town_permit(int idx)
{
    uint8_t *t = eng_town_ptr(idx);
    return t ? t[T_PERMIT] != 0 : -1;
}

int eng_town_set_permit(int idx, int on)
{
    uint8_t *t = eng_town_ptr(idx);
    if (!t) return 0;
    t[T_PERMIT] = (uint8_t)(on != 0);
    log_line("town %d (%s): building permit %s", idx, eng_town_name(idx), on ? "granted" : "taken back");
    return 1;
}

/* The master builder values a held permit for selling it back (0x61B1E0 ->
   dialog data +8, paid out by 0x61B770). A permit in a nation town is the
   nation's: it sells for nothing (otherwise granting it again every day
   would be a money tap). Hook at 0x410A53: mov ecx,[esi+0x14] / mov [ecx+8],eax. */
static void on_permit_value(Regs *r)
{
    uint8_t *dlg = *(uint8_t **)(uintptr_t)(r->esi + 0x14);
    uint8_t *t = dlg ? *(uint8_t **)(dlg + 4) : NULL;
    if (t && t[T_NATION] == 5 && r->eax) {
        log_line("master builder: permit in a nation town valued %u -> 0", r->eax);
        r->eax = 0;
    }
}

void towns_install(void)
{
    static const uint8_t b[] = {0x8B, 0x4E, 0x14, 0x89, 0x41, 0x08};
    hook_install("MasterBuilder permit value", 0x00410A53u, b, sizeof b, on_permit_value);
}

/* Ownership changes (research/conquest_transfer.md ง1): replicate what
   AddToNation does internally, since vanilla has no owned-town -> nation-5 path. */
typedef void (__attribute__((thiscall)) *ListOp_t)(void *list, uint32_t handle);
#define ListDetach     ((ListOp_t)0x00636630)                 /* ret 4, ecx = &CNation+0x14 */
typedef void (__attribute__((thiscall)) *AddToNation_t)(void *lager, int nation, int force);
#define AddToNation    ((AddToNation_t)0x005C9DA0)            /* ret 8 */
typedef void (__attribute__((thiscall)) *LagerNotify_t)(void *lager);
#define LagerNotify    ((LagerNotify_t)0x00624F50)            /* town-list refresh after a change */
#define L_HANDLE       0x91A4                                 /* lager + 0x91A4 = town handle */
#define L_FLAGS2       0x0C                                   /* lager + 0xC: bit 15 = hostile to player */

int eng_town_to_nation(int idx, int host)
{
    uint8_t *t = eng_town_ptr(idx);
    if (!t || host < 0 || host > 3) return 0;
    uint8_t *lager = t + T_LAGER;
    uint8_t cur = t[T_NATION];
    if (cur == 5) {                                    /* already ours: just fix the display power */
        t[T_DISPNAT] = (uint8_t)host;
        return 1;
    }
    if (cur < 4) {
        uint8_t *nat = *(uint8_t **)(uintptr_t)(GA_NATIONS + 4u * cur);
        if (nat)
            ListDetach(nat + 0x14, *(uint32_t *)(lager + L_HANDLE));
    }
    lager[0x358] = 0xFF;                               /* "no power" ... */
    AddToNation(lager, host, 1);                       /* ... force path: display = host, nation = 5 */
    *(uint32_t *)(lager + L_FLAGS2) &= ~0x8000u;
    LagerNotify(lager);
    log_line("town %d (%s): nation %d -> %d (display %d)", idx, eng_town_name(idx), cur,
             t[T_NATION], t[T_DISPNAT]);
    return t[T_NATION] == 5;
}

int eng_town_to_power(int idx, int power)
{
    uint8_t *t = eng_town_ptr(idx);
    if (!t || power < 0 || power > 3) return 0;
    uint8_t cur = t[T_NATION];
    AddToNation(t + T_LAGER, power, 0);   /* cur >= 4: no detach, attaches to the new power */
    LagerNotify(t + T_LAGER);
    log_line("town %d (%s): nation %d -> %d", idx, eng_town_name(idx), cur, t[T_NATION]);
    return t[T_NATION] == power;
}

int eng_power_town_count(int p)
{
    int n = 0;
    for (int i = 0; i < eng_town_count(); i++) {
        uint8_t *t = eng_town_ptr(i);
        if (t && t[T_NATION] == p) n++;
    }
    return n;
}

/* Unrest effect (economy_data.md ง3): a strike, which vanilla ends by itself
   (town event 5). 7 days = 7 * 256 ticks. */
typedef void (__attribute__((thiscall)) *SetStrike_t)(void *lager, int duration_ticks);
#define PR2_SetStrike ((SetStrike_t)0x00624460)

int eng_town_unrest(int idx, int on)
{
    uint8_t *t = eng_town_ptr(idx);
    if (!t || t[T_NATION] != 5) return 0;
    if (on) {
        PR2_SetStrike(t + T_LAGER, 7 * 256);
        log_line("town %d (%s): unrest -> strike for 7 days", idx, eng_town_name(idx));
    }
    return 1;
}
