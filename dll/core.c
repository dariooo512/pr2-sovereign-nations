/* Engine-independent core of the player-nation feature (see core.h).
 *
 * Plain C11: no Windows headers, no mutable globals, fully deterministic.
 * Every "random" AI decision uses roll100(day, power, salt), a hash of the
 * game day, so a replay of the same days gives the same decisions.
 *
 * ---------------------------------------------------------------------------
 * BALANCE MODEL (all numbers are the named constants below)
 * ---------------------------------------------------------------------------
 * Taxes (§5.3), settled every 30 days:
 *   base_i       = min(pop,200000) * 20 + max(wealth,0) / 10        (gold/month)
 *   tax_i        = town override, else national default, capped by Config
 *   eff_i (%)    = 40 + loyalty*45/100 + min(15, garrison/10)   -> 40..100
 *   revenue_i    = base_i * tax_i * eff_i / 10000, halved while in unrest
 *   tariff_i     = (base_i / 5) * tariff_pct/100 * eff_i/100     (§8, imports)
 *   upkeep       = members * upkeep_per_town   (+ national_convoys * upkeep_per_convoy
 *                  only when built with NATION_CONVOYS; off in this version)
 *   treasury    += sum(revenue) + sum(tariff) - upkeep            (exactly once)
 *
 * Loyalty (§4.4), daily drift of 1 point toward a target:
 *   55 - (tax-10)*1.5 - 15 if essential shortage + prosperity 0..10
 *   (wealth per head / 20) + min(10, garrison/20) + min(10, months/2) since
 *   joining - max(0, 25 - months) if conquered + 10 capital - 5 if at war with
 *   the prior sovereign + (stability-50)/5 - tariff/5 - 10 if insolvent.
 *   Loyalty < 20 at two consecutive month ends -> FX_TOWN_UNREST start
 *   (income halved); recovers at loyalty >= 30 -> FX_TOWN_UNREST end.
 *
 * Stability (§9), monthly, moves at most 5 toward:
 *   50 + 5 solvent / -20 insolvent + 5 surplus / -5 deficit
 *   + (avg loyalty-50)/2 - (default tax-15)/2 if >15
 *   - (5 + exhaustion/10) per war - 4 per conquest younger than 180 days (max 20)
 *   + 2 per power that recognizes us; capped at 10 while landless.
 *   Insolvency also costs 3 stability per month immediately and blocks
 *   withdrawals (the only optional spending the core controls).
 *
 * Relations (§6): monthly drift of 2 toward
 *   (reputation-50)/2 + 10 recognized + treaty bonus (trade 10, NAP 5, alliance 20)
 *   - 30 at war - tariff/2 + 10 per common enemy - 20 for the former sovereign.
 *   War exhaustion: +6 per month at war, -10 per month otherwise.
 *
 * AI (§6.3), every Config.ai_eval_interval_days, per power, weighing relation
 * score, relative strength (player = members*10 + warships*2 + ships/2 vs
 * World.power_strength, which the adapter must fill on the same scale),
 * trade dependence (vanilla reputation), its other wars and exhaustion:
 *   - recognizes the nation after >= 3 months (chance grows with time),
 *   - declares war per strategy weights below (bounded: 180 days, exh <= 70),
 *   - offers a ceasefire when exhausted / outmatched (pending 30 days: while
 *     pending, the player's ceasefire proposal is accepted for sure),
 *   - imposes a ceasefire after a year of war at exhaustion >= 90,
 *   - offers trade agreements to friendly recognized partners (pending 30 days),
 *   - cancels treaties when the relation sours.
 * Pending offers reuse Relation.expiry_day while status is WAR or PEACE.
 *
 * AI strategy (§10), derived per power at every evaluation (core_ai_strategy):
 *   DEFENSIVE if at war with another power, ratio >= 110 or exhaustion >= 50;
 *   else OPPORTUNISTIC if ratio < 100 and the player is insolvent, stability
 *   < 35 or at war elsewhere; else COMMERCIAL if reputation >= 60 or trade /
 *   alliance; else EXPANSIONIST if ratio < 50; else COMMERCIAL.
 *   Weights (k_strat): war at score <= -60 C / -30 E / never D / -20 O (O also
 *   up to ratio 150), chance bonus -15/+15/-/+20; trade offers C 35% from score
 *   15 & rep 50, D 25%, E/O 10%; recognition +10 C, +5 D, -10 O; ceasefire
 *   offers D from exhaustion 25 (+20), E/O -10; player-proposal acceptance
 *   shifted per strategy (alliances unaffected).
 *   Bounds: AI war only >= 180 days after the last treaty change (so at most
 *   one AI war per power per 180 days; was 90), never at exhaustion > 70, and
 *   a warring AI with exhaustion > 70 must offer a ceasefire (no roll).
 *
 * Government (§5.5), NationState.government = type | months_cooldown << 3:
 *   reform: once per 25 month settlements (>= 2 years), stability -10, needs 20.
 *   Merchant Republic: collection eff +5, tariffs x5/4, trade offers +10%,
 *     acceptance +15 trade / +10 peace, ceasefire, NAP; war stability -(9+exh/10).
 *   Colonial Monarchy: garrison eff min(20,g/8), loyalty min(15,g/12),
 *     stability +8; upkeep x5/4; conquered malus 25-months/2 (slow recovery).
 *   Pirate Republic: plunder per enemy power/month min(30000, warships*1500)
 *     *(100-exh)/100; war stability -(2+exh/10); relation target -10 with all
 *     (and -10 at adoption); conquest start loyalty 20, malus 35-months;
 *     acceptance -10 trade/NAP, -20 alliance.
 *   Maritime Federation: loyalty +8, unrest below 15, NAP +5; collection eff
 *     -10 (30..90); secession after 3 months instead of 4.
 *
 * Rebellion (§9): once open (loyalty < threshold two month ends), unrest keeps
 * counting until loyalty >= 30. Still open 4 month ends after the outbreak
 * (unrest counter >= 6): a member town secedes to its prior power (FX_TOWN_TO_POWER
 * via core_lose_town, stability -10 in total); the capital never secedes but
 * riots for -20 stability every such month.
 *
 * Calling conventions: functions APPEND to *out (caller zeroes it); out may be
 * NULL (effects dropped). core_daily's monthly settlement and AI decisions are
 * idempotent per day; the daily loyalty drift assumes one call per game day.
 * core_daily also treats a member town the World reports under a colonial
 * power (0..3) as lost to that power (former sovereign retakes the town).
 */
#include "core.h"
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define CAPITAL_NONE      0xFF
#define TAX_USE_DEFAULT   0xFF
#define FX_CAP            ((int)(sizeof(((Effects *)0)->fx) / sizeof(((Effects *)0)->fx[0])))
#define TREASURY_LIMIT    4000000000000000LL
#define MONTH_DAYS        30
#define CEASEFIRE_DAYS    60
#define TREATY_DAYS       360
#define OFFER_DAYS        30
#define MAX_CATCHUP_MONTHS 12

/* balance constants */
#define BASE_PER_HEAD          20
#define BASE_WEALTH_DIV        10
#define BASE_POP_CAP           200000
#define BASE_CAP               50000000LL
#define IMPORT_DIV             5
#define DEFAULT_TAX_PCT        10
#define HARD_MAX_TAX           50
#define START_STABILITY        70
#define CAPITAL_LOYALTY        75
#define UNREST_LOYALTY         20
#define UNREST_RECOVER         30
#define UNREST_MONTHS          2
#define FORMER_SOVEREIGN_SCORE (-60)
#define FORMER_SOV_WAR_REP     40
#define FOUNDING_REP_PENALTY   (-20)
#define DECLARE_WAR_SCORE      (-50)

/* rebellion / secession (§9 advanced) */
#define SECESSION_MONTHS       4      /* months of open unrest before a town secedes */
#define SECESSION_STABILITY    10     /* total stability cost of a secession */
#define CAPITAL_RIOT_STABILITY 20     /* per month while the capital is in persistent unrest */

/* government (§5.5) */
#define PLUNDER_PER_WARSHIP    1500   /* Pirate Republic, per month per enemy power */
#define PLUNDER_CAP            30000

/* AI bounds (§10) */
#define AI_WAR_COOLDOWN_DAYS   180    /* min days since the last treaty change before an AI war */
#define AI_WAR_MAX_EXHAUSTION  70     /* never declares war above this */
#define AI_EXHAUSTED           70     /* above this a warring AI must offer a ceasefire */
#define AI_WEAK_RATIO          110    /* player/power strength % at which a power feels weak */
#define AI_STRONG_RATIO        50     /* below this a power feels strong */

#ifdef __GNUC__
#define PRINTF_LIKE(f, a) __attribute__((format(printf, f, a)))
#else
#define PRINTF_LIKE(f, a)
#endif

static const char *const k_power_name[N_POWERS] = {"England", "France", "Holland", "Spain"};
static const char *const k_power_adj[N_POWERS] = {"English", "French", "Dutch", "Spanish"};
static const char *const k_titles[] = {"Republic", "Kingdom", "Free Republic", "Commonwealth",
                                       "Principality", "Confederation", "Grand Duchy", "Empire"};
#define N_TITLES ((int)(sizeof k_titles / sizeof k_titles[0]))
static const char *const k_treaty[] = {"Peace", "Trade Agreement", "Non-Aggression Pact",
                                       "Alliance", "War", "Ceasefire"};
static const int k_treaty_score_bonus[] = {0, 10, 5, 20, -30, 0};

/* ------------------------------------------------------------------------ */
/* small helpers                                                            */
/* ------------------------------------------------------------------------ */
static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
static int64_t clamp64(int64_t v, int64_t lo, int64_t hi) { return v < lo ? lo : v > hi ? hi : v; }
static int mini(int a, int b) { return a < b ? a : b; }
static int maxi(int a, int b) { return a > b ? a : b; }
static uint32_t days_since(uint32_t now, uint32_t then) { return now >= then ? now - then : 0; }
static int32_t to_i32(int64_t v) { return (int32_t)clamp64(v, INT32_MIN, INT32_MAX); }

/* ---- trace: every change of a relation score, with its cause (core_set_trace) ---- */
static CoreTraceFn g_trace;
void core_set_trace(CoreTraceFn fn) { g_trace = fn; }
static void trace(const char *fmt, ...) PRINTF_LIKE(1, 2);
static void trace(const char *fmt, ...)
{
    if (!g_trace) return;
    char buf[320];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    g_trace(buf);
}

/* the one place a relation score changes (besides the founding / declaration resets, which trace too) */
static void add_score(NationState *s, int p, int d, const char *why)
{
    Relation *r = &s->rel[p];
    int old = r->score;
    r->score = (int16_t)clampi(r->score + d, -100, 100);
    if (r->score != old)
        trace("REL %s score %d -> %d (%+d: %s)", k_power_name[p], old, r->score, r->score - old, why);
}
static void add_stability(NationState *s, int d) { s->stability = (uint8_t)clampi(s->stability + d, 0, 100); }
static void add_treasury(NationState *s, int64_t d)
{
    s->treasury = clamp64(s->treasury + clamp64(d, -TREASURY_LIMIT, TREASURY_LIMIT),
                          -TREASURY_LIMIT, TREASURY_LIMIT);
}
/* a treasury change, booked to its category of the national accounts (this month) */
static void book(NationState *s, int cat, int64_t d)
{
    int64_t before = s->treasury;
    add_treasury(s, d);
    if (cat >= 0 && cat < LEDGER_CATS)
        s->ledger.month[1][cat] = to_i32((int64_t)s->ledger.month[1][cat] + (s->treasury - before));
}

/* deterministic 0..99 roll from (day, power, salt) */
static int roll100(uint32_t day, int power, int salt)
{
    uint32_t x = day * 0x9E3779B1u ^ (uint32_t)(power + 1) * 0x85EBCA77u ^ (uint32_t)(salt + 7) * 0xC2B2AE3Du;
    x ^= x >> 16; x *= 0x7FEB352Du; x ^= x >> 15; x *= 0x846CA68Bu; x ^= x >> 16;
    return (int)(x % 100u);
}

static void set_why(char *why, int len, const char *fmt, ...) PRINTF_LIKE(3, 4);
static void set_why(char *why, int len, const char *fmt, ...)
{
    if (!why || len <= 0) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, (size_t)len, fmt, ap);
    va_end(ap);
}

static int fx_room(const Effects *o, int k) { return !o || (o->n >= 0 && o->n + k <= FX_CAP); }

static Effect *fx_add(Effects *o, FxKind k, int a, int b, int64_t v)
{
    if (!o || o->n < 0 || o->n >= FX_CAP) return NULL;
    Effect *e = &o->fx[o->n++];
    memset(e, 0, sizeof *e);
    e->kind = k; e->a = a; e->b = b; e->v = v;
    return e;
}

/* a change of the player's vanilla reputation, with its cause in text (logged by the adapter) */
static void fx_rep(Effects *o, int power, int delta, const char *why)
{
    Effect *e = fx_add(o, FX_REPUTATION, power, 0, delta);
    if (e) snprintf(e->text, sizeof e->text, "%s", why);
}

static void fx_msg(Effects *o, const char *fmt, ...) PRINTF_LIKE(2, 3);
static void fx_msg(Effects *o, const char *fmt, ...)
{
    Effect *e = fx_add(o, FX_MESSAGE, 0, 0, 0);
    if (!e) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(e->text, sizeof e->text, fmt, ap);
    va_end(ap);
}

static int n_towns(const World *w) { return mini(w->n_towns, MAX_TOWNS); }
static int town_ok(const World *w, int t) { return t >= 0 && t < n_towns(w) && w->town[t].exists; }
static int power_ok(int p) { return p >= 0 && p < N_POWERS; }
static int is_member(const NationState *s, int t) { return t >= 0 && t < MAX_TOWNS && s->town[t].member; }
static int has_capital(const NationState *s) { return s->capital < MAX_TOWNS && s->town[s->capital].member; }

/* sovereign of a town as a colonial power (nation-5 towns: their display power) */
static int town_prior_power(const TownSnap *t)
{
    if (t->power < N_POWERS) return t->power;
    if (t->display_power < N_POWERS) return t->display_power;
    return 0;
}

static int title_index(int title) { return (title >= 0 && title < N_TITLES) ? title : 0; }
static __attribute__((unused)) const char *nat_title(const NationState *s) { return k_titles[title_index(s->title)]; }

static void copy_name(char *dst, const char *src)
{
    int j = 0;
    if (src)
        for (int i = 0; src[i] && j < NAME_LEN - 1; i++)
            if ((unsigned char)src[i] >= 0x20) dst[j++] = src[i];
    while (j > 0 && dst[j - 1] == ' ') j--;
    memset(dst + j, 0, (size_t)(NAME_LEN - j));
}

int core_member_count(const NationState *s)
{
    int n = 0;
    for (int t = 0; t < MAX_TOWNS; t++) n += s->town[t].member ? 1 : 0;
    return n;
}

int core_officials_serve(const NationState *s, int town, int town_nation)
{
    /* both the nation state and the town byte must agree: a town a power has
       just retaken (byte 0..3) is theirs again, whatever the core still thinks */
    return s && s->founded && town >= 0 && town < MAX_TOWNS && s->town[town].member &&
           town_nation == NATION_ID;
}

int core_loyalty_label(const TownState *ts, char *out, int cap)
{
    if (!out || cap <= 0) return 0;
    out[0] = 0;
    if (!ts) return 0;
    /* the Towns page's thresholds: unrest from 2 months below 20, red below 20, green from 50 */
    if (ts->unrest >= 2) { snprintf(out, (size_t)cap, "in unrest"); return -1; }
    if (ts->unrest == 1 || ts->loyalty < 20) { snprintf(out, (size_t)cap, "restless (%d)", ts->loyalty); return -1; }
    if (ts->loyalty >= 50) { snprintf(out, (size_t)cap, "loyal (%d)", ts->loyalty); return 1; }
    snprintf(out, (size_t)cap, "calm (%d)", ts->loyalty);
    return 0;
}

int core_town_role(const NationState *s, int town, char *out, int cap)
{
    if (!out || cap <= 0) return 0;
    out[0] = 0;
    if (!s || !s->founded || town < 0 || town >= MAX_TOWNS || !s->town[town].member) return 0;
    snprintf(out, (size_t)cap, "%s of %s", town == s->capital ? "Capital" : "Town", s->name);
    return 1;
}

static int power_wars(const World *w, int p)
{
    int n = 0;
    for (int q = 0; q < N_POWERS; q++)
        if (q != p && (w->power_war[p][q] || w->power_war[q][p])) n++;
    return n;
}

/* powers the player is at war with that power p is also fighting */
static int common_enemies(const NationState *s, const World *w, int p)
{
    int n = 0;
    for (int q = 0; q < N_POWERS; q++)
        if (q != p && s->rel[q].status == TREATY_WAR && (w->power_war[p][q] || w->power_war[q][p])) n++;
    return n;
}

static int player_strength(const NationState *s, const World *w)
{
    return core_member_count(s) * 10 + w->player_warships * 2 + w->player_ships / 2;
}

/* player strength relative to power p in percent, 0..400 */
static int strength_ratio(const NationState *s, const World *w, int p)
{
    int ps = player_strength(s, w);
    int ws = maxi(1, w->power_strength[p]);
    return (int)clamp64((int64_t)ps * 100 / ws, 0, 400);
}

static int strength_term(int ratio)
{
    return ratio >= 100 ? mini(20, (ratio - 100) / 5) : -mini(20, (100 - ratio) / 5);
}

/* ------------------------------------------------------------------------ */
/* government (§5.5)                                                        */
/* ------------------------------------------------------------------------ */
static const char *const k_gov_name[GOV_COUNT] = {"Sovereign Government", "Merchant Republic",
                                                  "Colonial Monarchy", "Pirate Republic",
                                                  "Maritime Federation"};

int core_government(const NationState *s)
{
    int g = s->government & GOV_TYPE_MASK;
    return g < GOV_COUNT ? g : GOV_SOVEREIGN;
}
int core_government_cooldown(const NationState *s) { return s->government >> GOV_COOLDOWN_SHIFT; }
static int gov_is(const NationState *s, GovType g) { return core_government(s) == (int)g; }

const char *core_government_name(int gov)
{
    if (gov < 0) return "?";
    gov &= GOV_TYPE_MASK;
    return gov < GOV_COUNT ? k_gov_name[gov] : "?";
}

static int unrest_threshold(const NationState *s)
{
    return gov_is(s, GOV_MARITIME_FEDERATION) ? UNREST_LOYALTY - 5 : UNREST_LOYALTY;
}

static int secession_months(const NationState *s)
{
    return gov_is(s, GOV_MARITIME_FEDERATION) ? SECESSION_MONTHS - 1 : SECESSION_MONTHS;
}

/* ------------------------------------------------------------------------ */
/* AI strategy profiles (§10)                                               */
/* ------------------------------------------------------------------------ */
static const char *const k_strat_name[AI_STRAT_COUNT] = {"Commercial", "Expansionist", "Defensive",
                                                         "Opportunistic"};

const char *core_ai_strategy_name(int strategy)
{
    return (strategy >= 0 && strategy < AI_STRAT_COUNT) ? k_strat_name[strategy] : "?";
}

int core_ai_strategy(const NationState *s, const World *w, int power)
{
    if (!power_ok(power)) return -1;
    const Relation *r = &s->rel[power];
    int ratio = strength_ratio(s, w, power);
    if (power_wars(w, power) > 0 || ratio >= AI_WEAK_RATIO || r->war_exhaustion >= 50)
        return AI_STRAT_DEFENSIVE;
    int distracted = 0;
    for (int q = 0; q < N_POWERS; q++)
        if (q != power && s->rel[q].status == TREATY_WAR) distracted = 1;
    if (s->founded && ratio < 100 && (s->treasury < 0 || s->stability < 35 || distracted))
        return AI_STRAT_OPPORTUNISTIC;
    if (w->reputation[power] >= 60 || r->status == TREATY_TRADE || r->status == TREATY_ALLIANCE)
        return AI_STRAT_COMMERCIAL;
    if (ratio < AI_STRONG_RATIO) return AI_STRAT_EXPANSIONIST;
    return AI_STRAT_COMMERCIAL;
}

/* acceptance modifiers for player proposals (strategy of the power + our government) */
static int accept_mod(const NationState *s, int strat, Treaty t)
{
    int m = 0;
    switch (strat) {
    case AI_STRAT_DEFENSIVE:
        m += t == TREATY_CEASEFIRE ? 15 : t == TREATY_PEACE ? 10 : t == TREATY_NONAGGRESSION ? 15 : 0;
        break;
    case AI_STRAT_COMMERCIAL:
        m += t == TREATY_TRADE ? 15 : (t == TREATY_PEACE || t == TREATY_CEASEFIRE) ? 5 : 0;
        break;
    case AI_STRAT_EXPANSIONIST:
        m -= (t == TREATY_CEASEFIRE || t == TREATY_PEACE || t == TREATY_NONAGGRESSION) ? 10 : 0;
        break;
    case AI_STRAT_OPPORTUNISTIC:
        m -= (t == TREATY_CEASEFIRE || t == TREATY_NONAGGRESSION) ? 15 : (t == TREATY_PEACE || t == TREATY_TRADE) ? 10 : 0;
        break;
    default:
        break;
    }
    switch (core_government(s)) {
    case GOV_MERCHANT_REPUBLIC:
        m += t == TREATY_TRADE ? 15 : (t == TREATY_PEACE || t == TREATY_CEASEFIRE || t == TREATY_NONAGGRESSION) ? 10 : 0;
        break;
    case GOV_PIRATE_REPUBLIC:
        m -= t == TREATY_ALLIANCE ? 20 : (t == TREATY_TRADE || t == TREATY_NONAGGRESSION) ? 10 : 0;
        break;
    case GOV_MARITIME_FEDERATION:
        m += t == TREATY_NONAGGRESSION ? 5 : 0;
        break;
    default:
        break;
    }
    return m;
}

/* ------------------------------------------------------------------------ */
/* economy                                                                  */
/* ------------------------------------------------------------------------ */
static int64_t town_base(const TownSnap *t)
{
    int64_t pop = t->population > (uint32_t)BASE_POP_CAP ? BASE_POP_CAP : (int64_t)t->population;
    int64_t wealth = t->wealth > 0 ? t->wealth : 0;
    return clamp64(pop * BASE_PER_HEAD + wealth / BASE_WEALTH_DIV, 0, BASE_CAP);
}

static int eff_tax(const NationState *s, int t, int max_tax)
{
    int pct = s->town[t].tax_pct == TAX_USE_DEFAULT ? s->default_tax_pct : s->town[t].tax_pct;
    return clampi(pct, 0, clampi(max_tax, 0, HARD_MAX_TAX));
}

static int collection_eff(const NationState *s, const TownState *ts, const TownSnap *snap)
{
    int gov = core_government(s);
    int garrison = gov == GOV_COLONIAL_MONARCHY ? mini(20, snap->garrison / 8) : mini(15, snap->garrison / 10);
    int e = 40 + ts->loyalty * 45 / 100 + garrison;
    if (gov == GOV_MERCHANT_REPUBLIC) e += 5;
    if (gov == GOV_MARITIME_FEDERATION) return clampi(e - 10, 30, 90);
    return clampi(e, 40, 100);
}

static int in_unrest(const TownState *ts) { return ts->unrest >= UNREST_MONTHS; }

static int64_t town_tax(const NationState *s, const World *w, int t, int max_tax)
{
    const TownSnap *snap = &w->town[t];
    int64_t r = town_base(snap) * eff_tax(s, t, max_tax) * collection_eff(s, &s->town[t], snap) / 10000;
    return in_unrest(&s->town[t]) ? r / 2 : r;
}

static int64_t town_tariff(const NationState *s, const World *w, int t)
{
    const TownSnap *snap = &w->town[t];
    int64_t r = town_base(snap) / IMPORT_DIV * clampi(s->tariff_pct, 0, 100) / 100
                * collection_eff(s, &s->town[t], snap) / 100;
    if (gov_is(s, GOV_MERCHANT_REPUBLIC)) r = r * 5 / 4;
    return in_unrest(&s->town[t]) ? r / 2 : r;
}

int64_t core_monthly_tax_estimate(const NationState *s, const World *w)
{
    int64_t sum = 0;
    if (!s->founded) return 0;
    for (int t = 0; t < n_towns(w); t++)
        if (s->town[t].member && w->town[t].exists) sum += town_tax(s, w, t, HARD_MAX_TAX);
    return sum;
}

static const char *const k_ledger_name[LEDGER_CATS] = {
    "Taxes", "Import tariffs", "Privateering", "Plunder", "Donations",
    "Administration", "Fleet upkeep", "Tower upkeep", "New fleets", "Soldiers", "Cannon towers", "Towns bought",
    "Withdrawals"};

const char *core_ledger_name(int cat) { return cat >= 0 && cat < LEDGER_CATS ? k_ledger_name[cat] : "?"; }

static void month_end_sums(const NationState *s, const World *w, const Config *c, int64_t v[LEDGER_CATS]);

void core_ledger_forecast(const NationState *s, const World *w, const Config *c, int64_t out[LEDGER_CATS])
{
    int64_t v[LEDGER_CATS];
    if (s->founded) month_end_sums(s, w, c, v);
    else memset(v, 0, sizeof v);
    for (int k = 0; k < LEDGER_CATS; k++) out[k] = s->ledger.month[1][k] + v[k];
}

void core_refund(NationState *s, int64_t gold, int cat)
{
    if (gold > 0) book(s, cat, gold);
}

static int loyalty_target(const NationState *s, const World *w, int t)
{
    const TownState *ts = &s->town[t];
    const TownSnap *snap = &w->town[t];
    int months = (int)(days_since(w->day, ts->joined_day) / MONTH_DAYS);
    int tgt = 55;
    tgt -= (eff_tax(s, t, HARD_MAX_TAX) - DEFAULT_TAX_PCT) * 3 / 2;
    if (snap->essential_shortage) tgt -= 15;
    if (snap->wealth < 0) tgt -= 5;
    else tgt += (int)clamp64((int64_t)snap->wealth / (snap->population ? (int64_t)snap->population : 1) / 20, 0, 10);
    int gov = core_government(s);
    tgt += gov == GOV_COLONIAL_MONARCHY ? mini(15, snap->garrison / 12) : mini(10, snap->garrison / 20);
    tgt += mini(10, months / 2);
    if (ts->conquered)
        tgt -= gov == GOV_COLONIAL_MONARCHY ? maxi(0, 25 - months / 2)      /* slower recovery */
             : gov == GOV_PIRATE_REPUBLIC   ? maxi(0, 35 - months)          /* harsher occupation */
             : maxi(0, 25 - months);
    if (gov == GOV_MARITIME_FEDERATION) tgt += 8;
    if (t == s->capital) tgt += 10;
    if (power_ok(ts->prior_power) && s->rel[ts->prior_power].status == TREATY_WAR) tgt -= 5;
    tgt += (s->stability - 50) / 5;
    tgt -= s->tariff_pct / 5;
    if (s->treasury < 0) tgt -= 10;
    return clampi(tgt, 0, 100);
}

/* ------------------------------------------------------------------------ */
/* lifecycle                                                                */
/* ------------------------------------------------------------------------ */
void core_default_config(Config *c)
{
    memset(c, 0, sizeof *c);
    c->found_min_gold = 5000000;
    c->found_min_ships = 10;
    c->found_min_warships = 3;
    c->found_min_towns = 1;
    c->upkeep_per_town = 2000;
    c->upkeep_per_convoy = 3000;
    c->max_tax_pct = HARD_MAX_TAX;
    c->ai_eval_interval_days = 7;
    c->fleet_cost = 120000;
    c->fleet_upkeep = 6000;
    c->garrison_cost = 20000;
    c->tower_cost = 50000;
    c->tower_upkeep = 500;
}

void core_init(NationState *s)
{
    memset(s, 0, sizeof *s);
    s->magic = NATION_MAGIC;
    s->version = NATION_STATE_VERSION;
    s->size = (uint16_t)sizeof(NationState);
    s->capital = CAPITAL_NONE;
    s->default_tax_pct = DEFAULT_TAX_PCT;
    s->stability = 50;
    for (int p = 0; p < N_POWERS; p++) s->rel[p].status = TREATY_PEACE;
    for (int t = 0; t < MAX_TOWNS; t++) s->town[t].tax_pct = TAX_USE_DEFAULT;
}

const char *core_treaty_name(Treaty t)
{
    return ((int)t >= 0 && (int)t < (int)(sizeof k_treaty / sizeof k_treaty[0])) ? k_treaty[t] : "?";
}
const char *core_power_name(int power) { return power_ok(power) ? k_power_name[power] : "?"; }
const char *core_title_name(int title) { return k_titles[title_index(title)]; }

/* "a" or "an" before word (by its first letter: an English, an Alliance; a Spanish) */
const char *core_article(const char *word, int capital)
{
    int c = word ? (unsigned char)word[0] | 0x20 : 0;
    int an = c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u';
    return capital ? (an ? "An" : "A") : (an ? "an" : "a");
}

/* ------------------------------------------------------------------------ */
/* founding (§3, §11.5)                                                     */
/* ------------------------------------------------------------------------ */
static int capital_eligible(const World *w, int t)
{
    if (!town_ok(w, t)) return 0;
    const TownSnap *s = &w->town[t];
    return s->player_property && !s->is_viceroy_seat && (s->power < N_POWERS || s->power == NATION_ID);
}

int core_can_found(const NationState *s, const World *w, const Config *c, int capital,
                   char *why, int why_len)
{
    set_why(why, why_len, "%s", "");
    if (s->founded) {
        set_why(why, why_len, "You already lead %s; only one nation can be founded.",
                s->name);
        return 0;
    }
    if (w->player_gold < c->found_min_gold) {
        set_why(why, why_len, "Requires %lld gold in personal wealth (you have %lld).",
                (long long)c->found_min_gold, (long long)w->player_gold);
        return 0;
    }
    if (w->player_ships < c->found_min_ships) {
        set_why(why, why_len, "Requires at least %d ships (you have %d).", c->found_min_ships,
                w->player_ships);
        return 0;
    }
    if (w->player_warships < c->found_min_warships) {
        set_why(why, why_len, "Requires at least %d armed warships (you have %d).",
                c->found_min_warships, w->player_warships);
        return 0;
    }
    int eligible = 0;
    for (int t = 0; t < n_towns(w); t++) eligible += capital_eligible(w, t);
    if (eligible < c->found_min_towns) {
        set_why(why, why_len, "Requires %d eligible town(s) where you own property (found %d).",
                c->found_min_towns, eligible);
        return 0;
    }
    if (!town_ok(w, capital)) {
        set_why(why, why_len, "%s", "The chosen capital is not a valid town.");
        return 0;
    }
    const TownSnap *cap = &w->town[capital];
    if (cap->is_viceroy_seat) {
        set_why(why, why_len, "%s", "A viceroy seat cannot become the capital of a new nation.");
        return 0;
    }
    if (!cap->player_property) {
        set_why(why, why_len, "%s", "You must own property (businesses or a warehouse) in the capital.");
        return 0;
    }
    if (!(cap->power < N_POWERS || cap->power == NATION_ID)) {
        set_why(why, why_len, "%s", "The chosen capital has no valid sovereign.");
        return 0;
    }
    return 1;
}

int core_found(NationState *s, const World *w, const Config *c, int capital,
               const char *name, const char *adjective, int title, int flag,
               Effects *out, char *why, int why_len)
{
    if (!core_can_found(s, w, c, capital, why, why_len)) return 0;
    if (!name || !name[0] || name[0] == ' ') {
        set_why(why, why_len, "%s", "Enter a name for the nation.");
        return 0;
    }

    /* §11.5 steps 3-6 on a private copy; committed only if everything fits */
    NationState n = *s;
    Effects fx;
    memset(&fx, 0, sizeof fx);
    const TownSnap *cap = &w->town[capital];
    int former = town_prior_power(cap);
    uint32_t day = w->day;

    n.founded = 1;
    copy_name(n.name, name);
    copy_name(n.adjective, (adjective && adjective[0]) ? adjective : name);
    if (!n.name[0]) {
        set_why(why, why_len, "%s", "Enter a name for the nation.");
        return 0;
    }
    n.title = (uint8_t)title_index(title);
    n.flag = (uint8_t)clampi(flag, 0, 255);
    n.capital = (uint8_t)capital;
    n.host_power = (uint8_t)former;
    n.default_tax_pct = DEFAULT_TAX_PCT;
    n.tariff_pct = 0;
    n.stability = START_STABILITY;
    n.government = 0;
    n.treasury = 0;                 /* no money without economic cause (§5.3) */
    n.founded_day = day;
    n.last_month_day = day;
    n.last_tax_income = n.last_upkeep = n.last_tariff_income = 0;

    TownState *ts = &n.town[capital];
    memset(ts, 0, sizeof *ts);
    ts->member = 1;
    ts->prior_power = (uint8_t)former;
    ts->loyalty = CAPITAL_LOYALTY;
    ts->tax_pct = TAX_USE_DEFAULT;
    ts->joined_day = day;
    ts->permit_before = cap->permit ? PERMIT_HAD : PERMIT_HAD_NONE;

    for (int p = 0; p < N_POWERS; p++) {
        Relation *r = &n.rel[p];
        memset(r, 0, sizeof *r);
        r->last_change_day = day;
        if (p == former) {
            r->score = FORMER_SOVEREIGN_SCORE;
            r->status = w->reputation[p] < FORMER_SOV_WAR_REP ? TREATY_WAR : TREATY_PEACE;
        } else {
            int sc = (w->reputation[p] - 50) / 2;
            if (w->power_war[p][former] || w->power_war[former][p]) sc += 15;   /* enemy of my enemy */
            r->score = (int16_t)clampi(sc, -100, 100);
            r->status = TREATY_PEACE;
        }
    }

    /* §11.5 step 7: adapter effects; step 9: event last */
    fx_add(&fx, FX_TOWN_TO_NATION, capital, former, 0);
    if (!cap->permit) fx_add(&fx, FX_PERMIT, capital, 1, 0);   /* build in your own capital */
    for (int p = 0; p < N_POWERS; p++)
        fx_add(&fx, FX_SET_WAR, p, n.rel[p].status == TREATY_WAR, 0);
    fx_rep(&fx, former, FOUNDING_REP_PENALTY, "the nation declared its independence from it");
    for (int p = 0; p < N_POWERS; p++)
        trace("REL %s score %d (founding: %s)", k_power_name[p], n.rel[p].score,
              p == former ? "the former sovereign of the capital" : "reputation and its wars");
    fx_msg(&fx, "%s has declared its independence from %s! Its flag now flies over town %d. "
           "You may build there without a permit.", n.name, k_power_name[former], capital);
    if (n.rel[former].status == TREATY_WAR)
        fx_msg(&fx, "%s refuses to accept the secession and declares war on %s.",
               k_power_name[former], n.name);
    else
        fx_msg(&fx, "The %s crown condemns the secession; relations are hostile.", k_power_adj[former]);

    if (!fx_room(out, fx.n)) {
        set_why(why, why_len, "%s", "Internal error: effect queue full; nothing was changed.");
        return 0;
    }
    *s = n;                                         /* commit */
    for (int i = 0; out && i < fx.n; i++) out->fx[out->n++] = fx.fx[i];
    set_why(why, why_len, "%s", "");
    return 1;
}

/* ------------------------------------------------------------------------ */
/* territory (§4)                                                           */
/* ------------------------------------------------------------------------ */
int core_annex(NationState *s, const World *w, int town, int reason, Effects *out)
{
    if (!s->founded || !town_ok(w, town) || town >= MAX_TOWNS || s->town[town].member) return 0;
    const TownSnap *snap = &w->town[town];
    if (snap->is_viceroy_seat) return 0;           /* viceroy seats stay with their power */
    if (reason < 0 || reason > 2) return 0;
    if (!fx_room(out, 4 + N_POWERS)) return 0;

    int prior = town_prior_power(snap);
    /* conquest needs a war: a won battle in peacetime is no title to the town */
    if (reason == 0 && prior < N_POWERS && s->rel[prior].status != TREATY_WAR) return 0;
    TownState *ts = &s->town[town];
    memset(ts, 0, sizeof *ts);
    ts->member = 1;
    ts->prior_power = (uint8_t)prior;
    ts->loyalty = (uint8_t)(reason == 0 ? (gov_is(s, GOV_PIRATE_REPUBLIC) ? 20 : 30) : reason == 1 ? 50 : 70);
    ts->tax_pct = TAX_USE_DEFAULT;
    ts->joined_day = w->day;
    ts->conquered = reason == 0;
    ts->permit_before = snap->permit ? PERMIT_HAD : PERMIT_HAD_NONE;

    fx_add(out, FX_TOWN_TO_NATION, town, prior, 0);
    if (!snap->permit) fx_add(out, FX_PERMIT, town, 1, 0);
    if (reason == 0) {
        add_score(s, prior, -15, "the nation conquered one of its towns");
        for (int p = 0; p < N_POWERS; p++)
            if (p != prior && s->rel[p].status != TREATY_WAR) add_score(s, p, -3, "the nation conquered a town");
        add_stability(s, -3);
    } else if (reason == 2) {
        add_score(s, prior, -10, "one of its towns joined the nation by petition");
    }
    if (!has_capital(s)) {
        s->capital = (uint8_t)town;
        fx_msg(out, "%s establishes its new capital in town %d.", s->name, town);
    }
    fx_msg(out, "Town %d (formerly %s) has joined %s%s. You may now build there.", town, k_power_name[prior],
           s->name, reason == 0 ? " by conquest" : reason == 1 ? " by treaty" : " by petition");
    return 1;
}

int core_permit_sync(NationState *s, const World *w, Effects *out)
{
    if (!s->founded) return 0;
    int added = 0;
    for (int t = 0; t < n_towns(w) && t < MAX_TOWNS; t++) {
        TownState *ts = &s->town[t];
        if (!ts->member || !w->town[t].exists) continue;
        if (ts->permit_before != PERMIT_HAD && ts->permit_before != PERMIT_HAD_NONE)
            ts->permit_before = w->town[t].permit ? PERMIT_HAD : PERMIT_HAD_NONE;   /* older save */
        if (w->town[t].permit || !fx_room(out, 1)) continue;
        fx_add(out, FX_PERMIT, t, 1, 0);
        added++;
    }
    return added;
}

int core_relocate_capital(NationState *s, const World *w, Effects *out)
{
    if (!s->founded) return 0;
    if (has_capital(s)) return 1;
    int best = -1;
    uint32_t best_pop = 0;
    for (int t = 0; t < n_towns(w); t++) {
        if (!s->town[t].member || !w->town[t].exists) continue;
        if (best < 0 || w->town[t].population > best_pop) { best = t; best_pop = w->town[t].population; }
    }
    if (best >= 0) {
        s->capital = (uint8_t)best;
        add_stability(s, -10);
        fx_msg(out, "The capital of %s has fallen! The government relocates to town %d.",
               s->name, best);
        return 1;
    }
    s->capital = CAPITAL_NONE;
    add_stability(s, -30);
    fx_msg(out, "%s has lost its last territory and governs in exile.", s->name);
    return 0;
}

int core_lose_town(NationState *s, const World *w, int town, int new_power, Effects *out)
{
    if (!s->founded || !is_member(s, town) || !power_ok(new_power)) return 0;
    if (!fx_room(out, 5)) return 0;
    TownState *ts = &s->town[town];
    if (in_unrest(ts)) fx_add(out, FX_TOWN_UNREST, town, 0, 0);
    int before = ts->permit_before;
    memset(ts, 0, sizeof *ts);
    ts->tax_pct = TAX_USE_DEFAULT;
    fx_add(out, FX_TOWN_TO_POWER, town, new_power, 0);
    /* the permit goes back to what it was before the town joined; the
       player's buildings stay, as in vanilla when a permit is given up */
    int held = town < n_towns(w) && w->town[town].permit;
    if (before == PERMIT_HAD_NONE && held) fx_add(out, FX_PERMIT, town, 0, 0);
    else if (before == PERMIT_HAD && !held) fx_add(out, FX_PERMIT, town, 1, 0);
    add_stability(s, -8);
    fx_msg(out, "Town %d has been lost to %s.", town, k_power_name[new_power]);
    if (s->capital == town) {
        s->capital = CAPITAL_NONE;
        core_relocate_capital(s, w, out);
    }
    return 1;
}

/* ------------------------------------------------------------------------ */
/* diplomacy (§6)                                                           */
/* ------------------------------------------------------------------------ */
int core_acceptance_chance(const NationState *s, const World *w, int power, Treaty t)
{
    if (!s->founded || !power_ok(power)) return 0;
    const Relation *r = &s->rel[power];
    int ratio = strength_ratio(s, w, power);
    int st = strength_term(ratio);
    int wars = power_wars(w, power);
    int rep = w->reputation[power];
    int weak = (s->treasury < 0 ? -10 : 0) + (s->stability < 30 ? -10 : 0);
    int unrec = r->recognized ? 0 : -15;
    int c;
    switch (t) {
    case TREATY_WAR:
        return 100;
    case TREATY_CEASEFIRE:
        if (r->status != TREATY_WAR) return 0;
        if (r->expiry_day && w->day <= r->expiry_day) return 100;      /* AI offer pending */
        c = 15 + r->score / 4 + r->war_exhaustion * 6 / 10 + wars * 10 + st;
        if (days_since(w->day, r->last_change_day) < 30) c -= 30;
        break;
    case TREATY_PEACE:
        if (r->status == TREATY_WAR) return 0;
        if (r->status != TREATY_CEASEFIRE) return 100;                  /* dissolving a treaty */
        c = 40 + r->score / 3 + r->war_exhaustion / 3 + wars * 5 + st / 2 + weak;
        break;
    case TREATY_TRADE:
    case TREATY_NONAGGRESSION:
    case TREATY_ALLIANCE:
        if (r->status == TREATY_WAR || r->status == TREATY_CEASEFIRE) return 0;
        if ((int)t < (int)r->status) return 100;                        /* downgrade */
        if (t == TREATY_TRADE) {
            if (r->status == TREATY_PEACE && r->expiry_day && w->day <= r->expiry_day) return 100;
            c = 25 + r->score / 2 + (rep - 50) / 2 + unrec + weak;
        } else if (t == TREATY_NONAGGRESSION) {
            c = 15 + r->score / 2 + st + wars * 10 + unrec + weak;
        } else {
            if (r->score < 60 || !r->recognized) return 0;
            c = 20 + (r->score - 60) + common_enemies(s, w, power) * 25 + st + weak;
        }
        break;
    default:
        return 0;
    }
    c += accept_mod(s, core_ai_strategy(s, w, power), t);
    return clampi(c, 0, 100);
}

int core_declare_war(NationState *s, const World *w, int power, Effects *out)
{
    if (!s->founded || !power_ok(power)) return 0;
    Relation *r = &s->rel[power];
    if (r->status == TREATY_WAR) return 0;
    if (!fx_room(out, 3 + N_POWERS)) return 0;

    Treaty prev = r->status;
    int treaty_break = prev == TREATY_TRADE || prev == TREATY_NONAGGRESSION ||
                       prev == TREATY_ALLIANCE || prev == TREATY_CEASEFIRE;
    int unprovoked = r->recognized && r->score > -30;

    int old_score = r->score;
    r->status = TREATY_WAR;
    r->score = (int16_t)clampi(mini(r->score - 50, DECLARE_WAR_SCORE), -100, 100);
    trace("REL %s score %d -> %d (%+d: the nation declared war on it)", k_power_name[power], old_score, r->score,
          r->score - old_score);
    r->expiry_day = 0;
    r->last_change_day = w->day;
    r->threat = THREAT_NONE;
    fx_add(out, FX_SET_WAR, power, 1, 0);
    fx_rep(out, power, -10, "the nation declared war on it");

    for (int q = 0; q < N_POWERS; q++) {
        if (q == power) continue;
        if (w->power_war[q][power] || w->power_war[power][q]) {
            add_score(s, q, 10, "the nation declared war on its enemy");   /* their enemy is our enemy */
        } else if (unprovoked || treaty_break) {
            add_score(s, q, treaty_break ? -15 : -10, treaty_break ? "the nation broke a treaty to declare war"
                                                               : "the nation declared war without provocation");
            fx_rep(out, q, -5, treaty_break ? "the nation broke a treaty to declare war on another power"
                                            : "the nation declared war on another power without provocation");
        }
    }
    if (treaty_break) add_stability(s, -15);
    else if (unprovoked) add_stability(s, -10);
    fx_msg(out, "%s has declared war on %s%s.", s->name, k_power_name[power],
           treaty_break ? ", breaking a treaty" : unprovoked ? " without provocation" : "");
    return 1;
}

int core_propose(NationState *s, const World *w, int power, Treaty t, Effects *out,
                 char *why, int why_len)
{
    set_why(why, why_len, "%s", "");
    if (!s->founded) { set_why(why, why_len, "%s", "You have not founded a nation."); return 0; }
    if (!power_ok(power)) { set_why(why, why_len, "%s", "Unknown power."); return 0; }
    if ((int)t < (int)TREATY_PEACE || (int)t > (int)TREATY_CEASEFIRE) {
        set_why(why, why_len, "%s", "Unknown treaty."); return 0;
    }
    if (t == TREATY_WAR) {
        if (core_declare_war(s, w, power, out)) return 1;
        set_why(why, why_len, "Already at war with %s.", k_power_name[power]);
        return 0;
    }
    Relation *r = &s->rel[power];
    const char *pn = k_power_name[power];
    if (t == r->status) { set_why(why, why_len, "%s with %s is already in effect.", k_treaty[t], pn); return 0; }
    if (t == TREATY_PEACE && r->status == TREATY_WAR) {
        set_why(why, why_len, "A ceasefire with %s must be agreed before peace.", pn); return 0;
    }
    if (t == TREATY_CEASEFIRE && r->status != TREATY_WAR) {
        set_why(why, why_len, "You are not at war with %s.", pn); return 0;
    }
    if (t != TREATY_PEACE && t != TREATY_CEASEFIRE &&
        (r->status == TREATY_WAR || r->status == TREATY_CEASEFIRE)) {
        set_why(why, why_len, "Make peace with %s first.", pn); return 0;
    }
    if (t == TREATY_ALLIANCE && r->score < 60) {
        set_why(why, why_len, "An alliance requires a relation of at least 60 (now %d).", r->score); return 0;
    }
    if (t == TREATY_ALLIANCE && !r->recognized) {
        set_why(why, why_len, "%s has not recognized your nation.", pn); return 0;
    }
    if (!fx_room(out, 2)) { set_why(why, why_len, "%s", "Effect queue full."); return 0; }

    int chance = core_acceptance_chance(s, w, power, t);
    if (roll100(w->day, power, 100 + (int)t) >= chance) {
        add_score(s, power, -2, "a proposal it rejected");   /* repeated demands annoy */
        set_why(why, why_len, "%s rejects the %s (chance was %d%%).", pn, k_treaty[t], chance);
        return 0;
    }

    Treaty prev = r->status;
    int downgrade = (int)t < (int)prev && prev != TREATY_WAR && prev != TREATY_CEASEFIRE;
    r->status = t;
    r->last_change_day = w->day;
    switch (t) {
    case TREATY_CEASEFIRE:
        r->expiry_day = w->day + CEASEFIRE_DAYS;
        add_score(s, power, 5, "ceasefire agreed");
        fx_add(out, FX_SET_WAR, power, 0, 0);
        break;
    case TREATY_PEACE:
        r->expiry_day = 0;
        if (prev == TREATY_CEASEFIRE) { add_score(s, power, 10, "peace agreed"); fx_add(out, FX_SET_WAR, power, 0, 0); }
        else add_score(s, power, -5, "the nation dissolved a treaty");
        break;
    default:   /* trade / non-aggression / alliance */
        r->expiry_day = t == TREATY_ALLIANCE ? 0 : w->day + TREATY_DAYS;
        add_score(s, power, downgrade ? -5 : 5, downgrade ? "treaty reduced" : "treaty agreed");
        break;
    }
    fx_msg(out, "%s and %s: %s%s.", pn, s->name, k_treaty[t],
           downgrade ? " (treaty reduced)" : " agreed");
    return 1;
}

/* ------------------------------------------------------------------------ */
/* treasury (§5)                                                            */
/* ------------------------------------------------------------------------ */
int core_donate(NationState *s, const World *w, int64_t amount, Effects *out)
{
    if (!s->founded || amount <= 0 || amount > w->player_gold || amount > TREASURY_LIMIT) return 0;
    if (!fx_room(out, 1)) return 0;
    book(s, LG_DONATION, amount);
    fx_add(out, FX_PLAYER_GOLD, 0, 0, -amount);
    return 1;
}

int core_withdraw(NationState *s, const World *w, int64_t amount, Effects *out)
{
    (void)w;
    if (!s->founded || amount <= 0 || s->treasury <= 0) return 0;
    if (amount > s->treasury / 2 || s->stability < 25) return 0;   /* restricted (§5.2) */
    if (!fx_room(out, 2)) return 0;
    int cost = 2 + (int)(amount * 20 / s->treasury);
    book(s, LG_WITHDRAWAL, -amount);
    add_stability(s, -cost);
    fx_add(out, FX_PLAYER_GOLD, 0, 0, amount);
    fx_msg(out, "%lld gold transferred from the national treasury to you; stability -%d.",
           (long long)amount, cost);
    return 1;
}

void core_set_tax(NationState *s, int town, int pct)
{
    if (town < 0) {
        s->default_tax_pct = (uint8_t)clampi(pct, 0, HARD_MAX_TAX);
    } else if (town < MAX_TOWNS) {
        s->town[town].tax_pct = (pct < 0 || pct == TAX_USE_DEFAULT) ? TAX_USE_DEFAULT
                                                                    : (uint8_t)clampi(pct, 0, HARD_MAX_TAX);
    }
}

int core_set_government(NationState *s, const World *w, int gov, Effects *out, char *why, int why_len)
{
    (void)w;
    set_why(why, why_len, "%s", "");
    if (!s->founded) { set_why(why, why_len, "%s", "You have not founded a nation."); return 0; }
    if (gov < 0 || gov >= GOV_COUNT) { set_why(why, why_len, "%s", "Unknown form of government."); return 0; }
    if (gov == core_government(s)) {
        set_why(why, why_len, "%s already is %s %s.", s->name, core_article(k_gov_name[gov], 0), k_gov_name[gov]); return 0;
    }
    if (core_government_cooldown(s) > 0) {
        set_why(why, why_len, "Another constitutional reform is possible in %d months.",
                core_government_cooldown(s));
        return 0;
    }
    if (s->stability < GOV_CHANGE_MIN_STAB) {
        set_why(why, why_len, "The nation is too unstable for a reform (stability %d, needs %d).",
                s->stability, GOV_CHANGE_MIN_STAB);
        return 0;
    }
    if (!fx_room(out, 1)) { set_why(why, why_len, "%s", "Effect queue full."); return 0; }
    s->government = (uint8_t)(gov | (GOV_COOLDOWN_MONTHS << GOV_COOLDOWN_SHIFT));
    add_stability(s, -GOV_CHANGE_STABILITY);
    if (gov == GOV_PIRATE_REPUBLIC)                 /* the powers take note at once */
        for (int p = 0; p < N_POWERS; p++) add_score(s, p, -10, "the nation became a Pirate Republic");
    fx_msg(out, "%s adopts a new constitution and becomes %s %s (stability -%d).", s->name,
           core_article(k_gov_name[gov], 0),
           k_gov_name[gov], GOV_CHANGE_STABILITY);
    return 1;
}

/* ------------------------------------------------------------------------ */
/* simulation (§11.6)                                                       */
/* ------------------------------------------------------------------------ */
static void daily_loyalty(NationState *s, const World *w)
{
    for (int t = 0; t < n_towns(w); t++) {
        TownState *ts = &s->town[t];
        if (!ts->member || !w->town[t].exists) continue;
        int tgt = loyalty_target(s, w, t);
        if (ts->loyalty < tgt) ts->loyalty++;
        else if (ts->loyalty > tgt) ts->loyalty--;
    }
}

static void daily_treaties(NationState *s, const World *w, Effects *out)
{
    for (int p = 0; p < N_POWERS; p++) {
        Relation *r = &s->rel[p];
        if (!r->expiry_day || w->day < r->expiry_day) continue;
        switch (r->status) {
        case TREATY_CEASEFIRE:
            if (!fx_room(out, 2)) break;
            r->status = TREATY_PEACE;
            r->expiry_day = 0;
            r->last_change_day = w->day;
            fx_add(out, FX_SET_WAR, p, 0, 0);
            fx_msg(out, "The ceasefire with %s has expired; peace holds.", k_power_name[p]);
            break;
        case TREATY_WAR:
        case TREATY_PEACE:
            if (w->day > r->expiry_day) r->expiry_day = 0;        /* pending AI offer lapsed */
            break;
        case TREATY_TRADE:
        case TREATY_NONAGGRESSION:
            if (r->score >= (r->status == TREATY_TRADE ? 0 : 10)) {
                r->expiry_day = w->day + TREATY_DAYS;              /* silent renewal */
            } else if (fx_room(out, 1)) {
                fx_msg(out, "The %s with %s has lapsed.", k_treaty[r->status], k_power_name[p]);
                r->status = TREATY_PEACE;
                r->expiry_day = 0;
                r->last_change_day = w->day;
            }
            break;
        default:
            r->expiry_day = 0;
            break;
        }
    }
}

/* §6: the relation a power drifts towards every month, with its terms ("rep 23: -13, ...") */
int core_relation_target(const NationState *s, const World *w, int p, char *why, int why_len)
{
    if (why && why_len > 0) why[0] = 0;
    if (!power_ok(p)) return 0;
    const Relation *r = &s->rel[p];
    int gov = core_government(s);
    int t_rep = (w->reputation[p] - 50) / 2, t_rec = r->recognized ? 10 : 0;
    int t_treaty = k_treaty_score_bonus[clampi((int)r->status, 0, 5)];
    int t_tariff = -(s->tariff_pct / 2), t_common = common_enemies(s, w, p) * 10;
    int t_host = p == s->host_power ? -20 : 0, t_pirate = gov == GOV_PIRATE_REPUBLIC ? -10 : 0;
    int tgt = clampi(t_rep + t_rec + t_treaty + t_tariff + t_common + t_host + t_pirate, -100, 100);
    if (why && why_len > 0) {
        int o = snprintf(why, why_len, "reputation %d: %+d", w->reputation[p], t_rep);
        if (t_rec && o < why_len) o += snprintf(why + o, why_len - o, ", recognition %+d", t_rec);
        if (t_treaty && o < why_len) o += snprintf(why + o, why_len - o, ", %s %+d", k_treaty[r->status], t_treaty);
        if (t_tariff && o < why_len) o += snprintf(why + o, why_len - o, ", tariff %d%% %+d", s->tariff_pct, t_tariff);
        if (t_common && o < why_len) o += snprintf(why + o, why_len - o, ", common enemies %+d", t_common);
        if (t_host && o < why_len) o += snprintf(why + o, why_len - o, ", former sovereign of the capital %+d", t_host);
        if (t_pirate && o < why_len) snprintf(why + o, why_len - o, ", Pirate Republic %+d", t_pirate);
    }
    return tgt;
}

static void navy_month(NationState *s, const World *w, const Config *c, Effects *out);
static void petition_month(NationState *s, const World *w, Effects *out);

/* what a month end books, by category (signed: income > 0, spending < 0) */
static void month_end_sums(const NationState *s, const World *w, const Config *c, int64_t v[LEDGER_CATS])
{
    int members = 0;
    int64_t towers = 0;
    memset(v, 0, sizeof(int64_t) * LEDGER_CATS);
    for (int t = 0; t < MAX_TOWNS; t++) {
        if (!s->town[t].member) continue;
        members++;
        towers += s->navy.towers_bought[t];
        if (t >= n_towns(w) || !w->town[t].exists) continue;
        v[LG_TAX] += town_tax(s, w, t, c->max_tax_pct);
        v[LG_TARIFF] += town_tariff(s, w, t);
    }
    int gov = core_government(s);
    int64_t upkeep = (int64_t)members * c->upkeep_per_town;
#if NATION_CONVOYS
    upkeep += (int64_t)s->national_convoys * c->upkeep_per_convoy;
#endif
    if (gov == GOV_COLONIAL_MONARCHY) upkeep = upkeep * 5 / 4;          /* court and garrisons */
    v[LG_ADMIN] = -upkeep;
    if (gov == GOV_PIRATE_REPUBLIC)                                     /* privateering (§5.5) */
        for (int p = 0; p < N_POWERS; p++)
            if (s->rel[p].status == TREATY_WAR)
                v[LG_PRIVATEER] += (int64_t)mini(PLUNDER_CAP, w->player_warships * PLUNDER_PER_WARSHIP)
                                   * (100 - s->rel[p].war_exhaustion) / 100;
    v[LG_FLEET_UPKEEP] = -(int64_t)w->nation_fleets * c->fleet_upkeep;  /* = core_military_upkeep() */
    v[LG_TOWER_UPKEEP] = -towers * c->tower_upkeep;
}

static void settle_month(NationState *s, const World *w, const Config *c, Effects *out)
{
    int loy_sum = 0, loy_n = 0, recent_conq = 0;
    for (int t = 0; t < MAX_TOWNS; t++) {
        TownState *ts = &s->town[t];
        if (!ts->member || t >= n_towns(w) || !w->town[t].exists) continue;
        loy_sum += ts->loyalty; loy_n++;
        if (ts->conquered && days_since(w->day, ts->joined_day) < 180) recent_conq++;
    }
    int gov = core_government(s);
    int64_t v[LEDGER_CATS];
    month_end_sums(s, w, c, v);
    int64_t tax = v[LG_TAX], tariff = v[LG_TARIFF], plunder = v[LG_PRIVATEER], upkeep = -v[LG_ADMIN];
    int64_t military = -(v[LG_FLEET_UPKEEP] + v[LG_TOWER_UPKEEP]), net = 0;
    for (int k = 0; k < LEDGER_CATS; k++) {
        net += v[k];
        if (v[k]) book(s, k, v[k]);
    }
    memcpy(s->ledger.month[0], s->ledger.month[1], sizeof s->ledger.month[0]);   /* the month is closed */
    memset(s->ledger.month[1], 0, sizeof s->ledger.month[1]);
    s->navy.last_military = to_i32(military);
    s->last_tax_income = to_i32(tax);
    s->last_tariff_income = to_i32(tariff);
    s->last_upkeep = to_i32(upkeep);
    if (core_government_cooldown(s) > 0) s->government = (uint8_t)(s->government - (1 << GOV_COOLDOWN_SHIFT));

    /* war exhaustion and relation drift (§6) */
    for (int p = 0; p < N_POWERS; p++) {
        Relation *r = &s->rel[p];
        r->war_exhaustion = (uint8_t)clampi(r->war_exhaustion + (r->status == TREATY_WAR ? 6 : -10), 0, 100);
        char why[200];
        int tgt = core_relation_target(s, w, p, why, sizeof why);
        char cause[260];
        snprintf(cause, sizeof cause, "monthly drift towards %d = %s", tgt, why);
        if (r->score < tgt) add_score(s, p, mini(2, tgt - r->score), cause);
        else if (r->score > tgt) add_score(s, p, -mini(2, r->score - tgt), cause);
    }

    /* stability (§9) */
    int tgt = 50 + (s->treasury >= 0 ? 5 : -20) + (net >= 0 ? 5 : -5);
    if (loy_n) tgt += (loy_sum / loy_n - 50) / 2;
    if (s->default_tax_pct > 15) tgt -= (s->default_tax_pct - 15) / 2;
    int war_base = gov == GOV_MERCHANT_REPUBLIC ? 9 : gov == GOV_PIRATE_REPUBLIC ? 2 : 5;
    for (int p = 0; p < N_POWERS; p++) {
        if (s->rel[p].status == TREATY_WAR) tgt -= war_base + s->rel[p].war_exhaustion / 10;
        if (s->rel[p].recognized) tgt += 2;
    }
    if (gov == GOV_COLONIAL_MONARCHY) tgt += 8;
    tgt -= mini(20, recent_conq * 4);
    if (!has_capital(s)) tgt = mini(tgt, 10);
    tgt = clampi(tgt, 0, 100);
    if (s->stability < tgt) add_stability(s, mini(5, tgt - s->stability));
    else if (s->stability > tgt) add_stability(s, -mini(5, s->stability - tgt));

    /* unrest (§4.4): loyalty < 20 (Federation 15) at two consecutive month ends;
       once open, the count keeps running until loyalty recovers to 30.
       Rebellion (§9): open unrest still present SECESSION_MONTHS month ends
       after the outbreak -> a member town secedes to its prior power; the
       capital never secedes but riots (stability crash every such month). */
    int secede_at = UNREST_MONTHS + secession_months(s);
    for (int t = 0; t < n_towns(w); t++) {
        TownState *ts = &s->town[t];
        if (!ts->member || !w->town[t].exists) continue;
        int low = ts->loyalty < unrest_threshold(s);
        if (low || (in_unrest(ts) && ts->loyalty < UNREST_RECOVER)) {
            if (low && ts->unrest + 1 == UNREST_MONTHS) {
                if (!fx_room(out, 2)) continue;                 /* retried next month */
                fx_add(out, FX_TOWN_UNREST, t, 1, 0);
                fx_msg(out, "Unrest has broken out in town %d (loyalty %d).", t, ts->loyalty);
            }
            if (ts->unrest < 255) ts->unrest++;
            if (ts->unrest < secede_at) continue;
            if (t == s->capital) {
                add_stability(s, -CAPITAL_RIOT_STABILITY);
                fx_msg(out, "Riots paralyse the capital (town %d); the government totters (stability -%d).",
                       t, CAPITAL_RIOT_STABILITY);
            } else if (fx_room(out, 6)) {
                int prior = power_ok(ts->prior_power) ? ts->prior_power : 0;
                fx_msg(out, "After %d months of unrest, town %d secedes from %s and returns to %s rule.",
                       ts->unrest - UNREST_MONTHS, t, s->name, k_power_adj[prior]);
                int st0 = s->stability;
                if (core_lose_town(s, w, t, prior, out))   /* -8 there; total SECESSION_STABILITY */
                    add_stability(s, -(SECESSION_STABILITY - (st0 - s->stability)));
            }
        } else if (in_unrest(ts)) {
            if (fx_room(out, 2)) {
                fx_add(out, FX_TOWN_UNREST, t, 0, 0);
                fx_msg(out, "Order has been restored in town %d.", t);
                ts->unrest = 0;
            }
        } else {
            ts->unrest = 0;
        }
    }

    if (s->treasury < 0) {
        add_stability(s, -3);
        fx_msg(out, "The national treasury is insolvent (%lld gold); stability suffers.",
               (long long)s->treasury);
    }
    if (plunder > 0)
        fx_msg(out, "Monthly accounts: taxes %+lld, tariffs %+lld, privateering %+lld, upkeep -%lld, treasury %lld.",
               (long long)tax, (long long)tariff, (long long)plunder, (long long)upkeep, (long long)s->treasury);
    else if (military > 0)
        fx_msg(out, "Monthly accounts: taxes %+lld, tariffs %+lld, upkeep -%lld, navy and forts -%lld, treasury %lld.",
               (long long)tax, (long long)tariff, (long long)upkeep, (long long)military, (long long)s->treasury);
    else
        fx_msg(out, "Monthly accounts: taxes %+lld, tariffs %+lld, upkeep -%lld, treasury %lld.",
               (long long)tax, (long long)tariff, (long long)upkeep, (long long)s->treasury);
    navy_month(s, w, c, out);
    petition_month(s, w, out);
}

/* per-strategy weights of the AI decisions (§10); index = AiStrategy */
typedef struct {
    int war_score;      /* declares war only at relation <= this (-999 = never) */
    int war_ratio;      /* ... and player/power strength ratio below this */
    int war_exh;        /* ... and war exhaustion below this (hard-capped by AI_WAR_MAX_EXHAUSTION) */
    int war_bonus;      /* added to the war chance */
    int trade_score, trade_rep, trade_ch;   /* trade-offer thresholds / chance */
    int recog_bonus;    /* added to the recognition chance */
    int cancel_shift;   /* added to the treaty-cancel floors */
    int cf_exh, cf_bonus;                   /* ceasefire-offer exhaustion threshold / chance bonus */
} StratWeights;

static const StratWeights k_strat[AI_STRAT_COUNT] = {
    /* COMMERCIAL    */ { -60, 100, 30, -15,  15, 50, 35,  10, -10, 40,   5 },
    /* EXPANSIONIST  */ { -30, 100, 50,  15,  30, 60, 10,   0,  10, 40, -10 },
    /* DEFENSIVE     */ {-999,   0,  0,   0,  25, 55, 25,   5,   0, 25,  20 },
    /* OPPORTUNISTIC */ { -20, 150, 50,  20,  30, 60, 10, -10,  10, 40, -10 },
};

/* the AI's war warning (Relation.threat): evaluations since it was given, 0 = none */
static int threat_evals(const Relation *r)
{
    return r->threat > THREAT_BASE && r->threat <= THREAT_BASE + THREAT_EVALS ? r->threat - THREAT_BASE : 0;
}

/* why a power thinks the moment is right, in words for the warning (", and it sees ...") */
static void threat_reason(const NationState *s, const World *w, int p, int strat, char *out, int cap)
{
    out[0] = 0;
    if (strat == AI_STRAT_OPPORTUNISTIC) {
        int enemy = -1;
        for (int q = 0; q < N_POWERS; q++)
            if (q != p && s->rel[q].status == TREATY_WAR && enemy < 0) enemy = q;
        if (s->treasury < 0) snprintf(out, cap, ", and it sees the nation's treasury empty");
        else if (s->stability < 35) snprintf(out, cap, ", and it sees the nation unstable (stability %d)", s->stability);
        else if (enemy >= 0) snprintf(out, cap, ", and it sees the nation tied up in its war with %s", k_power_name[enemy]);
    } else if (strat == AI_STRAT_EXPANSIONIST) {
        snprintf(out, cap, ", and it is far stronger than the nation (strength %d%%)", strength_ratio(s, w, p));
    }
}

static void ai_evaluate(NationState *s, const World *w, Effects *out)
{
    uint32_t day = w->day;
    int months = (int)(days_since(day, s->founded_day) / MONTH_DAYS);
    int members = core_member_count(s);
    for (int p = 0; p < N_POWERS; p++) {
        Relation *r = &s->rel[p];
        const char *pn = k_power_name[p];
        if (!fx_room(out, 3)) return;
        int ratio = strength_ratio(s, w, p);
        int wars = power_wars(w, p);
        int rep = w->reputation[p];
        uint32_t since = days_since(day, r->last_change_day);
        const StratWeights *k = &k_strat[core_ai_strategy(s, w, p)];

        /* recognition: independent of war (§6.1), grows with time */
        if (!r->recognized && months >= 3 && members > 0 && r->score >= -20) {
            int ch = clampi(5 + r->score / 5 + months * 2 + members * 2 + (s->stability - 50) / 5
                            - (r->status == TREATY_WAR ? 20 : 0) + k->recog_bonus, 0, 50);
            if (roll100(day, p, 1) < ch) {
                r->recognized = 1;
                add_score(s, p, 5, "it recognized the nation");
                fx_msg(out, "%s formally recognizes %s as a sovereign nation.", pn,
                       s->name);
            }
        }
        if (r->status != TREATY_PEACE) r->threat = THREAT_NONE;   /* a warning is about breaking the peace */
        if (r->last_change_day == day) continue;      /* at most one treaty change per day */

        switch (r->status) {
        case TREATY_PEACE:
            /* bounds: one AI war per power per AI_WAR_COOLDOWN_DAYS (every exit from a
               war is itself a treaty change), never above AI_WAR_MAX_EXHAUSTION */
            if (r->score <= k->war_score && ratio < k->war_ratio && since >= AI_WAR_COOLDOWN_DAYS &&
                wars < 2 && r->war_exhaustion < mini(k->war_exh, AI_WAR_MAX_EXHAUSTION + 1)) {
                int ch = clampi((-r->score - 30) + (100 - ratio) / 2 - wars * 15 - (rep - 50) / 2
                                + k->war_bonus, 0, 60);
                int strat = core_ai_strategy(s, w, p), warned = threat_evals(r);
                char head[240];
                snprintf(head, sizeof head, "AI %s (%s, day %u): score %d <= %d, strength ratio %d < %d, %u days "
                         "since the last treaty change, %d other wars, exhaustion %d, reputation %d: war chance %d",
                         pn, core_ai_strategy_name(strat), day, r->score, k->war_score, ratio, k->war_ratio, since,
                         wars, r->war_exhaustion, rep, ch);
                if (!warned) {
                    /* never out of nowhere: first a warning that names the causes */
                    char why[200], reason[96];
                    int tgt = core_relation_target(s, w, p, why, sizeof why);
                    threat_reason(s, w, p, strat, reason, sizeof reason);
                    r->threat = THREAT_BASE + 1;
                    trace("%s -> WARNING (war possible after %d more evaluations)", head, THREAT_EVALS - 1);
                    fx_msg(out, "%s may declare war on %s: relations are %s (%d)%s.", pn, s->name,
                           r->score <= -50 ? "hostile" : "unfriendly", r->score, reason);   /* the Diplomacy page's words */
                    fx_msg(out, "Improve relations within a month to keep the peace. %s's view drifts towards %d "
                           "(%s).", pn, tgt, why);
                    break;
                }
                if (warned < THREAT_EVALS) {
                    r->threat = (uint8_t)(THREAT_BASE + warned + 1);
                    trace("%s -> warned %d evaluation(s) ago, no war yet", head, warned);
                    break;
                }
                int roll = roll100(day, p, 2);
                trace("%s, warned %d evaluations ago, roll %d -> %s", head, warned, roll, roll < ch ? "WAR" : "no war");
                if (roll < ch) {
                    r->status = TREATY_WAR;
                    r->expiry_day = 0;
                    r->last_change_day = day;
                    r->threat = THREAT_NONE;
                    add_score(s, p, -10, "it declared war on the nation");
                    fx_add(out, FX_SET_WAR, p, 1, 0);
                    fx_msg(out, "%s has declared war on %s!", pn, s->name);
                    break;
                }
            } else if (threat_evals(r) && r->score >= k->war_score + THREAT_EASE) {
                int strat = core_ai_strategy(s, w, p);
                r->threat = THREAT_NONE;
                trace("AI %s (%s, day %u): score %d >= %d -> the war warning lapses", pn, core_ai_strategy_name(strat),
                      day, r->score, k->war_score + THREAT_EASE);
                if (strat == AI_STRAT_DEFENSIVE) {          /* a defensive power never starts a war */
                    int other = -1;
                    for (int q = 0; q < N_POWERS; q++)
                        if (q != p && (w->power_war[p][q] || w->power_war[q][p]) && other < 0) other = q;
                    if (other >= 0)
                        fx_msg(out, "%s no longer threatens war on %s: it is at war with %s now.", pn, s->name,
                               k_power_name[other]);
                    else
                        fx_msg(out, "%s no longer threatens war on %s: it is on the defensive now.", pn, s->name);
                } else {
                    fx_msg(out, "Tension with %s eases (relations %d): it no longer threatens war.", pn, r->score);
                }
            }
            if (r->recognized && r->score >= k->trade_score && rep >= k->trade_rep && !r->expiry_day &&
                roll100(day, p, 3) < k->trade_ch + (gov_is(s, GOV_MERCHANT_REPUBLIC) ? 10 : 0)) {
                r->expiry_day = day + OFFER_DAYS;
                fx_msg(out, "%s proposes a trade agreement (offer open %d days).", pn, OFFER_DAYS);
            }
            break;
        case TREATY_TRADE:
        case TREATY_NONAGGRESSION:
        case TREATY_ALLIANCE: {
            int floor = (r->status == TREATY_TRADE ? -10 : r->status == TREATY_NONAGGRESSION ? -20 : 30)
                        + k->cancel_shift;
            if (r->score < floor) {
                fx_msg(out, "%s cancels the %s with %s.", pn, k_treaty[r->status],
                       s->name);
                r->status = TREATY_PEACE;
                r->expiry_day = 0;
                r->last_change_day = day;
            }
            break;
        }
        case TREATY_WAR:
            if (r->war_exhaustion >= 90 && since >= 360) {
                r->status = TREATY_CEASEFIRE;
                r->expiry_day = day + CEASEFIRE_DAYS;
                r->last_change_day = day;
                fx_add(out, FX_SET_WAR, p, 0, 0);
                fx_msg(out, "Exhausted by war, %s halts hostilities: ceasefire for %d days.", pn, CEASEFIRE_DAYS);
            } else if (!r->expiry_day && r->war_exhaustion > AI_EXHAUSTED && since >= 30) {
                r->expiry_day = day + OFFER_DAYS;            /* bound: must seek a ceasefire */
                fx_msg(out, "War-weary %s offers a ceasefire (open %d days).", pn, OFFER_DAYS);
            } else if (!r->expiry_day && since >= 60 &&
                       (r->war_exhaustion >= k->cf_exh || ratio >= 120 || wars >= 2)) {
                int ch = clampi(r->war_exhaustion + (ratio - 100) / 4 + wars * 10 + k->cf_bonus, 10, 90);
                if (roll100(day, p, 4) < ch) {
                    r->expiry_day = day + OFFER_DAYS;
                    fx_msg(out, "%s offers a ceasefire (open %d days).", pn, OFFER_DAYS);
                }
            }
            break;
        default:
            break;
        }
    }
}

void core_daily(NationState *s, const World *w, const Config *c, Effects *out)
{
    if (!s->founded) return;
    uint32_t day = w->day;

    /* towns the game now reports under a colonial power were lost */
    for (int t = 0; t < n_towns(w); t++)
        if (s->town[t].member && w->town[t].exists && w->town[t].power < N_POWERS)
            core_lose_town(s, w, t, w->town[t].power, out);
    core_permit_sync(s, w, out);           /* e.g. a permit given up at the master builder */

    if (day < s->last_month_day) s->last_month_day = day;          /* clock went back */
    for (int i = 0; i < MAX_CATCHUP_MONTHS && day >= s->last_month_day + MONTH_DAYS; i++) {
        settle_month(s, w, c, out);
        s->last_month_day += MONTH_DAYS;
    }
    if (day >= s->last_month_day + MONTH_DAYS) s->last_month_day = day;

    daily_treaties(s, w, out);
    daily_loyalty(s, w);

    int iv = c->ai_eval_interval_days > 0 ? c->ai_eval_interval_days : 7;
    uint32_t since = days_since(day, s->founded_day);
    if (since > 0 && since % (uint32_t)iv == 0) ai_evaluate(s, w, out);
}

/* ------------------------------------------------------------------------ */
/* persistence (§13)                                                        */
/* ------------------------------------------------------------------------ */
static uint32_t fnv1a(const uint8_t *p, size_t n)
{
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
    return h;
}

int core_serialize(const NationState *s, uint8_t *buf, int len)
{
    if (!buf || len < (int)sizeof(NationState)) return 0;
    NationState tmp;
    memcpy(&tmp, s, sizeof tmp);
    tmp.magic = NATION_MAGIC;
    tmp.version = NATION_STATE_VERSION;
    tmp.size = (uint16_t)sizeof(NationState);
    memcpy(buf, &tmp, sizeof tmp);
    uint32_t ck = fnv1a(buf, offsetof(NationState, checksum));
    memcpy(buf + offsetof(NationState, checksum), &ck, sizeof ck);
    uint32_t ck2 = fnv1a(buf + offsetof(NationState, navy), offsetof(NationState, navy.checksum2) - offsetof(NationState, navy));
    memcpy(buf + offsetof(NationState, navy.checksum2), &ck2, sizeof ck2);
    uint32_t ck3 = fnv1a(buf + offsetof(NationState, ledger), sizeof tmp.ledger.month);
    memcpy(buf + offsetof(NationState, ledger.checksum3), &ck3, sizeof ck3);
    return (int)sizeof(NationState);
}

static int name_ok(const char *n) { return memchr(n, 0, NAME_LEN) != NULL; }

int core_deserialize(NationState *s, const uint8_t *buf, int len)
{
    if (!buf || len < NATION_STATE_V1_SIZE) return 0;
    NationState tmp;
    memset(&tmp, 0, sizeof tmp);
    memcpy(&tmp, buf, NATION_STATE_V1_SIZE);
    if (tmp.magic != NATION_MAGIC) return 0;
    if (tmp.version == 1 && tmp.size == NATION_STATE_V1_SIZE) {
        memset(&tmp.navy, 0, sizeof tmp.navy);      /* a save from before the navy */
    } else if ((tmp.version == 2 && tmp.size == NATION_STATE_V2_SIZE && len >= NATION_STATE_V2_SIZE) ||
               (tmp.version == NATION_STATE_VERSION && tmp.size == (uint16_t)sizeof(NationState) &&
                len >= (int)sizeof(NationState))) {
        memcpy(&tmp, buf, tmp.size);                /* version 2: a save from before the accounts */
        if (tmp.version == NATION_STATE_VERSION &&
            tmp.ledger.checksum3 != fnv1a(buf + offsetof(NationState, ledger), sizeof tmp.ledger.month))
            return 0;
        if (tmp.navy.checksum2 != fnv1a(buf + offsetof(NationState, navy),
                                        offsetof(NationState, navy.checksum2) - offsetof(NationState, navy)))
            return 0;
        if (tmp.navy.order >= NAVY_ORDER_COUNT || tmp.navy.fleet_target > 10) return 0;
        if (tmp.navy.petition > MAX_TOWNS) return 0;
        for (int t = 0; t < MAX_TOWNS; t++)
            if (tmp.navy.towers_bought[t] > 10) return 0;
    } else {
        return 0;
    }
    if (tmp.checksum != fnv1a(buf, offsetof(NationState, checksum))) return 0;
    /* semantic sanity: never load a state the core could not have produced */
    if (tmp.founded > 1 || !name_ok(tmp.name) || !name_ok(tmp.adjective)) return 0;
    if (tmp.capital >= MAX_TOWNS && tmp.capital != CAPITAL_NONE) return 0;
    if (tmp.stability > 100 || tmp.host_power >= N_POWERS) return 0;
    if (tmp.treasury > TREASURY_LIMIT || tmp.treasury < -TREASURY_LIMIT) return 0;
    if (tmp.default_tax_pct > HARD_MAX_TAX || tmp.title >= N_TITLES) return 0;
    if (tmp.tariff_pct != 0 && tmp.tariff_pct != 5 && tmp.tariff_pct != 10 && tmp.tariff_pct != 20) return 0;
    if ((tmp.government & GOV_TYPE_MASK) >= GOV_COUNT ||
        (tmp.government >> GOV_COOLDOWN_SHIFT) > GOV_COOLDOWN_MONTHS) return 0;
    for (int p = 0; p < N_POWERS; p++) {
        const Relation *r = &tmp.rel[p];
        if ((int)r->status < 0 || (int)r->status > (int)TREATY_CEASEFIRE) return 0;
        if (r->score < -100 || r->score > 100 || r->war_exhaustion > 100 || r->recognized > 1) return 0;
    }
    for (int t = 0; t < MAX_TOWNS; t++) {
        const TownState *ts = &tmp.town[t];
        if (ts->member > 1 || ts->loyalty > 100 || ts->prior_power >= N_POWERS) return 0;
        if (ts->tax_pct > HARD_MAX_TAX && ts->tax_pct != TAX_USE_DEFAULT) return 0;
    }
    for (int p = 0; p < N_POWERS; p++)            /* threat was padding: anything else = no warning */
        if (!threat_evals(&tmp.rel[p])) tmp.rel[p].threat = THREAT_NONE;
    for (int t = 0; t < MAX_TOWNS; t++) {         /* permit_before was padding: anything else = not recorded */
        TownState *ts = &tmp.town[t];
        if (!ts->member || (ts->permit_before != PERMIT_HAD && ts->permit_before != PERMIT_HAD_NONE))
            ts->permit_before = PERMIT_UNKNOWN;
    }
#if !NATION_CONVOYS
    tmp.national_convoys = 0;       /* an older save's national convoys: nothing is charged for them */
#endif
    *s = tmp;
    return 1;
}

/* ------------------------------------------------------------------------ */
/* national navy (NAVY.md)                                                  */
/* ------------------------------------------------------------------------ */
_Static_assert(sizeof(Relation) == 20 && offsetof(Relation, threat) == 7 && offsetof(Relation, expiry_day) == 8,
               "Relation.threat lives in what was padding: the save layout must not change");
_Static_assert(offsetof(NationState, navy) == NATION_STATE_V1_SIZE, "version-1 saves must still load");
_Static_assert(offsetof(NationState, ledger) == NATION_STATE_V2_SIZE, "version-2 saves must still load");
_Static_assert(sizeof(TownState) == 12 && offsetof(TownState, permit_before) == 10,
               "permit_before must stay in the old padding: the save layout may not change");

static int64_t min64(int64_t a, int64_t b) { return a < b ? a : b; }

static const int k_rank_fleets[4] = {1, 3, 6, 10};
static const char *const k_rank_name[4] = {"Fledgling state", "Regional power", "Naval power", "Great power"};
static const char *const k_order_name[NAVY_ORDER_COUNT] = {"Patrol", "Raid enemy trade", "War campaign"};
static const int k_order_rank[NAVY_ORDER_COUNT] = {0, 2, 3};

const char *core_naval_rank_name(int rank) { return rank >= 0 && rank < 4 ? k_rank_name[rank] : "?"; }
const char *core_navy_order_name(int o) { return o >= 0 && o < NAVY_ORDER_COUNT ? k_order_name[o] : "?"; }
int core_order_min_rank(int o) { return o >= 0 && o < NAVY_ORDER_COUNT ? k_order_rank[o] : 99; }

/* score = 12 per town + 1 per 500 inhabitants + 1 per 50,000 in the treasury (max 20)
   + stability / 10; ranks at 30, 60 and 100 */
int core_naval_rank(const NationState *s, const World *w)
{
    if (!s->founded) return 0;
    int64_t pop = 0;
    int members = 0;
    for (int t = 0; t < MAX_TOWNS; t++) {
        if (!s->town[t].member) continue;
        members++;
        if (t < n_towns(w) && w->town[t].exists) pop += w->town[t].population;
    }
    int score = members * 12 + (int)min64(pop / 500, 200) + s->stability / 10
              + (s->treasury > 0 ? (int)min64(s->treasury / 50000, 20) : 0);
    return score >= 100 ? 3 : score >= 60 ? 2 : score >= 30 ? 1 : 0;
}

int core_fleet_cap(const NationState *s, const World *w) { return k_rank_fleets[core_naval_rank(s, w)]; }

int64_t core_military_upkeep(const NationState *s, const World *w, const Config *c)
{
    int64_t towers = 0;
    for (int t = 0; t < MAX_TOWNS; t++)
        if (s->town[t].member) towers += s->navy.towers_bought[t];
    return (int64_t)w->nation_fleets * c->fleet_upkeep + towers * c->tower_upkeep;
}

void core_navy_credit(NationState *s, int64_t gold)
{
    if (gold <= 0) return;
    book(s, LG_PLUNDER, gold);
    s->navy.plunder_total += gold;
    s->navy.last_plunder = to_i32((int64_t)s->navy.last_plunder + gold);
}

static int navy_ok(const NationState *s, char *why, int why_len)
{
    if (!s->founded) { set_why(why, why_len, "%s", "Found a nation first."); return 0; }
    if (!has_capital(s)) { set_why(why, why_len, "%s", "The nation has no capital to fit out a fleet."); return 0; }
    return 1;
}

int core_navy_commission(NationState *s, const World *w, const Config *c, Effects *out, char *why, int why_len)
{
    if (!navy_ok(s, why, why_len)) return 0;
    int cap = core_fleet_cap(s, w), have = mini(w->nation_fleets, 255);
    if (have >= cap) {
        set_why(why, why_len, "%s %s can keep at most %d fleet%s. Grow the nation to command more.",
                core_article(core_naval_rank_name(core_naval_rank(s, w)), 1),
                core_naval_rank_name(core_naval_rank(s, w)), cap, cap == 1 ? "" : "s");
        return 0;
    }
    if (s->treasury < c->fleet_cost) {
        set_why(why, why_len, "A new fleet costs %d gold; the treasury holds %lld.", c->fleet_cost,
                (long long)s->treasury);
        return 0;
    }
    if (!fx_room(out, 2)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    book(s, LG_NEW_FLEETS, -c->fleet_cost);
    s->navy.fleet_target = (uint8_t)mini(cap, maxi(s->navy.fleet_target, have) + 1);
    fx_add(out, FX_FLEET_SPAWN, s->capital, 0, 0);
    fx_msg(out, "A new fleet of %s is fitted out in town %d (%d gold).", s->name, s->capital,
           c->fleet_cost);
    set_why(why, why_len, "%s", "");
    return 1;
}

int core_navy_decommission(NationState *s, const World *w, Effects *out, char *why, int why_len)
{
    if (!navy_ok(s, why, why_len)) return 0;
    if (w->nation_fleets == 0) { set_why(why, why_len, "%s", "The nation has no fleet to pay off."); return 0; }
    if (!fx_room(out, 2)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    s->navy.fleet_target = (uint8_t)(w->nation_fleets - 1);
    fx_add(out, FX_FLEET_DISBAND, 1, 0, 0);
    fx_msg(out, "%s pays off one of its fleets.", s->name);
    set_why(why, why_len, "%s", "");
    return 1;
}

int core_navy_set_order(NationState *s, const World *w, int order, Effects *out, char *why, int why_len)
{
    if (!navy_ok(s, why, why_len)) return 0;
    if (order < 0 || order >= NAVY_ORDER_COUNT) { set_why(why, why_len, "%s", "Unknown order."); return 0; }
    int rank = core_naval_rank(s, w);
    if (rank < k_order_rank[order]) {
        set_why(why, why_len, "%s needs %s %s; the nation is %s %s.", k_order_name[order],
                core_article(k_rank_name[k_order_rank[order]], 0), k_rank_name[k_order_rank[order]],
                core_article(k_rank_name[rank], 0), k_rank_name[rank]);
        return 0;
    }
    if (!fx_room(out, 1)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    s->navy.order = (uint8_t)order;
    fx_add(out, FX_FLEET_ORDER, order, 0, 0);
    set_why(why, why_len, "%s", "");
    return 1;
}

static int member_town_ok(const NationState *s, const World *w, int town, char *why, int why_len)
{
    if (town < 0 || town >= MAX_TOWNS || !s->town[town].member || town >= n_towns(w) || !w->town[town].exists) {
        set_why(why, why_len, "%s", "That town does not belong to the nation.");
        return 0;
    }
    return 1;
}

int core_navy_reinforce(NationState *s, const World *w, const Config *c, int town, Effects *out, char *why, int why_len)
{
    if (!navy_ok(s, why, why_len) || !member_town_ok(s, w, town, why, why_len)) return 0;
    if (s->treasury < c->garrison_cost) {
        set_why(why, why_len, "Recruiting costs %d gold; the treasury holds %lld.", c->garrison_cost,
                (long long)s->treasury);
        return 0;
    }
    if (!fx_room(out, 1)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    book(s, LG_SOLDIERS, -c->garrison_cost);
    fx_add(out, FX_GARRISON, town, 0, c->garrison_cost);
    set_why(why, why_len, "%s", "");
    return 1;
}

int core_navy_build_tower(NationState *s, const World *w, const Config *c, int town, Effects *out, char *why, int why_len)
{
    if (!navy_ok(s, why, why_len) || !member_town_ok(s, w, town, why, why_len)) return 0;
    if (w->town[town].cannons >= 10) { set_why(why, why_len, "%s", "The town already has 10 cannon towers."); return 0; }
    if (s->treasury < c->tower_cost) {
        set_why(why, why_len, "A cannon tower costs %d gold; the treasury holds %lld.", c->tower_cost,
                (long long)s->treasury);
        return 0;
    }
    if (!fx_room(out, 1)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    book(s, LG_TOWERS, -c->tower_cost);
    if (s->navy.towers_bought[town] < 10) s->navy.towers_bought[town]++;
    fx_add(out, FX_TOWER, town, 0, c->tower_cost);
    set_why(why, why_len, "%s", "");
    return 1;
}

/* month end, after the accounts: the naval command */
static void navy_month(NationState *s, const World *w, const Config *c, Effects *out)
{
    /* The rank only limits new fleets and new orders: a nation that spends its treasury
       on ships (and so drops a rank) keeps the fleets and the order it already has. */
    int have = w->nation_fleets;
    s->navy.last_plunder = 0;
    if (s->treasury < 0 && have > 0) {
        if (++s->navy.unpaid_months >= 2 && fx_room(out, 2)) {
            fx_add(out, FX_FLEET_DISBAND, 1, 0, 0);
            fx_msg(out, "Unpaid for two months, the crews of a fleet of %s desert.", s->name);
            s->navy.fleet_target = (uint8_t)(have - 1);
            s->navy.unpaid_months = 0;
        }
        return;
    }
    s->navy.unpaid_months = 0;
    if (have > s->navy.fleet_target && fx_room(out, 2)) {
        fx_add(out, FX_FLEET_DISBAND, have - s->navy.fleet_target, 0, 0);
        fx_msg(out, "The navy of %s pays off %d fleet%s it can no longer keep.", s->name,
               have - s->navy.fleet_target, have - s->navy.fleet_target == 1 ? "" : "s");
    } else if (have < s->navy.fleet_target && s->treasury >= c->fleet_cost && has_capital(s) && fx_room(out, 2)) {
        book(s, LG_NEW_FLEETS, -c->fleet_cost);       /* replace a lost fleet */
        fx_add(out, FX_FLEET_SPAWN, s->capital, 0, 0);
        fx_msg(out, "The naval command of %s fits out a new fleet to replace a loss (%d gold).", s->name,
               c->fleet_cost);
    }
}

/* ------------------------------------------------------------------------ */
/* peaceful growth: buying towns, petitions (spec §4.2)                     */
/* ------------------------------------------------------------------------ */
static int sellable(const NationState *s, const World *w, int t)
{
    if (!s->founded || t < 0 || t >= MAX_TOWNS || t >= n_towns(w) || !w->town[t].exists) return 0;
    const TownSnap *ts = &w->town[t];
    if (s->town[t].member || ts->power >= N_POWERS || ts->is_viceroy_seat || !ts->player_property) return 0;
    Treaty st = s->rel[ts->power].status;
    return st != TREATY_WAR && st != TREATY_CEASEFIRE;
}

/* 60 gold per inhabitant + half the town's wealth measure; a governor's seat costs double */
int64_t core_town_price(const NationState *s, const World *w, int t)
{
    (void)s;
    if (t < 0 || t >= n_towns(w) || !w->town[t].exists) return 0;
    const TownSnap *ts = &w->town[t];
    int64_t p = (int64_t)ts->population * 60 + (int64_t)(ts->wealth > 0 ? ts->wealth : 0) / 2;
    if (ts->is_governor_seat) p *= 2;
    return (p + 999) / 1000 * 1000;
}

int core_buy_chance(const NationState *s, const World *w, int t)
{
    if (!sellable(s, w, t)) return 0;
    int p = w->town[t].power;
    const Relation *r = &s->rel[p];
    int c = 20 + r->score / 2 + (r->recognized ? 10 : 0) + (w->reputation[p] - 50) / 3
          - (w->town[t].is_governor_seat ? 25 : 0) - (s->treasury < 0 ? 10 : 0);
    if (core_ai_strategy(s, w, p) == AI_STRAT_EXPANSIONIST) c -= 15;
    return clampi(c, 0, 95);
}

int core_buy_town(NationState *s, const World *w, int t, Effects *out, char *why, int why_len)
{
    if (!sellable(s, w, t)) {
        set_why(why, why_len, "%s", "That town is not for sale: you need property there, no viceroy seat, and "
                                    "no war with its power.");
        return 0;
    }
    int p = w->town[t].power;
    int64_t price = core_town_price(s, w, t);
    if (s->treasury < price) {
        set_why(why, why_len, "The price is %lld gold; the treasury holds %lld.", (long long)price,
                (long long)s->treasury);
        return 0;
    }
    int chance = core_buy_chance(s, w, t);
    if (roll100(w->day, p, 200 + t) >= chance) {
        set_why(why, why_len, "%s refuses to sell town %d (chance was %d%%).", k_power_name[p], t, chance);
        return 0;
    }
    if (!fx_room(out, 5 + N_POWERS)) { set_why(why, why_len, "%s", "Internal error: effect queue full."); return 0; }
    if (!core_annex(s, w, t, 1, out)) { set_why(why, why_len, "%s", "The town could not join the nation."); return 0; }
    book(s, LG_TOWNS, -price);
    add_score(s, p, -5, "it had to sell a town to the nation");
    fx_msg(out, "%s sells town %d to %s for %lld gold.", k_power_name[p], t, s->name,
           (long long)price);
    set_why(why, why_len, "%s", "");
    return 1;
}

int core_petition_town(const NationState *s) { return s->navy.petition ? s->navy.petition - 1 : -1; }

int core_answer_petition(NationState *s, const World *w, int accept, Effects *out, char *why, int why_len)
{
    int t = core_petition_town(s);
    if (t < 0) { set_why(why, why_len, "%s", "No town is asking to join."); return 0; }
    s->navy.petition = 0;
    if (!accept) {
        fx_msg(out, "Town %d is told that the nation does not want it.", t);
        set_why(why, why_len, "%s", "");
        return 1;
    }
    if (t >= n_towns(w) || !w->town[t].exists || w->town[t].power >= N_POWERS || s->town[t].member ||
        !core_annex(s, w, t, 2, out)) {
        set_why(why, why_len, "%s", "The town can no longer join.");
        return 0;
    }
    set_why(why, why_len, "%s", "");
    return 1;
}

/* month end: the old petition lapses; maybe a new town asks */
static void petition_month(NationState *s, const World *w, Effects *out)
{
    if (s->navy.petition) {
        fx_msg(out, "Town %d no longer waits for an answer.", s->navy.petition - 1);
        s->navy.petition = 0;
    }
    if (s->stability < 55 || s->treasury < 0) return;
    int n = n_towns(w);
    for (int k = 0; k < n; k++) {
        int t = (int)((w->day / MONTH_DAYS + (uint32_t)k) % (uint32_t)n);
        if (!sellable(s, w, t) || w->town[t].is_governor_seat || w->town[t].wealth < 100000) continue;
        int p = w->town[t].power;
        int c = 4 + (s->stability - 55) / 3 + (w->reputation[p] >= 60 ? 4 : 0);
        if (roll100(w->day, p, 300 + t) >= c) continue;
        s->navy.petition = (uint8_t)(t + 1);
        fx_msg(out, "The citizens of town %d ask to join %s. Answer them on the Towns page.", t,
               s->name);
        return;
    }
}
