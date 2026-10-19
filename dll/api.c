/* Nation_* Lua API -- the scripting surface of the feature.
 *
 * Registered into the game's Missions Lua state and re-registered whenever
 * New Game / Load replaces the globals table. Town arguments are staedte.ini
 * indices (0..59); Nation_TownIndex(handle) converts a Lua town handle.
 * Powers: 0 England, 1 France, 2 Holland, 3 Spain.
 *
 *   ok, why        = Nation_CanFound(capital)
 *   ok, why        = Nation_Found(capital, name, adjective, title, flag)
 *                    -- adjective "" = the nation's name (the founding page passes ""; saves made
 *                       before that hold the capital's name there and keep it)
 *   founded, name, adjective, capital, treasury, stability, towns, tax, tariff = Nation_GetInfo()
 *   status, score, recognized, chance, threat = Nation_GetRelation(power)   (threat: AI evaluations
 *       since the power warned that it may declare war, 0 = no warning; the Holland war fix)
 *   ok             = Nation_DeclareWar(power)
 *   ok, why        = Nation_Propose(power, treaty)   -- 0 peace,1 trade,2 nonaggr,3 alliance,5 ceasefire
 *   ok             = Nation_Annex(town)                 -- e.g. after a conquest
 *   ok             = Nation_ReleaseTown(town, power)
 *   member, loyalty, tax, unrest, permit, before = Nation_GetTown(town)
 *                    -- permit: the player holds the building permit there (game flag);
 *                       before: 0 not recorded, 1 had none before joining, 2 had one
 *   n              = Nation_NationalConvoys([n])         -- national convoys are off in this version
 *                                                          (NATION_CONVOYS 0): a no-op that returns 0
 *   n              = Nation_ShipCount()                  -- national ships: the fleets
 *   handle, x, y, visible, atSea, isFleet = Nation_ShipInfo(i)
 *   ok, why        = Nation_ShipGoto(i)                  -- centre the sea map on ship i (next frame)
 *   town, former   = Nation_PendingConquest()            -- -1 if none
 *   ok             = Nation_ResolveConquest(annex [, town]) -- 1 annex, 0 withdraw
 *                    Nation_SetTax(town or -1, pct) ; Nation_SetTariff(pct)
 *   ok             = Nation_Donate(amount) ; ok = Nation_Withdraw(amount)
 *   treasury, lastTax, lastUpkeep, lastTariff, lastMonthDay, taxEstimate, today = Nation_GetFinance()
 *   ok, why        = Nation_SetGovernment(gov)         -- 0 sovereign,1 merchant rep.,2 monarchy,3 pirate rep.,4 federation
 *   gov, name, cooldownMonths = Nation_GetGovernment()
 *   gold           = Nation_GetGold()                     -- the player's personal gold
 *   n = Nation_FlagCount() ; name, group = Nation_FlagName(i) ; i = Nation_GetFlag() ; ok = Nation_SetFlag(i)
 *   strategy, name = Nation_GetStrategy(power)          -- 0 commercial,1 expansionist,2 defensive,3 opportunistic
 *   idx            = Nation_TownIndex(handle) ; handle = Nation_TownHandle(idx)
 *   name           = Nation_TownName(idx)
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "adapter.h"
#include "engine.h"
#include "lua.h"
#include "log.h"
#include "war.h"
#include "flag.h"
#include "navy.h"
#include "panel.h"
#include "officials.h"
#include "towninfo.h"
#include "gui.h"
#include "sight.h"
#include "nation.h"

uint32_t eng_town_handle(int idx);

static char g_why[256];

static void run_effects(Effects *fx)
{
    adapter_apply(fx);
}

static int __cdecl l_can_found(lua_State *L)
{
    World w;
    adapter_snapshot(&w);
    int ok = core_can_found(adapter_state(), &w, adapter_config(), plua_int(L, 1, -1), g_why, sizeof g_why);
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}

int api_found(int capital, const char *name, const char *adj, int title, int flag, char *why, int why_len)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_found(adapter_state(), &w, adapter_config(), capital, name, adj, title, flag,
                        &fx, why, why_len);
    if (ok) {
        run_effects(&fx);
        flag_apply(flag);                          /* the nation's flag (Run\7.bmp); the player logo stays */
    }
    log_line("Nation_Found(%d, %s) -> %d %s", capital, name, ok, ok ? "" : why);
    return ok;
}

static int __cdecl l_found(lua_State *L)
{
    int ok = api_found(plua_int(L, 1, -1), plua_str(L, 2, ""), plua_str(L, 3, ""),
                       plua_int(L, 4, 0), plua_int(L, 5, 0), g_why, sizeof g_why);
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}

static int clamp32(int64_t v) { return v > 2000000000 ? 2000000000 : v < -2000000000 ? -2000000000 : (int)v; }

static int __cdecl l_info(lua_State *L)
{
    NationState *s = adapter_state();
    plua_push_int(L, s->founded);
    plua_push_str(L, s->name);
    plua_push_str(L, s->adjective);
    plua_push_int(L, s->capital);
    plua_push_int(L, clamp32(s->treasury));
    plua_push_int(L, s->stability);
    plua_push_int(L, core_member_count(s));
    plua_push_int(L, s->default_tax_pct);
    plua_push_int(L, s->tariff_pct);
    return 9;
}

static int __cdecl l_relation(lua_State *L)
{
    int p = plua_int(L, 1, -1);
    if (p < 0 || p >= N_POWERS) { plua_push_nil(L); return 1; }
    NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    plua_push_int(L, s->rel[p].status);
    plua_push_int(L, s->rel[p].score);
    plua_push_int(L, s->rel[p].recognized);
    /* chance for the next step: at war a ceasefire (peace needs one first), else peace */
    plua_push_int(L, core_acceptance_chance(s, &w, p, s->rel[p].status == TREATY_WAR ? TREATY_CEASEFIRE
                                                                                    : TREATY_PEACE));
    plua_push_int(L, s->rel[p].threat ? s->rel[p].threat - THREAT_BASE : 0);   /* war warning: evaluations ago */
    return 5;
}

static int __cdecl l_declare_war(lua_State *L)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_declare_war(adapter_state(), &w, plua_int(L, 1, -1), &fx);
    if (ok) run_effects(&fx);
    plua_push_int(L, ok);
    return 1;
}

static int __cdecl l_propose(lua_State *L)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_propose(adapter_state(), &w, plua_int(L, 1, -1), (Treaty)plua_int(L, 2, 0),
                          &fx, g_why, sizeof g_why);
    run_effects(&fx);
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}

static int __cdecl l_annex(lua_State *L)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_annex(adapter_state(), &w, plua_int(L, 1, -1), plua_int(L, 2, 0), &fx);
    if (ok) run_effects(&fx);
    plua_push_int(L, ok);
    return 1;
}

static int __cdecl l_release(lua_State *L)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_lose_town(adapter_state(), &w, plua_int(L, 1, -1), plua_int(L, 2, -1), &fx);
    if (ok) run_effects(&fx);
    plua_push_int(L, ok);
    return 1;
}

static int __cdecl l_town(lua_State *L)
{
    int t = plua_int(L, 1, -1);
    if (t < 0 || t >= MAX_TOWNS) { plua_push_nil(L); return 1; }
    TownState *ts = &adapter_state()->town[t];
    plua_push_int(L, ts->member);
    plua_push_int(L, ts->loyalty);
    plua_push_int(L, ts->tax_pct == 0xFF ? adapter_state()->default_tax_pct : ts->tax_pct);
    plua_push_int(L, ts->unrest >= 2);
    plua_push_int(L, eng_town_permit(t));
    plua_push_int(L, ts->permit_before == PERMIT_HAD ? 2 : ts->permit_before == PERMIT_HAD_NONE ? 1 : 0);
    return 6;
}

static int __cdecl l_set_tax(lua_State *L) { core_set_tax(adapter_state(), plua_int(L, 1, -1), plua_int(L, 2, 10)); return 0; }

static int __cdecl l_set_tariff(lua_State *L)
{
    int p = plua_int(L, 1, 0);
    adapter_state()->tariff_pct = (uint8_t)(p == 5 || p == 10 || p == 20 ? p : 0);
    return 0;
}

/* Donate/withdraw move gold between the purse and the treasury. The core
   books the treasury first; if the purse side is then refused (no player,
   int32 purse limit) the booking is rolled back, so no money is created. */
static int transfer(int withdraw, int amount)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    NationState *s = adapter_state();
    int64_t treasury0 = s->treasury, gold0 = eng_player_gold();
    uint8_t stab0 = s->stability;
    int ok = withdraw ? core_withdraw(s, &w, amount, &fx) : core_donate(s, &w, amount, &fx);
    if (!ok) return 0;
    run_effects(&fx);
    if (eng_player_gold() - gold0 != (withdraw ? amount : -(int64_t)amount)) {
        log_line("Nation_%s(%d): purse refused the transfer -> treasury rolled back",
                 withdraw ? "Withdraw" : "Donate", amount);
        s->treasury = treasury0;
        s->stability = stab0;
        return 0;
    }
    return 1;
}

/* The nation panel's actions (panel.c): the same core calls as the Lua API, with a reason.
   Returns 1 if the action was carried out. */
int api_action(int action, int arg, char *why, int why_len)
{
    World w;
    Effects fx = {0};
    NationState *s = adapter_state();
    int ok = 0;
    adapter_snapshot(&w);
    why[0] = 0;
    switch (action) {
    case API_DONATE:
        ok = transfer(0, arg);
        if (!ok) snprintf(why, why_len, "You do not have %d gold of your own.", arg);
        break;
    case API_WITHDRAW:
        ok = transfer(1, arg);
        if (!ok) snprintf(why, why_len, "%s", s->stability < 25 ? "Stability is too low (below 25) to take public money."
                                                                : "You may take at most half the treasury.");
        break;
    case API_TAX:
        if (arg < 0 || arg > 50) { snprintf(why, why_len, "Tax must stay between 0%% and 50%%."); break; }
        core_set_tax(s, -1, arg);
        ok = 1;
        break;
    case API_TARIFF:
        s->tariff_pct = (uint8_t)(arg == 5 || arg == 10 || arg == 20 ? arg : 0);
        ok = 1;
        break;
    case API_WAR:
        ok = core_declare_war(s, &w, arg, &fx);
        if (ok) run_effects(&fx);
        else snprintf(why, why_len, "War cannot be declared on %s now.", core_power_name(arg));
        break;
    case API_CEASEFIRE:
    case API_PEACE:
        ok = core_propose(s, &w, arg, action == API_CEASEFIRE ? TREATY_CEASEFIRE : TREATY_PEACE, &fx, why, why_len);
        run_effects(&fx);
        break;
    case API_GOVERNMENT:
        ok = core_set_government(s, &w, arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_COMMISSION:
        ok = navy_ready() && core_navy_commission(s, &w, adapter_config(), &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_PAYOFF:
        ok = navy_ready() && core_navy_decommission(s, &w, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_ORDER:
        ok = navy_ready() && core_navy_set_order(s, &w, arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_RECRUIT:
        ok = navy_ready() && core_navy_reinforce(s, &w, adapter_config(), arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_TOWER:
        ok = navy_ready() && core_navy_build_tower(s, &w, adapter_config(), arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_TOWN_TAX: {                       /* arg = town * 1000 + pct; the national rate means "follow it" */
        int t = arg / 1000, pct = arg % 1000;
        if (t < 0 || t >= MAX_TOWNS || !s->town[t].member || pct < 0 || pct > 50) {
            snprintf(why, why_len, "Not a town of the nation, or a tax outside 0..50%%.");
            break;
        }
        core_set_tax(s, t, pct == s->default_tax_pct ? 0xFF : pct);
        ok = 1;
        break;
    }
    case API_OFFER_ACCEPT:                      /* arg = power: take the AI's open offer */
    case API_OFFER_DECLINE: {
        if (arg < 0 || arg >= N_POWERS || !s->rel[arg].expiry_day || w.day > s->rel[arg].expiry_day) {
            snprintf(why, why_len, "There is no open offer from %s.", core_power_name(arg >= 0 && arg < N_POWERS ? arg : 0));
            break;
        }
        Relation *r = &s->rel[arg];
        if (action == API_OFFER_DECLINE) {
            r->expiry_day = 0;
            r->score = (int16_t)(r->score > -98 ? r->score - 2 : -100);
            ok = 1;
            break;
        }
        ok = core_propose(s, &w, arg, r->status == TREATY_WAR ? TREATY_CEASEFIRE : TREATY_TRADE, &fx, why, why_len);
        run_effects(&fx);
        break;
    }
    case API_FLEET_ORDER:                       /* arg = fleet handle */
        ok = navy_ready() && navy_fleet_next_order((uint32_t)arg, why, why_len);
        break;
    case API_FLEET_TARGET:
        ok = navy_ready() && navy_fleet_next_target((uint32_t)arg, why, why_len);
        break;
    case API_BUY_TOWN:
        ok = core_buy_town(s, &w, arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_PETITION:                          /* arg 1 = accept, 0 = decline */
        ok = core_answer_petition(s, &w, arg, &fx, why, why_len);
        if (ok) run_effects(&fx);
        break;
    case API_PROPOSE: {                        /* arg = power * 10 + treaty */
        int p = arg / 10, t = arg % 10;
        ok = core_propose(s, &w, p, (Treaty)t, &fx, why, why_len);
        run_effects(&fx);
        break;
    }
    case API_CONVOYS:                           /* arg = the wanted number of national convoys
                                                   (with NATION_CONVOYS 0 nothing can be designated) */
        if (arg > natc_count()) ok = natc_designate(why, why_len);
        else if (arg < natc_count()) ok = natc_release(0);
        else ok = 1;
        break;
    case API_CONVOY_RELEASE:                    /* arg = convoy handle */
        ok = natc_release((uint32_t)arg);
        if (!ok) snprintf(why, why_len, "That convoy is no longer a national convoy.");
        break;
    case API_GOTO:                              /* arg = ship handle */
        ok = sight_goto((uint32_t)arg, why, why_len);
        break;
    default:
        snprintf(why, why_len, "Unknown action.");
    }
    if (!ok && !why[0] && navy_ready() == 0 && action >= API_COMMISSION && action <= API_TOWER)
        snprintf(why, why_len, "The navy is unavailable in this game build.");
    log_line("PANEL action %d(%d) -> %d %s", action, arg, ok, ok ? "" : why);
    return ok;
}

static int __cdecl l_donate(lua_State *L) { plua_push_int(L, transfer(0, plua_int(L, 1, 0))); return 1; }
static int __cdecl l_withdraw(lua_State *L) { plua_push_int(L, transfer(1, plua_int(L, 1, 0))); return 1; }

static int __cdecl l_finance(lua_State *L)
{
    NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    plua_push_int(L, clamp32(s->treasury));
    plua_push_int(L, s->last_tax_income);
    plua_push_int(L, s->last_upkeep);
    plua_push_int(L, s->last_tariff_income);
    plua_push_int(L, (int)s->last_month_day);
    plua_push_int(L, clamp32(core_monthly_tax_estimate(s, &w)));
    plua_push_int(L, (int)adapter_day());
    plua_push_int(L, s->navy.last_military);
    return 8;
}

/* conquest flow: after the player wins a town, the UI asks Annex/Withdraw */
static int __cdecl l_pending_conquest(lua_State *L)
{
    int town = -1, former = -1;
    if (!war_pending_conquest(&town, &former)) { plua_push_int(L, -1); return 1; }
    plua_push_int(L, town);
    plua_push_int(L, former);
    return 2;
}

static int __cdecl l_resolve_conquest(lua_State *L)
{
    plua_push_int(L, war_resolve_conquest(plua_int(L, 1, 0), plua_int(L, 2, -1)));
    return 1;
}

/* §7.1 MVP: a number of the player's convoys is designated national; they are
   paid from the national treasury (core upkeep) and count for strength. */
/* Nation_NavyInfo() -> ready, fleets, cap, rank, rank name, order, order name, target,
   last month's military upkeep, plunder total, fleet cost, fleet upkeep */
static int __cdecl l_navy_info(lua_State *L)
{
    World w;
    NationState *s = adapter_state();
    const Config *c = adapter_config();
    adapter_snapshot(&w);
    int rank = core_naval_rank(s, &w);
    plua_push_int(L, navy_ready());
    plua_push_int(L, navy_fleet_count());
    plua_push_int(L, core_fleet_cap(s, &w));
    plua_push_int(L, rank);
    plua_push_str(L, core_naval_rank_name(rank));
    plua_push_int(L, s->navy.order);
    plua_push_str(L, core_navy_order_name(s->navy.order));
    plua_push_int(L, s->navy.fleet_target);
    plua_push_int(L, s->navy.last_military);
    plua_push_int(L, (int)(s->navy.plunder_total > 2000000000 ? 2000000000 : s->navy.plunder_total));
    plua_push_int(L, c->fleet_cost);
    plua_push_int(L, c->fleet_upkeep);
    return 12;
}

/* Nation_NavyCommission() / Nation_NavyDecommission() / Nation_NavySetOrder(order)
   / Nation_NavyReinforce(town) / Nation_NavyBuildTower(town) -> ok, why */
static int navy_call(lua_State *L, int what)
{
    World w;
    Effects fx = {0};
    NationState *s = adapter_state();
    const Config *c = adapter_config();
    adapter_snapshot(&w);
    int ok = 0, arg = plua_int(L, 1, -1);
    if (!navy_ready()) {
        snprintf(g_why, sizeof g_why, "%s", "The navy is unavailable in this game build (see PR2Nation.log).");
    } else switch (what) {
    case 0: ok = core_navy_commission(s, &w, c, &fx, g_why, sizeof g_why); break;
    case 1: ok = core_navy_decommission(s, &w, &fx, g_why, sizeof g_why); break;
    case 2: ok = core_navy_set_order(s, &w, arg, &fx, g_why, sizeof g_why); break;
    case 3: ok = core_navy_reinforce(s, &w, c, arg, &fx, g_why, sizeof g_why); break;
    case 4: ok = core_navy_build_tower(s, &w, c, arg, &fx, g_why, sizeof g_why); break;
    }
    if (ok) run_effects(&fx);
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}
static int __cdecl l_navy_commission(lua_State *L) { return navy_call(L, 0); }
static int __cdecl l_navy_decommission(lua_State *L) { return navy_call(L, 1); }
static int __cdecl l_navy_set_order(lua_State *L) { return navy_call(L, 2); }
static int __cdecl l_navy_reinforce(lua_State *L) { return navy_call(L, 3); }
static int __cdecl l_navy_build_tower(lua_State *L) { return navy_call(L, 4); }

/* Nation_TownDefence(town) -> soldiers, cannon towers, soldier budget, towers bought */
static int __cdecl l_town_defence(lua_State *L)
{
    int t = plua_int(L, 1, -1), so, to, bu;
    navy_town_defence(t, &so, &to, &bu);
    plua_push_int(L, so);
    plua_push_int(L, to);
    plua_push_int(L, bu);
    plua_push_int(L, t >= 0 && t < MAX_TOWNS ? adapter_state()->navy.towers_bought[t] : 0);
    return 4;
}

static int __cdecl l_national_convoys(lua_State *L)
{
#if !NATION_CONVOYS
    plua_push_int(L, 0);                       /* off in this version: a no-op */
    return 1;
#endif
    int n = plua_int(L, 1, -1);
    if (n >= 0 && adapter_state()->founded) natc_set_count(n);
    plua_push_int(L, natc_count());
    return 1;
}

static int __cdecl l_ship_count(lua_State *L) { plua_push_int(L, sight_ship_count()); return 1; }

static int __cdecl l_ship_info(lua_State *L)
{
    uint32_t h;
    int x, y, vis, sea, fleet;
    if (!sight_ship_info(plua_int(L, 1, -1), &h, &x, &y, &vis, &sea, &fleet)) { plua_push_nil(L); return 1; }
    plua_push_int(L, (int)h);
    plua_push_int(L, x);
    plua_push_int(L, y);
    plua_push_int(L, vis);
    plua_push_int(L, sea);
    plua_push_int(L, fleet);
    return 6;
}

static int __cdecl l_ship_goto(lua_State *L)
{
    uint32_t h;
    int x, y, vis, sea, fleet, ok = 0;
    if (sight_ship_info(plua_int(L, 1, -1), &h, &x, &y, &vis, &sea, &fleet)) ok = sight_goto(h, g_why, sizeof g_why);
    else snprintf(g_why, sizeof g_why, "No such ship.");
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}

/* Nation_DevSight(reveal) -> reveal on, view, centre x, centre y, last go-to handle, its x, y (tests) */
static int __cdecl l_dev_sight(lua_State *L)
{
    int on = sight_reveal_enabled(plua_int(L, 1, -1)), cx, cy, gx, gy, gv;
    uint32_t gh;
    int view = sight_view(&cx, &cy);
    sight_last_goto(&gh, &gx, &gy, &gv);
    plua_push_int(L, on);
    plua_push_int(L, view);
    plua_push_int(L, cx);
    plua_push_int(L, cy);
    plua_push_int(L, (int)gh);
    plua_push_int(L, gx);
    plua_push_int(L, gy);
    return 7;
}

/* Nation_DevCycle() -> ok: what Ctrl+Shift+N does (the next national ship) */
static int __cdecl l_dev_cycle(lua_State *L) { plua_push_int(L, sight_cycle()); return 1; }
/* Nation_DevFlags() -> nation flag ready, then how often each site drew the nation's flag for a national
   ship or gave a player convoy its own flag back (flag.c order: name, selection, info bar, trade,
   sea marker, sails, battle-player, town info, town marker, sail texture remade, marker reload,
   every nation-5 marker logo load, loads by a marker that had loaded before) */
static int __cdecl l_dev_flags(lua_State *L)
{
    unsigned long h[16];
    plua_push_int(L, flag_dev(h, 16));
    for (int i = 0; i < 13; i++) plua_push_int(L, (int)h[i]);
    return 14;
}
/* Nation_DevView(view, town handle) -> ok: 1 = sea map, 2 = enter that town (next frame; tests) */
static int __cdecl l_dev_view(lua_State *L) { plua_push_int(L, flag_dev_view(plua_int(L, 1, 0), (uint32_t)plua_int(L, 2, -1))); return 1; }
/* Nation_DevFrames() -> frames since the DLL loaded (frame-rate checks) */
static int __cdecl l_dev_frames(lua_State *L) { plua_push_int(L, (int)pr2n_frames()); return 1; }

/* Nation_DevVisibleNear(x, y, r) -> convoys marked visible, convoys at sea there (tests) */
static int __cdecl l_dev_visible_near(lua_State *L)
{
    int total, own, vis = sight_visible_near(plua_int(L, 1, 0), plua_int(L, 2, 0), plua_int(L, 3, 100), &total, &own);
    plua_push_int(L, vis);
    plua_push_int(L, total);
    plua_push_int(L, own);
    return 3;
}

/* §5.5 government (M6) and §10 AI strategy profiles */
static int __cdecl l_set_government(lua_State *L)
{
    World w;
    Effects fx = {0};
    adapter_snapshot(&w);
    int ok = core_set_government(adapter_state(), &w, plua_int(L, 1, -1), &fx, g_why, sizeof g_why);
    if (ok) run_effects(&fx);
    plua_push_int(L, ok);
    plua_push_str(L, ok ? "" : g_why);
    return 2;
}

static int __cdecl l_get_government(lua_State *L)
{
    NationState *s = adapter_state();
    plua_push_int(L, core_government(s));
    plua_push_str(L, core_government_name(core_government(s)));
    plua_push_int(L, core_government_cooldown(s));
    return 3;
}

static int __cdecl l_get_strategy(lua_State *L)
{
    World w;
    adapter_snapshot(&w);
    int st = core_ai_strategy(adapter_state(), &w, plua_int(L, 1, -1));
    plua_push_int(L, st);
    plua_push_str(L, st < 0 ? "" : core_ai_strategy_name(st));
    return 2;
}

/* Flags (art/flags_src, restyled into the game's look): number -> name, group */
static const struct { const char *name, *group; } k_flags[] = {
#include "flag_names.inc"
};
#define N_FLAGS ((int)(sizeof k_flags / sizeof *k_flags))

int api_flag_count(void) { return N_FLAGS; }

const char *api_flag_name(int i, const char **group)
{
    if (i < 0 || i >= N_FLAGS) { if (group) *group = ""; return ""; }
    if (group) *group = k_flags[i].group;
    return k_flags[i].name;
}

int api_can_found(int capital, char *why, int why_len)
{
    World w;
    adapter_snapshot(&w);
    return core_can_found(adapter_state(), &w, adapter_config(), capital, why, why_len);
}

static int __cdecl l_flag_count(lua_State *L) { plua_push_int(L, N_FLAGS); return 1; }

static int __cdecl l_flag_name(lua_State *L)
{
    int i = plua_int(L, 1, -1);
    if (i < 0 || i >= N_FLAGS) { plua_push_nil(L); return 1; }
    plua_push_str(L, k_flags[i].name);
    plua_push_str(L, k_flags[i].group);
    return 2;
}

static int __cdecl l_get_flag(lua_State *L) { plua_push_int(L, adapter_state()->flag); return 1; }

static int __cdecl l_set_flag(lua_State *L)
{
    int i = plua_int(L, 1, -1);
    int ok = adapter_state()->founded && i >= 0 && i < N_FLAGS;
    if (ok) {
        adapter_state()->flag = (uint8_t)i;
        log_line("flag -> %d (%s)", i, k_flags[i].name);
        flag_apply(i);
    }
    plua_push_int(L, ok);
    return 1;
}

static int __cdecl l_get_gold(lua_State *L) { plua_push_int(L, clamp32(eng_player_gold())); return 1; }

static int __cdecl l_town_index(lua_State *L) { plua_push_int(L, plua_int(L, 1, 0) & 0xFFFF); return 1; }
static int __cdecl l_town_handle(lua_State *L) { plua_push_int(L, (int)eng_town_handle(plua_int(L, 1, -1))); return 1; }
static int __cdecl l_town_name(lua_State *L) { plua_push_str(L, eng_town_name(plua_int(L, 1, -1))); return 1; }

static int __cdecl l_log(lua_State *L)
{
    char line[1024] = "";
    for (int i = 1; i <= plua_argc(L) && strlen(line) < 900; i++) {
        strncat(line, plua_str(L, i, "nil"), 120);
        strcat(line, i < plua_argc(L) ? " | " : "");
    }
    log_line("LUA: %s", line);
    return 0;
}

/* dev/test only: relax founding requirements, grant gold */
static int __cdecl l_dev_req(lua_State *L)
{
    Config *c = (Config *)adapter_config();
    c->found_min_gold = plua_int(L, 1, (int)c->found_min_gold);
    c->found_min_ships = plua_int(L, 2, c->found_min_ships);
    c->found_min_warships = plua_int(L, 3, c->found_min_warships);
    log_line("DEV requirements: gold %lld ships %d warships %d", (long long)c->found_min_gold,
             c->found_min_ships, c->found_min_warships);
    return 0;
}

static int __cdecl l_dev_gold(lua_State *L) { plua_push_int(L, eng_player_add_gold(plua_int(L, 1, 0))); return 1; }

/* Nation_DevSet(key, a [, b]) -> ok: put the nation into a test state that
   would otherwise take hours of play (tools/scenarios.py builds its saves
   with it). Keys: treasury v | stability v | loyalty town v | unrest town
   months | score power v | exhaustion power v | status power treaty |
   govcooldown months | recognized power 0/1 | lastchange power days_ago |
   rep power 0..100 (player reputation) */
static int __cdecl l_dev_set(lua_State *L)
{
    NationState *s = adapter_state();
    const char *k = plua_str(L, 1, "");
    int a = plua_int(L, 2, -1), b = plua_int(L, 3, -1), ok = 1;
    int town_ok = a >= 0 && a < MAX_TOWNS, power_ok = a >= 0 && a < N_POWERS;
    if (!strcmp(k, "treasury")) s->treasury = a;
    else if (!strcmp(k, "stability") && a >= 0 && a <= 100) s->stability = (uint8_t)a;
    else if (!strcmp(k, "loyalty") && town_ok && b >= 0 && b <= 100) s->town[a].loyalty = (uint8_t)b;
    else if (!strcmp(k, "unrest") && town_ok && b >= 0 && b <= 12) s->town[a].unrest = (uint8_t)b;
    else if (!strcmp(k, "score") && power_ok && b >= -100 && b <= 100) s->rel[a].score = (int16_t)b;
    else if (!strcmp(k, "exhaustion") && power_ok && b >= 0 && b <= 100) s->rel[a].war_exhaustion = (uint8_t)b;
    else if (!strcmp(k, "status") && power_ok && b >= 0 && b <= TREATY_CEASEFIRE) s->rel[a].status = (Treaty)b;
    else if (!strcmp(k, "recognized") && power_ok && (b == 0 || b == 1)) s->rel[a].recognized = (uint8_t)b;
    else if (!strcmp(k, "lastchange") && power_ok && b >= 0 && (uint32_t)b <= adapter_day())
        s->rel[a].last_change_day = adapter_day() - (uint32_t)b;
    else if (!strcmp(k, "govcooldown") && a >= 0 && a <= GOV_COOLDOWN_MONTHS)
        s->government = (uint8_t)((s->government & GOV_TYPE_MASK) | (a << GOV_COOLDOWN_SHIFT));
    else if (!strcmp(k, "navyorder") && a >= 0 && a < NAVY_ORDER_COUNT) {   /* skips the rank check */
        s->navy.order = (uint8_t)a;
        navy_apply_order(a);
    }
    else if (!strcmp(k, "soldiers") && town_ok && b >= 0 && b <= 5000) ok = navy_dev_soldiers(a, b);
    else if (!strcmp(k, "property") && town_ok && (b == 0 || b == 1)) g_dev_property[a] = (uint8_t)b;
    else if (!strcmp(k, "petition") && town_ok) s->navy.petition = (uint8_t)(a + 1);
    else if (!strcmp(k, "offer") && power_ok && s->rel[a].status == TREATY_PEACE) s->rel[a].expiry_day = adapter_day() + 30;
    else if (!strcmp(k, "rep") && power_ok && b >= 0 && b <= 100)   /* player reputation with a power */
        eng_player_add_reputation(a, b - eng_player_reputation(a));
    else ok = 0;
    Effects none = {0};
    adapter_apply(&none);                          /* re-sync the player_rel war table */
    log_line("DEV set %s %d %d -> %s", k, a, b, ok ? "ok" : "REFUSED");
    plua_push_int(L, ok);
    return 1;
}

/* Nation_DevPermit(town, 0/1) -> ok: set the player's building permit in a town
   directly, as if earned at the master builder or given up (tests) */
static int __cdecl l_dev_permit(lua_State *L)
{
    int t = plua_int(L, 1, -1), on = plua_int(L, 2, -1);
    plua_push_int(L, (on == 0 || on == 1) && t >= 0 && t < eng_town_count() && eng_town_set_permit(t, on));
    return 1;
}

/* Nation_DevFleetSail(town) -> ok: the first fleet of the nation sails to that town */
static int __cdecl l_dev_fleet_sail(lua_State *L)
{
    int ok = navy_dev_sail(plua_int(L, 1, -1));
    plua_push_int(L, ok);
    return 1;
}

/* Nation_PanelOpen([page]) -> ok / Nation_PanelClose() / Nation_PanelInfo() -> open, page, cards
   / Nation_PanelCard(i) -> caption, body / Nation_PanelClick(key) -> handled (test install) */
static int __cdecl l_panel_open(lua_State *L) { plua_push_int(L, panel_open(plua_int(L, 1, -1))); return 1; }
static int __cdecl l_panel_close(lua_State *L) { (void)L; panel_request_close(); return 0; }
static int __cdecl l_panel_info(lua_State *L)
{
    plua_push_int(L, panel_is_open());
    plua_push_int(L, panel_current_page());
    plua_push_int(L, panel_card_count());
    return 3;
}
static int __cdecl l_panel_card(lua_State *L)
{
    int i = plua_int(L, 1, -1);
    plua_push_str(L, panel_card_caption(i));
    plua_push_str(L, panel_card_body(i));
    return 2;
}
static int __cdecl l_panel_click(lua_State *L) { plua_push_int(L, panel_click(plua_int(L, 1, -1))); return 1; }
/* Nation_PanelMode(m) / Nation_PanelSelect(key) -> ok; Nation_PanelFeedback() -> ok (2 = asks), text;
   Nation_PanelRow(i) -> key, name, cell1..cell4; Nation_DevPanelRow(key) -> shown, x, y, w, h */
static int __cdecl l_panel_mode(lua_State *L) { plua_push_int(L, panel_set_mode(plua_int(L, 1, 0))); return 1; }
static int __cdecl l_panel_select(lua_State *L) { plua_push_int(L, panel_select(plua_int(L, 1, -1))); return 1; }
static int __cdecl l_panel_feedback(lua_State *L)
{
    int ok = 0;
    const char *t = panel_feedback(&ok);
    plua_push_int(L, ok);
    plua_push_str(L, t);
    return 2;
}
static int __cdecl l_panel_row(lua_State *L)
{
    int key = 0;
    const char *name = "", *cells[4] = {"", "", "", ""};
    int ok = panel_row(plua_int(L, 1, -1), &key, &name, cells);
    plua_push_int(L, ok ? key : -1);
    plua_push_str(L, name);
    for (int i = 0; i < 4; i++) plua_push_str(L, cells[i]);
    return 6;
}
static int __cdecl l_dev_panel_row(lua_State *L)
{
    int x, y, w, h;
    int ok = panel_row_rect(plua_int(L, 1, -1), &x, &y, &w, &h);
    plua_push_int(L, ok);
    plua_push_int(L, x);
    plua_push_int(L, y);
    plua_push_int(L, w);
    plua_push_int(L, h);
    return 5;
}

/* Nation_DevWarsRow(cell [, mask]) -> shown: the Overview's Wars cell 0..4 (0 = the nation) shows the
   entries of mask (bits 0..3 England..Spain, 4 "you"); -1 = the real wars; no mask: only ask.
   Returns the entries the cell showed at the last refresh (-1: the page was not up) */
static int __cdecl l_dev_wars_row(lua_State *L)
{
    plua_push_int(L, panel_dev_wars(plua_int(L, 1, -1), plua_int(L, 2, -2)));
    return 1;
}

/* Nation_DevPanelButton(card, slot) -> shown, x, y, w, h (layout pixels) of a card's text button */
static int __cdecl l_dev_panel_button(lua_State *L)
{
    int x, y, w, h;
    int ok = panel_button_rect(plua_int(L, 1, -1), plua_int(L, 2, 0), &x, &y, &w, &h);
    plua_push_int(L, ok);
    plua_push_int(L, x);
    plua_push_int(L, y);
    plua_push_int(L, w);
    plua_push_int(L, h);
    return 5;
}

/* Nation_DevGuiRect(name) -> found, x, y, w, h (layout pixels) of a named control */
static int __cdecl l_dev_gui_rect(lua_State *L)
{
    int x = 0, y = 0;
    void *d = gui_find(plua_str(L, 1, ""));
    if (d) gui_abs_pos(d, &x, &y);
    plua_push_int(L, d != NULL);
    plua_push_int(L, x);
    plua_push_int(L, y);
    plua_push_int(L, d ? gui_width(d) : 0);
    plua_push_int(L, d ? gui_height(d) : 0);
    return 5;
}

/* Nation_DevFoundInfo() -> shown, title, flag, name in the box, box x, y, w, h (window pixels) */
static int __cdecl l_dev_found_info(lua_State *L)
{
    int t, f, x, y, w, h;
    char name[96];
    int shown = panel_found_info(&t, &f, name, sizeof name, &x, &y, &w, &h);
    plua_push_int(L, shown);
    plua_push_int(L, t);
    plua_push_int(L, f);
    plua_push_str(L, name);
    plua_push_int(L, x);
    plua_push_int(L, y);
    plua_push_int(L, w);
    plua_push_int(L, h);
    return 8;
}

/* Nation_DevOfficial(town, kind) -> ok, dialog state, npc nation, vanilla tier: run the
   enter-dialog code of an official (0 treasurer, 1 commander, 2 building master) in a town */
static int __cdecl l_dev_official(lua_State *L)
{
    int st, nat, tier;
    plua_push_int(L, officials_dev_probe(plua_int(L, 1, -1), plua_int(L, 2, -1), &st, &nat, &tier));
    plua_push_int(L, st);
    plua_push_int(L, nat);
    plua_push_int(L, tier);
    return 4;
}

/* Nation_DevTownInfo() -> open, town, mode, flag ok, heading, relation, role: what the open
   town info dialog shows (mode 1 = the nation section of a member town, the conquered-town info fix) */
static int __cdecl l_dev_town_info(lua_State *L)
{
    TownInfoView v;
    plua_push_int(L, towninfo_dev(&v));
    plua_push_int(L, v.town);
    plua_push_int(L, v.mode);
    plua_push_int(L, v.flag_ok);
    plua_push_str(L, v.heading);
    plua_push_str(L, v.relation);
    plua_push_str(L, v.role);
    return 7;
}

/* Nation_DevNationName(n) -> the game's nation-name helper 0x4081B0 for nation n */
static int __cdecl l_dev_nation_name(lua_State *L)
{
    char t[96];
    towninfo_dev_nation_name(plua_int(L, 1, 0), t, sizeof t);
    plua_push_str(L, t);
    return 1;
}

/* Nation_DevGuiFind(name) -> address of a UI control (0 if none), for research */
static int __cdecl l_dev_gui_find(lua_State *L) { plua_push_int(L, (int)(uintptr_t)gui_find(plua_str(L, 1, ""))); return 1; }

/* ---- DEV/TEST ONLY: open vanilla windows for the UI gallery (tools/ui_gallery.py) ----
   Calls a CGameMenu::Open* (this = gm = *(app+0xEC)) or the town view's building-click
   dispatcher 0x516AA0 (this = vc = *(app+0xF0)) on the next frame, and reads/selects the
   tabs of an open CTabControl (gm+field). Registered only in a test install (PR2Nation.dev).
   The VAs are listed in tools/ui_gallery.py; a wrong VA or argument count crashes the game. */
typedef void **(*DevGetApp_t)(void);
#define DevGetApp ((DevGetApp_t)0x00403360)
typedef void (__attribute__((thiscall)) *DevCall0_t)(void *);
typedef void (__attribute__((thiscall)) *DevCall1_t)(void *, int);
typedef void (__attribute__((thiscall)) *DevCall2_t)(void *, int, int);
typedef void (__attribute__((thiscall)) *DevCall3_t)(void *, int, int, int);
#define DEV_CLOSE_ALL   0x00507600u     /* CGameMenu::CloseAllMenus(bool) */
#define DEV_SELECT_TAB  0x004DCC70u     /* CTabControl::SelectTab(int id) */

static struct { int pending, on_vc, n, a[3]; uint32_t va; } g_dev_call;

static uint8_t *dev_app_obj(int off)
{
    void **app = DevGetApp();
    uint8_t *a = app ? (uint8_t *)*app : NULL;
    return a ? *(uint8_t **)(a + off) : NULL;
}

static void dev_call_tick(void)
{
    if (!g_dev_call.pending) return;
    g_dev_call.pending = 0;
    uint8_t *obj = dev_app_obj(g_dev_call.on_vc ? 0xF0 : 0xEC);
    int *a = g_dev_call.a;
    void *f = (void *)(uintptr_t)g_dev_call.va;
    log_line("DEV: menu call %08X on %s %p (%d args %d %d %d)", g_dev_call.va, g_dev_call.on_vc ? "vc" : "gm",
             obj, g_dev_call.n, a[0], a[1], a[2]);
    if (!obj) return;
    switch (g_dev_call.n) {
    case 0: ((DevCall0_t)f)(obj); break;
    case 1: ((DevCall1_t)f)(obj, a[0]); break;
    case 2: ((DevCall2_t)f)(obj, a[0], a[1]); break;
    case 3: ((DevCall3_t)f)(obj, a[0], a[1], a[2]); break;
    }
    log_line("DEV: menu call %08X done", g_dev_call.va);
}

/* Nation_DevMenu(va, nargs [, a1, a2, a3 [, on_vc]]) -> queued: call va(gm or vc, args) next frame */
static int __cdecl l_dev_menu(lua_State *L)
{
    uint32_t va = (uint32_t)plua_int(L, 1, 0);
    int n = plua_int(L, 2, 0), ok = va >= 0x00401000u && va < 0x00680000u && n >= 0 && n <= 3;
    if (ok) {
        g_dev_call.va = va;
        g_dev_call.n = n;
        for (int i = 0; i < 3; i++) g_dev_call.a[i] = plua_int(L, 3 + i, 0);
        g_dev_call.on_vc = plua_int(L, 6, 0);
        g_dev_call.pending = 1;
    }
    plua_push_int(L, ok);
    return 1;
}

/* Nation_DevMenuField(off) -> the pointer at gm+off (0 = that window is closed), gm, vc */
static int __cdecl l_dev_menu_field(lua_State *L)
{
    uint8_t *gm = dev_app_obj(0xEC);
    int off = plua_int(L, 1, 0);
    plua_push_int(L, gm && off >= 0 && off < 0x200 ? *(int *)(gm + off) : 0);
    plua_push_int(L, (int)(uintptr_t)gm);
    plua_push_int(L, (int)(uintptr_t)dev_app_obj(0xF0));
    return 3;
}

/* Nation_DevCloseMenus() -> ok: CGameMenu::CloseAllMenus(0), now */
static int __cdecl l_dev_close_menus(lua_State *L)
{
    uint8_t *gm = dev_app_obj(0xEC);
    if (gm) ((DevCall1_t)DEV_CLOSE_ALL)(gm, 0);
    plua_push_int(L, gm != NULL);
    return 1;
}

/* the CTabControl (vtable 0x694AA8) at gm+off, or NULL if that slot holds something else */
static uint8_t *dev_tab_control(uint8_t *gm, int off)
{
    uint8_t *tab = gm && off >= 0 && off < 0x200 ? *(uint8_t **)(gm + off) : NULL;
    return tab && !IsBadReadPtr(tab, 0x108) && *(uint32_t *)tab == 0x00694AA8u ? tab : NULL;
}

/* Nation_DevTabs(off) -> n, current id, then id, radio for each tab of the CTabControl at gm+off */
static int __cdecl l_dev_tabs(lua_State *L)
{
    uint8_t *gm = dev_app_obj(0xEC), *tab = dev_tab_control(gm, plua_int(L, 1, 0));
    uint8_t **b = tab ? *(uint8_t ***)(tab + 0xF8) : NULL, **e = tab ? *(uint8_t ***)(tab + 0xFC) : NULL;
    int n = b && e > b ? (int)(e - b) : 0;
    if (n > 16) n = 16;
    uint8_t *cur = tab ? *(uint8_t **)(tab + 0x104) : NULL;
    plua_push_int(L, n);
    plua_push_int(L, cur ? *(int *)cur : -1);
    for (int i = 0; i < n; i++) {
        plua_push_int(L, b[i] ? *(int *)b[i] : -1);
        plua_push_int(L, b[i] ? b[i][0x1D] : 0);
    }
    return 2 + 2 * n;
}

/* Nation_DevSelectTab(off, id) -> ok: CTabControl::SelectTab on the tab control at gm+off */
static int __cdecl l_dev_select_tab(lua_State *L)
{
    uint8_t *gm = dev_app_obj(0xEC), *tab = dev_tab_control(gm, plua_int(L, 1, 0));
    if (tab) ((DevCall1_t)DEV_SELECT_TAB)(tab, plua_int(L, 2, -1));
    plua_push_int(L, tab != NULL);
    return 1;
}

/* Dev helpers (cheats) and the PR2Nation.cmd console exist only in a test
   install: a file PR2Nation.dev next to the exe (tools/feature_suite.py
   creates it; the private test installer does not). */
static const struct { const char *name; lua_CFunction f; } k_dev[] = {
    {"Nation_DevSetRequirements", l_dev_req}, {"Nation_DevGrantGold", l_dev_gold},
    {"Nation_DevSet", l_dev_set}, {"Nation_DevFleetSail", l_dev_fleet_sail}, {"Nation_PanelClick", l_panel_click}, {"Nation_PanelMode", l_panel_mode}, {"Nation_PanelSelect", l_panel_select},
    {"Nation_PanelFeedback", l_panel_feedback}, {"Nation_PanelRow", l_panel_row}, {"Nation_DevPanelRow", l_dev_panel_row},
    {"Nation_DevGuiFind", l_dev_gui_find}, {"Nation_DevWarsRow", l_dev_wars_row},
    {"Nation_DevFoundInfo", l_dev_found_info}, {"Nation_DevPanelButton", l_dev_panel_button},
    {"Nation_DevGuiRect", l_dev_gui_rect}, {"Nation_DevOfficial", l_dev_official},
    {"Nation_DevTownInfo", l_dev_town_info}, {"Nation_DevNationName", l_dev_nation_name},
    {"Nation_DevPermit", l_dev_permit},
    {"Nation_DevFoundInfo", l_dev_found_info}, {"Nation_DevSight", l_dev_sight},
    {"Nation_DevVisibleNear", l_dev_visible_near}, {"Nation_DevCycle", l_dev_cycle},
    {"Nation_DevFrames", l_dev_frames}, {"Nation_DevFlags", l_dev_flags}, {"Nation_DevView", l_dev_view},
    {"Nation_DevMenu", l_dev_menu}, {"Nation_DevMenuField", l_dev_menu_field},           /* UI gallery */
    {"Nation_DevCloseMenus", l_dev_close_menus}, {"Nation_DevTabs", l_dev_tabs}, {"Nation_DevSelectTab", l_dev_select_tab},
};

static void exe_dir_file(char *path, const char *name)
{
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    while (n && path[n - 1] != '\\') n--;
    lstrcpynA(path + n, name, MAX_PATH - (int)n);
}

static int dev_mode(void)
{
    static int cached = -1;
    if (cached < 0) {
        char path[MAX_PATH];
        exe_dir_file(path, "PR2Nation.dev");
        cached = GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
        log_line("dev mode %s (PR2Nation.dev)", cached ? "ON" : "off");
    }
    return cached;
}

static const struct { const char *name; lua_CFunction f; } k_api[] = {
    {"Nation_Log", l_log},
    {"Nation_CanFound", l_can_found}, {"Nation_Found", l_found}, {"Nation_GetInfo", l_info},
    {"Nation_GetRelation", l_relation}, {"Nation_DeclareWar", l_declare_war},
    {"Nation_Propose", l_propose}, {"Nation_Annex", l_annex}, {"Nation_ReleaseTown", l_release},
    {"Nation_GetTown", l_town}, {"Nation_NationalConvoys", l_national_convoys}, {"Nation_NavyInfo", l_navy_info}, {"Nation_PanelOpen", l_panel_open}, {"Nation_PanelClose", l_panel_close},
    {"Nation_PanelInfo", l_panel_info}, {"Nation_PanelCard", l_panel_card}, {"Nation_NavyCommission", l_navy_commission}, {"Nation_NavyDecommission", l_navy_decommission},
    {"Nation_NavySetOrder", l_navy_set_order}, {"Nation_NavyReinforce", l_navy_reinforce},
    {"Nation_NavyBuildTower", l_navy_build_tower}, {"Nation_TownDefence", l_town_defence}, {"Nation_PendingConquest", l_pending_conquest},
    {"Nation_ResolveConquest", l_resolve_conquest}, {"Nation_GetFinance", l_finance}, {"Nation_SetTax", l_set_tax}, {"Nation_SetTariff", l_set_tariff},
    {"Nation_Donate", l_donate}, {"Nation_Withdraw", l_withdraw},
    {"Nation_TownIndex", l_town_index}, {"Nation_TownHandle", l_town_handle},
    {"Nation_TownName", l_town_name},
    {"Nation_SetGovernment", l_set_government}, {"Nation_GetGovernment", l_get_government},
    {"Nation_GetStrategy", l_get_strategy}, {"Nation_GetGold", l_get_gold},
    {"Nation_FlagCount", l_flag_count}, {"Nation_FlagName", l_flag_name},
    {"Nation_GetFlag", l_get_flag}, {"Nation_SetFlag", l_set_flag},
    {"Nation_ShipCount", l_ship_count}, {"Nation_ShipInfo", l_ship_info}, {"Nation_ShipGoto", l_ship_goto},
};

/* Called every frame: (re)register after New Game / Load replaced the globals,
   and run the dev console file (tests, debugging). */
void api_frame(void)
{
    static unsigned long tick;
    dev_call_tick();                  /* Nation_DevMenu (test install only) */
    if (++tick % 30) return;
    if (!plua_state()) return;
    if (plua_global_is_nil("Nation_GetInfo")) {
        for (unsigned i = 0; i < sizeof k_api / sizeof *k_api; i++)
            plua_register(k_api[i].name, k_api[i].f);
        if (dev_mode())
            for (unsigned i = 0; i < sizeof k_dev / sizeof *k_dev; i++)
                plua_register(k_dev[i].name, k_dev[i].f);
        log_line("Nation_* Lua API registered (%u functions)", (unsigned)(sizeof k_api / sizeof *k_api));
    }
    if (!dev_mode()) return;
    char path[MAX_PATH];
    exe_dir_file(path, "PR2Nation.cmd");
    FILE *f = fopen(path, "rb");
    if (!f) return;
    static char code[8192];
    size_t len = fread(code, 1, sizeof code - 1, f);
    fclose(f);
    DeleteFileA(path);
    code[len] = 0;
    log_line("CONSOLE run (%u bytes)", (unsigned)len);
    int st = plua_run(code);
    log_line("CONSOLE status %d", st);
}
