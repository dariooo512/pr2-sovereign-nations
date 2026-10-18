#include <windows.h>
/* Engine adapter: snapshot -> core -> effects. See adapter.h. */
#include <stdio.h>
#include <string.h>
#include "adapter.h"
#include "engine.h"
#include "game.h"
#include "log.h"
#include "war.h"
#include "flag.h"
#include "navy.h"
#include "panel.h"
#include "sight.h"
#include "replog.h"

static NationState g_state;
static Config g_cfg;
static int g_cfg_ready;
static int g_world_ready;

NationState *adapter_state(void) { return &g_state; }

/* Founding requirements can be overridden in PR2Nation.ini next to the exe
   (spec §3.1 "configurable balance defaults"):
     [Requirements]
     MinGold=5000000
     MinShips=10
     MinWarships=3
   Read again at every New Game / Load. */
static void load_ini(Config *c)
{
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    while (n && path[n - 1] != '\\') n--;
    lstrcpynA(path + n, "PR2Nation.ini", MAX_PATH - (int)n);
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return;
    c->found_min_gold = GetPrivateProfileIntA("Requirements", "MinGold", (int)c->found_min_gold, path);
    c->found_min_ships = GetPrivateProfileIntA("Requirements", "MinShips", c->found_min_ships, path);
    c->found_min_warships = GetPrivateProfileIntA("Requirements", "MinWarships", c->found_min_warships, path);
    log_line("PR2Nation.ini: founding needs %lld gold, %d ships, %d warships",
             (long long)c->found_min_gold, c->found_min_ships, c->found_min_warships);
}

const Config *adapter_config(void)
{
    if (!g_cfg_ready) {
        core_default_config(&g_cfg);
        load_ini(&g_cfg);
        g_cfg_ready = 1;
    }
    return &g_cfg;
}

uint32_t adapter_day(void) { return G_U32(GA_WORLD_TIME) >> 8; }

/* The war table P01/P04 read (player_rel) mirrors the core's relations. */
static void sync_war_table(void)
{
    for (int p = 0; p < N_POWERS; p++) {
        uint8_t war = g_state.founded && g_state.rel[p].status == TREATY_WAR;
        G_U8(GA_PLAYER_REL + p) = war;
    }
}

void adapter_on_reset(void)
{
    panel_reset();
    sight_reset();
    g_world_ready = 0;
    g_cfg_ready = 0;                 /* dev requirement overrides end with the game */
    ui_reset();
    war_reset();
    flag_reset();
    replog_reset();
    sync_war_table();
}

void adapter_on_loaded_state(void)
{
    sync_war_table();
    if (g_state.founded) flag_apply(g_state.flag);   /* the nation's flag file before the world draws */
}

void adapter_on_world_ready(void)
{
    g_world_ready = 1;
    sync_war_table();
    flag_world_ready(g_state.founded, g_state.flag);   /* Run\0.bmp stays the player's own flag */
    if (g_state.founded) {
        /* Re-assert nation-5 ownership for member towns (the save already holds
           the bytes; this repairs any town a power retook while we weren't
           looking -- core_daily then notices the loss). */
        log_line("world ready: nation '%s', %d towns, treasury %lld",
                 g_state.name, core_member_count(&g_state), (long long)g_state.treasury);
        /* building permits in member towns; records the pre-joining state for
           towns gained in a save from before this feature */
        World w;
        Effects fx = {0};
        adapter_snapshot(&w);
        int n = core_permit_sync(&g_state, &w, &fx);
        adapter_apply(&fx);
        log_line("world ready: building permit granted in %d member town(s)", n);
        /* where each relation stands and where it drifts (the Holland war fix: every war has a visible cause) */
        for (int p = 0; p < N_POWERS; p++) {
            const Relation *r = &g_state.rel[p];
            char why[200];
            int tgt = core_relation_target(&g_state, &w, p, why, sizeof why);
            log_line("REL %s: %s, score %d (drifts towards %d: %s), recognized %d, exhaustion %d, last treaty "
                     "change day %u (today %u), strategy %s, reputation %d", core_power_name(p),
                     core_treaty_name(r->status), r->score, tgt, why, r->recognized, r->war_exhaustion,
                     r->last_change_day, w.day, core_ai_strategy_name(core_ai_strategy(&g_state, &w, p)),
                     w.reputation[p]);
        }
    }
}

int adapter_world_ready(void) { return g_world_ready; }

void adapter_snapshot(World *w)
{
    memset(w, 0, sizeof *w);
    w->day = adapter_day();
    w->player_gold = eng_player_gold();
    eng_player_fleet(&w->player_ships, &w->player_warships);
    w->nation_fleets = (uint8_t)navy_fleet_count();
    w->player_rank = (uint8_t)eng_player_rank();
    int n = eng_town_count();
    if (n > MAX_TOWNS) n = MAX_TOWNS;
    w->n_towns = (uint8_t)n;
    int towns_of[N_POWERS] = {0};
    for (int i = 0; i < n; i++) {
        eng_town_snapshot(i, &w->town[i]);
        if (w->town[i].exists && w->town[i].power < N_POWERS)
            towns_of[w->town[i].power]++;
    }
    for (int p = 0; p < N_POWERS; p++) {
        w->reputation[p] = (uint8_t)eng_player_reputation(p);
        for (int q = 0; q < N_POWERS; q++)
            w->power_war[p][q] = (uint8_t)(p != q && eng_power_war(p, q));
        /* core expects the player's scale: towns*10 + warships*2 + ships/2 */
        w->power_strength[p] = (uint16_t)(towns_of[p] * 10 + towns_of[p] * 4);
    }
}

/* Core messages name towns by index ("town 52", "Town 52"); show the real
   name instead ("Coro"). */
static void name_towns(const char *in, char *out, int cap)
{
    int o = 0;
    while (*in && o < cap - 1) {
        if ((!strncmp(in, "town ", 5) || !strncmp(in, "Town ", 5)) && in[5] >= '0' && in[5] <= '9') {
            const char *p = in + 5;
            int idx = 0;
            while (*p >= '0' && *p <= '9') idx = idx * 10 + (*p++ - '0');
            char name[48];
            if (idx < eng_town_count() && strcmp(eng_town_name(idx), "?")) {
                ui_town_label(idx, name, sizeof name);
                o += snprintf(out + o, cap - o, "%s", name);
                if (o > cap - 1) o = cap - 1;
                in = p;
                continue;
            }
        }
        out[o++] = *in++;
    }
    out[o] = 0;
}

void adapter_apply(const Effects *fx)
{
    for (int i = 0; i < fx->n; i++) {
        const Effect *e = &fx->fx[i];
        switch (e->kind) {
        case FX_TOWN_TO_NATION:
            if (!eng_town_to_nation(e->a, g_state.host_power))
                log_line("FX town %d -> nation FAILED", e->a);
            break;
        case FX_TOWN_TO_POWER:
            if (!eng_town_to_power(e->a, e->b))
                log_line("FX town %d -> power %d FAILED", e->a, e->b);
            break;
        case FX_SET_WAR:
            if (e->a >= 0 && e->a < N_POWERS)
                G_U8(GA_PLAYER_REL + e->a) = (uint8_t)(e->b != 0);
            break;
        case FX_PLAYER_GOLD:
            if (!eng_player_add_gold(e->v))
                log_line("FX gold %lld refused", (long long)e->v);
            break;
        case FX_MESSAGE: {
            char text[sizeof e->text + 64];
            name_towns(e->text, text, sizeof text);
            ui_message(text);
            break;
        }
        case FX_TOWN_UNREST:
            log_line("FX unrest town %d %s", e->a, e->b ? "start" : "end");
            eng_town_unrest(e->a, e->b);
            break;
        case FX_REPUTATION:
            eng_player_add_reputation(e->a, (int)e->v);
            replog_mod_change(e->a, (int)e->v, e->text);
            break;
        case FX_PERMIT:
            if (!eng_town_set_permit(e->a, e->b))
                log_line("FX permit town %d -> %d FAILED", e->a, e->b);
            break;
        case FX_FLEET_SPAWN:
        case FX_FLEET_DISBAND:
        case FX_FLEET_ORDER:
        case FX_GARRISON:
        case FX_TOWER:
            navy_effect(e);
            break;
        default:
            break;
        }
    }
    sync_war_table();
}

void adapter_daily(void)
{
    if (!g_world_ready)
        return;
    replog_daily();
    if (!g_state.founded)
        return;
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    core_daily(&g_state, &w, adapter_config(), &fx);
    adapter_apply(&fx);
    navy_daily(w.day);
}

void adapter_frame(void)
{
    ui_frame();
}

void adapter_message(const char *text) { ui_message(text); }
