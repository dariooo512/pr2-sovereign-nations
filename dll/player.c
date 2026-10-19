/* Player access (research/economy_data.md §2). */
#include "engine.h"
#include "game.h"
#include "log.h"

#define PLR_BASE   (*(uint8_t **)0x00701EC0)   /* inline array, stride 0x94 */
#define HUMAN_H    (*(uint32_t *)0x00701ED0)
#define SHIP_BASE  (*(uint8_t **)0x00703CD4)   /* inline array, stride 0x28 */
#define SHIP_CAP   (*(uint16_t *)0x00703CDC)
enum { P_GOLD = 0x3C, P_REP = 0x54 };
enum { S_OWNER = 0x14, S_FLAGS = 0x20 };       /* flags: 1 valid, 4 battleship */

typedef void (__attribute__((thiscall)) *AddGold_t)(void *ctr, int amount, int cat);
#define PR2_AddGold ((AddGold_t)0x0060E570)     /* ret 8; category 9 = scripts */

static uint8_t *human(void)
{
    if (!PLR_BASE || !HUMAN_H || (HUMAN_H & 0xFFFF) == 0xFFFF) return NULL;   /* 0xFFFF: no player yet (New Game pre-simulation) */
    return PLR_BASE + 0x94u * (HUMAN_H & 0xFFFF);
}

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
    if (!SHIP_BASE || !HUMAN_H) return;
    for (unsigned i = 0; i < SHIP_CAP; i++) {
        uint8_t *s = SHIP_BASE + 0x28u * i;
        uint32_t fl = *(uint32_t *)(s + S_FLAGS);
        if (!(fl & 1) || *(uint32_t *)(s + S_OWNER) != HUMAN_H) continue;
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
