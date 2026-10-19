/* Player access (research/economy_data.md §2). */
#include "engine.h"
#include "game.h"
#include "log.h"

/* The CPlayer pool 0x701EBC (research/human_handle_presim.md): +4 the records (stride 0x94),
   +8 the slot table (u32 per slot, generation tag in its high word), +0xC the capacity (u16). */
#define PLR_BASE   (*(uint8_t **)0x00701EC0)   /* inline array, stride 0x94 */
#define PLR_SLOTS  (*(uint8_t **)0x00701EC4)
#define PLR_CAP    (*(uint16_t *)0x00701EC8)
#define HUMAN_H    (*(uint32_t *)0x00701ED0)   /* 0x0009FFFF (index 0xFFFF) while there is no player */
#define SHIP_BASE  (*(uint8_t **)0x00703CD4)   /* inline array, stride 0x28 */
#define SHIP_CAP   (*(uint16_t *)0x00703CDC)
enum { P_GOLD = 0x3C, P_ALIVE = 0x25, P_REP = 0x54 };
enum { S_OWNER = 0x14, S_FLAGS = 0x20 };       /* flags: 1 valid, 4 battleship */

typedef void (__attribute__((thiscall)) *AddGold_t)(void *ctr, int amount, int cat);
#define PR2_AddGold ((AddGold_t)0x0060E570)     /* ret 8; category 9 = scripts */

/* The human player's CPlayer, or NULL while there is none: before a game, during a New Game's
   pre-simulation (the handle's index is 0xFFFF for about 90 game days after "new game ready") and
   after the player is destroyed. The same tests as the engine's own 0x5C29E0, without its throw.
   Every use of the human player in the DLL goes through here (replog.c, officials.c, sight.c). */
uint8_t *eng_human_player(void)
{
    uint8_t *base = PLR_BASE, *slots = PLR_SLOTS;
    uint32_t h = HUMAN_H;
    int i = core_player_index(h, PLR_CAP);
    if (!base || !slots || i < 0 || !core_player_tag_ok(h, *(uint16_t *)(slots + 4u * (unsigned)i + 2)))
        return NULL;
    uint8_t *p = base + 0x94u * (unsigned)i;
    return p[P_ALIVE] ? p : NULL;
}

uint32_t eng_human_handle(void)
{
    return eng_human_player() ? HUMAN_H : 0;
}

static uint8_t *human(void) { return eng_human_player(); }

int64_t eng_player_gold(void)
{
    uint8_t *p = human();
    return p ? *(int32_t *)(p + P_GOLD) : 0;
}

int eng_player_add_gold(int64_t d)
{
    uint8_t *p = human();
    if (!p) return 0;
    if (d < -2000000000LL || d > 2000000000LL) return 0;
    if (d < 0 && eng_player_gold() + d < 0) return 0;      /* never push the player into debt */
    if (d > 0 && eng_player_gold() + d > 2000000000LL) return 0;   /* the purse is an int32 */
    PR2_AddGold(p + P_GOLD, (int)d, 9);
    return 1;
}

void eng_player_fleet(uint16_t *ships, uint16_t *warships)
{
    *ships = *warships = 0;
    uint32_t h = eng_human_handle();          /* not HUMAN_H: 0x0009FFFF is no player, not an owner */
    if (!SHIP_BASE || !h) return;
    for (unsigned i = 0; i < SHIP_CAP; i++) {
        uint8_t *s = SHIP_BASE + 0x28u * i;
        uint32_t fl = *(uint32_t *)(s + S_FLAGS);
        if (!(fl & 1) || *(uint32_t *)(s + S_OWNER) != h) continue;
        (*ships)++;
        if (fl & 4) (*warships)++;
    }
}

int eng_player_reputation(int power)
{
    uint8_t *p = human();
    if (!p || power < 0 || power > 3) return 50;
    int v = *(int32_t *)(p + P_REP + 4 * power) >> 16;
    return v < 0 ? 0 : v > 100 ? 100 : v;
}

void eng_player_add_reputation(int power, int delta)
{
    uint8_t *p = human();
    if (!p || power < 0 || power > 3) return;
    int v = eng_player_reputation(power) + delta;
    v = v < 0 ? 0 : v > 100 ? 100 : v;
    *(int32_t *)(p + P_REP + 4 * power) = v << 16;
}

int eng_player_rank(void) { return 0; }

int eng_power_war(int a, int b)
{
    if (a < 0 || a > 3 || b < 0 || b > 3 || a == b) return 0;
    uint8_t *n = *(uint8_t **)(uintptr_t)(GA_NATIONS + 4u * a);
    return n ? (n[b] & 0x7F) == 1 : 0;
}
