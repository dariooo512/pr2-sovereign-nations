/* Town officials in the nation's own towns (the own-town officials change, research/officials.md).
 *
 * The treasurer, commander (general), governor and building master are NPC
 * objects that carry a nation byte (NPC data +0x12). Vanilla fills it from
 * the town with the ">= 4 -> display power" substitution, so in a member
 * town (nation byte 5, display = host power) they ask
 * CPlayer::ReputationTier(0x5D2C10) for the reputation with the former /
 * host power and answer "reputation too low" (ID_NPC_*_BAD_REP).
 *
 * Fix: a hook at the entry of 0x5D2C10 looks at the return address. For the
 * officials' own call sites (table below) it takes the NPC from the register
 * the caller keeps it in, checks the NPC's class (vtable) and its town, and
 * when that town is a member town (core_officials_serve) answers tier 3, the
 * highest, without running the function. Every other caller, and every other
 * town, gets the vanilla function untouched.
 */
#include <windows.h>
#include <string.h>
#include "adapter.h"
#include "core.h"
#include "engine.h"
#include "hook.h"
#include "log.h"
#include "lua.h"
#include "officials.h"

#define GA_REP_TIER     0x005D2C10u      /* thiscall int CPlayer::ReputationTier(nation), ret 4 */
#define T_NATION        0x390

enum { R_ESI, R_EDI };

#define VT_BMASTER      0x00681AA8u      /* NPC type 5, building master (licences) */
#define VT_GENERAL      0x00682440u      /* NPC type 3, commander (garrison, cannons) */
#define VT_GOVERNOR     0x00682C50u      /* NPC type 1, governor */
#define VT_TREASURER    0x00687860u      /* NPC type 4, treasurer (loans) */

static const struct { uint32_t ret; uint32_t vt; uint8_t reg; const char *what; } k_sites[] = {
    {0x00410A6F, VT_BMASTER, R_ESI, "building master enter"},
    {0x00410ABC, VT_BMASTER, R_ESI, "building master enter"},
    {0x00410ADF, VT_BMASTER, R_ESI, "building master enter"},
    {0x00410B74, VT_BMASTER, R_ESI, "building master enter"},
    {0x0041677E, VT_GENERAL, R_ESI, "commander portrait"},
    {0x00417469, VT_GENERAL, R_ESI, "commander enter (BAD_REP)"},
    {0x00418C76, VT_GOVERNOR, R_EDI, "governor welcome"},
    {0x00419AA5, VT_GOVERNOR, R_EDI, "governor BAD_REP_HOSTILE"},
    {0x0041AC8F, VT_GOVERNOR, R_EDI, "governor dialog end"},
    {0x0041ACB3, VT_GOVERNOR, R_EDI, "governor dialog end text"},
    {0x0041B921, VT_GOVERNOR, R_ESI, "governor answer"},
    {0x0041B95A, VT_GOVERNOR, R_ESI, "governor answer"},
    {0x0041BB56, VT_GOVERNOR, R_ESI, "governor answer"},
    {0x0041BB8E, VT_GOVERNOR, R_ESI, "governor answer fee"},
    {0x0044462C, VT_TREASURER, R_ESI, "treasurer portrait"},
    {0x00444871, VT_TREASURER, R_ESI, "treasurer enter (BAD_REP)"},
};
#define N_SITES ((int)(sizeof k_sites / sizeof *k_sites))
static uint8_t g_logged[N_SITES];

/* NPC object: +0 vtable, +0x10 base data (+4 player handle, +0xC dialog
   state, +0x12 nation, +0x14 town handle), +0x14 class data. */
static int npc_town(const uint8_t *npc)
{
    const uint8_t *d = *(const uint8_t *const *)(npc + 0x10);
    if (!d) return -1;
    uint32_t h = *(const uint32_t *)(d + 0x14);
    int idx = (int)(h & 0xFFFF);
    if (idx >= eng_town_count() || eng_town_handle(idx) != h) return -1;
    return idx;
}

static int npc_serves(const uint8_t *npc, int *town_out)
{
    int t = npc_town(npc);
    if (town_out) *town_out = t;
    if (t < 0) return 0;
    const uint8_t *town = eng_town_ptr(t);
    return town && core_officials_serve(adapter_state(), t, town[T_NATION]);
}

static int on_rep_tier(Regs *r)
{
    uint32_t ret = stack_arg(r, 0);
    if (ret < 0x00410A6F || ret > 0x00444871) return 0;          /* fast path: not an official */
    for (int i = 0; i < N_SITES; i++) {
        if (k_sites[i].ret != ret) continue;
        const uint8_t *npc = (const uint8_t *)(uintptr_t)(k_sites[i].reg == R_ESI ? r->esi : r->edi);
        if (!npc || *(const uint32_t *)npc != k_sites[i].vt) return 0;
        int town;
        if (!npc_serves(npc, &town)) return 0;
        if (!g_logged[i]) {
            g_logged[i] = 1;
            log_line("OFFICIALS %s in %s (town %d, asks nation %d): sovereign, full access",
                     k_sites[i].what, eng_town_name(town), town, (int)(stack_arg(r, 1) & 0xFF));
        }
        r->eax = 3;                                               /* highest tier */
        return 1;
    }
    return 0;
}

void officials_install(void)
{
    static int done;
    if (done) return;
    done = 1;
    /* mov eax,[esp+4] ; push eax */
    static const uint8_t b[] = {0x8B, 0x44, 0x24, 0x04, 0x50};
    if (!hook_install_ret("officials.ReputationTier", GA_REP_TIER, b, sizeof b, on_rep_tier, 4))
        log_line("OFFICIALS hook not installed: officials keep the vanilla reputation check");
}

/* ---- test install: Nation_DevOfficial(town, kind) -------------------------
   Runs the official's real "enter dialog" code the way the town menu does:
   the World getter (which also sets the NPC's town and nation) and then the
   NPC's vtable slot 19. Returns the dialog state (1 = BAD_REP / refused),
   the NPC's nation and the vanilla reputation tier with that nation. */
typedef void *(__attribute__((thiscall)) *GetNpc_t)(void *stadt);
typedef void (__attribute__((thiscall)) *Enter_t)(void *npc);
typedef int (__attribute__((thiscall)) *RepTier_t)(void *player, int nation);
#define PLR_BASE   (*(uint8_t **)0x00701EC0)
#define HUMAN_H    (*(uint32_t *)0x00701ED0)

static const struct { uint32_t getter; uint32_t vt; } k_kinds[] = {
    {0x005C4BB0, VT_TREASURER},          /* 0: treasurer  (World+0xAE4) */
    {0x005C4BD0, VT_GENERAL},            /* 1: commander  (World+0xAF8) */
    {0x005C4B90, VT_BMASTER},            /* 2: building master (World+0xAE8) */
};

int officials_dev_probe(int town, int kind, int *state, int *nation, int *tier)
{
    *state = *nation = *tier = -1;
    if (kind < 0 || kind >= (int)(sizeof k_kinds / sizeof *k_kinds)) return 0;
    uint8_t *t = eng_town_ptr(town);
    if (!t || !PLR_BASE || !HUMAN_H || (HUMAN_H & 0xFFFF) == 0xFFFF) return 0;
    uint8_t *npc = ((GetNpc_t)(uintptr_t)k_kinds[kind].getter)(t);
    if (!npc || *(uint32_t *)npc != k_kinds[kind].vt) return 0;
    uint8_t *d = *(uint8_t **)(npc + 0x10);
    uint32_t old_player = *(uint32_t *)(d + 4);
    *(uint32_t *)(d + 4) = HUMAN_H;                    /* the dialog's player */
    ((Enter_t)(uintptr_t)(*(uint32_t **)npc)[19])(npc);
    *state = (int)*(uint32_t *)(d + 0xC);
    *nation = d[0x12];
    *tier = ((RepTier_t)(uintptr_t)GA_REP_TIER)(PLR_BASE + 0x94u * (HUMAN_H & 0xFFFF), d[0x12]);
    *(uint32_t *)(d + 4) = old_player;
    log_line("DEV official town %d kind %d: state %d, npc nation %d, vanilla tier %d, serves %d",
             town, kind, *state, *nation, *tier, npc_serves(npc, NULL));
    return 1;
}
