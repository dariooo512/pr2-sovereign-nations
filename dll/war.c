/* War and conquest hooks (research/conquest_transfer.md §3-§4, spec §4.2-4.3,
 * TER-01, TER-03, MIL-01). See war.h.
 *
 * Every hook site was checked against PR2.exe.unpacked.exe with capstone: the
 * bytes match, the range ends on an instruction boundary, the displaced
 * instructions are position-independent (no rel8/rel32), and no branch or
 * jump table in .text targets the inside of a range.
 *
 *  #  site      displaced instructions                    purpose
 *  1  0x60309F  shr ecx,16h / test cl,1        (6)       NewCoastBattle: player convoy vs own-nation town -> refuse
 *  2  0x5B4B2D  shr edx,16h / test dl,1        (6)       convoy arrival with attack flag: same refusal
 *  3  0x6011BE  mov al,[esi+58h] / cmp al,4    (5)       CCoastBattle state 8 (player won): record conquest,
 *                                                        suppress vanilla power annexation (+59h=FF, +58h&=~4)
 *  4  0x601481  movzx eax,byte[esi+59h] / cmp eax,4 (7)  CCoastBattle annex execute: guard -> vanilla withdraw (0x60155D)
 *  5  0x605A50  sub esp,0Ch / push ebx / push esi (5)    CHarbourBattle state 7 (player won): record conquest
 *  6  0x605D9C  movzx edi,byte[esp+17h] / cmp edi,4 (8)  CHarbourBattle annex execute: guard -> skip 0x5BC310
 *  7  0x602500  sub esp,10h / mov edx,[esp+18h] (7)      AI town assault won (plunder fn): AI conquest of nation-5 town
 *
 * Hook handlers only read/write game memory and queue work; everything that
 * runs the core, Lua or the UI happens in war_frame() / the UI calls.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "war.h"
#include "hook.h"
#include "log.h"
#include "adapter.h"
#include "core.h"
#include "engine.h"
#include "game.h"

/* ---- game access ---------------------------------------------------------- */
typedef void *(__attribute__((thiscall)) *PoolGet_t)(void *pool, uint32_t h);
#define PoolGet       ((PoolGet_t)0x0041F620)      /* handle pool lookup, NULL if stale; ret 4 */
#define POOL_TOWNS    ((void *)0x00702068)
#define POOL_CONVOYS  ((void *)0x00701EE8)
#define POOL_BATTLES  ((void *)0x007036C0)         /* battle store (add 0x5FCCA0, remove 0x5FCCF0) */

/* CStadt */
enum { T_LAGER = 0x38, T_FLAGS = 0x40, T_FLAGS2 = 0x44, T_NATION = 0x390 };
#define L_HANDLE        0x91A4                     /* lager + 0x91A4 = town handle */
#define TF_PLAYERTOWN   (1u << 22)                 /* the bit vanilla's refusal tests */
#define TF2_VICEROY     0x2000u
/* CKonvoi */
enum { K_TYPE = 0xB4, K_NATION = 0xB8 };
#define KT_PLAYER       1
#define KT_MILITARY     4
/* battles */
#define VT_COAST        0x006AB578u                /* CCoastBattle (land side) */
#define VT_HARBOUR      0x006AB648u                /* CHarbourBattle (sea side) */
#define B_HANDLE        0x04                       /* battle-store handle (0x514C70 copies this+4) */
enum { CB_TOWN = 0x18, CB_OUTCOME = 0x58, CB_ANNEXER = 0x59 };
enum { HB_TOWN = 0x238, HB_QUESTION = 0x23C };
/* return addresses of the two calls to the AI "attacker won" function 0x602500 */
#define RET_AI_LAND_WIN 0x006033FBu                /* siege state 6: land assault won */
#define RET_AI_SEA_WIN  0x006039FEu                /* siege state 5: bombardment destroyed the defences */

/* Design choice: only a won land assault takes a town; a bombardment that
   silences the guns is vanilla damage + plunder. Set to 1 to let it conquer too. */
#define WAR_AI_BOMBARD_CONQUERS 0

static uint8_t *town_from_handle(uint32_t h, int *idx)
{
    uint8_t *t = (uint8_t *)PoolGet(POOL_TOWNS, h);
    int i = (int)(h & 0xFFFF);
    if (!t || i >= eng_town_count()) return NULL;
    if (idx) *idx = i;
    return t;
}

static int town_index_of(const uint8_t *t)
{
    return (int)(*(const uint32_t *)(t + T_LAGER + L_HANDLE) & 0xFFFF);
}

/* ---- pending player conquests (TER-01) ----------------------------------- */
typedef struct {
    uint8_t used, kind, ready_logged;   /* kind 0 = coast (land), 1 = harbour (sea) */
    uint8_t resolved;                   /* decided while its battle still existed: keep
                                           blocking vanilla's annex (#4/#6) until it ends */
    uint32_t ready_day;
    int town, former;
    uint32_t town_h;
    void *battle;
    uint32_t battle_h;
} Conquest;

#define MAX_CONQ 8
static Conquest g_conq[MAX_CONQ];

static Conquest *conquest_for_town(int town)
{
    for (int i = 0; i < MAX_CONQ; i++)
        if (g_conq[i].used && g_conq[i].town == town) return &g_conq[i];
    return NULL;
}

static void record_conquest(uint8_t *battle, int kind, uint32_t town_h, int town, int former)
{
    Conquest *c = conquest_for_town(town);
    if (!c)
        for (int i = 0; i < MAX_CONQ && !c; i++)
            if (!g_conq[i].used) c = &g_conq[i];
    if (!c) {
        log_line("WAR conquest of town %d (%s) NOT recorded: queue full", town, eng_town_name(town));
        return;
    }
    c->used = 1;
    c->kind = (uint8_t)kind;
    c->ready_logged = 0;
    c->resolved = 0;
    c->town = town;
    c->town_h = town_h;
    c->former = former;
    c->battle = battle;
    c->battle_h = *(uint32_t *)(battle + B_HANDLE);
    log_line("WAR conquest recorded: town %d (%s) from power %d (%s), %s battle %p handle %08X",
             town, eng_town_name(town), former, core_power_name(former),
             kind ? "harbour" : "coast", (void *)battle, c->battle_h);
}

/* Is a player victory over town t a nation conquest? Logs the decision. */
static int conquest_applies(const uint8_t *t, int idx, int *former, const char *where)
{
    const NationState *s = adapter_state();
    int o = t[T_NATION];
    if (!s->founded) {
        log_line("WAR %s victory at town %d (%s): no nation founded -> vanilla outcome", where, idx, eng_town_name(idx));
        return 0;
    }
    if (o >= N_POWERS) {
        log_line("WAR %s victory at town %d (%s): owner byte %d is not a power -> vanilla outcome",
                 where, idx, eng_town_name(idx), o);
        return 0;
    }
    if (s->rel[o].status != TREATY_WAR) {
        log_line("WAR %s victory at town %d (%s): nation not at war with %s -> vanilla outcome",
                 where, idx, eng_town_name(idx), core_power_name(o));
        return 0;
    }
    if (*(const uint32_t *)(t + T_FLAGS2) & TF2_VICEROY) {
        log_line("WAR %s victory at town %d (%s): viceroy seat cannot be annexed -> vanilla outcome",
                 where, idx, eng_town_name(idx));
        return 0;
    }
    if (idx >= MAX_TOWNS || s->town[idx].member) {
        log_line("WAR %s victory at town %d (%s): already a member / out of range -> vanilla outcome",
                 where, idx, eng_town_name(idx));
        return 0;
    }
    *former = o;
    return 1;
}

static int battle_alive(const Conquest *c)
{
    return c->battle && PoolGet(POOL_BATTLES, c->battle_h) == c->battle;
}

/* First conquest whose battle has ended and that is still valid; drops stale ones. */
static Conquest *ready_conquest(void)
{
    const NationState *s = adapter_state();
    for (int i = 0; i < MAX_CONQ; i++) {
        Conquest *c = &g_conq[i];
        if (!c->used) continue;
        if (c->resolved) {                         /* free it once its battle is gone */
            if (!battle_alive(c)) memset(c, 0, sizeof *c);
            continue;
        }
        if (battle_alive(c)) continue;
        uint8_t *t = town_from_handle(c->town_h, NULL);
        int cur = t ? t[T_NATION] : -1;
        if (!s->founded || cur != c->former || s->town[c->town].member) {
            log_line("WAR conquest of town %d dropped: founded=%d owner now %d (was %d) member=%d",
                     c->town, s->founded, cur, c->former, s->town[c->town].member);
            memset(c, 0, sizeof *c);
            continue;
        }
        if (c->ready_logged && adapter_day() - c->ready_day > 30) {
            log_line("WAR conquest of town %d (%s) expired: no decision within 30 days -> withdraw",
                     c->town, eng_town_name(c->town));
            memset(c, 0, sizeof *c);
            continue;
        }
        if (!c->ready_logged) {
            c->ready_logged = 1;
            c->ready_day = adapter_day();
            log_line("WAR conquest of town %d (%s) ready: battle ended, awaiting Annex/Withdraw",
                     c->town, eng_town_name(c->town));
            ui_conquest_popup(c->town);
        }
        return c;
    }
    return NULL;
}

int war_pending_conquest(int *town, int *former)
{
    Conquest *c = ready_conquest();
    if (!c) return 0;
    if (town) *town = c->town;
    if (former) *former = c->former;
    return 1;
}

static World g_w;          /* large: keep off the stack */
static Effects g_fx;

int war_resolve_conquest(int annex, int town_sel)
{
    Conquest *c = NULL;
    if (town_sel >= 0) {
        for (int i = 0; i < MAX_CONQ && !c; i++)
            if (g_conq[i].used && !g_conq[i].resolved && g_conq[i].town == town_sel) c = &g_conq[i];
    } else {
        c = ready_conquest();
    }
    if (!c) {
        log_line("WAR resolve(%d, town %d): no conquest pending", annex, town_sel);
        return 0;
    }
    int town = c->town, former = c->former;
    if (battle_alive(c)) c->resolved = 1;          /* keep #4/#6 blocking vanilla's annex */
    else memset(c, 0, sizeof *c);
    if (!annex) {
        log_line("WAR conquest of town %d (%s): WITHDRAW, stays with %s", town, eng_town_name(town),
                 core_power_name(former));
        return 1;
    }
    adapter_snapshot(&g_w);
    memset(&g_fx, 0, sizeof g_fx);
    int ok = core_annex(adapter_state(), &g_w, town, 0, &g_fx);
    if (ok) adapter_apply(&g_fx);
    log_line("WAR conquest of town %d (%s) from %s: ANNEX -> %s", town, eng_town_name(town),
             core_power_name(former), ok ? "ok" : "refused by core");
    return ok;
}

/* ---- AI conquest of nation-5 towns (TER-03, MIL-01) ---------------------- */
typedef struct { int town, power; } AiConquest;
#define MAX_AI 8
static AiConquest g_ai[MAX_AI];
static volatile int g_ai_n;

static volatile int g_refused_town = -1;    /* for the deferred player message */

/* ---- hook handlers -------------------------------------------------------- */

/* #1 0x60309F in NewCoastBattle 0x603030, player convoys only (0x603093
   cmp [esi+0xB4],1 / jne create). eax = CStadt*, ecx = CStadt+0x40. Vanilla
   refuses bit-22 towns; make nation-5 towns look the same. */
static void h_refuse_new_battle(Regs *r)
{
    uint8_t *t = (uint8_t *)(uintptr_t)r->eax;
    if (!t || t[T_NATION] != NATION_ID) return;
    r->ecx |= TF_PLAYERTOWN;
    int idx = town_index_of(t);
    log_line("WAR refuse: player attack on own-nation town %d (%s) blocked (NewCoastBattle)", idx, eng_town_name(idx));
    g_refused_town = idx;
}

/* #2 0x5B4B2D in the convoy-arrival function: esi = convoy, ebx = CStadt*,
   edx = CStadt+0x40. Vanilla skips the attack for bit-22 towns (all convoy
   types); refuse nation-5 towns for player convoys only so AI military can
   still attack them. */
static void h_refuse_arrival(Regs *r)
{
    uint8_t *t = (uint8_t *)(uintptr_t)r->ebx, *k = (uint8_t *)(uintptr_t)r->esi;
    if (!t || !k || t[T_NATION] != NATION_ID || *(uint32_t *)(k + K_TYPE) != KT_PLAYER) return;
    r->edx |= TF_PLAYERTOWN;
    int idx = town_index_of(t);
    log_line("WAR refuse: player convoy arrival attack on own-nation town %d (%s) blocked", idx, eng_town_name(idx));
    g_refused_town = idx;
}

/* #3 0x6011BE in CCoastBattle state 8 (player won the land battle), after the
   vanilla argmin of annexation orders wrote +0x59 and maybe +0x58|=4.
   esi = battle. For a nation conquest: record it and cancel the vanilla power
   annexation, so vanilla goes straight to its raid (state 9) and never calls
   0x5BC310. */
static void h_coast_offer(Regs *r)
{
    uint8_t *b = (uint8_t *)(uintptr_t)r->esi;
    if (!b || *(uint32_t *)b != VT_COAST) return;
    int idx, former;
    uint8_t *t = town_from_handle(*(uint32_t *)(b + CB_TOWN), &idx);
    if (!t || !conquest_applies(t, idx, &former, "coast")) return;
    uint8_t o58 = b[CB_OUTCOME], o59 = b[CB_ANNEXER];
    b[CB_ANNEXER] = 0xFF;
    b[CB_OUTCOME] = (uint8_t)(o58 & ~4u);
    record_conquest(b, 0, *(uint32_t *)(b + CB_TOWN), idx, former);
    log_line("WAR coast: vanilla annexer %d cancelled (+58h %02X->%02X); vanilla continues (raid / no transfer)",
             o59 == 0xFF ? -1 : o59, o58, b[CB_OUTCOME]);
}

/* #4 0x601481 in CCoastBattle state 10 (annex chosen in a vanilla question).
   esi = battle. If the town has a pending nation conquest, force +0x59=0xFF:
   the displaced cmp then takes vanilla's own exit 0x60155D (state 14, no
   transfer). Belt and braces for #3. */
static void h_coast_execute(Regs *r)
{
    uint8_t *b = (uint8_t *)(uintptr_t)r->esi;
    if (!b || *(uint32_t *)b != VT_COAST) return;
    int idx;
    if (!town_from_handle(*(uint32_t *)(b + CB_TOWN), &idx) || !conquest_for_town(idx)) return;
    log_line("WAR coast execute: town %d has a pending nation conquest, vanilla annexer %d -> withdraw path",
             idx, b[CB_ANNEXER]);
    b[CB_ANNEXER] = 0xFF;
}

/* #5 0x605A50 = CHarbourBattle state 7 (player won at sea), entry; ecx = battle.
   Runs every tick while its question is open; evaluate only when vanilla is
   about to decide (+0x23C == -1). Vanilla may still ask its raid/annex
   question if a power holds an annexation order; #6 neutralises that annex. */
static void h_harbour_gate(Regs *r)
{
    uint8_t *b = (uint8_t *)(uintptr_t)r->ecx;
    if (!b || *(uint32_t *)b != VT_HARBOUR || *(int32_t *)(b + HB_QUESTION) != -1) return;
    int idx, former;
    uint8_t *t = town_from_handle(*(uint32_t *)(b + HB_TOWN), &idx);
    if (!t) return;
    Conquest *c = conquest_for_town(idx);
    if (c && c->battle == b) return;                 /* already recorded for this battle */
    if (!conquest_applies(t, idx, &former, "harbour")) return;
    record_conquest(b, 1, *(uint32_t *)(b + HB_TOWN), idx, former);
}

/* #6 0x605D9C in CHarbourBattle state 9 (annex chosen): [esp+0x17] = vanilla
   annexer (argmin). esi = battle. Force 0xFF -> jae 0x605DE2 skips 0x5BC310. */
static void h_harbour_execute(Regs *r)
{
    uint8_t *b = (uint8_t *)(uintptr_t)r->esi;
    if (!b || *(uint32_t *)b != VT_HARBOUR) return;
    int idx;
    if (!town_from_handle(*(uint32_t *)(b + HB_TOWN), &idx) || !conquest_for_town(idx)) return;
    uint8_t *annexer = (uint8_t *)(uintptr_t)(r->esp + 0x17);
    log_line("WAR harbour execute: town %d has a pending nation conquest, vanilla annexer %d -> skipped", idx, *annexer);
    *annexer = 0xFF;
}

/* #7 0x602500 = cdecl AttackerWon(townHandle, convoyHandle): plunder after an
   AI (non-player) town attack was won. Called only from the siege object's
   land-assault (0x6033F6) and bombardment (0x6039F9) resolutions. Queue the
   transfer; war_frame() applies it after the siege has finished its tick. */
typedef char (__attribute__((thiscall)) *BattleAt_t)(void *battles, uint32_t town_handle);
#define BattleAtTown ((BattleAt_t)0x005FD050)        /* ret 4; ecx = battle store 0x7036C0 */

/* the nation's own fleets that won a land assault on a power's town (annexed in war_frame) */
static int g_navy_conq[8], g_navy_conq_n;

static void h_ai_attack_won(Regs *r)
{
    uint32_t ret = stack_arg(r, 0);
    int idx;
    uint8_t *t = town_from_handle(stack_arg(r, 1), &idx);
    uint8_t *k = (uint8_t *)PoolGet(POOL_CONVOYS, stack_arg(r, 2));
    if (!t || !k) return;
    if (k[K_NATION] == NATION_ID && t[T_NATION] < N_POWERS) {       /* our navy won */
        uint32_t kt = *(uint32_t *)(k + K_TYPE);
        int owner = t[T_NATION], land = ret == RET_AI_LAND_WIN;
        log_line("WAR navy %s won at %s (town %d, %s)", land ? "land assault" : "bombardment", eng_town_name(idx),
                 idx, core_power_name(owner));
        if ((kt == KT_MILITARY || kt == 9) && land && G_U8(GA_PLAYER_REL + owner) && g_navy_conq_n < 8 &&
            idx >= 0 && idx < MAX_TOWNS)
            g_navy_conq[g_navy_conq_n++] = idx;
        return;
    }
    if (t[T_NATION] != NATION_ID) return;
    uint32_t type = *(uint32_t *)(k + K_TYPE);
    int p = k[K_NATION];
    int land = ret == RET_AI_LAND_WIN;
    const NationState *s = adapter_state();
    log_line("WAR AI %s won at nation town %d (%s): convoy type %u nation %d",
             land ? "land assault" : ret == RET_AI_SEA_WIN ? "bombardment" : "attack", idx, eng_town_name(idx),
             (unsigned)type, p);
    /* sieges come from war-mission fleets (type 9, research/power_siege_nation.md); type 4 kept for safety */
    if ((type != KT_MILITARY && type != 9) || p >= N_POWERS) { log_line("WAR   -> not a power's military convoy: no transfer"); return; }
    if (!land && !WAR_AI_BOMBARD_CONQUERS) { log_line("WAR   -> bombardment only: no transfer"); return; }
    if (!s->founded || idx >= MAX_TOWNS || !s->town[idx].member) { log_line("WAR   -> not a nation member: no transfer"); return; }
    if (s->rel[p].status != TREATY_WAR) { log_line("WAR   -> nation not at war with %s: no transfer", core_power_name(p)); return; }
    for (int i = 0; i < g_ai_n; i++)
        if (g_ai[i].town == idx) { g_ai[i].power = p; return; }
    if (g_ai_n >= MAX_AI) { log_line("WAR   -> AI conquest queue full: dropped"); return; }
    g_ai[g_ai_n].town = idx;
    g_ai[g_ai_n].power = p;
    g_ai_n++;
    log_line("WAR   -> queued: town %d to %s", idx, core_power_name(p));
}

/* ---- letters about a siege won by the nation's own fleet ------------------------
   After an AI siege the game files a letter (type 0x30 land / 0x26 sea) through the
   letter manager 0x42ECB0; its create function returns NULL for a nation-5 attacker
   and THandler::CreateElement then throws (report.xml, scenario 46). The four calls in
   the siege code go through this filter: letters about the nation's own fleets are
   skipped (war_frame tells the player itself). */
typedef void (__attribute__((thiscall)) *Letter_t)(void *mgr, void *out, void *desc);
#define LetterCreate ((Letter_t)0x0042ECB0)                /* ret 8 */

static void __attribute__((thiscall)) letter_filter(void *mgr, void *out, void *desc)
{
    const uint32_t *d = desc;
    for (int i = 1; d && i <= 2; i++) {
        uint32_t h = d[i];
        uint32_t kind = (h >> 16) & 0x1F;
        if (kind == 2) {                                      /* a convoy: one of the nation's fleets? */
            uint8_t *k = (uint8_t *)PoolGet(POOL_CONVOYS, h);
            if (k && k[K_NATION] == NATION_ID) {
                log_line("WAR letter %u about the nation's fleet skipped", d[0]);
                return;
            }
        } else if (kind == 1) {                               /* a town: one of the nation's towns? */
            int idx;
            uint8_t *t = town_from_handle(h, &idx);
            if (t && t[T_NATION] == NATION_ID) {
                log_line("WAR letter %u about nation town %d skipped", d[0], idx);
                return;
            }
        }
    }
    LetterCreate(mgr, out, desc);
}

static int redirect_call(uint32_t at)
{
    uint8_t old[5], rep[5];
    old[0] = rep[0] = 0xE8;
    int32_t o = (int32_t)(0x0042ECB0 - (at + 5)), n = (int32_t)((uintptr_t)letter_filter - (at + 5));
    memcpy(old + 1, &o, 4);
    memcpy(rep + 1, &n, 4);
    return patch_bytes("war.SiegeLetter", at, old, rep, 5);
}

/* ---- frame / lifecycle ---------------------------------------------------- */
void war_frame(void)
{
    int rt = g_refused_town;
    if (rt >= 0) {
        g_refused_town = -1;
        char msg[160];
        snprintf(msg, sizeof msg, "You cannot attack %s: the town belongs to your own nation.", eng_town_name(rt));
        adapter_message(msg);
    }

    int n = g_ai_n;
    if (n) {
        AiConquest q[MAX_AI];
        memcpy(q, g_ai, sizeof q);
        g_ai_n = 0;
        for (int i = 0; i < n; i++) {
            NationState *s = adapter_state();
            adapter_snapshot(&g_w);
            if (!s->founded || !s->town[q[i].town].member || g_w.town[q[i].town].power != NATION_ID) {
                log_line("WAR AI conquest of town %d skipped (founded=%d member=%d owner=%d)", q[i].town,
                         s->founded, s->town[q[i].town].member, g_w.town[q[i].town].power);
                continue;
            }
            memset(&g_fx, 0, sizeof g_fx);
            int ok = core_lose_town(s, &g_w, q[i].town, q[i].power, &g_fx);
            if (ok) adapter_apply(&g_fx);
            log_line("WAR AI conquest: town %d (%s) -> %s: %s", q[i].town, eng_town_name(q[i].town),
                     core_power_name(q[i].power), ok ? "transferred" : "refused by core");
        }
    }

    /* annex only once the siege is over: the game finishes the battle (plunder, letters,
       releasing the fleet) with the town still under its old owner */
    int nc = g_navy_conq_n, keep[8], nk = 0;
    g_navy_conq_n = 0;
    for (int i = 0; i < nc; i++) {
        int town = g_navy_conq[i];
        if (BattleAtTown((void *)0x007036C0, eng_town_handle(town))) { keep[nk++] = town; continue; }
        adapter_snapshot(&g_w);
        memset(&g_fx, 0, sizeof g_fx);
        int ok = core_annex(adapter_state(), &g_w, town, 0, &g_fx);   /* reason 0 = conquest: needs the war */
        if (ok) adapter_apply(&g_fx);
        char msg[160];
        snprintf(msg, sizeof msg, ok ? "The navy of %s has stormed %s! The town joins the nation."
                                     : "The navy of %s stormed %s, but cannot hold it.",
                 adapter_state()->name, eng_town_name(town));
        adapter_message(msg);
        log_line("WAR navy conquest of town %d (%s): %s", town, eng_town_name(town), ok ? "annexed" : "refused by core");
    }
    for (int i = 0; i < nk && g_navy_conq_n < 8; i++) g_navy_conq[g_navy_conq_n++] = keep[i];

    ready_conquest();    /* logs readiness once, drops stale entries */
}

void war_reset(void)
{
    memset(g_conq, 0, sizeof g_conq);
    g_ai_n = 0;
    g_navy_conq_n = 0;
    g_refused_town = -1;
    log_line("WAR reset: pending conquests cleared");
}

void war_install(void)
{
    static int done;
    if (done) return;
    done = 1;
    static const uint8_t b1[] = {0xC1, 0xE9, 0x16, 0xF6, 0xC1, 0x01};
    static const uint8_t b2[] = {0xC1, 0xEA, 0x16, 0xF6, 0xC2, 0x01};
    static const uint8_t b3[] = {0x8A, 0x46, 0x58, 0x3C, 0x04};
    static const uint8_t b4[] = {0x0F, 0xB6, 0x46, 0x59, 0x83, 0xF8, 0x04};
    static const uint8_t b5[] = {0x83, 0xEC, 0x0C, 0x53, 0x56};
    static const uint8_t b6[] = {0x0F, 0xB6, 0x7C, 0x24, 0x17, 0x83, 0xFF, 0x04};
    static const uint8_t b7[] = {0x83, 0xEC, 0x10, 0x8B, 0x54, 0x24, 0x18};
    int ok = 0;
    ok += hook_install("war.RefuseNewBattle", 0x0060309F, b1, sizeof b1, h_refuse_new_battle);
    ok += hook_install("war.RefuseArrival", 0x005B4B2D, b2, sizeof b2, h_refuse_arrival);
    ok += hook_install("war.CoastOffer", 0x006011BE, b3, sizeof b3, h_coast_offer);
    ok += hook_install("war.CoastExecute", 0x00601481, b4, sizeof b4, h_coast_execute);
    ok += hook_install("war.HarbourGate", 0x00605A50, b5, sizeof b5, h_harbour_gate);
    ok += hook_install("war.HarbourExecute", 0x00605D9C, b6, sizeof b6, h_harbour_execute);
    ok += hook_install("war.AiAttackWon", 0x00602500, b7, sizeof b7, h_ai_attack_won);
    log_line("WAR hooks installed: %d/7", ok);
    int lf = redirect_call(0x006034AD) + redirect_call(0x00603ABF) + redirect_call(0x00603BD0) + redirect_call(0x00607C14);
    log_line("WAR siege letter filter: %d/4 calls", lf);
}
