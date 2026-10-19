/* The national navy: military convoys of nation 5 that the game's own
 * military AI sails, patrols and fights with (research/military_ai.md).
 *
 * Vanilla keeps one CNation per power in g_nations[0..3] (World+0x9D4 =
 * 0x702B14) and every site tests `n < 4` before it reads the table. The
 * nation gets a real CNation of its own (g_pc, built by the game's ctor with
 * index 5) and a six-slot mirror g_nations6 = {g[0..3], NULL, &g_pc}. Only the
 * military sites that must see nation 5 are switched to the mirror, each by a
 * same-length edit (`cmp r,4` -> `cmp r,6`, disp32 0x702B14 -> g_nations6):
 *   SetType 4/9 (keeps nation 5, registers the convoy in g_pc+8),
 *   ClearOwner (the matching removal), the home-town picker (reads address 8
 *   for n >= 4), the attack-mask builder and its inner check.
 * The mirror is refreshed at the three writers of g_nations: the end of
 * World::Reset (H1, which also rebuilds g_pc), World::CreateNations (H2) and
 * World::Load (H3, from persist.c), so an opted-in site never sees a stale or
 * freed pointer for powers 0..3.
 *
 * The flagship table byte[4] 0x6AC4B4 gives an invalid ship type (0xF0) for
 * nation 5; its four readers are pointed at g_flag6, which has a sixth entry.
 * P01's IsAtWar stub answers "war" for (nation object 5, other 5); its jump is
 * retargeted to the branch that maps 5 to peace.
 *
 * g_pc.rel[0..3] (CNation+0) follows the war table player_rel every frame, so
 * the fleet's friend/foe matches the nation's wars.
 */
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "navy.h"
#include "game.h"
#include "hook.h"
#include "log.h"
#include "lua.h"
#include "engine.h"
#include "adapter.h"

#define G_NATIONS        0x00702B14u
#define CONVOY_TABLE     0x00701EE8u   /* {u32 *slots, ?, u16 count} */
#define K_LIST_NODE      0
#define K_TYPE           0xB4
#define K_NATION         0xB8
#define K_HANDLE         0xA8
#define KT_MILITARY      4
#define KT_WAR_MISSION   9
#define PC_MIL_LIST      8              /* CNation+8: the power's military convoys */
#define CNATION_SIZE     0x170

typedef char (__attribute__((thiscall)) *Sail_t)(void *k, uint32_t town_h);
#define SailToTown ((Sail_t)0x005B19D0)          /* ret 4 */
#define K_DEST     0x1B0

static int is_ours(const uint8_t *k);
static uint8_t *fleet_by_handle(uint32_t h);

#define T_SOLDIERS       0x38E
#define T_TOWERS         0x919C
#define T_BUDGET         0x91C8       /* +0 soldier gold, +0xC tower gold */
#define T_LAGER          0x38
typedef void (__attribute__((thiscall)) *AddSB_t)(void *t, int *amount);
typedef void (__attribute__((thiscall)) *AddTB_t)(void *budget, void *lager, int amount);
typedef char (__attribute__((thiscall)) *BattleAt_t)(void *battles, uint32_t town_handle);
#define PR2_AddSoldierBudget ((AddSB_t)0x005C4B50)    /* ret 4; *amount = gold booked */
#define PR2_AddTowerBudget   ((AddTB_t)0x00623CB0)    /* ret 8; ecx = t+0x91C8 */
#define PR2_BattleAtTown     ((BattleAt_t)0x005FD050) /* ret 4; ecx = 0x7036C0 */

static int g_order;                     /* NavyOrder applied to every fleet */
static int g_disband_pending;
typedef struct { uint32_t h, day; int16_t town; uint8_t power, pending; } RaidDay;
static RaidDay g_raid_day[16];          /* per fleet: game day its last raid began (0 = due), its target */
static void send_raids(void);
static void port_watch_reset(void);
static uint8_t g_raid_peace_told[4];      /* the player was told the raids on this power stopped */

typedef void (__attribute__((thiscall)) *Ctor_t)(void *self, int idx);
typedef void (__attribute__((thiscall)) *Dtor_t)(void *self);
typedef char (__attribute__((thiscall)) *ListAdd_t)(void *list, uint32_t handle);
typedef int  (__attribute__((thiscall)) *ListCount_t)(void *self);
#define CNation_Ctor     ((Ctor_t)0x005BBC70)
#define CNation_Dtor     ((Dtor_t)0x005BBDB0)
#define MilList_Add      ((ListAdd_t)0x00636DD0)          /* insert-unique, ret 4 */
#define CNation_MilCount ((ListCount_t)0x005BBB00)

static uint8_t g_pc[CNATION_SIZE] __attribute__((aligned(16)));
static int g_pc_built;
void *g_nations6[6];
static uint8_t g_flag6[8] = {0x0F, 0x0D, 0x0C, 0x0E, 0x00, 0x0F};   /* flagship type per nation */
static int g_ready;                                                  /* all patches applied */

static void mirror_powers(void)
{
    for (int i = 0; i < 4; i++)
        g_nations6[i] = *(void **)(uintptr_t)(G_NATIONS + 4 * i);
    g_nations6[4] = NULL;
    g_nations6[5] = g_pc_built ? g_pc : NULL;
}

/* H1: the end of World::Reset. g_nations[0..3] are now 0; rebuild the nation's object. */
static void on_world_reset_end(Regs *r)
{
    (void)r;
    if (g_pc_built) CNation_Dtor(g_pc);
    memset(g_pc, 0, sizeof g_pc);
    CNation_Ctor(g_pc, 5);
    g_pc_built = 1;
    mirror_powers();
}

/* H2: the end of World::CreateNations (new game). */
static void on_nations_created(Regs *r) { (void)r; mirror_powers(); }

/* The convoy's own handle field (+0xA8) carries other bits in 16..20; the pool handle the
   game's functions expect has the convoy type 2 there (Lua's Global_CreateMilitaryConvoy
   returns 0x00A20091 for a fleet whose +0xA8 reads 0x00A80091; DeleteConvoy 0x635600
   rejects anything else). */
static uint32_t fleet_handle(const uint8_t *k)
{
    return (*(const uint32_t *)(k + K_HANDLE) & ~(0x1Fu << 16)) | (2u << 16);
}

static uint8_t *convoy_slots(int *n)
{
    uint32_t *hdr = (uint32_t *)(uintptr_t)CONVOY_TABLE;
    *n = (int)(hdr[2] & 0xFFFF);
    return (uint8_t *)(uintptr_t)hdr[0];
}

void navy_after_load_nations(void)
{
    mirror_powers();
}

/* After a load: register the nation's military convoys (they keep nation 5 in the save). */
static void rebuild_list(void)
{
    int n, added = 0, seen = 0;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    if (!slots || !g_pc_built) return;
    for (int i = 0; i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k) continue;
        uint32_t type = *(uint32_t *)(k + K_TYPE);
        if ((type != KT_MILITARY && type != KT_WAR_MISSION) || k[K_NATION] != 5) continue;
        seen++;
        if (MilList_Add(g_pc + PC_MIL_LIST, fleet_handle(k))) added++;
    }
    if (seen) log_line("NAVY: %d national fleet(s) in the world, %d re-registered", seen, added);
}

/* ---- the powers' war against the nation ------------------------------------
   Vanilla only sends war-mission fleets (type 9) between powers. With the
   AssignWarMission guard raised to 6 (navy_install), a power at war with the
   nation gets one, like the war-start handler 0x5F5360 does for powers: at
   most one running mission per power, a new one at the war's start and then at
   most every 56 days (research/power_siege_nation.md). */
#define K_MISSION_TARGET 0x172
#define K_STATE          0x90
#define K_SHIPS          0x95
#define K_CANNONS        0x142
#define K_LUAFLAGS       0x7C
#define K_ON_MAP         0x1C          /* byte: the convoy is on the sea map */
#define MISSION_GAP_DAYS 56
typedef char (__attribute__((thiscall)) *Assign_t)(void *convoy, uint32_t target, uint32_t count);
#define AssignWarMission ((Assign_t)0x005B4870)                    /* ret 8, AL = 1 ok */

static uint32_t g_next_mission[4];        /* game day of the next allowed mission per power */
static uint8_t g_was_war[4];

static int power_has_mission(int p)
{
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (k && *(uint32_t *)(k + K_TYPE) == KT_WAR_MISSION && k[K_NATION] == p) return 1;
    }
    return 0;
}

/* vanilla's choice: a veteran fleet (Lua flag 0x10000) first, else the most cannons among those in port */
static uint8_t *pick_fleet(int p)
{
    int n;
    uint8_t *best = NULL, *veteran = NULL;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || *(uint32_t *)(k + K_TYPE) != KT_MILITARY || k[K_NATION] != p) continue;
        if (*(uint32_t *)(k + K_STATE) == 9 || k[K_SHIPS] < 2) continue;
        if ((*(uint32_t *)(k + K_LUAFLAGS) & 0x10000) && !veteran) veteran = k;
        if (k[K_ON_MAP]) continue;                                   /* vanilla prefers fleets in port */
        if (!best || *(uint16_t *)(k + K_CANNONS) > *(uint16_t *)(best + K_CANNONS)) best = k;
    }
    return veteran ? veteran : best;
}

static const char *const k_adj[4] = {"English", "French", "Dutch", "Spanish"};
static const char *const k_names[4] = {"England", "France", "Holland", "Spain"};

void navy_daily(uint32_t day)
{
    if (!g_ready || !adapter_state()->founded) return;
    send_raids();
    for (int p = 0; p < 4; p++) {
        int war = G_U8(GA_PLAYER_REL + p) != 0;
        if (war && !g_was_war[p]) g_next_mission[p] = day;            /* a new war: strike at once */
        g_was_war[p] = (uint8_t)war;
        if (!war || day < g_next_mission[p] || power_has_mission(p)) continue;
        uint8_t *k = pick_fleet(p);
        if (!k) continue;
        g_next_mission[p] = day + MISSION_GAP_DAYS;
        if (AssignWarMission(k, 5, 1)) {
            log_line("NAVY: %s fleet %08X sent against the nation (ships %u, cannons %u)", k_adj[p],
                     *(uint32_t *)(k + K_HANDLE), k[K_SHIPS], *(uint16_t *)(k + K_CANNONS));
            char msg[160];
            snprintf(msg, sizeof msg, "%s %s war fleet has put to sea against your nation. Look to your towns' defences!",
                     core_article(k_adj[p], 1), k_adj[p]);
            adapter_message(msg);
        } else {
            log_line("NAVY: %s war mission against the nation refused by the game (player rank too low?)", k_adj[p]);
        }
    }
}

void navy_world_ready(void)
{
    if (!g_ready) return;
    mirror_powers();
    rebuild_list();
    memset(g_next_mission, 0, sizeof g_next_mission);
    memset(g_raid_day, 0, sizeof g_raid_day);
    memset(g_raid_peace_told, 0, sizeof g_raid_peace_told);
    port_watch_reset();
    g_disband_pending = 0;
    g_order = adapter_state()->navy.order;
    for (int p = 0; p < 4; p++) g_was_war[p] = G_U8(GA_PLAYER_REL + p) != 0;
}

/* ---- fleets: orders, assaults, raids, plunder, pay-off ----------------------
   research/navy_operations.md. Patrol is the game's own behaviour: with the
   sortie sites opted in, a fleet at home strikes at a weak enemy port every
   few decisions and fights what it meets. War campaign: a fleet that anchors
   at an enemy town besieges it (hook S); a won land assault annexes the town
   (war.c). Raid: fleets circle an enemy port and attack that power's
   convoys. Captured cargo becomes treasury gold when the fleet docks (hook K). */
#define K_STATE_DOCKED   2
#define K_STATE_ANCHORED 4
#define K_STATE_BATTLE   9
#define K_FLAGS48        0x48          /* word: attack mask; 0x40 = attack towns */
#define K_SAILORS        0x86
#define K_GOODS          0xBE          /* u16[20] hold */
#define K_GROUP          0x4C
#define T_X              0x0E
#define T_Y              0x12
#define T_FLAGS2         0x44
#define SWP              ((const uint16_t *)0x00702114)     /* base price per good, gold per unit */
#define NOW_TICKS        (*(const uint32_t *)0x00702C14)    /* 256 ticks per day */
#define PLUNDER_PCT      50                                 /* captured cargo sells for half its base price */
typedef void *(__attribute__((thiscall)) *CurTown_t)(void *group);
typedef void (__cdecl *Attack_t)(uint32_t convoy_h);
typedef void (__cdecl *Delete_t)(uint32_t convoy_h);
typedef uint32_t *(__cdecl *MkPos_t)(uint32_t *out, int x, int y);
typedef void (__attribute__((thiscall)) *Circle_t)(void *k, const uint32_t *pos, uint32_t radius,
                                                    uint32_t target_h, uint32_t nation, uint32_t end_time);
#define ConvoyTown   ((CurTown_t)0x00635C40)     /* group = k+0x4C -> CStadt* */
#define TownAttack   ((Attack_t)0x00603030)      /* AI siege of the convoy's current town */
#define DeleteConvoy ((Delete_t)0x00635600)
#define MakePos      ((MkPos_t)0x0063ADC0)
#define TaskCircle   ((Circle_t)0x005AD9F0)      /* ret 0x14 */

static uint32_t game_day(void) { return NOW_TICKS / 256; }

/* test install: send the first fleet to a town and keep re-issuing the order (the
   fleet's own planner replaces the destination at every decision) until it arrives */
static uint32_t g_dev_fleet, g_dev_town_h;
static int g_dev_town, g_dev_ticks;

static uint8_t *fleet_by_handle(uint32_t h)
{
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (k && is_ours(k) && *(uint32_t *)(k + K_HANDLE) == h) return k;
    }
    return NULL;
}

static void dev_sail_tick(void)
{
    if (!g_dev_fleet || ++g_dev_ticks % 60) return;
    uint8_t *k = fleet_by_handle(g_dev_fleet);
    if (!k || g_dev_ticks > 60 * 600) { g_dev_fleet = 0; return; }
    uint32_t st = *(uint32_t *)(k + K_STATE);
    if (st == K_STATE_BATTLE) return;
    if (*(uint32_t *)(k + 0x9C) == g_dev_town_h) {                 /* arrived */
        log_line("NAVY dev: fleet %08X arrived at town %d", g_dev_fleet, g_dev_town);
        g_dev_fleet = 0;
        return;
    }
    if (*(uint32_t *)(k + K_DEST) != g_dev_town_h) {
        *(uint32_t *)(k + K_DEST) = g_dev_town_h;
        SailToTown(k, g_dev_town_h);
    }
}

/* ---- per-fleet orders ------------------------------------------------------------ */
typedef struct { uint32_t handle; uint8_t order, town; } FleetOrder;
#define MAX_FLEET_ORDERS 16
static FleetOrder g_fo[MAX_FLEET_ORDERS];
static int g_fo_n;

static FleetOrder *fleet_order(uint32_t h, int create)
{
    for (int i = 0; i < g_fo_n; i++)
        if (g_fo[i].handle == h) return &g_fo[i];
    if (!create || g_fo_n >= MAX_FLEET_ORDERS) return NULL;
    FleetOrder *f = &g_fo[g_fo_n++];
    memset(f, 0, sizeof *f);
    f->handle = h;
    return f;
}

/* the order a fleet follows now: its own, or the nation's standing order */
static int effective_order(const uint8_t *k)
{
    FleetOrder *f = fleet_order(*(const uint32_t *)(k + K_HANDLE), 0);
    if (f && f->order != FLEET_STANDING) return f->order;
    return g_order == NAVY_RAID ? FLEET_RAID : g_order == NAVY_WAR ? FLEET_CAMPAIGN : FLEET_STANDING;
}

void navy_disband(int n)
{
    g_disband_pending += n;
    log_line("NAVY: %d fleet(s) to pay off (as soon as they are out of battle)", g_disband_pending);
}

void navy_apply_order(int order)
{
    g_order = order;
    log_line("NAVY: standing order %d", order);
}

static int is_ours(const uint8_t *k)
{
    uint32_t type = *(const uint32_t *)(k + K_TYPE);
    return k[K_NATION] == 5 && (type == KT_MILITARY || type == KT_WAR_MISSION);
}

/* the game day of each fleet's last attack on a town (slot = handle % 16) */
static uint32_t g_attack[16][2];

static int attacked_within(uint32_t h, uint32_t days)
{
    uint32_t *a = g_attack[h % 16];
    return a[0] == h && game_day() < a[1] + days;
}

/* hook S (0x5B4E35, type-4 arrival): a fleet under "war campaign" that anchors at an enemy town attacks it */
static void on_fleet_arrived(Regs *r)
{
    uint8_t *k = (uint8_t *)(uintptr_t)r->esi;
    if (!g_ready || !k || !is_ours(k) || *(uint32_t *)(k + K_STATE) != K_STATE_ANCHORED) return;
    if (effective_order(k) != FLEET_CAMPAIGN) return;
    uint8_t *t = (uint8_t *)ConvoyTown(k + K_GROUP);
    if (!t) return;
    int owner = t[0x390];
    if (owner >= 4 || !G_U8(GA_PLAYER_REL + owner) || (*(uint32_t *)(t + T_FLAGS2) & 0x2000)) return;   /* viceroy seats hold */
    uint32_t th = *(uint32_t *)(t + 0x38 + 0x91A4);
    if (PR2_BattleAtTown((void *)0x007036C0, th)) return;
    /* one attack per fleet per week: a beaten fleet must not storm again at once with what is left */
    uint32_t h = *(uint32_t *)(k + K_HANDLE);
    if (attacked_within(h, 7)) return;
    uint16_t soldiers = *(uint16_t *)(t + T_SOLDIERS), sailors = *(uint16_t *)(k + K_SAILORS);
    uint8_t towers = t[T_TOWERS];
    if (sailors <= soldiers && *(uint16_t *)(k + K_CANNONS) <= 20u * towers) return;   /* vanilla's courage test */
    g_attack[h % 16][0] = h;
    g_attack[h % 16][1] = game_day();
    *(uint16_t *)(k + K_FLAGS48) |= 0x40;
    log_line("NAVY: fleet %08X attacks %s %s town (sailors %u vs %u soldiers, %u towers; day %u)",
             *(uint32_t *)(k + K_HANDLE), core_article(k_adj[owner], 0), k_adj[owner], sailors, soldiers, towers,
             game_day());
    TownAttack(fleet_handle(k));
}

/* hook K (0x5B582A, harbour sub-state 1, just before vanilla deletes the hold): plunder -> treasury */
static void on_fleet_unload(Regs *r)
{
    uint8_t *k = (uint8_t *)(uintptr_t)r->esi;
    if (!g_ready || !k || !is_ours(k)) return;
    int64_t gold = 0;
    for (int g = 0; g < 19; g++) {
        if (g == 0 || g == 1 || g == 5) continue;               /* weapons stay with the fleet */
        gold += (int64_t)((uint16_t *)(k + K_GOODS))[g] * SWP[g];
    }
    gold = gold * PLUNDER_PCT / 100;
    if (gold <= 0) return;
    core_navy_credit(adapter_state(), gold);
    log_line("NAVY: fleet %08X brought home plunder worth %lld gold", *(uint32_t *)(k + K_HANDLE), (long long)gold);
    if (gold >= 1000) {
        char msg[160];
        snprintf(msg, sizeof msg, "A fleet of %s brings home plunder worth %lld gold for the treasury.",
                 adapter_state()->name, (long long)gold);
        adapter_message(msg);
    }
}

/* raid: a docked fleet puts to sea for a port of a power at war with the nation and circles it.
   The Circle task must be given AT SEA. Given in port it traps the fleet: the harbour AI
   0x5B53C0 skips the harbour cycle while a task runs and only re-plans the circle
   (0x5B0AA0 -> 0x5AD9F0), which plots a route but never leaves the town -- only SailToPos
   0x5AE1B0 (via SailToTown) calls LeaveTown 0x6374A0. So the day's raid check sends the fleet out
   towards the target port (state 0 at once; it is linked into the sea map a moment later), and
   raid_tick gives it the Circle task as soon as it is on the map. research/navy_operations.md 3.4 */
#define RAID_DAYS 20
#define RAID_REFIT_DAYS 2
static uint32_t docked_since(uint32_t h);
typedef void (__attribute__((thiscall)) *TaskNone_t)(void *k);
#define TaskNone ((TaskNone_t)0x005ADAF0)
#define K_TASK   0x1B8
#define K_TASK_NATION 0x1C0      /* byte: the task attacks every convoy of this nation (circle / stay) */
#define K_TASK_END 0x1C8
#define K_STATE_WAIT 3

static RaidDay *raid_slot(uint32_t h)
{
    int free_i = -1;
    for (int i = 0; i < 16; i++) {
        if (g_raid_day[i].h == h) return &g_raid_day[i];
        if (!g_raid_day[i].h && free_i < 0) free_i = i;
    }
    RaidDay *r = &g_raid_day[free_i < 0 ? (int)(h % 16) : free_i];
    memset(r, 0, sizeof *r);
    r->h = h;
    return r;
}

static void send_raids(void)
{
    int wars[4], nw = 0;
    for (int p = 0; p < 4; p++) if (G_U8(GA_PLAYER_REL + p)) wars[nw++] = p;
    if (!nw) return;
    uint32_t day = game_day();
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k) || *(uint32_t *)(k + K_STATE) != K_STATE_DOCKED) continue;
        if (effective_order(k) != FLEET_RAID || *(uint32_t *)(k + K_TASK) || k[K_SHIPS] < 2) continue;
        uint32_t h = *(uint32_t *)(k + K_HANDLE);
        RaidDay *r = raid_slot(h);
        if (r->pending || (r->day && day < r->day + RAID_DAYS)) continue;
        if (day < docked_since(h) + RAID_REFIT_DAYS) continue;   /* the harbour cycle repairs and re-arms first */
        int p = wars[(h + day) % (uint32_t)nw];
        int towns[64], nt = 0;
        for (int t = 0; t < eng_town_count() && nt < 64; t++) {
            uint8_t *tp = eng_town_ptr(t);
            if (tp && tp[0x390] == p) towns[nt++] = t;
        }
        if (!nt) continue;
        int t = towns[(h / 7 + day) % (uint32_t)nt];
        uint32_t th = eng_town_handle(t);
        if (!th) continue;
        *(uint32_t *)(k + K_DEST) = th;
        SailToTown(k, th);
        if (*(uint32_t *)(k + K_STATE) == K_STATE_DOCKED) {
            log_line("NAVY: fleet %08X cannot put to sea for a raid on %s (ships %u, sailors %u); tried again "
                     "tomorrow", h, eng_town_name(t), k[K_SHIPS], *(uint16_t *)(k + K_SAILORS));
            continue;
        }
        r->day = day;
        r->town = (int16_t)t;
        r->power = (uint8_t)p;
        r->pending = 1;
        log_line("NAVY: fleet %08X sails to raid %s shipping around %s", h, k_adj[p], eng_town_name(t));
    }
}

/* Raids only ever hit a power the nation is at war with (the Holland war fix). A Circle or Stay task attacks every
   convoy whose nation byte matches the task's (+0x1C0), whatever the diplomacy (research/navy_operations.md
   3.3): a raid begun in a war goes on after a ceasefire or peace unless it is called off. So a raid task
   against a power at peace is cancelled at once (the fleet goes back to its own patrol), and the player is
   told once per peace. Returns 1 when it cancelled the task. */

static int stop_raid_at_peace(uint8_t *k, uint32_t h)
{
    uint32_t task = *(uint32_t *)(k + K_TASK);
    int p = k[K_TASK_NATION];
    if ((task != 2 && task != 3) || p >= 4 || G_U8(GA_PLAYER_REL + p)) return 0;
    TaskNone(k);
    raid_slot(h)->day = 0;
    log_line("NAVY: fleet %08X stops raiding %s shipping: the nation is not at war with %s (task %u cancelled)",
             h, k_adj[p], k_names[p], task);
    if (!g_raid_peace_told[p]) {
        g_raid_peace_told[p] = 1;
        char msg[160];
        snprintf(msg, sizeof msg, "Your fleets break off their raids on %s shipping: the nation is not at war with %s.",
                 k_adj[p], k_names[p]);
        adapter_message(msg);
    }
    return 1;
}

/* The attack mask (+0x48: bit j = traders of power j, bit j+7 = its warships, 4 pirates, 6 towns) is rebuilt
   from the nation's wars only now and then (0x63C280, about every 256 ticks); in between, game events can OR
   a power's bit into it (0x5F1BC0, the patrol event). So the bits of every power the nation is not at war
   with are cleared here as well; NewSeaBattle refuses what slips through (replog.c). */
static void strip_peace_bits(uint8_t *k, uint32_t h)
{
    uint16_t m = *(uint16_t *)(k + K_FLAGS48), keep = m;
    for (int p = 0; p < 4; p++)
        if (!G_U8(GA_PLAYER_REL + p)) keep &= (uint16_t)~((1u << p) | (0x80u << p));
    if (keep == m) return;
    *(uint16_t *)(k + K_FLAGS48) = keep;
    static uint32_t logged;
    if (logged++ < 50)
        log_line("NAVY: fleet %08X attack mask %04X -> %04X (powers it is not at war with taken out)", h, m, keep);
}

/* every ~0.5 s: (1) a fleet sent out to raid gets its Circle task once it is on the sea map;
   (2) a fleet of ours sitting in port with a task is trapped there (see above) -- saves from
   before this fix have such fleets, and one can dock with its task still running. The task is
   cancelled: its harbour cycle resumes and the next day's raid check sends it out properly.
   (3) a raid on a power the nation is no longer at war with is called off (stop_raid_at_peace). */
static void raid_tick(void)
{
    static int ticks;
    if (++ticks % 30) return;
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    uint32_t day = game_day();
    for (int p = 0; p < 4; p++)
        if (G_U8(GA_PLAYER_REL + p)) g_raid_peace_told[p] = 0;      /* a new war: tell again at its end */
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k)) continue;
        uint32_t h = *(uint32_t *)(k + K_HANDLE), st = *(uint32_t *)(k + K_STATE);
        strip_peace_bits(k, h);
        if (stop_raid_at_peace(k, h)) continue;
        RaidDay *r = NULL;
        for (int j = 0; j < 16; j++)
            if (g_raid_day[j].h == h) r = &g_raid_day[j];
        if (r && r->pending) {
            if (r->power < 4 && !G_U8(GA_PLAYER_REL + r->power)) {      /* peace came while it sailed out */
                log_line("NAVY: fleet %08X does not start its raid on %s shipping: the nation is not at war with %s",
                         h, k_adj[r->power], k_names[r->power]);
                r->pending = 0;
                r->day = 0;
                continue;
            }
            if (st == 0 && k[K_ON_MAP]) {
                uint8_t *tp = eng_town_ptr(r->town);
                r->pending = 0;
                if (!tp) continue;
                uint32_t pos[2] = {0, 0}, end = (r->day + RAID_DAYS) * 256u;
                MakePos(pos, *(uint16_t *)(tp + T_X), *(uint16_t *)(tp + T_Y));
                TaskCircle(k, pos, 250, 0x0002FFFF, r->power, end > NOW_TICKS ? end : NOW_TICKS + 256);
                if (*(uint32_t *)(k + K_TASK) == 2)
                    log_line("NAVY: fleet %08X raids %s shipping around %s (until day %u)", h, k_adj[r->power],
                             eng_town_name(r->town), end / 256);
                else
                    log_line("NAVY: fleet %08X: no raid route to %s; it sails there on its own", h,
                             eng_town_name(r->town));
            } else if (st == K_STATE_DOCKED && day > r->day + 1) {
                r->pending = 0;                                /* never got out: due again */
                r->day = 0;
            }
            continue;
        }
        if (st == K_STATE_DOCKED && *(uint32_t *)(k + K_TASK)) {
            log_line("NAVY: fleet %08X held in port by a task (%u, ends day %u): cancelled", h,
                     *(uint32_t *)(k + K_TASK), *(uint32_t *)(k + K_TASK_END) / 256);
            TaskNone(k);
            raid_slot(h)->day = 0;                             /* due again */
        }
    }
}

int navy_dev_sail(int town)
{
    uint32_t th = eng_town_handle(town);
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    if (!g_ready || !th) return 0;
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k) || *(uint32_t *)(k + K_STATE) == K_STATE_BATTLE) continue;
        *(uint32_t *)(k + K_DEST) = th;
        char ok = SailToTown(k, th);
        g_dev_fleet = *(uint32_t *)(k + K_HANDLE);
        g_dev_town_h = th;
        g_dev_town = town;
        g_dev_ticks = 0;
        log_line("NAVY dev: fleet %08X sails to town %d (%s): %d", g_dev_fleet, town, eng_town_name(town), ok);
        return ok ? 1 : 0;
    }
    return 0;
}

int navy_dev_soldiers(int town, int n)
{
    uint8_t *t = eng_town_ptr(town);
    if (!t) return 0;
    *(uint16_t *)(t + T_SOLDIERS) = (uint16_t)n;
    return 1;
}

int navy_fleets(FleetInfo *out, int max)
{
    int n, c = 0;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n && c < max; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k)) continue;
        FleetInfo *o = &out[c++];
        o->handle = *(uint32_t *)(k + K_HANDLE);
        o->ships = k[K_SHIPS];
        o->sailors = *(uint16_t *)(k + K_SAILORS);
        o->state = (int)*(uint32_t *)(k + K_STATE);
        uint32_t th = *(uint32_t *)(k + 0x9C);
        o->town = (th & 0xFFFF) < 0xFFFF ? (int)(th & 0xFFFF) : -1;
        FleetOrder *f = fleet_order(o->handle, 0);
        o->order = f ? f->order : FLEET_STANDING;
        o->target = f && (f->order == FLEET_GUARD || f->order == FLEET_CAMPAIGN) ? f->town : -1;
        uint32_t dh = *(uint32_t *)(k + K_DEST);
        o->dest = (dh & 0xFFFF) < 0xFFFF && (int)(dh & 0xFFFF) < eng_town_count() ? (int)(dh & 0xFFFF) : -1;
    }
    return c;
}

/* guard: towns of the nation; campaign: towns of powers at war with the nation */
static int target_ok(int order, int t)
{
    uint8_t *tp = eng_town_ptr(t);
    if (!tp) return 0;
    if (order == FLEET_GUARD) return tp[0x390] == 5;
    return tp[0x390] < 4 && G_U8(GA_PLAYER_REL + tp[0x390]) && !(*(uint32_t *)(tp + T_FLAGS2) & 0x2000);
}

static int first_target(int order, int after)
{
    int n = eng_town_count();
    for (int k = 1; k <= n; k++) {
        int t = ((after < 0 ? -1 : after) + k + n) % n;
        if (target_ok(order, t)) return t;
    }
    return -1;
}

int navy_fleet_next_order(uint32_t h, char *why, int why_len)
{
    World w;
    adapter_snapshot(&w);
    int rank = core_naval_rank(adapter_state(), &w);
    FleetOrder *f = fleet_order(h, 1);
    if (!f || !fleet_by_handle(h)) { snprintf(why, why_len, "That fleet is no longer in service."); return 0; }
    for (int step = 1; step <= FLEET_ORDER_COUNT; step++) {
        int o = (f->order + step) % FLEET_ORDER_COUNT;
        int need = o == FLEET_RAID ? core_order_min_rank(NAVY_RAID) : o == FLEET_CAMPAIGN ? core_order_min_rank(NAVY_WAR) : 0;
        if (rank < need) continue;
        int t = (o == FLEET_GUARD || o == FLEET_CAMPAIGN) ? first_target(o, -1) : -1;
        if ((o == FLEET_GUARD || o == FLEET_CAMPAIGN) && t < 0) continue;     /* nothing to guard / attack */
        f->order = (uint8_t)o;
        f->town = (uint8_t)(t < 0 ? 0 : t);
        log_line("NAVY: fleet %08X order %d target %d", h, o, t);
        return 1;
    }
    snprintf(why, why_len, "No other order is possible for this fleet now.");
    return 0;
}

int navy_fleet_next_target(uint32_t h, char *why, int why_len)
{
    FleetOrder *f = fleet_order(h, 0);
    if (!f || (f->order != FLEET_GUARD && f->order != FLEET_CAMPAIGN)) {
        snprintf(why, why_len, "Only a guard or campaign order has a target.");
        return 0;
    }
    int t = first_target(f->order, f->town);
    if (t < 0) { snprintf(why, why_len, "There is no other target."); return 0; }
    f->town = (uint8_t)t;
    return 1;
}

/* every ~2 s: guard and campaign fleets head for their town (their planner keeps choosing others) */
static void fleet_orders_tick(void)
{
    static int ticks;
    if (++ticks % 120) return;
    for (int i = 0; i < g_fo_n; i++) {
        FleetOrder *f = &g_fo[i];
        if (f->order != FLEET_GUARD && f->order != FLEET_CAMPAIGN) continue;
        uint8_t *k = fleet_by_handle(f->handle);
        if (!k) continue;
        if (!target_ok(f->order, f->town)) {                 /* taken, lost or at peace now */
            int t = first_target(f->order, f->town);
            if (t < 0) { f->order = FLEET_STANDING; continue; }
            f->town = (uint8_t)t;
        }
        uint32_t th = eng_town_handle(f->town);
        if (!th || *(uint32_t *)(k + K_STATE) == K_STATE_BATTLE || *(uint32_t *)(k + 0x9C) == th) continue;
        if (f->order == FLEET_CAMPAIGN) {
            /* leave the fleet to the game while its siege runs, for two weeks after an attack (it sails home
               and refits), and while it is too weak for the garrison */
            uint8_t *t = eng_town_ptr(f->town);
            unsigned sailors = *(uint16_t *)(k + K_SAILORS);
            if (PR2_BattleAtTown((void *)0x007036C0, th) || attacked_within(f->handle, 14) || sailors < 100
                || (t && sailors < 2u * *(uint16_t *)(t + T_SOLDIERS))) continue;
        }
        if (*(uint32_t *)(k + K_DEST) != th) {
            *(uint32_t *)(k + K_DEST) = th;
            SailToTown(k, th);
        }
    }
}

/* a newly fitted-out fleet takes over the order of a fleet that was lost */
static void adopt_orphan_order(void)
{
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k)) continue;
        uint32_t h = *(uint32_t *)(k + K_HANDLE);
        if (fleet_order(h, 0)) continue;
        for (int j = 0; j < g_fo_n; j++) {
            if (g_fo[j].order == FLEET_STANDING || fleet_by_handle(g_fo[j].handle)) continue;
            log_line("NAVY: fleet %08X takes over the order of lost fleet %08X (order %d target %d)",
                     h, g_fo[j].handle, g_fo[j].order, g_fo[j].town);
            g_fo[j].handle = h;
            return;
        }
        return;
    }
}

int navy_save_orders(uint8_t *buf, int cap)
{
    int n = 0;
    for (int i = 0; i < g_fo_n; i++) {
        if (g_fo[i].order == FLEET_STANDING || !fleet_by_handle(g_fo[i].handle)) continue;
        if (n + 6 > cap) break;
        memcpy(buf + n, &g_fo[i].handle, 4);
        buf[n + 4] = g_fo[i].order;
        buf[n + 5] = g_fo[i].town;
        n += 6;
    }
    return n;
}

void navy_load_orders(const uint8_t *buf, int len)
{
    g_fo_n = 0;
    if (!buf || len <= 0) return;
    for (int o = 0; o + 6 <= len && g_fo_n < MAX_FLEET_ORDERS; o += 6) {
        FleetOrder *f = &g_fo[g_fo_n++];
        memcpy(&f->handle, buf + o, 4);
        f->order = buf[o + 4] < FLEET_ORDER_COUNT ? buf[o + 4] : FLEET_STANDING;
        f->town = buf[o + 5];
    }
    log_line("NAVY: %d fleet order(s) restored", g_fo_n);
}

static void run_disbands(void)
{
    if (g_disband_pending <= 0) return;
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; slots && i < n && g_disband_pending > 0; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k) || *(uint32_t *)(k + K_STATE) == K_STATE_BATTLE) continue;   /* never mid-battle */
        uint32_t h = fleet_handle(k);
        DeleteConvoy(h);
        g_disband_pending--;
        log_line("NAVY: fleet %08X paid off (%d in the world, %d on the nation's list)", h, navy_fleet_count(),
                 navy_list_count());
    }
}

/* ---- effects from the core ------------------------------------------------ */

static int g_spawn_q[8], g_spawn_n;               /* towns waiting for a new fleet */

static void refund(int64_t gold, int cat, const char *what)
{
    if (gold <= 0) return;
    core_refund(adapter_state(), gold, cat);
    log_line("NAVY: %lld gold refunded (%s)", (long long)gold, what);
}

void navy_effect(const Effect *e)
{
    switch (e->kind) {
    case FX_FLEET_SPAWN:
        if (g_spawn_n < (int)(sizeof g_spawn_q / sizeof g_spawn_q[0])) g_spawn_q[g_spawn_n++] = e->a;
        else refund(adapter_config()->fleet_cost, LG_NEW_FLEETS, "spawn queue full");
        break;
    case FX_FLEET_DISBAND:
        navy_disband(e->a);
        break;
    case FX_FLEET_ORDER:
        navy_apply_order(e->a);
        break;
    case FX_GARRISON: {
        uint8_t *t = eng_town_ptr(e->a);
        int amount = (int)e->v;
        if (!t || PR2_BattleAtTown((void *)0x007036C0, eng_town_handle(e->a))) {
            refund(e->v, LG_SOLDIERS, "garrison: no town or a battle is running there");
            break;
        }
        PR2_AddSoldierBudget(t, &amount);                 /* the town takes what it can house */
        log_line("NAVY: town %d soldier budget +%d of %lld", e->a, amount, (long long)e->v);
        refund(e->v - amount, LG_SOLDIERS, "garrison: the town cannot house more soldiers");
        break;
    }
    case FX_TOWER: {
        uint8_t *t = eng_town_ptr(e->a);
        if (!t || PR2_BattleAtTown((void *)0x007036C0, eng_town_handle(e->a))) {
            refund(e->v, LG_TOWERS, "tower: no town or a battle is running there");
            if (e->a >= 0 && e->a < MAX_TOWNS && adapter_state()->navy.towers_bought[e->a]) adapter_state()->navy.towers_bought[e->a]--;
            break;
        }
        uint8_t before = t[T_TOWERS];
        PR2_AddTowerBudget(t + T_BUDGET, t + T_LAGER, (int)e->v);
        if (t[T_TOWERS] == before) {                    /* the build failed and wiped the tower budget */
            refund(e->v, LG_TOWERS, "tower could not be built");
            if (adapter_state()->navy.towers_bought[e->a]) adapter_state()->navy.towers_bought[e->a]--;
        } else {
            log_line("NAVY: town %d cannon towers %u -> %u", e->a, before, t[T_TOWERS]);
        }
        break;
    }
    default:
        break;
    }
}

void navy_town_defence(int town, int *soldiers, int *towers, int *budget)
{
    uint8_t *t = eng_town_ptr(town);
    *soldiers = t ? *(uint16_t *)(t + T_SOLDIERS) : 0;
    *towers = t ? t[T_TOWERS] : 0;
    *budget = t ? *(int32_t *)(t + T_BUDGET) : 0;
}

static void run_spawns(void)
{
    while (g_spawn_n > 0) {
        int town = g_spawn_q[--g_spawn_n];
        int before = navy_fleet_count();
        char code[160];
        snprintf(code, sizeof code, "Global_CreateMilitaryConvoy(0, Nation_TownHandle(%d))", town);
        plua_run(code);
        if (navy_fleet_count() == before + 1) {
            log_line("NAVY: fleet commissioned at town %d (%d in service)", town, before + 1);
            adopt_orphan_order();
            navy_apply_order(adapter_state()->navy.order);
        } else {
            log_line("NAVY: commissioning at town %d FAILED; refunded", town);
            refund(adapter_config()->fleet_cost, LG_NEW_FLEETS, "commissioning failed");
        }
    }
}

/* ---- port watch: the log says when a fleet really leaves port and when it is back ----
   An order only sets a task or a destination; the fleet's own harbour cycle decides when it
   sails. In port = state 2 (docked) or 3 (waiting in a town); the sea-map flag +0x1C is not
   used here, it flickers while a convoy anchors at a foreign town. */
#define MAX_WATCH 16
static struct { uint32_t h, since; uint16_t town; uint8_t at_sea, seen; } g_watch[MAX_WATCH];
static int g_watch_n;

/* game day the fleet last docked (the day it was first seen, if it has not moved since) */
static uint32_t docked_since(uint32_t h)
{
    for (int i = 0; i < g_watch_n; i++)
        if (g_watch[i].h == h) return g_watch[i].since;
    return game_day();
}

static void port_watch_reset(void) { g_watch_n = 0; }

static void port_watch_tick(void)
{
    static int ticks;
    if (++ticks % 30) return;
    int n;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    for (int i = 0; i < g_watch_n; i++) g_watch[i].seen = 0;
    for (int i = 0; slots && i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || !is_ours(k)) continue;
        uint32_t h = *(uint32_t *)(k + K_HANDLE), st = *(uint32_t *)(k + K_STATE);
        int at_sea = st != K_STATE_DOCKED && st != K_STATE_WAIT;
        uint16_t town = (uint16_t)(*(uint32_t *)(k + 0x9C) & 0xFFFF);
        int w = 0;
        while (w < g_watch_n && g_watch[w].h != h) w++;
        if (w == g_watch_n) {                                  /* first sight: no event */
            if (g_watch_n >= MAX_WATCH) continue;
            g_watch_n++;
            g_watch[w].h = h;
            g_watch[w].at_sea = (uint8_t)at_sea;
            g_watch[w].town = town;
            g_watch[w].since = game_day();
        } else if (at_sea != g_watch[w].at_sea) {
            uint16_t t = at_sea ? g_watch[w].town : town;
            const char *name = t < eng_town_count() ? eng_town_name(t) : "?";
            if (at_sea) {
                uint32_t dest = *(uint32_t *)(k + K_DEST) & 0xFFFF;
                log_line("NAVY: fleet %08X leaves port at %s for %s (day %u)", h, name,
                         dest < (uint32_t)eng_town_count() ? eng_town_name((int)dest) : "the open sea", game_day());
            } else {
                log_line("NAVY: fleet %08X in port at %s (day %u)", h, name, game_day());
                g_watch[w].since = game_day();
            }
            g_watch[w].at_sea = (uint8_t)at_sea;
        }
        if (!at_sea) g_watch[w].town = town;
        g_watch[w].seen = 1;
    }
    for (int i = 0; i < g_watch_n;)                            /* lost or paid off */
        if (!g_watch[i].seen) g_watch[i] = g_watch[--g_watch_n];
        else i++;
}

void navy_frame(void)
{
    if (!g_ready || !g_pc_built) return;
    for (int p = 0; p < 4; p++)                  /* friend/foe follows the nation's wars */
        g_pc[p] = G_U8(GA_PLAYER_REL + p) ? 1 : 0;
    run_spawns();
    run_disbands();
    dev_sail_tick();
    fleet_orders_tick();
    if (adapter_world_ready()) {                 /* not while a save is still loading */
        raid_tick();
        port_watch_tick();
    }
}

/* Counted in the convoy pool rather than in g_pc+8: the pool is what the game sails. */
int navy_fleet_count(void)
{
    int n, count = 0;
    uint32_t *slots = (uint32_t *)convoy_slots(&n);
    if (!g_ready || !slots) return 0;
    for (int i = 0; i < n; i++) {
        uint8_t *k = (uint8_t *)(uintptr_t)slots[i];
        if (!k || k[K_NATION] != 5) continue;
        uint32_t type = *(uint32_t *)(k + K_TYPE);
        if (type == KT_MILITARY || type == KT_WAR_MISSION) count++;
    }
    return count;
}

int navy_list_count(void) { return g_ready && g_pc_built ? CNation_MilCount(g_pc) : 0; }

int navy_ready(void) { return g_ready; }

/* ---- install --------------------------------------------------------------- */

static int opt_in(const char *name, uint32_t guard, uint8_t reg_modrm, uint32_t disp_at)
{
    const uint8_t g_old[3] = {0x83, reg_modrm, 0x04}, g_new[3] = {0x83, reg_modrm, 0x06};
    uint32_t want = G_NATIONS, mine = (uint32_t)(uintptr_t)g_nations6;
    if (memcmp((void *)(uintptr_t)guard, g_old, 3) || memcmp((void *)(uintptr_t)disp_at, &want, 4)) {
        log_line("NAVY: %s: original bytes differ, not opted in", name);
        return 0;
    }
    return patch_bytes(name, disp_at, (const uint8_t *)&want, (const uint8_t *)&mine, 4)
         & patch_bytes(name, guard, g_old, g_new, 3);
}

static int repoint_flag(uint32_t disp_at)
{
    uint32_t old = 0x006AC4B4, mine = (uint32_t)(uintptr_t)g_flag6;
    return patch_bytes("navy.flagship", disp_at, (const uint8_t *)&old, (const uint8_t *)&mine, 4);
}

/* P01's stub: `jae war` (73 23 at +0x1E) -> `jae notpower` (73 1E), which maps 5 to peace. */
static int fix_p01(void)
{
    uint8_t *at = (uint8_t *)0x005BA0A0;
    if (at[0] != 0xE9) { log_line("NAVY: IsAtWar is not detoured (P01 missing)"); return 0; }
    uint32_t stub = 0x005BA0A5 + *(int32_t *)(at + 1);
    static const uint8_t old[] = {0x73, 0x23}, rep[] = {0x73, 0x1E};
    return patch_bytes("navy.P01 self-peace", stub + 0x1E, old, rep, 2);
}

void navy_install(void)
{
    static const uint8_t h1[] = {0xB9, 0x68, 0x20, 0x70, 0x00};   /* mov ecx, 0x702068 */
    static const uint8_t h2[] = {0x8B, 0x4C, 0x24, 0x10, 0x5E};   /* mov ecx,[esp+0x10]; pop esi */
    int ok = 1;
    ok &= hook_install("navy.World::Reset end", 0x005D12EB, h1, sizeof h1, on_world_reset_end);
    ok &= hook_install("navy.CreateNations end", 0x005D14F5, h2, sizeof h2, on_nations_created);
    if (!ok) { log_line("NAVY: lifecycle hooks missing; the navy stays off"); return; }
    ok &= opt_in("navy.SetType", 0x0063707A, 0xF8, 0x0063708D);
    ok &= opt_in("navy.ClearOwner", 0x00636720, 0xF8, 0x00636728);
    ok &= opt_in("navy.HomePicker", 0x0063C7A0, 0xF8, 0x0063C7AB);
    ok &= opt_in("navy.AttackMask", 0x0063C28C, 0xFE, 0x0063C29F);
    ok &= opt_in("navy.AttackMaskInner", 0x0063C34E, 0xFE, 0x0063C356);
    ok &= repoint_flag(0x006352C0) & repoint_flag(0x00634944) & repoint_flag(0x0063511C)
        & repoint_flag(0x006344AC);
    ok &= fix_p01();
    static const uint8_t aw_old[] = {0x80, 0xFB, 0x04}, aw_new[] = {0x80, 0xFB, 0x06};   /* cmp bl,4 -> 6 */
    ok &= patch_bytes("navy.AssignWarMission target 5", 0x005B4892, aw_old, aw_new, 3);
    /* the player-rank gate inside AssignWarMission: the DLL's missions against the nation
       must not depend on the founder's personal rank (the war-start handler keeps its own) */
    static const uint8_t rk_old[] = {0x0F, 0x86, 0xEE, 0x00, 0x00, 0x00}, rk_new[] = {0x90, 0x90, 0x90, 0x90, 0x90, 0x90};
    ok &= patch_bytes("navy.AssignWarMission rank gate", 0x005B48C4, rk_old, rk_new, 6);
    ok &= opt_in("navy.Sortie", 0x005B1FF7, 0xF8, 0x005B2003);
    ok &= opt_in("navy.SortieTarget", 0x0063B3C8, 0xF8, 0x0063B3DA);
    ok &= opt_in("navy.SiegeFlag", 0x0063C463, 0xF8, 0x0063C46B);
    static const uint8_t hs[] = {0x8B, 0x96, 0xB0, 0x01, 0x00, 0x00};   /* mov edx,[esi+0x1B0] */
    static const uint8_t hk[] = {0x32, 0xDB, 0x88, 0x5C, 0x24, 0x10};   /* xor bl,bl; mov [esp+0x10],bl */
    ok &= hook_install("navy.FleetArrived", 0x005B4E35, hs, sizeof hs, on_fleet_arrived);
    ok &= hook_install("navy.FleetUnload", 0x005B582A, hk, sizeof hk, on_fleet_unload);
    g_ready = ok;
    log_line("NAVY: %s", ok ? "ready (nation 5 has a CNation; 5 military sites opted in)"
                            : "NOT ready: a patch failed (see above)");
}
