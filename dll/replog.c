/* Reputation and relation log (the Holland war fix, research/holland_war.md).
 *
 * Every change of a power's relation score (core.c, through core_set_trace) and of the player's
 * vanilla reputation with a power is written to PR2Nation.log with its cause, so a declaration of
 * war can always be traced back:
 *
 *   REL ...   core.c: a relation score changed (cause in brackets), or an AI war decision.
 *   REP ...   a vanilla reputation writer ran for the human player: AddReputation 0x5D45F0,
 *             SubReputation 0x5D4840, SetReputation 0x5D3B50 or the Lua path 0x5D2FB0. The line
 *             names the call site and the next return addresses on the stack (the callers), so
 *             the game action is known (research/holland_war.md has the table of call sites).
 *             Gains (trading, deliveries) are summed and shown with the next change instead.
 *   REP X a -> b   once per game day per power whose whole-number reputation changed, with the
 *             sum of the logged gains and losses since the last such line; the rest is vanilla's
 *             daily update 0x5D4B40 (the slow drift towards 50).
 *   BATTLE ... a sea battle with one of the nation's fleets on either side (NewSeaBattle 0x5FEF80):
 *             both convoys' type, nation and ships, the fleet's raid task and the nearest town.
 *   BATTLE refused ...  a national fleet went for a convoy of a power the nation is at peace with:
 *             the battle is not started and the fleet drops the target (the Holland war fix).
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "replog.h"
#include "adapter.h"
#include "core.h"
#include "engine.h"
#include "game.h"
#include "hook.h"
#include "log.h"

#define PLR_BASE   (*(uint8_t **)0x00701EC0)   /* CPlayer array, stride 0x94 */
#define HUMAN_H    (*(uint32_t *)0x00701ED0)
#define P_REP      0x54                        /* int32[4], 16.16 */
#define TEXT_LO    0x00401000u
#define TEXT_HI    0x0067E455u
#define CONVOY_TABLE 0x00701EE8u
#define NOW_TICKS  (*(const uint32_t *)0x00702C14)

static const char *const k_pow[4] = {"England", "France", "Holland", "Spain"};

static uint8_t *human(void)
{
    if (!PLR_BASE || !HUMAN_H) return NULL;
    return PLR_BASE + 0x94u * (HUMAN_H & 0xFFFF);
}

static int32_t rep_raw(int p)
{
    uint8_t *h = human();
    return h ? *(int32_t *)(h + P_REP + 4 * p) : 0;
}

/* return addresses on the stack above esp (the callers of the hooked function), as text */
static int is_call_ret(uint32_t v)
{
    if (v < TEXT_LO + 6 || v >= TEXT_HI) return 0;
    const uint8_t *b = (const uint8_t *)(uintptr_t)v;
    if (b[-5] == 0xE8) return 1;                                        /* call rel32 */
    if (b[-6] == 0xFF && (b[-5] & 0x38) == 0x10) return 1;              /* call [disp32] / [r+disp32] */
    if (b[-3] == 0xFF && (b[-2] & 0x38) == 0x10 && (b[-2] & 0xC0) == 0x40) return 1;   /* call [r+d8] */
    if (b[-2] == 0xFF && (b[-1] & 0x38) == 0x10) return 1;              /* call reg / [reg] */
    return 0;
}

static void backtrace(const Regs *r, char *out, int cap)
{
    const uint32_t *sp = (const uint32_t *)(uintptr_t)r->esp;
    int o = snprintf(out, cap, "%08X", sp[0] - 5);
    int n = 0;
    for (int i = 1; i < 96 && n < 5 && o < cap - 12; i++) {
        if (!is_call_ret(sp[i])) continue;
        o += snprintf(out + o, cap - o, " <- %08X", sp[i] - 5);
        n++;
    }
}

/* gains/losses since the last "REP X a -> b" line, per power */
static struct { int32_t last; int32_t add, sub, mod; int n_add, n_sub; uint32_t day; int init; } g_acc[4];

static double fx16(int32_t v) { return v / 65536.0; }

/* what the game was doing when it lowered the reputation: SubReputation's call sites (return addresses) */
static const char *sub_cause(uint32_t ret)
{
    switch (ret) {
    case 0x005D52BE: return "an attack on one of its convoys";          /* 0x5D5170 OnConvoyAttacked */
    case 0x005D4AAA: return "an attack on one of its towns";            /* 0x5D4A50, siege / harbour attack */
    case 0x005D5808: return "a trade in one of its towns";              /* 0x5D5660 */
    default: return "another action";
    }
}

/* A reputation loss with a power at peace with the nation moves that power's relations with the nation
   (core_relation_target), so the player hears of it at once, once per power and game day (the Holland war fix). */
static void announce_loss(int p, int32_t amt, const char *cause)
{
    static uint32_t told_day[4];
    const NationState *s = adapter_state();
    uint32_t day = NOW_TICKS / 256;
    if (!s->founded || s->rel[p].status == TREATY_WAR || amt < (1 << 16) || told_day[p] == day + 1) return;
    told_day[p] = day + 1;
    char msg[160];
    snprintf(msg, sizeof msg, "Your reputation with %s falls by %d after %s; %s's relations with %s follow it.",
             k_pow[p], (amt + 0x8000) >> 16, cause, k_pow[p], s->name);
    adapter_message(msg);
}

static void on_rep(Regs *r, const char *what, int nation_arg, int amount_arg, int sign)
{
    uint8_t *h = human();
    if (!h || r->ecx != (uint32_t)(uintptr_t)h) return;                  /* the human player only */
    int p = (int)(stack_arg(r, nation_arg) & 0xFF);
    if (p >= 4) return;
    int32_t amt = amount_arg ? (int32_t)stack_arg(r, amount_arg) : 0;
    if (sign > 0 && amt < 0) { sign = -1; amt = -amt; what = "AddReputation (negative)"; }   /* a loss after all */
    if (sign > 0) {                                                       /* gains: summed, shown later */
        g_acc[p].add += amt;
        g_acc[p].n_add++;
        return;
    }
    char bt[128];
    backtrace(r, bt, sizeof bt);
    if (sign < 0) {
        g_acc[p].sub += amt;
        g_acc[p].n_sub++;
        const char *cause = sub_cause(stack_arg(r, 0));
        log_line("REP %s -%.2f by %s (was %.2f; %s) at %s", k_pow[p], fx16(amt), what, fx16(rep_raw(p)), cause, bt);
        announce_loss(p, amt, cause);
    } else {
        log_line("REP %s %s(%d) (was %.2f) at %s", k_pow[p], what, (int)(int8_t)(stack_arg(r, 2) & 0xFF),
                 fx16(rep_raw(p)), bt);
        g_acc[p].mod++;
    }
}

/* AddReputation(nation, fixed amount) ret 8; SubReputation(nation, fixed amount) ret 8 */
static void on_add(Regs *r) { on_rep(r, "AddReputation", 1, 2, +1); }
static void on_sub(Regs *r) { on_rep(r, "SubReputation", 1, 2, -1); }
static void on_set(Regs *r) { on_rep(r, "SetReputation", 1, 0, 0); }
static void on_alter(Regs *r) { on_rep(r, "AlterReputation (Lua)", 1, 0, 0); }

/* the mod's own changes (adapter FX_REPUTATION) */
void replog_mod_change(int power, int delta, const char *why)
{
    if (power < 0 || power >= 4) return;
    log_line("REP %s %+d by the nation (%s), now %.2f", k_pow[power], delta, why && *why ? why : "?",
             fx16(rep_raw(power)));
    g_acc[power].mod++;
}

void replog_daily(void)
{
    if (!human()) return;
    for (int p = 0; p < 4; p++) {
        int32_t now = rep_raw(p);
        if (!g_acc[p].init) {
            memset(&g_acc[p], 0, sizeof g_acc[p]);
            g_acc[p].init = 1;
            g_acc[p].last = now;
            continue;
        }
        if ((now >> 16) == (g_acc[p].last >> 16) && !g_acc[p].n_sub && !g_acc[p].mod) continue;
        int32_t rest = now - g_acc[p].last - g_acc[p].add + g_acc[p].sub;
        log_line("REP %s %.2f -> %.2f: gains +%.2f (%d), losses -%.2f (%d), %s%d, daily update and rest %+.2f",
                 k_pow[p], fx16(g_acc[p].last), fx16(now), fx16(g_acc[p].add), g_acc[p].n_add, fx16(g_acc[p].sub),
                 g_acc[p].n_sub, "set/mod ", g_acc[p].mod, fx16(rest));
        memset(&g_acc[p], 0, sizeof g_acc[p]);
        g_acc[p].init = 1;
        g_acc[p].last = now;
    }
}

void replog_reset(void) { memset(g_acc, 0, sizeof g_acc); }

/* ---- sea battles with the nation's fleets ------------------------------------- */
static uint8_t *convoy_by_handle(uint32_t h)
{
    uint32_t *hdr = (uint32_t *)(uintptr_t)CONVOY_TABLE;
    uint32_t *slots = (uint32_t *)(uintptr_t)hdr[0];
    int n = (int)(hdr[2] & 0xFFFF);
    if (!slots) return NULL;
    int i = (int)(h & 0xFFFF);
    if (i < n && slots[i] && (*(uint32_t *)(uintptr_t)(slots[i] + 0xA8) & 0xFFFF) == (h & 0xFFFF))
        return (uint8_t *)(uintptr_t)slots[i];
    for (i = 0; i < n; i++)                                   /* the slot is not the handle's index */
        if (slots[i] && (*(uint32_t *)(uintptr_t)(slots[i] + 0xA8) & 0xFFFF) == (h & 0xFFFF))
            return (uint8_t *)(uintptr_t)slots[i];
    return NULL;
}

static const char *type_name(uint32_t t)
{
    switch (t) {
    case 1: return "player convoy";
    case 2: return "trader";
    case 3: case 7: return "pirate";
    case 4: return "warship";
    case 9: return "war fleet";
    default: return "convoy";
    }
}

static void convoy_text(const uint8_t *k, uint32_t h, char *out, int cap)
{
    if (!k) { snprintf(out, cap, "an unknown object (handle %08X)", h); return; }
    uint32_t t = *(const uint32_t *)(k + 0xB4);
    int n = k[0xB8];
    snprintf(out, cap, "%s %s %08X (%u ships)", n == 5 && (t == 4 || t == 9) ? "national" : n < 4 ? k_pow[n] :
             n == 5 ? "player" : "other", type_name(t), *(const uint32_t *)(k + 0xA8), k[0x95]);
}

static int nearest_town(const uint8_t *k)
{
    int best = -1;
    long bd = 0;
    int x = *(const int16_t *)(k + 0x0E), y = *(const int16_t *)(k + 0x12);
    for (int t = 0; t < eng_town_count(); t++) {
        uint8_t *tp = eng_town_ptr(t);
        if (!tp) continue;
        long dx = *(uint16_t *)(tp + 0x0E) - x, dy = *(uint16_t *)(tp + 0x12) - y, d = dx * dx + dy * dy;
        if (best < 0 || d < bd) { best = t; bd = d; }
    }
    return best;
}

static int ours(const uint8_t *k)
{
    uint32_t t = k ? *(const uint32_t *)(k + 0xB4) : 0;
    return k && k[0xB8] == 5 && (t == 4 || t == 9);
}

/* NewSeaBattle(A attacker, B defender, ctx) entry. Logs every battle with a national fleet on either side,
   and refuses one where a national fleet attacks a convoy of a power the nation is not at war with, or
   one of the player's own convoys (seen in the Holland war fix's save: the hunter 0x5AED30 went for one) (the Holland war fix): the battle does not start (cdecl, nothing to pop) and the fleet drops that target, so it
   sails on. A power's ship attacking a fleet is the power's decision and is only logged. */
#define K_TARGET   0x168                       /* the convoy the hunter pursues (handle) */
#define NO_TARGET  0x0002FFFFu

static uint32_t g_refused;

static int on_new_battle(Regs *r)
{
    uint8_t *a = convoy_by_handle(stack_arg(r, 1)), *b = convoy_by_handle(stack_arg(r, 2));
    if (!ours(a) && !ours(b)) return 0;
    char ta[96], tb[96], task[64] = "";
    convoy_text(a, stack_arg(r, 1), ta, sizeof ta);
    convoy_text(b, stack_arg(r, 2), tb, sizeof tb);
    uint8_t *f = ours(a) ? a : b;
    if (*(const uint32_t *)(f + 0x1B8) == 2 || *(const uint32_t *)(f + 0x1B8) == 3) {
        int tn = f[0x1C0];
        snprintf(task, sizeof task, ", fleet task %u against %s", *(const uint32_t *)(f + 0x1B8),
                 tn < 4 ? k_pow[tn] : "?");
    }
    const uint8_t *o = f == a ? b : a;                                    /* the other side */
    int on = o ? o[0xB8] : 0xFF;
    char rel[48] = "";
    int at_peace = on < 4 && !G_U8(GA_PLAYER_REL + on);
    if (on < 4)
        snprintf(rel, sizeof rel, "; the nation is %s with %s", at_peace ? "AT PEACE" : "at war", k_pow[on]);
    int t = nearest_town(f);
    char why[96];
    snprintf(why, sizeof why, "caller %08X, fleet mask %04X flags %08X state %u", stack_arg(r, 0) - 5,
             *(const uint16_t *)(f + 0x48), *(const uint32_t *)(f + 0x7C), *(const uint32_t *)(f + 0x90));
    int own = on == 5;                                                    /* the player's convoys, other fleets */
    if (f == a && (at_peace || own)) {
        *(uint32_t *)(f + K_TARGET) = NO_TARGET;
        if (g_refused++ < 200)
            log_line("BATTLE refused: %s may not attack %s near %s (day %u%s%s; %s)", ta, tb,
                     t >= 0 ? eng_town_name(t) : "?", NOW_TICKS / 256, task,
                     own ? "; it sails for the same nation" : rel, why);
        return 1;                                                         /* no battle */
    }
    log_line("BATTLE %s attacks %s near %s (day %u%s%s; %s)", ta, tb, t >= 0 ? eng_town_name(t) : "?",
             NOW_TICKS / 256, task, rel, why);
    return 0;
}

static void core_trace(const char *line) { log_line("%s", line); }

void replog_install(void)
{
    core_set_trace(core_trace);
    static const uint8_t add_b[] = {0x83, 0xEC, 0x0C, 0x53, 0x56};               /* sub esp,0xC; push ebx; push esi */
    static const uint8_t sub_b[] = {0x83, 0xEC, 0x08, 0x56, 0x8B, 0xF1};         /* sub esp,8; push esi; mov esi,ecx */
    static const uint8_t set_b[] = {0x51, 0x8A, 0x44, 0x24, 0x08};               /* push ecx; mov al,[esp+8] */
    static const uint8_t alt_b[] = {0x8B, 0x54, 0x24, 0x04, 0x80, 0xFA, 0x04};   /* mov edx,[esp+4]; cmp dl,4 */
    static const uint8_t bat_b[] = {0x83, 0xEC, 0x08, 0x8B, 0x54, 0x24, 0x0C};   /* sub esp,8; mov edx,[esp+0xC] */
    hook_install("replog.AddReputation", 0x005D45F0, add_b, sizeof add_b, on_add);
    hook_install("replog.SubReputation", 0x005D4840, sub_b, sizeof sub_b, on_sub);
    hook_install("replog.SetReputation", 0x005D3B50, set_b, sizeof set_b, on_set);
    hook_install("replog.AlterReputation", 0x005D2FB0, alt_b, sizeof alt_b, on_alter);
    hook_install_ret("replog.NewSeaBattle", 0x005FEF80, bat_b, sizeof bat_b, on_new_battle, 0);   /* cdecl */
}
