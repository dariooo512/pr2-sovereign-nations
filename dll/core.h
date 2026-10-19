/* Engine-independent core of the player-nation feature.
 *
 * Everything here is pure C over plain data: no game addresses, no Windows
 * calls. The engine adapter (adapter.c) fills a World snapshot from the game,
 * calls these functions, and applies the returned Effects back to the game.
 * Unit-tested natively by tests/test_core.c.
 *
 * Spec references: port_royale_2_sovereign_nations_spec.md (§ numbers below).
 */
#ifndef PR2N_CORE_H
#define PR2N_CORE_H
#include <stdint.h>

#define N_POWERS        4          /* 0 England, 1 Frankreich, 2 Holland, 3 Spanien */
#define MAX_TOWNS       64         /* staedte.ini has 60 power towns + spare */
#define NATION_ID       5          /* SPIELER_NATION: the town nation byte of player-nation towns */
#define NAME_LEN        32

/* National convoys (player convoys designated national, renamed "National convoy N", flying the
   nation's flag and paid from the treasury; the national-ships-on-the-sea-map change, research/sea_map_sight.md §4) are switched
   off in this version (the removal of national convoys): they gave the player nothing. With 0
   no convoy is designated, the upkeep has no convoy term, Nation_NationalConvoys returns 0, and
   an older save's designations are undone on load (old name and the player's flag back, nothing
   charged, no PNCV block written again). Build with -DNATION_CONVOYS=1 to bring them back (the
   panel's National convoys card has to be re-added too, see sea_map_sight.md §4). */
#ifndef NATION_CONVOYS
#define NATION_CONVOYS  0
#endif

/* ---- diplomacy (§6) ------------------------------------------------------ */
typedef enum { TREATY_PEACE = 0, TREATY_TRADE, TREATY_NONAGGRESSION, TREATY_ALLIANCE,
               TREATY_WAR, TREATY_CEASEFIRE } Treaty;

typedef struct {
    Treaty   status;
    int16_t  score;            /* -100 .. +100 relation */
    uint8_t  recognized;       /* recognition independent of war (§6.1) */
    uint8_t  threat;           /* THREAT_*: the power has warned that it may declare war. Was struct
                                  padding (0 in older saves = no warning), so the save layout is unchanged */
    uint32_t expiry_day;       /* 0 = none; ceasefire / treaty expiry */
    uint32_t last_change_day;
    uint8_t  war_exhaustion;   /* 0..100 */
} Relation;

/* Relation.threat. A power at peace never declares war without a warning first (the Holland war fix): when the AI's
   war conditions first hold it tells the player why and stays at peace; it may declare war only after
   the warning has stood THREAT_EVALS AI evaluations (about a month) with the conditions still true.
   The warning lapses ("tension eases") once the relation rises THREAT_EASE above the war threshold. */
#define THREAT_NONE   0x00
#define THREAT_BASE   0xB0      /* THREAT_BASE + n: warned n AI evaluations ago (1..THREAT_EVALS) */
#define THREAT_EVALS  4
#define THREAT_EASE   5

/* ---- persistent state (§13) ---------------------------------------------- */
typedef struct {
    uint8_t  member;           /* town belongs to the player nation */
    uint8_t  prior_power;      /* sovereign before joining (0..3) */
    uint8_t  loyalty;          /* 0..100 (§4.4) */
    uint8_t  tax_pct;          /* 0..50, 0xFF = use national default */
    uint32_t joined_day;
    uint8_t  conquered;        /* joined by conquest (loyalty malus) */
    uint8_t  unrest;           /* consecutive months below 20 loyalty */
    uint8_t  permit_before;    /* PERMIT_*: did the player hold the building permit before the
                                  town joined? Lives in what was struct padding (always 0 in
                                  older saves = PERMIT_UNKNOWN), so the save layout is unchanged */
} TownState;

/* TownState.permit_before. Member towns always grant the player the building
   permit; when a town leaves, the permit goes back to this state. */
#define PERMIT_UNKNOWN   0x00      /* not recorded yet (older save, or not a member) */
#define PERMIT_HAD_NONE  0xA0      /* recorded at joining: the player had no permit there */
#define PERMIT_HAD       0xA1      /* recorded at joining: the player had earned the permit */

/* Categories of the national accounts (NationState.ledger), in the Treasury page's row order:
   income first, then spending. The order is saved: append new categories only. */
typedef enum {
    LG_TAX = 0, LG_TARIFF, LG_PRIVATEER, LG_PLUNDER, LG_DONATION,
    LG_ADMIN, LG_FLEET_UPKEEP, LG_TOWER_UPKEEP, LG_NEW_FLEETS, LG_SOLDIERS, LG_TOWERS, LG_TOWNS,
    LG_WITHDRAWAL, LEDGER_CATS
} LedgerCat;

typedef struct {
    uint32_t magic;            /* 'PNAT' */
    uint16_t version;          /* NATION_STATE_VERSION */
    uint16_t size;             /* sizeof(NationState) */
    uint8_t  founded;
    char     name[NAME_LEN];
    char     adjective[NAME_LEN];
    uint8_t  title;            /* index into leader titles */
    uint8_t  flag;             /* index into flag/colour presets */
    uint8_t  capital;          /* town index (staedte.ini order) */
    uint8_t  host_power;       /* display power used for art/UI (0..3) */
    uint8_t  default_tax_pct;  /* §5.3 */
    uint8_t  tariff_pct;       /* §8: 0, 5, 10, 20 */
    uint8_t  stability;        /* 0..100 (§9) */
    uint8_t  government;       /* §5.5: bits 0-2 GovType (0 = generic sovereign), bits 3-7
                                  months until it may change again; read via core_government() */
    int64_t  treasury;         /* national funds, separate from personal (§5.2) */
    uint32_t founded_day;
    uint32_t last_month_day;   /* day of last monthly settlement */
    int32_t  last_tax_income, last_upkeep, last_tariff_income;
    Relation rel[N_POWERS];
    TownState town[MAX_TOWNS];
    uint8_t  national_convoys; /* convoys designated national (§7.1); always 0 unless NATION_CONVOYS */
    uint32_t checksum;         /* over all bytes before this field */
    /* ---- version 2: the national navy (appended, so version-1 saves still load) */
    struct {
        int64_t  plunder_total;        /* gold the navy has brought in */
        int32_t  last_military;        /* last month: fleets + bought towers upkeep */
        int32_t  last_plunder;         /* plunder credited since the last month end */
        uint8_t  fleet_target;         /* fleets the naval command keeps in service */
        uint8_t  order;                /* NavyOrder */
        uint8_t  unpaid_months;        /* consecutive insolvent month ends with fleets */
        uint8_t  petition;             /* town index + 1 that asks to join (0 = none) */
        uint8_t  towers_bought[MAX_TOWNS];   /* cannon towers paid by the treasury */
        uint32_t checksum2;            /* over the navy fields before this one */
    } navy;
    /* ---- version 3: the national accounts by category (the Treasury page's balance) */
    struct {
        int32_t  month[2][LEDGER_CATS];   /* [0] the last finished month, [1] this month so far */
        uint32_t checksum3;               /* over month[] */
    } ledger;
} NationState;

#define NATION_MAGIC          0x54414E50u   /* 'PNAT' little-endian */
#define NATION_STATE_VERSION  3
#define NATION_STATE_V1_SIZE  976           /* sizeof(NationState) of version 1 = offsetof(navy) */
#define NATION_STATE_V2_SIZE  1064          /* sizeof(NationState) of version 2 = offsetof(ledger) */

typedef enum { NAVY_PATROL = 0, NAVY_RAID, NAVY_WAR, NAVY_ORDER_COUNT } NavyOrder;

/* ---- read-only snapshot of the game, filled by the adapter --------------- */
typedef struct {
    uint8_t  exists;
    uint8_t  power;            /* current town nation byte (0..3 or 5) */
    uint8_t  display_power;
    uint8_t  is_governor_seat, is_viceroy_seat;
    uint32_t population;
    int32_t  wealth;           /* economic activity measure from the game */
    uint8_t  player_property;  /* player owns businesses/warehouse here */
    uint8_t  essential_shortage; /* food/essential goods missing */
    uint16_t garrison;         /* soldiers */
    uint16_t cannons;          /* cannon towers (CStadt+0x919C) */
    uint8_t  permit;           /* the player holds the building permit here (CStadt+0x91B0) */
} TownSnap;

typedef struct {
    uint32_t day;              /* game day counter (monotonic) */
    int64_t  player_gold;
    uint16_t player_ships, player_warships;
    uint8_t  player_rank;
    uint8_t  reputation[N_POWERS];  /* 0..100 vanilla reputation with each power */
    uint8_t  power_war[N_POWERS][N_POWERS]; /* vanilla power-vs-power war matrix */
    uint16_t power_strength[N_POWERS];      /* towns/fleets measure */
    TownSnap town[MAX_TOWNS];
    uint8_t  n_towns;
    uint8_t  nation_fleets;    /* military convoys of the nation in the world */
} World;

/* ---- effects the adapter must apply to the game -------------------------- */
typedef enum {
    FX_NONE = 0,
    FX_TOWN_TO_NATION,         /* a = town  : make town nation 5, display host power */
    FX_TOWN_TO_POWER,          /* a = town, b = power */
    FX_SET_WAR,                /* a = power, b = 1 war / 0 peace  -> player_rel */
    FX_PLAYER_GOLD,            /* v = delta to the player's personal gold */
    FX_MESSAGE,                /* text = message to show to the player */
    FX_TOWN_UNREST,            /* a = town, b = 1 start / 0 end (strike / shortage effect) */
    FX_REPUTATION,             /* a = power, v = delta to vanilla reputation */
    FX_FLEET_SPAWN,            /* a = town: commission a fleet there (paid already) */
    FX_FLEET_DISBAND,          /* a = number of fleets to pay off */
    FX_FLEET_ORDER,            /* a = NavyOrder for every fleet */
    FX_GARRISON,               /* a = town, v = gold for soldiers (adapter refunds what the town cannot take) */
    FX_TOWER,                  /* a = town, v = gold: build one cannon tower (adapter refunds on failure) */
    FX_PERMIT,                 /* a = town, b = 1 grant / 0 take away the player's building permit */
} FxKind;

typedef struct { FxKind kind; int a, b; int64_t v; char text[160]; } Effect;
typedef struct { Effect fx[64]; int n; } Effects;

/* ---- configuration (balance defaults, §3.1 etc.) ------------------------- */
typedef struct {
    int64_t found_min_gold;          /* default 5,000,000 */
    int     found_min_ships;         /* 10 */
    int     found_min_warships;      /* 3 */
    int     found_min_towns;         /* 1 eligible capital */
    int     upkeep_per_town;         /* administration per town per month */
    int     upkeep_per_convoy;       /* national convoy upkeep per month (only with NATION_CONVOYS) */
    int     max_tax_pct;             /* 50 */
    int     ai_eval_interval_days;   /* AI strategic evaluation cadence (§11.6) */
    int     fleet_cost;              /* commissioning one fleet (treasury) */
    int     fleet_upkeep;            /* per fleet per month */
    int     garrison_cost;           /* one "reinforce garrison" purchase */
    int     tower_cost;              /* one cannon tower */
    int     tower_upkeep;            /* per bought tower per month */
} Config;

void core_default_config(Config *c);
void core_init(NationState *s);                         /* not founded, all zero/defaults */

/* §3: eligibility. Returns 1 if eligible; otherwise 0 and a human-readable reason. */
int  core_can_found(const NationState *s, const World *w, const Config *c, int capital,
                    char *why, int why_len);
/* §3.3 / §11.5: transactional founding. On success fills effects and returns 1;
   on failure leaves *s untouched and returns 0 with reason. */
int  core_found(NationState *s, const World *w, const Config *c, int capital,
                const char *name, const char *adjective, int title, int flag,
                Effects *out, char *why, int why_len);

/* §4: territory. reason: 0 = annex after conquest, 1 = treaty/purchase, 2 = petition */
int  core_annex(NationState *s, const World *w, int town, int reason, Effects *out);
int  core_lose_town(NationState *s, const World *w, int town, int new_power, Effects *out);
int  core_relocate_capital(NationState *s, const World *w, Effects *out);   /* TER-03 */

/* Building permits in the nation's own towns. Founding and core_annex record
   whether the player already held the permit (TownState.permit_before) and
   grant it; core_lose_town puts it back to that state (buildings stay).
   core_permit_sync records towns not recorded yet (older saves) and grants the
   permit to every member town that lacks it; it runs on load and every day
   (core_daily). Returns the number of FX_PERMIT effects added. */
int  core_permit_sync(NationState *s, const World *w, Effects *out);

/* §6: diplomacy. Returns 1 if accepted / applied. */
int  core_declare_war(NationState *s, const World *w, int power, Effects *out);
int  core_propose(NationState *s, const World *w, int power, Treaty t, Effects *out,
                  char *why, int why_len);           /* AI decides acceptance */
int  core_acceptance_chance(const NationState *s, const World *w, int power, Treaty t); /* 0..100 */

/* §5: treasury */
int  core_donate(NationState *s, const World *w, int64_t amount, Effects *out);   /* personal -> national */
int  core_withdraw(NationState *s, const World *w, int64_t amount, Effects *out); /* restricted, stability cost */
void core_set_tax(NationState *s, int town /* -1 = default */, int pct);

/* §11.6 cadence: call once per game day; runs daily loyalty, treaty expiry,
   monthly taxes/upkeep (every 30 days), AI evaluation (every interval). */
void core_daily(NationState *s, const World *w, const Config *c, Effects *out);

/* §13: persistence. serialize returns bytes written (0 if buf too small);
   deserialize validates magic/version/size/checksum and returns 1 on success,
   0 = invalid/mismatch (caller must keep the game safe and tell the player). */
int  core_serialize(const NationState *s, uint8_t *buf, int len);
int  core_deserialize(NationState *s, const uint8_t *buf, int len);

/* ---- national navy (NAVY.md) ---------------------------------------------
   Naval rank grows with towns, population, treasury and stability:
     0 Fledgling state (1 fleet, patrol)   1 Regional power (3 fleets)
     2 Naval power (6 fleets, raiding)     3 Great power (10 fleets, war campaigns)
   Fleets are commissioned from the treasury and cost upkeep every month
   (with the towers the treasury bought: World.nation_fleets and navy.towers_bought).
   At each month end the naval command commissions one missing fleet if the
   treasury can pay, pays off fleets above the target (after "Pay off a fleet")
   and lets unpaid crews desert after two insolvent months. A lower rank only
   blocks new fleets and new orders; it takes nothing away. */
int  core_naval_rank(const NationState *s, const World *w);           /* 0..3 */
int  core_fleet_cap(const NationState *s, const World *w);
int  core_order_min_rank(int order);
const char *core_naval_rank_name(int rank);
const char *core_navy_order_name(int order);
int  core_navy_commission(NationState *s, const World *w, const Config *c, Effects *out, char *why, int why_len);
int  core_navy_decommission(NationState *s, const World *w, Effects *out, char *why, int why_len);
int  core_navy_set_order(NationState *s, const World *w, int order, Effects *out, char *why, int why_len);
int  core_navy_reinforce(NationState *s, const World *w, const Config *c, int town, Effects *out, char *why, int why_len);
int  core_navy_build_tower(NationState *s, const World *w, const Config *c, int town, Effects *out, char *why, int why_len);
void core_navy_credit(NationState *s, int64_t gold);                  /* plunder */
int64_t core_military_upkeep(const NationState *s, const World *w, const Config *c);

/* ---- peaceful growth (spec §4.2): buying towns, petitions ----------------
   A power sells a town where the player owns property (not a viceroy seat, not
   at war) for core_town_price(); its answer is a roll against core_buy_chance().
   At each month end a prosperous town with the player's property may petition to
   join a stable nation; the petition stands until the next month end. */
int64_t core_town_price(const NationState *s, const World *w, int town);
int  core_buy_chance(const NationState *s, const World *w, int town);   /* 0..100, 0 = impossible */
int  core_buy_town(NationState *s, const World *w, int town, Effects *out, char *why, int why_len);
int  core_petition_town(const NationState *s);                         /* -1 = none */
int  core_answer_petition(NationState *s, const World *w, int accept, Effects *out, char *why, int why_len);

/* Derived values for UI (§5.1) */
int     core_member_count(const NationState *s);
/* Town officials (treasurer, commander, governor, building master) serve the
   player as sovereign in a member town: 1 = full access (highest reputation
   tier), 0 = vanilla check. town_nation = the town's raw nation byte. */
int     core_officials_serve(const NationState *s, int town, int town_nation);
/* Town info of a member town (the conquered-town info fix): the loyalty word with the Towns page's
   thresholds ("loyal (72)", "calm (35)", "restless (18)", "in unrest"); returns
   1 good, 0 neutral, -1 bad. core_town_role: "Capital of <nation>" / "Town of
   <nation>"; 0 (empty) when the town is not a member. */
int     core_loyalty_label(const TownState *ts, char *out, int cap);
int     core_town_role(const NationState *s, int town, char *out, int cap);
int64_t core_monthly_tax_estimate(const NationState *s, const World *w);
/* The national accounts (NationState.ledger): every treasury change is booked to a
   category; the month end moves "this month" to "last month". forecast = this month
   so far plus what the coming month end will book (taxes, tariffs, upkeep, ...). */
const char *core_ledger_name(int cat);
void    core_ledger_forecast(const NationState *s, const World *w, const Config *c, int64_t out[LEDGER_CATS]);
void    core_refund(NationState *s, int64_t gold, int cat);           /* money back for a failed purchase */
const char *core_treaty_name(Treaty t);
const char *core_power_name(int power);
const char *core_title_name(int title);
const char *core_article(const char *word, int capital); /* "a"/"an" ("A"/"An") before word */

/* ---- government types (§5.5, M6) ----------------------------------------
   Stored in NationState.government (low 3 bits) together with the reform
   cooldown in months (high 5 bits), so no save-format change was needed. */
typedef enum { GOV_SOVEREIGN = 0, GOV_MERCHANT_REPUBLIC, GOV_COLONIAL_MONARCHY,
               GOV_PIRATE_REPUBLIC, GOV_MARITIME_FEDERATION, GOV_COUNT } GovType;
#define GOV_TYPE_MASK        0x07
#define GOV_COOLDOWN_SHIFT   3
#define GOV_COOLDOWN_MONTHS  25        /* month settlements before the next reform (>= 2 years) */
#define GOV_CHANGE_STABILITY 10        /* cost of a constitutional reform */
#define GOV_CHANGE_MIN_STAB  20        /* reform impossible below this stability */

/* Changes the government. Allowed once per 2 years, costs stability, emits
   FX_MESSAGE. Returns 1 on success; 0 with a reason (state untouched). */
int  core_set_government(NationState *s, const World *w, int gov, Effects *out, char *why, int why_len);
int  core_government(const NationState *s);               /* GovType */
int  core_government_cooldown(const NationState *s);      /* months until a reform is allowed */
const char *core_government_name(int gov);                /* GovType or raw government byte */

/* ---- AI strategy profiles (§10) -----------------------------------------
   Derived from current conditions at every AI evaluation (never stored):
     DEFENSIVE     power at war with another power, weaker than the player
                   (ratio >= 110%) or war-exhausted (>= 50) vs the player
     OPPORTUNISTIC the player nation is weak: insolvent, stability < 35 or
                   at war with another power (and ratio < 100%)
     COMMERCIAL    reputation >= 60, or a trade agreement / alliance in force;
                   also the default
     EXPANSIONIST  power at least twice the player's strength (ratio < 50%)
   Returns -1 for an invalid power. */
typedef enum { AI_STRAT_COMMERCIAL = 0, AI_STRAT_EXPANSIONIST, AI_STRAT_DEFENSIVE,
               AI_STRAT_OPPORTUNISTIC, AI_STRAT_COUNT } AiStrategy;
int  core_ai_strategy(const NationState *s, const World *w, int power);
const char *core_ai_strategy_name(int strategy);

/* §6: the relation score a power drifts towards at each month end, and its terms in words
   ("reputation 23: -13, recognition +10, former sovereign of the capital -20") when why != NULL. */
int  core_relation_target(const NationState *s, const World *w, int power, char *why, int why_len);

/* Trace: every change of a relation score is reported with its cause ("REL Holland score -40 -> -42
   (-2: monthly drift towards -55 = ...)"), and every AI war decision with its numbers ("AI Holland
   ..."). The DLL writes these lines to PR2Nation.log; NULL (the default) switches it off. */
typedef void (*CoreTraceFn)(const char *line);
void core_set_trace(CoreTraceFn fn);

/* ---- player handles (research/human_handle_presim.md) ----------------------
   A CPlayer handle is bits 0..15 the pool index, 16..20 the type (9 = player), 21..31 the slot's
   generation. The engine's "no player" is the index 0xFFFF: its empty player handle is 0x0009FFFF
   (0x41C510), which the human handle holds from start-up until a New Game creates the player after
   its pre-simulation, and again once the human player is destroyed. The engine only takes a handle
   (0x5C29E0) whose index is below the pool's capacity (at most 0xFFFE) and whose generation matches
   the slot's tag; the player record must also be alive (+0x25). These are its first two tests:
   core_player_index returns the pool index, or -1 for no player (0 or 0xFFFF index, wrong type,
   index out of the pool); core_player_tag_ok compares the generation with the slot's tag word. */
#define PLAYER_TYPE        9
#define PLAYER_NO_INDEX    0xFFFFu
int  core_player_index(uint32_t handle, uint32_t pool_capacity);
int  core_player_tag_ok(uint32_t handle, uint16_t slot_tag);

#endif
