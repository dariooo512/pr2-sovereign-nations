/* Native unit tests for core.c (spec §15 acceptance tests at the core level).
 * Build + run: python dll/tests/run_tests.py
 * Exit code = number of failed checks.
 */
#include "../core.h"
#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* national convoys are switched off in this version (core.h NATION_CONVOYS): no convoy upkeep */
#define CONVOY_UPKEEP (NATION_CONVOYS ? 3000 : 0)

static int g_pass, g_fail;
#define CHECK(cond) do { if (cond) g_pass++; else { g_fail++; \
    printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECKF(cond, ...) do { if (cond) g_pass++; else { g_fail++; \
    printf("  FAIL %s:%d: %s -- ", __FILE__, __LINE__, #cond); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- helpers ------------------------------------------------------------ */
static int g_war[N_POWERS];       /* the adapter's power -> player war table */

static void make_world(World *w)
{
    memset(w, 0, sizeof *w);
    w->day = 1000;
    w->player_gold = 6000000;
    w->player_ships = 12;
    w->player_warships = 4;
    w->player_rank = 5;
    for (int p = 0; p < N_POWERS; p++) { w->reputation[p] = 50; w->power_strength[p] = 200; }
    w->n_towns = 12;
    for (int t = 0; t < w->n_towns; t++) {
        TownSnap *s = &w->town[t];
        s->exists = 1;
        s->power = s->display_power = (uint8_t)(t % N_POWERS);
        s->population = 2000 + (uint32_t)t * 300;
        s->wealth = (int32_t)s->population * 100;
        s->garrison = 50;
    }
    /* town 0: Spanish town with player property -> capital candidate */
    w->town[0] = (TownSnap){1, 3, 3, 0, 0, 3000, 300000, 1, 0, 100, 10, 0};
    /* town 1: Spanish viceroy seat with property */
    w->town[1] = (TownSnap){1, 3, 3, 1, 1, 6000, 600000, 1, 0, 200, 30, 0};
    /* town 2: big Spanish town with player property (TER-02) */
    w->town[2] = (TownSnap){1, 3, 3, 0, 0, 5000, 500000, 1, 0, 0, 5, 0};
    /* town 3: small Spanish town */
    w->town[3] = (TownSnap){1, 3, 3, 0, 0, 2000, 200000, 0, 0, 20, 2, 0};
    memset(g_war, 0, sizeof g_war);
}

static void apply_fx(World *w, const Effects *e)
{
    for (int i = 0; i < e->n; i++) {
        const Effect *f = &e->fx[i];
        switch (f->kind) {
        case FX_TOWN_TO_NATION: w->town[f->a].power = NATION_ID; break;
        case FX_TOWN_TO_POWER: w->town[f->a].power = w->town[f->a].display_power = (uint8_t)f->b; break;
        case FX_SET_WAR: g_war[f->a] = f->b; break;
        case FX_PLAYER_GOLD: w->player_gold += f->v; break;
        case FX_PERMIT: w->town[f->a].permit = (uint8_t)(f->b != 0); break;
        case FX_REPUTATION: {
            int r = w->reputation[f->a] + (int)f->v;
            w->reputation[f->a] = (uint8_t)(r < 0 ? 0 : r > 100 ? 100 : r);
            break;
        }
        default: break;
        }
    }
}

static int has_fx(const Effects *e, FxKind k, int a, int b)
{
    for (int i = 0; i < e->n; i++)
        if (e->fx[i].kind == k && (a < 0 || e->fx[i].a == a) && (b < 0 || e->fx[i].b == b)) return 1;
    return 0;
}

static int has_msg(const Effects *e, const char *needle)
{
    for (int i = 0; i < e->n; i++)
        if (e->fx[i].kind == FX_MESSAGE && strstr(e->fx[i].text, needle)) return 1;
    return 0;
}

static int same_state(const NationState *a, const NationState *b)
{
    return memcmp(a, b, offsetof(NationState, checksum)) == 0;
}

/* founds "Tortuga" with capital town 0 */
static void found_ok(NationState *s, World *w, const Config *c)
{
    Effects e; char why[160];
    memset(&e, 0, sizeof e);
    core_init(s);
    int ok = core_found(s, w, c, 0, "Tortuga", "Tortugan", 2, 1, &e, why, sizeof why);
    CHECKF(ok == 1, "found failed: %s", why);
    apply_fx(w, &e);
}

/* ---- FND ---------------------------------------------------------------- */
static void test_fnd01(void)
{
    printf("FND-01 found without prerequisites -> blocked with explanation\n");
    Config c; World w; NationState s, before; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w); core_init(&s); memcpy(&before, &s, sizeof s); memset(&e, 0, sizeof e);
    w.player_gold = 1000000;
    CHECK(core_can_found(&s, &w, &c, 0, why, sizeof why) == 0);
    CHECKF(strstr(why, "gold") != NULL, "why='%s'", why);
    CHECK(core_found(&s, &w, &c, 0, "X", "Xian", 0, 0, &e, why, sizeof why) == 0);
    CHECK(same_state(&s, &before) && e.n == 0);

    make_world(&w); w.player_ships = 5;
    CHECK(core_can_found(&s, &w, &c, 0, why, sizeof why) == 0);
    CHECKF(strstr(why, "ships") != NULL, "why='%s'", why);

    make_world(&w); w.player_warships = 1;
    CHECK(core_can_found(&s, &w, &c, 0, why, sizeof why) == 0);
    CHECKF(strstr(why, "warships") != NULL, "why='%s'", why);

    make_world(&w);
    CHECK(core_can_found(&s, &w, &c, 3, why, sizeof why) == 0);          /* no property */
    CHECKF(strstr(why, "property") != NULL, "why='%s'", why);

    make_world(&w);
    CHECK(core_can_found(&s, &w, &c, 1, why, sizeof why) == 0);          /* viceroy seat */
    CHECKF(strstr(why, "viceroy") != NULL, "why='%s'", why);
    CHECK(core_found(&s, &w, &c, 1, "X", "Xian", 0, 0, &e, why, sizeof why) == 0);
    CHECK(same_state(&s, &before) && e.n == 0);

    make_world(&w);
    CHECK(core_can_found(&s, &w, &c, 40, why, sizeof why) == 0);         /* no such town */
    for (int t = 0; t < w.n_towns; t++) w.town[t].player_property = 0;
    CHECK(core_can_found(&s, &w, &c, 0, why, sizeof why) == 0);
    CHECKF(strstr(why, "eligible") != NULL, "why='%s'", why);

    make_world(&w);
    CHECK(core_found(&s, &w, &c, 0, "", "", 0, 0, &e, why, sizeof why) == 0);  /* empty name */
    CHECK(same_state(&s, &before) && e.n == 0);
    CHECK(core_can_found(&s, &w, &c, 0, why, sizeof why) == 1);
}

static void test_fnd02(void)
{
    printf("FND-02 valid declaration -> sovereign nation\n");
    Config c; World w; NationState s; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w); core_init(&s); memset(&e, 0, sizeof e);
    w.power_war[0][3] = w.power_war[3][0] = 1;           /* England at war with Spain */
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 2, 1, &e, why, sizeof why) == 1);
    CHECK(s.founded == 1 && s.capital == 0 && s.host_power == 3);
    CHECK(strcmp(s.name, "Tortuga") == 0 && strcmp(s.adjective, "Tortugan") == 0);
    CHECK(s.town[0].member == 1 && s.town[0].prior_power == 3 && s.town[0].loyalty == 75);
    CHECK(core_member_count(&s) == 1);
    CHECK(s.treasury == 0 && s.founded_day == 1000 && s.last_month_day == 1000);
    CHECK(has_fx(&e, FX_TOWN_TO_NATION, 0, -1));
    CHECK(has_msg(&e, "Tortuga has declared its independence from Spain"));   /* name is the full official name */
    CHECK(has_msg(&e, "Its flag now flies over town 0"));   /* not the adjective (the overview page fix) */
    /* reputation 50 >= 40 -> former sovereign hostile but at peace */
    CHECK(s.rel[3].score == -60 && s.rel[3].status == TREATY_PEACE && !s.rel[3].recognized);
    CHECK(has_fx(&e, FX_SET_WAR, 3, 0));
    CHECK(has_fx(&e, FX_REPUTATION, 3, -1));
    CHECK(s.rel[0].score == 15);                         /* enemy of Spain likes us */
    CHECK(s.rel[1].score == 0 && s.rel[1].status == TREATY_PEACE && !s.rel[1].recognized);
    apply_fx(&w, &e);
    CHECK(w.town[0].power == NATION_ID && w.reputation[3] == 30);

    /* low reputation with Spain -> Spain at war from day one */
    make_world(&w); core_init(&s); memset(&e, 0, sizeof e);
    w.reputation[3] = 30;
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 0, 0, &e, why, sizeof why) == 1);
    CHECK(s.rel[3].status == TREATY_WAR && has_fx(&e, FX_SET_WAR, 3, 1));
    CHECK(has_msg(&e, "declares war"));
    CHECK(s.rel[1].score == 0);

    /* capital that is already the player's own nation-5 town */
    make_world(&w); core_init(&s); memset(&e, 0, sizeof e);
    w.town[0].power = NATION_ID; w.town[0].display_power = 2;
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 0, 0, &e, why, sizeof why) == 1);
    CHECK(s.town[0].prior_power == 2 && s.host_power == 2 && s.rel[2].score == -60);
}

static void test_fnd03(void)
{
    printf("FND-03 second founding -> rejected\n");
    Config c; World w; NationState s, before; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memcpy(&before, &s, sizeof s);
    memset(&e, 0, sizeof e);
    w.town[2].player_property = 1;
    CHECK(core_can_found(&s, &w, &c, 2, why, sizeof why) == 0);
    CHECKF(strstr(why, "already") != NULL, "why='%s'", why);
    CHECK(core_found(&s, &w, &c, 2, "Nassau", "Nassauvian", 0, 0, &e, why, sizeof why) == 0);
    CHECK(same_state(&s, &before) && e.n == 0);
}

/* ADJ: the nation's adjective (Nation_GetInfo). The panel founds with none, so the core stores the
   nation's name; before, the panel stored the capital's name there. Such a save must keep loading,
   with its adjective as it was. */
static void v1_buffer(const NationState *s, uint8_t *buf)
{
    NationState v1;
    memcpy(&v1, s, NATION_STATE_V1_SIZE);
    v1.version = 1;
    v1.size = NATION_STATE_V1_SIZE;
    memcpy(buf, &v1, NATION_STATE_V1_SIZE);
    uint32_t h = 2166136261u;                                /* the version-1 checksum (FNV-1a) */
    for (size_t i = 0; i < offsetof(NationState, checksum); i++) { h ^= buf[i]; h *= 16777619u; }
    memcpy(buf + offsetof(NationState, checksum), &h, 4);
}

static void test_adjective(void)
{
    printf("ADJ-01 founding without an adjective stores the nation's name; old saves keep theirs\n");
    Config c; World w; NationState s; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w); core_init(&s); memset(&e, 0, sizeof e);
    CHECK(core_found(&s, &w, &c, 0, "Kingdom of Tortuga", "", 0, 0, &e, why, sizeof why) == 1);
    CHECK(!strcmp(s.adjective, "Kingdom of Tortuga") && !strcmp(s.adjective, s.name));
    make_world(&w); core_init(&s); memset(&e, 0, sizeof e);
    CHECK(core_found(&s, &w, &c, 0, "Kingdom of Tortuga", NULL, 0, 0, &e, why, sizeof why) == 1);
    CHECK(!strcmp(s.adjective, "Kingdom of Tortuga"));
    CHECK(has_msg(&e, "Kingdom of Tortuga") && !has_msg(&e, "Tortugan"));

    /* an old save: the panel stored the capital's name as the adjective */
    snprintf(s.adjective, sizeof s.adjective, "%s", "Turk Islands");
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState) && core_deserialize(&back, buf, n) == 1);
    CHECK(!strcmp(back.adjective, "Turk Islands") && !strcmp(back.name, "Kingdom of Tortuga"));
    v1_buffer(&s, buf);                                      /* the same from a version-1 save */
    CHECK(core_deserialize(&back, buf, NATION_STATE_V1_SIZE) == 1);
    CHECK(!strcmp(back.adjective, "Turk Islands") && !strcmp(back.name, "Kingdom of Tortuga"));
    /* the old adjective is not used in the nation's messages: a month and a war still name the nation */
    memset(&e, 0, sizeof e);
    w.day = back.last_month_day + 31;
    core_daily(&back, &w, &c, &e);
    CHECK(core_declare_war(&back, &w, 1, &e) == 1 && has_msg(&e, "Kingdom of Tortuga"));
    CHECK(!has_msg(&e, "Turk Islands"));
    /* an empty adjective (never written by the core) still loads */
    s.adjective[0] = 0;
    n = core_serialize(&s, buf, sizeof buf);
    CHECK(core_deserialize(&back, buf, n) == 1 && back.adjective[0] == 0);
}

/* annex by conquest (reason 0) -- needs a war with the town's power */
static int annex_conq(NationState *s, World *w, int t, Effects *e)
{
    int p = (t >= 0 && t < MAX_TOWNS) ? w->town[t].power : -1;
    if (p < 0 || p >= N_POWERS) return core_annex(s, w, t, 0, e);
    uint8_t was = s->rel[p].status;
    s->rel[p].status = TREATY_WAR;
    int ok = core_annex(s, w, t, 0, e);
    s->rel[p].status = was;
    return ok;
}

/* ---- TER ---------------------------------------------------------------- */
static void test_ter01_02(void)
{
    printf("TER-01 annex conquered town / TER-02 property preserved\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    int st0 = s.stability, sc0 = s.rel[3].score;
    memset(&e, 0, sizeof e);
    CHECK(core_annex(&s, &w, 2, 0, &e) == 0 && e.n == 0);   /* no war with Spain: no conquest */
    CHECK(annex_conq(&s, &w, 2, &e) == 1);
    CHECK(s.town[2].member && s.town[2].conquered && s.town[2].loyalty == 30);
    CHECK(s.town[2].prior_power == 3 && s.town[2].joined_day == w.day);
    CHECK(has_fx(&e, FX_TOWN_TO_NATION, 2, -1));
    CHECK(s.rel[3].score == sc0 - 15 && s.stability == st0 - 3);
    for (int i = 0; i < e.n; i++)               /* no effect may touch private property */
        CHECK(e.fx[i].kind == FX_TOWN_TO_NATION || e.fx[i].kind == FX_MESSAGE || e.fx[i].kind == FX_PERMIT);
    apply_fx(&w, &e);
    CHECK(w.town[2].power == NATION_ID);
    CHECK(w.town[2].player_property == 1);        /* TER-02 */
    CHECK(core_member_count(&s) == 2);

    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&s, &w, 2, &e) == 0);     /* already member */
    CHECK(annex_conq(&s, &w, 1, &e) == 0);     /* viceroy seat */
    CHECK(annex_conq(&s, &w, 99, &e) == 0);    /* invalid */
    CHECK(e.n == 0);
    CHECK(core_annex(&s, &w, 3, 1, &e) == 1 && s.town[3].loyalty == 50 && !s.town[3].conquered);
    CHECK(core_annex(&s, &w, 4, 2, &e) == 1 && s.town[4].loyalty == 70 && s.town[4].prior_power == 0);

    /* losing a town also leaves the property flag alone */
    apply_fx(&w, &e);
    memset(&e, 0, sizeof e);
    CHECK(core_lose_town(&s, &w, 2, 3, &e) == 1);
    CHECK(has_fx(&e, FX_TOWN_TO_POWER, 2, 3) && !s.town[2].member);
    apply_fx(&w, &e);
    CHECK(w.town[2].power == 3 && w.town[2].player_property == 1);
    CHECK(core_lose_town(&s, &w, 2, 3, &e) == 0);  /* not a member any more */

    NationState u; core_init(&u);
    CHECK(annex_conq(&u, &w, 2, &e) == 0);     /* no nation */
}

static void test_ter03(void)
{
    printf("TER-03 capital lost -> relocation / landless\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    CHECK(core_annex(&s, &w, 3, 1, &e) == 1);     /* pop 2000 */
    CHECK(core_annex(&s, &w, 2, 1, &e) == 1);     /* pop 5000 -> most populous */
    apply_fx(&w, &e);
    int st = s.stability;
    memset(&e, 0, sizeof e);
    CHECK(core_lose_town(&s, &w, 0, 3, &e) == 1);
    CHECK(s.capital == 2);
    CHECK(has_fx(&e, FX_TOWN_TO_POWER, 0, 3) && has_msg(&e, "relocates to town 2"));
    CHECK(s.stability == st - 8 - 10);
    CHECK(core_relocate_capital(&s, &w, &e) == 1 && s.capital == 2);   /* no-op */

    /* lose everything -> landless, still founded */
    memset(&e, 0, sizeof e);
    CHECK(core_lose_town(&s, &w, 2, 3, &e) == 1 && s.capital == 3);
    CHECK(core_lose_town(&s, &w, 3, 0, &e) == 1);
    CHECK(s.founded == 1 && s.capital == 0xFF && core_member_count(&s) == 0);
    CHECK(has_msg(&e, "exile"));
    CHECK(s.stability < 30);
    apply_fx(&w, &e);
    /* a landless nation's next annexation becomes the capital */
    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&s, &w, 5, &e) == 1 && s.capital == 5);
    CHECK(has_msg(&e, "capital"));

    /* former sovereign retakes a town: core_daily notices the world change */
    apply_fx(&w, &e);
    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&s, &w, 6, &e) == 1);
    apply_fx(&w, &e);
    w.town[5].power = 1;                          /* France retook the capital */
    w.day++;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(!s.town[5].member && s.capital == 6 && has_fx(&e, FX_TOWN_TO_POWER, 5, 1));
}

/* ---- DIP ---------------------------------------------------------------- */
static void test_dip01(void)
{
    printf("DIP-01 declare war on Spain -> war state\n");
    Config c; World w; NationState s; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    CHECK(core_declare_war(&s, &w, 3, &e) == 1);
    apply_fx(&w, &e);
    CHECK(s.rel[3].status == TREATY_WAR && g_war[3] == 1 && s.rel[3].score <= -50);
    CHECK(has_fx(&e, FX_SET_WAR, 3, 1) && has_msg(&e, "declared war on Spain"));
    CHECK(g_war[0] == 0 && g_war[1] == 0 && g_war[2] == 0);
    CHECK(core_declare_war(&s, &w, 3, &e) == 0);  /* already at war */
    CHECK(core_declare_war(&s, &w, 7, &e) == 0);
    CHECK(core_propose(&s, &w, 3, TREATY_WAR, &e, why, sizeof why) == 0);

    /* unprovoked war against a power that recognized us */
    s.rel[0].recognized = 1; s.rel[0].score = 20; s.rel[0].status = TREATY_TRADE;
    int st = s.stability, s1 = s.rel[1].score;
    memset(&e, 0, sizeof e);
    CHECK(core_declare_war(&s, &w, 0, &e) == 1);
    CHECK(s.rel[0].score == -50 && s.stability == st - 15 && s.rel[1].score == s1 - 15);
    CHECK(has_fx(&e, FX_REPUTATION, 1, -1) && has_fx(&e, FX_REPUTATION, 2, -1));
    CHECK(has_msg(&e, "breaking a treaty"));
}

static void test_dip02(void)
{
    printf("DIP-02 make peace via ceasefire\n");
    Config c; World w; NationState s; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    core_declare_war(&s, &w, 3, &e);
    apply_fx(&w, &e);
    w.day += 40;

    memset(&e, 0, sizeof e);
    CHECK(core_propose(&s, &w, 3, TREATY_PEACE, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "ceasefire") != NULL, "why='%s'", why);
    CHECK(core_propose(&s, &w, 3, TREATY_TRADE, &e, why, sizeof why) == 0);
    CHECK(s.rel[3].status == TREATY_WAR && e.n == 0);

    /* an AI ceasefire offer is pending -> acceptance certain */
    s.rel[3].expiry_day = w.day + 10;
    CHECK(core_acceptance_chance(&s, &w, 3, TREATY_CEASEFIRE) == 100);
    CHECK(core_propose(&s, &w, 3, TREATY_CEASEFIRE, &e, why, sizeof why) == 1);
    apply_fx(&w, &e);
    CHECK(s.rel[3].status == TREATY_CEASEFIRE && s.rel[3].expiry_day == w.day + 60);
    CHECK(g_war[3] == 0 && has_fx(&e, FX_SET_WAR, 3, 0));   /* hostility cleared */

    /* peace from ceasefire with overwhelming willingness */
    s.rel[3].score = 100; s.rel[3].war_exhaustion = 100;
    w.power_strength[3] = 24;                     /* equal strength (player = 10 + 8 + 6) */
    CHECK(core_acceptance_chance(&s, &w, 3, TREATY_PEACE) == 100);
    memset(&e, 0, sizeof e);
    CHECK(core_propose(&s, &w, 3, TREATY_PEACE, &e, why, sizeof why) == 1);
    CHECK(s.rel[3].status == TREATY_PEACE && s.rel[3].expiry_day == 0 && has_fx(&e, FX_SET_WAR, 3, 0));
    CHECK(core_propose(&s, &w, 3, TREATY_PEACE, &e, why, sizeof why) == 0);  /* already */

    /* ceasefire expiry -> peace; war re-declared during ceasefire stays war */
    s.rel[1].status = TREATY_CEASEFIRE; s.rel[1].expiry_day = w.day + 60;
    s.rel[2].status = TREATY_CEASEFIRE; s.rel[2].expiry_day = w.day + 60;
    memset(&e, 0, sizeof e);
    CHECK(core_declare_war(&s, &w, 2, &e) == 1 && s.rel[2].expiry_day == 0);
    apply_fx(&w, &e);
    for (int d = 0; d < 60; d++) {
        w.day++;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        apply_fx(&w, &e);
        if (d < 59) CHECK(s.rel[1].status == TREATY_CEASEFIRE);
    }
    CHECK(s.rel[1].status == TREATY_PEACE && s.rel[1].expiry_day == 0);
    CHECK(s.rel[2].status == TREATY_WAR || s.rel[2].status == TREATY_CEASEFIRE);

    /* alliance requires score >= 60 and recognition */
    s.rel[0].status = TREATY_PEACE; s.rel[0].score = 50; s.rel[0].recognized = 1;
    memset(&e, 0, sizeof e);
    CHECK(core_propose(&s, &w, 0, TREATY_ALLIANCE, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "60") != NULL, "why='%s'", why);
    CHECK(core_acceptance_chance(&s, &w, 0, TREATY_ALLIANCE) == 0);
    s.rel[0].score = 100;
    w.power_strength[0] = 24;                     /* equal strength (player = 10 + 8 + 6) */
    w.power_war[0][2] = 1;                        /* common enemy: Holland */
    CHECK(core_acceptance_chance(&s, &w, 0, TREATY_ALLIANCE) == 85);
    s.rel[0].recognized = 0;
    CHECK(core_propose(&s, &w, 0, TREATY_ALLIANCE, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "recognized") != NULL, "why='%s'", why);
    /* dissolving a treaty is always possible */
    s.rel[0].status = TREATY_TRADE;
    CHECK(core_propose(&s, &w, 0, TREATY_PEACE, &e, why, sizeof why) == 1 && s.rel[0].status == TREATY_PEACE);
}

/* ---- ECO ---------------------------------------------------------------- */
static void test_eco01(void)
{
    printf("ECO-01 collect taxes -> treasury updated exactly\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    s.town[0].loyalty = 80;
    /* base = 3000*20 + 300000/10 = 90000; eff = 40+36+min(15,100/10)=86; 10% */
    CHECK(core_monthly_tax_estimate(&s, &w) == 90000LL * 10 * 86 / 10000);   /* 7740 */
    CHECK(core_monthly_tax_estimate(&s, &w) == 7740);

    memset(&e, 0, sizeof e);
    core_annex(&s, &w, 2, 1, &e);
    apply_fx(&w, &e);
    s.town[2].loyalty = 50;
    s.town[2].unrest = 2;                              /* in unrest -> half */
    core_set_tax(&s, 2, 20);
    /* base = 5000*20 + 500000/10 = 150000; eff = 40+22+0 = 62; 20% -> 18600 /2 = 9300 */
    CHECK(core_monthly_tax_estimate(&s, &w) == 7740 + 9300);
    s.national_convoys = 1;
    int64_t t0 = s.treasury = 1000;
    w.day = s.last_month_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(s.last_tax_income == 17040 && s.last_upkeep == 2 * 2000 + CONVOY_UPKEEP && s.last_tariff_income == 0);
    CHECKF(s.treasury == t0 + 17040 - (4000 + CONVOY_UPKEEP), "treasury=%lld", (long long)s.treasury);
    CHECK(has_fx(&e, FX_TOWN_UNREST, 2, 0));          /* loyalty 50 -> unrest ends */
    CHECK(has_msg(&e, "Monthly accounts"));

    /* tariffs: imports = base/5, 10%, scaled by efficiency */
    s.tariff_pct = 10;
    s.town[0].loyalty = 80; s.town[2].loyalty = 50; s.town[2].unrest = 0;
    int64_t tar = 90000 / 5 * 10 / 100 * 86 / 100 + 150000 / 5 * 10 / 100 * 62 / 100;
    int64_t tax = 7740 + 18600;
    int64_t t1 = s.treasury;
    w.day = s.last_month_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(s.last_tariff_income == tar && s.last_tax_income == tax);
    CHECK(s.treasury == t1 + tax + tar - (4000 + CONVOY_UPKEEP));

    /* tax setting clamps */
    core_set_tax(&s, -1, 90); CHECK(s.default_tax_pct == 50);
    core_set_tax(&s, 2, -1); CHECK(s.town[2].tax_pct == 0xFF);
    core_set_tax(&s, 2, 70); CHECK(s.town[2].tax_pct == 50);
}

static void test_eco02(void)
{
    printf("ECO-02 upkeep deducted exactly once per month\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    s.town[0].loyalty = 80;
    s.national_convoys = 1;
    int64_t est = core_monthly_tax_estimate(&s, &w);
    int64_t up = 2000 + CONVOY_UPKEEP;
    int64_t t0 = s.treasury;
    for (int d = 1; d < 30; d++) {
        w.day = s.founded_day + (uint32_t)d;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
    }
    CHECK(s.treasury == t0);                          /* nothing before the month ends */
    s.town[0].loyalty = 80;
    w.day = s.founded_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    int64_t t1 = s.treasury;
    CHECK(t1 == t0 + est - up && s.last_upkeep == up);
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);                       /* same day again */
    CHECK(s.treasury == t1);
    w.day += 1;
    core_daily(&s, &w, &c, &e);
    CHECK(s.treasury == t1);
    w.day = s.founded_day + 60;
    s.town[0].loyalty = 80;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(s.treasury == t1 + est - up);
    /* a 3-month gap settles three months, once each */
    int64_t t2 = s.treasury;
    s.town[0].loyalty = 80;
    w.day = s.founded_day + 150;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(s.last_month_day == s.founded_day + 150);
    CHECK(s.treasury == t2 + 3 * (est - up));

    /* treasury: donate / withdraw / insolvency blocks withdrawal */
    memset(&e, 0, sizeof e);
    int64_t g = w.player_gold;
    CHECK(core_donate(&s, &w, 100000, &e) == 1 && has_fx(&e, FX_PLAYER_GOLD, -1, -1));
    apply_fx(&w, &e);
    CHECK(w.player_gold == g - 100000);
    CHECK(core_donate(&s, &w, w.player_gold + 1, &e) == 0);
    int64_t tr = s.treasury;
    CHECK(core_withdraw(&s, &w, tr, &e) == 0);        /* more than half */
    memset(&e, 0, sizeof e);
    int st = s.stability;
    CHECK(core_withdraw(&s, &w, tr / 4, &e) == 1 && s.treasury == tr - tr / 4 && s.stability < st);
    s.treasury = -5;
    CHECK(core_withdraw(&s, &w, 1, &e) == 0);
}

/* ---- SAV ---------------------------------------------------------------- */
static uint32_t fnv(const uint8_t *p, size_t n)
{
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
    return h;
}

static void test_sav01(void)
{
    printf("SAV-01 save/reload -> identical state; corrupt/mismatch rejected\n");
    Config c; World w; NationState s, r; Effects e;
    static uint8_t buf[4096], buf2[4096];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    annex_conq(&s, &w, 2, &e);
    core_declare_war(&s, &w, 3, &e);                 /* SAV-02 flavour: during war */
    s.treasury = 123456789;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState));
    CHECK(core_serialize(&s, buf, n - 1) == 0);
    memset(&r, 0xAB, sizeof r);
    CHECK(core_deserialize(&r, buf, n) == 1);
    CHECK(same_state(&s, &r));
    CHECK(r.rel[3].status == TREATY_WAR && r.town[2].member && r.treasury == 123456789);
    CHECK(core_serialize(&r, buf2, sizeof buf2) == n && memcmp(buf, buf2, (size_t)n) == 0);

    NationState keep;
    memcpy(&keep, &r, sizeof r);
    memcpy(buf2, buf, (size_t)n);
    buf2[offsetof(NationState, treasury)] ^= 1;      /* corrupted payload */
    CHECK(core_deserialize(&r, buf2, n) == 0 && same_state(&r, &keep));
    memcpy(buf2, buf, (size_t)n);
    buf2[offsetof(NationState, checksum)] ^= 0x80;   /* corrupted checksum */
    CHECK(core_deserialize(&r, buf2, n) == 0);
    memcpy(buf2, buf, (size_t)n);
    uint16_t v = NATION_STATE_VERSION + 1;           /* wrong version, valid checksum */
    memcpy(buf2 + offsetof(NationState, version), &v, sizeof v);
    uint32_t ck = fnv(buf2, offsetof(NationState, checksum));
    memcpy(buf2 + offsetof(NationState, checksum), &ck, sizeof ck);
    CHECK(core_deserialize(&r, buf2, n) == 0);
    memcpy(buf2, buf, (size_t)n);
    buf2[0] = 'X';                                   /* wrong magic */
    ck = fnv(buf2, offsetof(NationState, checksum));
    memcpy(buf2 + offsetof(NationState, checksum), &ck, sizeof ck);
    CHECK(core_deserialize(&r, buf2, n) == 0);
    CHECK(core_deserialize(&r, buf, n - 1) == 0);    /* truncated */
    memcpy(buf2, buf, (size_t)n);
    buf2[offsetof(NationState, stability)] = 200;    /* checksum-valid but impossible */
    ck = fnv(buf2, offsetof(NationState, checksum));
    memcpy(buf2 + offsetof(NationState, checksum), &ck, sizeof ck);
    CHECK(core_deserialize(&r, buf2, n) == 0);
    CHECK(same_state(&r, &keep));

    NationState fresh; core_init(&fresh);             /* unfounded state round-trips too */
    n = core_serialize(&fresh, buf, sizeof buf);
    CHECK(core_deserialize(&r, buf, n) == 1 && same_state(&r, &fresh) && !r.founded);
}

/* ---- GOV: government types (§5.5) ---------------------------------------- */
/* runs one month settlement (core_daily on the month-end day) and returns the treasury delta */
static int64_t settle(NationState *s, World *w, const Config *c, Effects *e)
{
    int64_t t0 = s->treasury;
    w->day = s->last_month_day + 30;
    memset(e, 0, sizeof *e);
    core_daily(s, w, c, e);
    return s->treasury - t0;
}

static void test_gov(void)
{
    printf("GOV-01 government types: change rules, cooldown, cost, persistence\n");
    Config c; World w; NationState s, u; Effects e; char why[160];
    static uint8_t buf[4096];
    core_default_config(&c);
    CHECK(strcmp(core_government_name(GOV_SOVEREIGN), "Sovereign Government") == 0);
    CHECK(strcmp(core_government_name(GOV_PIRATE_REPUBLIC), "Pirate Republic") == 0);
    CHECK(strcmp(core_government_name(GOV_MARITIME_FEDERATION), "Maritime Federation") == 0);
    CHECK(strcmp(core_government_name(-1), "?") == 0 && strcmp(core_government_name(7), "?") == 0);
    make_world(&w);
    core_init(&u); memset(&e, 0, sizeof e);
    CHECK(core_set_government(&u, &w, GOV_MERCHANT_REPUBLIC, &e, why, sizeof why) == 0 && e.n == 0);
    found_ok(&s, &w, &c);
    CHECK(core_government(&s) == GOV_SOVEREIGN && core_government_cooldown(&s) == 0);
    memset(&e, 0, sizeof e);
    CHECK(core_set_government(&s, &w, 9, &e, why, sizeof why) == 0);
    CHECK(core_set_government(&s, &w, GOV_SOVEREIGN, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "already") != NULL, "why='%s'", why);
    int st = s.stability;
    CHECK(core_set_government(&s, &w, GOV_MERCHANT_REPUBLIC, &e, why, sizeof why) == 1);
    CHECK(core_government(&s) == GOV_MERCHANT_REPUBLIC && s.stability == st - 10);
    CHECK(core_government_cooldown(&s) == GOV_COOLDOWN_MONTHS);
    CHECK(has_msg(&e, "Merchant Republic") && e.n == 1);
    NationState keep = s;
    CHECK(core_set_government(&s, &w, GOV_PIRATE_REPUBLIC, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "months") != NULL, "why='%s'", why);
    CHECK(same_state(&s, &keep));
    /* save/load keeps type + cooldown; impossible government bytes are rejected */
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(core_deserialize(&u, buf, n) == 1 && core_government(&u) == GOV_MERCHANT_REPUBLIC &&
          core_government_cooldown(&u) == GOV_COOLDOWN_MONTHS);
    buf[offsetof(NationState, government)] = 7;
    uint32_t ck = fnv(buf, offsetof(NationState, checksum));
    memcpy(buf + offsetof(NationState, checksum), &ck, sizeof ck);
    CHECK(core_deserialize(&u, buf, n) == 0);
    /* cooldown: still blocked after 700 days, allowed again after 2 years */
    uint32_t d0 = w.day;
    while (w.day < d0 + 700) {
        w.day++;
        s.town[0].loyalty = 80;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        apply_fx(&w, &e);
    }
    CHECKF(core_government_cooldown(&s) > 0, "cooldown %d", core_government_cooldown(&s));
    CHECK(core_set_government(&s, &w, GOV_PIRATE_REPUBLIC, &e, why, sizeof why) == 0);
    while (w.day < d0 + 760) {
        w.day++;
        s.town[0].loyalty = 80;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        apply_fx(&w, &e);
    }
    CHECK(core_government_cooldown(&s) == 0);
    s.stability = 15;                                 /* too unstable */
    CHECK(core_set_government(&s, &w, GOV_PIRATE_REPUBLIC, &e, why, sizeof why) == 0);
    CHECKF(strstr(why, "unstable") != NULL, "why='%s'", why);
    s.stability = 60;
    int sc1 = s.rel[1].score;
    memset(&e, 0, sizeof e);
    CHECK(core_set_government(&s, &w, GOV_PIRATE_REPUBLIC, &e, why, sizeof why) == 1);
    CHECK(s.stability == 50 && s.rel[1].score == sc1 - 10);   /* pirates alarm every power */
}

static void test_gov_effects(void)
{
    printf("GOV-02 government effects are measurable trade-offs\n");
    Config c; World w, w2; NationState g, m, x; Effects e; char why[160];
    core_default_config(&c);
    make_world(&w);
    found_ok(&g, &w, &c);
    g.tariff_pct = 10;
    g.town[0].loyalty = 80;

    /* Merchant Republic: tax eff +5, tariffs x5/4; generic: eff 86 */
    m = g;
    CHECK(core_set_government(&m, &w, GOV_MERCHANT_REPUBLIC, NULL, why, sizeof why) == 1);
    w2 = w; settle(&g, &w2, &c, &e);
    w2 = w; settle(&m, &w2, &c, &e);
    CHECK(g.last_tariff_income == 90000 / 5 * 10 / 100 * 86 / 100);           /* 1548 */
    CHECK(m.last_tariff_income == 90000 / 5 * 10 / 100 * 91 / 100 * 5 / 4);   /* 2047 */
    CHECK(m.last_tax_income == 90000LL * 10 * 91 / 10000 && g.last_tax_income == 7740);
    CHECK(m.last_tariff_income > g.last_tariff_income && m.last_tax_income > g.last_tax_income);
    /* ... better trade diplomacy */
    g.rel[1].recognized = m.rel[1].recognized = 1;
    CHECK(core_acceptance_chance(&m, &w, 1, TREATY_TRADE) == core_acceptance_chance(&g, &w, 1, TREATY_TRADE) + 15);
    /* ... but wars hurt stability more: same war, stability target lower */
    {
        NationState a, b; Effects e2;
        a = g; b = m;
        a.rel[1].status = b.rel[1].status = TREATY_WAR;
        a.stability = b.stability = 68;               /* targets: generic ~71, merchant ~67 */
        w2 = w; settle(&a, &w2, &c, &e2);
        w2 = w; settle(&b, &w2, &c, &e2);
        CHECKF(b.stability < a.stability, "merchant %d generic %d", b.stability, a.stability);
    }

    /* Colonial Monarchy: garrison counts more, stability +8, upkeep x5/4, slow conquest recovery */
    make_world(&w);
    found_ok(&g, &w, &c);
    g.town[0].loyalty = 80;
    x = g;
    CHECK(core_set_government(&x, &w, GOV_COLONIAL_MONARCHY, NULL, why, sizeof why) == 1);
    g.stability = x.stability = 76;                   /* generic target 75, monarchy 83 */
    w2 = w; settle(&g, &w2, &c, &e);
    w2 = w; settle(&x, &w2, &c, &e);
    CHECK(g.last_upkeep == 2000 && x.last_upkeep == 2500);
    CHECK(x.last_tax_income == 90000LL * 10 * (40 + 36 + 12) / 10000);       /* garrison 100/8 */
    CHECKF(g.stability == 75 && x.stability == 81, "generic %d monarchy %d", g.stability, x.stability);

    /* Pirate Republic: plunder only while at war, harsher conquest, relations drift down */
    make_world(&w);
    found_ok(&g, &w, &c);
    g.town[0].loyalty = 80;
    x = g;
    CHECK(core_set_government(&x, &w, GOV_PIRATE_REPUBLIC, NULL, why, sizeof why) == 1);
    x.town[0].loyalty = 80;
    w2 = w;
    int64_t d = settle(&x, &w2, &c, &e);
    CHECK(d == (int64_t)x.last_tax_income + x.last_tariff_income - x.last_upkeep);   /* peace: none */
    CHECK(!has_msg(&e, "privateering"));
    memset(&e, 0, sizeof e);
    CHECK(core_declare_war(&x, &w2, 3, &e) == 1 && core_declare_war(&g, &w2, 3, &e) == 1);
    x.town[0].loyalty = 80; g.town[0].loyalty = 80;
    w2.day = x.last_month_day; g.last_month_day = x.last_month_day;
    World w3 = w2;
    d = settle(&x, &w2, &c, &e);
    int64_t plunder = 4 * 1500;                       /* 4 warships, exhaustion 0 */
    CHECKF(d == (int64_t)x.last_tax_income + x.last_tariff_income - x.last_upkeep + plunder,
           "delta %lld", (long long)d);
    CHECK(has_msg(&e, "privateering +6000"));
    d = settle(&g, &w3, &c, &e);                      /* generic at war: no plunder */
    CHECK(d == (int64_t)g.last_tax_income + g.last_tariff_income - g.last_upkeep);
    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&x, &w2, 2, &e) == 1 && x.town[2].loyalty == 20);
    x.rel[1].recognized = g.rel[1].recognized = 1;
    x.rel[1].score = g.rel[1].score = 20;
    CHECK(core_acceptance_chance(&x, &w2, 1, TREATY_TRADE) == core_acceptance_chance(&g, &w2, 1, TREATY_TRADE) - 10);

    /* Maritime Federation: more loyalty, unrest only below 15, but lower collection */
    make_world(&w);
    found_ok(&g, &w, &c);
    g.town[0].loyalty = 80;
    x = g;
    CHECK(core_set_government(&x, &w, GOV_MARITIME_FEDERATION, NULL, why, sizeof why) == 1);
    CHECK(core_monthly_tax_estimate(&x, &w) == 90000LL * 10 * 76 / 10000 &&
          core_monthly_tax_estimate(&x, &w) < core_monthly_tax_estimate(&g, &w));
    g.town[0].loyalty = x.town[0].loyalty = 17;
    w2 = w; settle(&g, &w2, &c, &e);
    w2 = w; settle(&x, &w2, &c, &e);
    CHECK(g.town[0].unrest == 1 && x.town[0].unrest == 0);
    /* loyalty target +8: drift over 40 days from the same start */
    g.town[0].loyalty = x.town[0].loyalty = 70;
    g.stability = x.stability = 60;
    for (int i = 0; i < 40; i++) {
        w2.day++;
        core_daily(&g, &w2, &c, NULL);
        core_daily(&x, &w2, &c, NULL);
    }
    CHECKF(x.town[0].loyalty > g.town[0].loyalty, "fed %d gen %d", x.town[0].loyalty, g.town[0].loyalty);
}

/* ---- AI: strategy profiles and bounds (§10) -------------------------------- */
static int count_ai_wars(NationState *s, World *w, const Config *c, int days, int force_insolvent,
                         int stop_first, const int score[N_POWERS], int wars_out[N_POWERS])
{
    Effects e;
    int total = 0;
    memset(wars_out, 0, sizeof(int) * N_POWERS);
    for (int d = 0; d < days; d++) {
        w->day++;
        for (int p = 0; p < N_POWERS; p++)
            if (s->rel[p].status == TREATY_PEACE) s->rel[p].score = (int16_t)score[p];
        if (force_insolvent) s->treasury = -1000;
        else if (s->treasury < 0) s->treasury = 0;
        memset(&e, 0, sizeof e);
        core_daily(s, w, c, &e);
        for (int i = 0; i < e.n; i++)
            if (e.fx[i].kind == FX_SET_WAR && e.fx[i].b == 1) { wars_out[e.fx[i].a]++; total++; }
        apply_fx(w, &e);
        if (stop_first && total) break;
    }
    return total;
}

static void test_ai_strategy(void)
{
    printf("AI-01 strategy profiles from current conditions\n");
    Config c; World w; NationState s;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);                             /* player strength 24 vs 200: ratio 12 */
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_EXPANSIONIST);
    CHECK(core_ai_strategy(&s, &w, 4) == -1 && core_ai_strategy(&s, &w, -1) == -1);
    CHECK(strcmp(core_ai_strategy_name(AI_STRAT_DEFENSIVE), "Defensive") == 0 &&
          strcmp(core_ai_strategy_name(9), "?") == 0);
    w.reputation[1] = 70;
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_COMMERCIAL);
    w.reputation[1] = 50; s.rel[1].status = TREATY_TRADE;
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_COMMERCIAL);
    s.rel[1].status = TREATY_PEACE;
    w.power_war[1][2] = 1;                             /* busy fighting Holland */
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_DEFENSIVE && core_ai_strategy(&s, &w, 2) == AI_STRAT_DEFENSIVE);
    CHECK(core_ai_strategy(&s, &w, 0) == AI_STRAT_EXPANSIONIST);
    w.power_war[1][2] = 0;
    w.power_strength[1] = 20;                          /* weaker than the player */
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_DEFENSIVE);
    w.power_strength[1] = 30;                          /* ratio 80: neither strong nor weak */
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_COMMERCIAL);
    w.power_strength[1] = 200;
    s.rel[1].war_exhaustion = 60;
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_DEFENSIVE);
    s.rel[1].war_exhaustion = 0;
    s.treasury = -1;
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_OPPORTUNISTIC);
    s.treasury = 0; s.stability = 30;
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_OPPORTUNISTIC);
    s.stability = 70; s.rel[3].status = TREATY_WAR;    /* player distracted by Spain */
    CHECK(core_ai_strategy(&s, &w, 1) == AI_STRAT_OPPORTUNISTIC);
    CHECK(core_ai_strategy(&s, &w, 3) == AI_STRAT_EXPANSIONIST);
    s.rel[3].status = TREATY_PEACE;
    /* acceptance follows strategy: a defensive power welcomes a non-aggression pact */
    s.rel[1].recognized = 1;
    int nap_exp = core_acceptance_chance(&s, &w, 1, TREATY_NONAGGRESSION);
    w.power_war[1][2] = 1;
    int nap_def = core_acceptance_chance(&s, &w, 1, TREATY_NONAGGRESSION);
    CHECKF(nap_def > nap_exp, "def %d exp %d", nap_def, nap_exp);
    w.power_war[1][2] = 0;

    printf("AI-02 strategy weights change AI decisions\n");
    int wars[N_POWERS];
    /* 0 commercial (rep 70), 1 defensive (weaker), 2 expansionist, 3 neutral score:
       same hostile relation -35 for 0..2; only the expansionist goes to war */
    make_world(&w);
    w.reputation[0] = 70; w.power_strength[1] = 20;
    found_ok(&s, &w, &c);
    const int sc_a[N_POWERS] = {-35, -35, -35, 0};
    count_ai_wars(&s, &w, &c, 720, 0, 1, sc_a, wars);
    CHECKF(wars[2] >= 1 && wars[0] == 0 && wars[1] == 0 && wars[3] == 0,
           "wars %d %d %d %d", wars[0], wars[1], wars[2], wars[3]);
    /* relation -25: an expansionist waits, but pounces on an insolvent nation */
    const int sc_b[N_POWERS] = {0, 0, -25, 0};
    make_world(&w); found_ok(&s, &w, &c);
    count_ai_wars(&s, &w, &c, 720, 0, 0, sc_b, wars);
    CHECKF(wars[2] == 0, "solvent: %d", wars[2]);
    make_world(&w); found_ok(&s, &w, &c);
    CHECK(core_ai_strategy(&s, &w, 2) == AI_STRAT_EXPANSIONIST);
    count_ai_wars(&s, &w, &c, 720, 1, 1, sc_b, wars);
    CHECKF(wars[2] >= 1, "insolvent: %d", wars[2]);

    printf("AI-03 bounds: exhausted AI must offer a ceasefire\n");
    Effects e;
    make_world(&w); found_ok(&s, &w, &c);
    for (int p = 0; p < N_POWERS; p++) {
        s.rel[p].status = TREATY_WAR; g_war[p] = 1;
        s.rel[p].war_exhaustion = p < 2 ? 75 : 65;
        s.rel[p].last_change_day = w.day - 40;         /* too early for the voluntary offer */
        s.rel[p].expiry_day = 0;
    }
    int offered = 0;
    for (int d = 0; d < 7; d++) {
        w.day++;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        apply_fx(&w, &e);
        for (int i = 0; i < e.n; i++)
            if (e.fx[i].kind == FX_MESSAGE && strstr(e.fx[i].text, "War-weary")) offered++;
    }
    CHECK(offered == 2 && s.rel[0].expiry_day && s.rel[1].expiry_day);
    CHECK(!s.rel[2].expiry_day && !s.rel[3].expiry_day);
    CHECK(core_acceptance_chance(&s, &w, 0, TREATY_CEASEFIRE) == 100);
}

/* ---- REB: rebellion and secession (§9 advanced) ---------------------------- */
static void run_month(NationState *s, World *w, const Config *c, int riot_town, int riot_loy,
                      Effects *last, NationState *twin, int twin_unrest)
{
    Effects e;
    for (int d = 1; d <= 30; d++) {
        w->day++;
        for (int t = 0; t < MAX_TOWNS; t++)
            if (s->town[t].member) s->town[t].loyalty = (uint8_t)(t == riot_town ? riot_loy : 80);
        if (d == 30 && twin) {                        /* identical copy, one month less of unrest */
            *twin = *s;
            twin->town[riot_town].unrest = (uint8_t)twin_unrest;
        }
        memset(&e, 0, sizeof e);
        core_daily(s, w, c, &e);
        if (d == 30 && last) *last = e;
        if (d == 30 && twin) { World w2 = *w; core_daily(twin, &w2, c, NULL); }
        apply_fx(w, &e);
    }
}

static void test_rebellion(void)
{
    printf("REB-01 persistent unrest -> secession after 4 months, never the capital\n");
    Config c; World w; NationState s, twin; Effects e, last;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&s, &w, 2, &e) == 1 && core_annex(&s, &w, 3, 1, &e) == 1);
    apply_fx(&w, &e);
    for (int m = 1; m <= 5; m++) {
        run_month(&s, &w, &c, 2, 5, &last, NULL, 0);
        CHECK(s.town[2].member && s.town[2].unrest == m);
        if (m == 2) CHECK(has_fx(&last, FX_TOWN_UNREST, 2, 1));       /* outbreak */
        CHECK(!has_msg(&last, "secedes"));
    }
    /* 4th month-end after the outbreak: secession (twin with one month less does not) */
    run_month(&s, &w, &c, 2, 5, &last, &twin, 4);
    CHECK(!s.town[2].member && twin.town[2].member);
    CHECK(has_fx(&last, FX_TOWN_TO_POWER, 2, 3) && has_fx(&last, FX_TOWN_UNREST, 2, 0));
    CHECK(has_msg(&last, "secedes from Tortuga") && has_msg(&last, "Spanish"));
    CHECKF(s.stability == twin.stability - 10, "stab %d twin %d", s.stability, twin.stability);
    CHECK(w.town[2].power == 3 && core_member_count(&s) == 2 && s.capital == 0);

    /* a town that recovers in time stays */
    make_world(&w); found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    annex_conq(&s, &w, 2, &e); apply_fx(&w, &e);
    for (int m = 1; m <= 4; m++) run_month(&s, &w, &c, 2, 5, NULL, NULL, 0);
    run_month(&s, &w, &c, 2, 35, &last, NULL, 0);
    CHECK(s.town[2].member && s.town[2].unrest == 0 && has_fx(&last, FX_TOWN_UNREST, 2, 0));
    for (int m = 1; m <= 3; m++) run_month(&s, &w, &c, 2, 5, NULL, NULL, 0);
    CHECK(s.town[2].member);

    /* loyalty 20..29 keeps open unrest running: still secedes */
    make_world(&w); found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    annex_conq(&s, &w, 2, &e); apply_fx(&w, &e);
    for (int m = 1; m <= 2; m++) run_month(&s, &w, &c, 2, 5, NULL, NULL, 0);
    for (int m = 3; m <= 6; m++) run_month(&s, &w, &c, 2, 25, NULL, NULL, 0);
    CHECK(!s.town[2].member);

    /* Maritime Federation: looser union, secession after 3 months */
    make_world(&w); found_ok(&s, &w, &c);
    CHECK(core_set_government(&s, &w, GOV_MARITIME_FEDERATION, NULL, NULL, 0) == 1);
    memset(&e, 0, sizeof e);
    annex_conq(&s, &w, 2, &e); apply_fx(&w, &e);
    for (int m = 1; m <= 4; m++) run_month(&s, &w, &c, 2, 5, NULL, NULL, 0);
    CHECK(s.town[2].member);
    run_month(&s, &w, &c, 2, 5, NULL, NULL, 0);
    CHECK(!s.town[2].member);

    /* the capital never secedes, but its riots crash stability */
    make_world(&w); found_ok(&s, &w, &c);
    int riots = 0;
    for (int m = 1; m <= 5; m++) {
        run_month(&s, &w, &c, 0, 5, &last, NULL, 0);
        riots += has_msg(&last, "Riots paralyse the capital");
    }
    CHECK(riots == 0);
    s.stability = 60;
    run_month(&s, &w, &c, 0, 5, &last, &twin, 4);
    CHECK(has_msg(&last, "Riots paralyse the capital") && !has_fx(&last, FX_TOWN_TO_POWER, 0, -1));
    CHECKF(s.stability == twin.stability - 20, "stab %d twin %d", s.stability, twin.stability);
    for (int m = 1; m <= 6; m++) run_month(&s, &w, &c, 0, 5, NULL, NULL, 0);
    CHECK(s.town[0].member && s.capital == 0 && core_member_count(&s) == 1 && w.town[0].power == NATION_ID);
    CHECK(s.stability < 10);
}

/* ---- REG-02: long simulation ---------------------------------------------- */
static uint32_t rng_state;
static uint32_t rnd(void)
{
    uint32_t x = rng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return rng_state = x;
}
static int rr(int lo, int hi) { return lo + (int)(rnd() % (uint32_t)(hi - lo + 1)); }

typedef struct { int ai_actions, ai_wars, recognitions, offers, unrest_starts, max_effects;
                 int64_t min_treasury, max_treasury; int final_members, final_stability;
                 int strat[AI_STRAT_COUNT], gov_changes, secessions, min_war_gap, warnings; } SimStats;

static int sim_world(uint32_t seed, NationState *out_state, SimStats *st)
{
    Config c; World w; NationState s; Effects e; char why[160];
    int fails0 = g_fail;
    core_default_config(&c);
    rng_state = seed * 2654435761u + 1;
    memset(&w, 0, sizeof w);
    memset(st, 0, sizeof *st);
    memset(g_war, 0, sizeof g_war);
    w.day = (uint32_t)rr(0, 2000);
    w.player_gold = rr(5000000, 20000000);
    w.player_ships = (uint16_t)rr(10, 40);
    w.player_warships = (uint16_t)rr(3, 15);
    for (int p = 0; p < N_POWERS; p++) {
        w.reputation[p] = (uint8_t)rr(20, 80);
        w.power_strength[p] = (uint16_t)rr(100, 400);
        for (int q = p + 1; q < N_POWERS; q++) w.power_war[p][q] = w.power_war[q][p] = (uint8_t)(rr(0, 3) == 0);
    }
    w.n_towns = 40;
    for (int t = 0; t < w.n_towns; t++) {
        TownSnap *ts = &w.town[t];
        ts->exists = 1;
        ts->power = ts->display_power = (uint8_t)rr(0, 3);
        ts->is_viceroy_seat = t < 4;
        ts->population = (uint32_t)rr(500, 9000);
        ts->wealth = (int32_t)ts->population * rr(20, 300);
        ts->garrison = (uint16_t)rr(0, 300);
        ts->player_property = rr(0, 2) == 0;
    }
    int cap = 4 + rr(0, 35);
    w.town[cap].player_property = 1;
    core_init(&s);
    memset(&e, 0, sizeof e);
    CHECKF(core_found(&s, &w, &c, cap, "Libertalia", "Libertalian", rr(0, 7), 0, &e, why, sizeof why) == 1,
           "seed %u: %s", seed, why);
    apply_fx(&w, &e);
    const int64_t max_month = 40LL * (12000 * 20 + 12000 * 400 / 10) * 70 / 100
                              + 4 * 30000;                       /* + Pirate Republic plunder cap */
    int64_t donated = 0, withdrawn = 0;
    int last_war[N_POWERS], last_warn[N_POWERS];
    for (int p = 0; p < N_POWERS; p++) last_war[p] = last_warn[p] = -100000;
    st->min_treasury = st->max_treasury = 0;
    st->min_war_gap = 100000;

    for (int day = 1; day <= 20 * 360; day++) {
        w.day++;
        if (day % 30 == 0) {
            for (int t = 0; t < w.n_towns; t++) {
                TownSnap *ts = &w.town[t];
                int pop = (int)ts->population + rr(-(int)ts->population / 20, (int)ts->population / 20);
                ts->population = (uint32_t)(pop < 300 ? 300 : pop > 12000 ? 12000 : pop);
                ts->wealth = (int32_t)ts->population * rr(20, 400);
                ts->essential_shortage = rr(0, 9) == 0;
                ts->garrison = (uint16_t)rr(0, 300);
            }
            for (int p = 0; p < N_POWERS; p++) {
                int r = w.reputation[p] + rr(-3, 3);
                w.reputation[p] = (uint8_t)(r < 0 ? 0 : r > 100 ? 100 : r);
            }
        }
        if (day % 360 == 0) { uint8_t nc = (uint8_t)rr(0, 5); if (NATION_CONVOYS) s.national_convoys = nc; }
        memset(&e, 0, sizeof e);
        /* the player */
        if (rr(0, 199) == 0) {
            int t = rr(0, 39);
            if (!s.town[t].member) core_annex(&s, &w, t, rr(0, 2), &e);
        }
        if (rr(0, 399) == 0) {                       /* a power retakes a town in the game */
            int t = rr(0, 39);
            if (s.town[t].member) w.town[t].power = (uint8_t)rr(0, 3);
        }
        if (rr(0, 299) == 0) core_set_tax(&s, rr(0, 3) ? -1 : rr(0, 39), rr(0, 40));
        if (rr(0, 299) == 0) s.tariff_pct = (uint8_t)(rr(0, 3) * 5 + (rr(0, 1) ? 0 : 5));
        if (rr(0, 999) == 0) core_declare_war(&s, &w, rr(0, 3), &e);
        if (rr(0, 59) == 0) core_propose(&s, &w, rr(0, 3), (Treaty)rr(0, 5), &e, why, sizeof why);
        if (rr(0, 359) == 0 && core_set_government(&s, &w, rr(0, GOV_COUNT - 1), &e, why, sizeof why))
            st->gov_changes++;
        if (s.treasury < 0 && rr(0, 29) == 0) {
            int64_t a = 50000;
            if (core_donate(&s, &w, a, &e)) donated += a;
        }
        if (rr(0, 364) == 0 && s.treasury > 0) {
            int64_t a = s.treasury / 4;
            if (core_withdraw(&s, &w, a, &e)) withdrawn += a;
        }
        apply_fx(&w, &e);
        /* the game day */
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        if (e.n > st->max_effects) st->max_effects = e.n;
        for (int i = 0; i < e.n; i++) {
            const Effect *f = &e.fx[i];
            if (f->kind == FX_TOWN_UNREST && f->b == 1) st->unrest_starts++;
            if (f->kind == FX_SET_WAR && f->b == 1) {          /* only the AI declares inside core_daily */
                int gap = day - last_war[f->a];
                if (gap < st->min_war_gap) st->min_war_gap = gap;
                CHECKF(gap >= 180, "seed %u: power %d declared war again after %d days", seed, f->a, gap);
                CHECKF(s.rel[f->a].war_exhaustion <= 70, "seed %u: war at exhaustion %d", seed,
                       s.rel[f->a].war_exhaustion);
                CHECKF(day - last_warn[f->a] >= 7 * THREAT_EVALS, "seed %u: %s declared war %d days after its "
                       "warning", seed, core_power_name(f->a), day - last_warn[f->a]);   /* the Holland war fix */
                last_warn[f->a] = -100000;
                last_war[f->a] = day;
                st->ai_wars++; st->ai_actions++;
            }
            if (f->kind != FX_MESSAGE) continue;
            for (int p = 0; p < N_POWERS; p++) {
                char w1[48], w2[48], w3[48];
                snprintf(w1, sizeof w1, "%s may declare war", core_power_name(p));
                snprintf(w2, sizeof w2, "Tension with %s eases", core_power_name(p));
                snprintf(w3, sizeof w3, "%s no longer threatens war", core_power_name(p));
                if (strstr(f->text, w1)) { if (last_warn[p] < 0) last_warn[p] = day; st->warnings++; }
                if (strstr(f->text, w2) || strstr(f->text, w3)) last_warn[p] = -100000;
            }
            if (strstr(f->text, "secedes from")) st->secessions++;
            if (strstr(f->text, "formally recognizes")) { st->recognitions++; st->ai_actions++; }
            if (strstr(f->text, "offers a ceasefire") || strstr(f->text, "proposes a trade") ||
                strstr(f->text, "halts hostilities") || strstr(f->text, "cancels the")) { st->offers++; st->ai_actions++; }
        }
        apply_fx(&w, &e);
        if (w.player_gold < 0) w.player_gold = 0;

        /* invariants */
        int ok = e.n >= 0 && e.n <= 64 && s.stability <= 100 && s.founded == 1;
        for (int p = 0; p < N_POWERS; p++) {
            const Relation *r = &s.rel[p];
            ok &= r->score >= -100 && r->score <= 100 && r->war_exhaustion <= 100;
            ok &= (int)r->status >= 0 && (int)r->status <= (int)TREATY_CEASEFIRE;
            ok &= (r->status == TREATY_WAR) == (g_war[p] == 1);      /* adapter table coherent */
        }
        for (int t = 0; t < MAX_TOWNS; t++) {
            ok &= s.town[t].loyalty <= 100;
            if (s.town[t].member) ok &= w.town[t].power == NATION_ID;
        }
        ok &= s.capital == 0xFF ? core_member_count(&s) == 0 : s.town[s.capital].member == 1;
        int months = day / 30 + 1;
        ok &= s.treasury <= months * max_month + donated;
        ok &= s.treasury >= -(int64_t)months * (40 * c.upkeep_per_town + 5 * c.upkeep_per_convoy) * 5 / 4
                            - withdrawn;                          /* Colonial Monarchy upkeep x5/4 */
        ok &= core_government(&s) < GOV_COUNT && core_government_cooldown(&s) <= GOV_COOLDOWN_MONTHS;
        if (day % 30 == 0)
            for (int p = 0; p < N_POWERS; p++) {
                int k = core_ai_strategy(&s, &w, p);
                ok &= k >= 0 && k < AI_STRAT_COUNT;
                if (k >= 0 && k < AI_STRAT_COUNT) st->strat[k]++;
            }
        if (!ok) {
            CHECKF(0, "seed %u: invariant broken on day %d (treasury %lld, stab %d)", seed, day,
                   (long long)s.treasury, s.stability);
            break;
        }
        if (s.treasury < st->min_treasury) st->min_treasury = s.treasury;
        if (s.treasury > st->max_treasury) st->max_treasury = s.treasury;
    }
    st->final_members = core_member_count(&s);
    st->final_stability = s.stability;
    memcpy(out_state, &s, sizeof s);
    return g_fail == fails0;
}

static void test_reg02(void)
{
    printf("REG-02 20-year simulations on seeded random worlds\n");
    int strat_total[AI_STRAT_COUNT] = {0}, gov_total = 0, wars_total = 0;
    for (uint32_t seed = 1; seed <= 8; seed++) {
        NationState s, s2; SimStats st, st2;
        static uint8_t b1[4096], b2[4096];
        sim_world(seed, &s, &st);
        printf("  seed %u: members %d stab %d treasury [%lld..%lld] final %lld, AI wars %d recog %d offers %d, unrest %d, max fx/day %d\n",
               seed, st.final_members, st.final_stability, (long long)st.min_treasury,
               (long long)st.max_treasury, (long long)s.treasury, st.ai_wars, st.recognitions,
               st.offers, st.unrest_starts, st.max_effects);
        printf("           strategies C/E/D/O %d/%d/%d/%d, gov changes %d, secessions %d, min AI war gap %d, "
               "war warnings %d\n", st.strat[0], st.strat[1], st.strat[2], st.strat[3], st.gov_changes,
               st.secessions, st.min_war_gap, st.warnings);
        for (int k = 0; k < AI_STRAT_COUNT; k++) strat_total[k] += st.strat[k];
        gov_total += st.gov_changes;
        wars_total += st.ai_wars;
        CHECKF(st.ai_actions >= 1, "seed %u: AI never initiated anything", seed);
        /* bound: at most one AI war per power per 180 days */
        CHECKF(st.ai_wars <= N_POWERS * (20 * 360 / 180 + 1), "seed %u: %d AI wars", seed, st.ai_wars);
        /* "not exploding": a 20-town nation nets ~0.3M/month; 100M = far beyond linear growth */
        CHECKF(st.max_treasury < 100000000LL, "seed %u: treasury %lld", seed, (long long)st.max_treasury);
        int n = core_serialize(&s, b1, sizeof b1);
        NationState r;
        CHECK(core_deserialize(&r, b1, n) == 1 && same_state(&r, &s));
        if (seed <= 2) {                             /* determinism: same seed, same history */
            sim_world(seed, &s2, &st2);
            CHECK(core_serialize(&s2, b2, sizeof b2) == n && memcmp(b1, b2, (size_t)n) == 0);
        }
    }
    for (int k = 0; k < AI_STRAT_COUNT; k++)
        CHECKF(strat_total[k] > 0, "strategy %s never chosen", core_ai_strategy_name(k));
    CHECKF(gov_total > 0 && wars_total > 0, "gov changes %d, AI wars %d", gov_total, wars_total);
}

static void test_names(void)
{
    printf("misc names / init\n");
    NationState s; core_init(&s);
    CHECK(strcmp(core_power_name(3), "Spain") == 0 && strcmp(core_power_name(9), "?") == 0);
    CHECK(strcmp(core_treaty_name(TREATY_CEASEFIRE), "Ceasefire") == 0);
    CHECK(strcmp(core_title_name(0), "Republic") == 0 && core_title_name(99) != NULL);
    CHECK(s.magic == NATION_MAGIC && s.version == NATION_STATE_VERSION && s.size == sizeof s);
    CHECK(!s.founded && core_member_count(&s) == 0 && s.capital == 0xFF);
    Config c; core_default_config(&c);
    CHECK(c.found_min_gold == 5000000 && c.found_min_ships == 10 && c.found_min_warships == 3 &&
          c.max_tax_pct == 50 && c.ai_eval_interval_days > 0);
    World w; make_world(&w); Effects e; memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);                      /* unfounded: nothing happens */
    CHECK(e.n == 0 && !s.founded);
}


/* ---- NAV: national navy ------------------------------------------------- */
static void month_end(NationState *s, World *w, const Config *c, Effects *e)
{
    w->day = s->last_month_day + 30;
    memset(e, 0, sizeof *e);
    core_daily(s, w, c, e);
}

static void test_navy(void)
{
    printf("NAV-01..08 national navy: rank, commissioning, upkeep, orders, naval command, towers, saves\n");
    Config c; World w; NationState s; Effects e; char why[200];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    /* town 0: pop 3000 -> 12 + 6 + stability 70/10 = 25 -> Fledgling state, 1 fleet */
    CHECKF(core_naval_rank(&s, &w) == 0 && core_fleet_cap(&s, &w) == 1, "rank %d stab %d treasury %lld",
           core_naval_rank(&s, &w), s.stability, (long long)s.treasury);

    /* NAV-02 commissioning needs the money, then the rank's limit */
    s.treasury = 100000;
    memset(&e, 0, sizeof e);
    CHECK(core_navy_commission(&s, &w, &c, &e, why, sizeof why) == 0 && strstr(why, "120000"));
    CHECK(s.treasury == 100000 && e.n == 0);
    s.treasury = 500000;                                   /* +10 score -> 35: Regional power */
    CHECK(core_naval_rank(&s, &w) == 1 && core_fleet_cap(&s, &w) == 3);
    s.treasury = 200000;                                   /* +4 -> 29: Fledgling, 1 fleet */
    memset(&e, 0, sizeof e);
    CHECK(core_navy_commission(&s, &w, &c, &e, why, sizeof why) == 1);
    CHECK(s.treasury == 80000 && has_fx(&e, FX_FLEET_SPAWN, 0, -1) && s.navy.fleet_target == 1);
    CHECK(has_msg(&e, "A new fleet of Tortuga is fitted out in town 0") && !has_msg(&e, "Tortugan"));
    w.nation_fleets = 3;
    s.treasury = 1000000;
    memset(&e, 0, sizeof e);
    CHECK(core_navy_commission(&s, &w, &c, &e, why, sizeof why) == 0 && strstr(why, "at most 3"));

    /* NAV-03 monthly military upkeep: its own line, exact */
    w.nation_fleets = 2;
    s.navy.fleet_target = 2;
    s.national_convoys = 0;
    int64_t t0 = s.treasury = 400000;
    month_end(&s, &w, &c, &e);
    CHECK(s.navy.last_military == 2 * 6000);
    CHECKF(s.treasury == t0 + s.last_tax_income + s.last_tariff_income - s.last_upkeep - 12000,
           "treasury=%lld", (long long)s.treasury);
    CHECK(has_msg(&e, "navy and forts -12000"));
    CHECK(!has_fx(&e, FX_FLEET_SPAWN, -1, -1) && !has_fx(&e, FX_FLEET_DISBAND, -1, -1));

    /* NAV-04 orders unlock with rank */
    memset(&e, 0, sizeof e);
    CHECK(core_navy_set_order(&s, &w, NAVY_RAID, &e, why, sizeof why) == 0 && strstr(why, "Naval power"));
    memset(&e, 0, sizeof e);
    core_annex(&s, &w, 2, 1, &e);                          /* +12 +10 (pop 5000) */
    apply_fx(&w, &e);
    s.treasury = 1000000;
    CHECK(core_naval_rank(&s, &w) == 2 && core_fleet_cap(&s, &w) == 6);
    memset(&e, 0, sizeof e);
    CHECK(core_navy_set_order(&s, &w, NAVY_RAID, &e, why, sizeof why) == 1 && s.navy.order == NAVY_RAID);
    CHECK(has_fx(&e, FX_FLEET_ORDER, NAVY_RAID, -1));
    memset(&e, 0, sizeof e);
    CHECK(core_navy_set_order(&s, &w, NAVY_WAR, &e, why, sizeof why) == 0 && strstr(why, "Great power"));

    /* rank falls (treasury spent on the navy) -> fleets and order stay; only new ones are blocked */
    s.treasury = 0;
    w.nation_fleets = 2;
    s.navy.fleet_target = 2;
    month_end(&s, &w, &c, &e);
    CHECK(core_naval_rank(&s, &w) == 1 && s.navy.order == NAVY_RAID);
    CHECK(!has_fx(&e, FX_FLEET_ORDER, -1, -1) && !has_fx(&e, FX_FLEET_DISBAND, -1, -1));
    memset(&e, 0, sizeof e);
    CHECK(core_navy_set_order(&s, &w, NAVY_RAID, &e, why, sizeof why) == 0);     /* cannot re-issue it */
    CHECK(core_navy_set_order(&s, &w, NAVY_PATROL, &e, why, sizeof why) == 1 && s.navy.order == NAVY_PATROL);

    /* NAV-05 unpaid crews desert after two insolvent month ends */
    w.nation_fleets = 2;
    s.navy.fleet_target = 2;
    s.treasury = -50000;
    month_end(&s, &w, &c, &e);
    CHECK(s.navy.unpaid_months == 1 && !has_fx(&e, FX_FLEET_DISBAND, -1, -1));
    month_end(&s, &w, &c, &e);
    CHECK(has_fx(&e, FX_FLEET_DISBAND, 1, -1) && has_msg(&e, "desert") && s.navy.fleet_target == 1);
    CHECK(s.navy.unpaid_months == 0);

    /* NAV-06 the naval command replaces a lost fleet, and pays off fleets above the target */
    w.nation_fleets = 0;
    s.navy.fleet_target = 1;
    s.treasury = 600000;
    month_end(&s, &w, &c, &e);
    CHECK(has_fx(&e, FX_FLEET_SPAWN, s.capital, -1) && has_msg(&e, "replace a loss"));
    w.nation_fleets = 3;
    s.navy.fleet_target = 1;
    month_end(&s, &w, &c, &e);
    CHECK(has_fx(&e, FX_FLEET_DISBAND, 2, -1));
    memset(&e, 0, sizeof e);
    CHECK(core_navy_decommission(&s, &w, &e, why, sizeof why) == 1 && s.navy.fleet_target == 2);
    w.nation_fleets = 0;
    CHECK(core_navy_decommission(&s, &w, &e, why, sizeof why) == 0);

    /* NAV-07 garrison and towers are paid from the treasury; bought towers cost upkeep */
    s.treasury = 100000;
    memset(&e, 0, sizeof e);
    CHECK(core_navy_reinforce(&s, &w, &c, 2, &e, why, sizeof why) == 1);
    CHECK(s.treasury == 80000 && e.n == 1 && e.fx[0].kind == FX_GARRISON && e.fx[0].v == 20000);
    CHECK(core_navy_reinforce(&s, &w, &c, 3, &e, why, sizeof why) == 0);       /* not a member */
    w.town[2].cannons = 2;
    memset(&e, 0, sizeof e);
    CHECK(core_navy_build_tower(&s, &w, &c, 2, &e, why, sizeof why) == 1);
    CHECK(s.treasury == 30000 && s.navy.towers_bought[2] == 1 && has_fx(&e, FX_TOWER, 2, -1));
    CHECK(core_navy_build_tower(&s, &w, &c, 2, &e, why, sizeof why) == 0);     /* 30000 < 50000 */
    w.town[0].cannons = 10;
    s.treasury = 1000000;
    CHECK(core_navy_build_tower(&s, &w, &c, 0, &e, why, sizeof why) == 0 && strstr(why, "10 cannon"));
    CHECK(core_military_upkeep(&s, &w, &c) == 500);
    core_navy_credit(&s, 7000);
    CHECK(s.treasury == 1007000 && s.navy.plunder_total == 7000 && s.navy.last_plunder == 7000);

    /* NAV-08 saves: version 2 round-trips the navy; a version-1 save loads with an empty navy */
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    s.navy.fleet_target = 2; s.navy.order = NAVY_PATROL;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState) && core_deserialize(&back, buf, n) == 1);
    CHECK(memcmp(&back.navy, &s.navy, offsetof(NationState, navy.checksum2) - offsetof(NationState, navy)) == 0 &&
          same_state(&back, &s));
    buf[offsetof(NationState, navy) + 1] ^= 1;               /* damage the navy part */
    CHECK(core_deserialize(&back, buf, n) == 0);
    n = core_serialize(&s, buf, sizeof buf);
    NationState v1;
    memcpy(&v1, buf, NATION_STATE_V1_SIZE);
    v1.version = 1;
    v1.size = NATION_STATE_V1_SIZE;
    memcpy(buf, &v1, NATION_STATE_V1_SIZE);
    {
        uint32_t h = 2166136261u;                            /* the version-1 checksum (FNV-1a) */
        for (size_t i = 0; i < offsetof(NationState, checksum); i++) { h ^= buf[i]; h *= 16777619u; }
        memcpy(buf + offsetof(NationState, checksum), &h, 4);
    }
    CHECK(core_deserialize(&back, buf, NATION_STATE_V1_SIZE) == 1);
    CHECK(back.navy.fleet_target == 0 && back.navy.plunder_total == 0 && back.founded == 1 &&
          strcmp(back.name, "Tortuga") == 0);
}


static void test_peaceful(void)
{
    printf("TER-04/05 buying towns and petitions\n");
    Config c; World w; NationState s; Effects e; char why[200];
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    /* town 3: small Spanish town, no property -> not for sale */
    CHECK(core_buy_chance(&s, &w, 3) == 0);
    memset(&e, 0, sizeof e);
    CHECK(core_buy_town(&s, &w, 3, &e, why, sizeof why) == 0 && strstr(why, "not for sale"));
    w.town[3].player_property = 1;
    int64_t price = core_town_price(&s, &w, 3);
    CHECK(price == 2000 * 60 + 200000 / 2);                       /* 220,000 */
    s.treasury = price - 1;
    CHECK(core_buy_town(&s, &w, 3, &e, why, sizeof why) == 0 && strstr(why, "price"));
    /* a governor's seat costs double; a viceroy seat is never for sale */
    w.town[1].player_property = 1;
    CHECK(core_buy_chance(&s, &w, 1) == 0);
    /* friendly Spain sells */
    s.treasury = 1000000;
    s.rel[3].score = 100;
    s.rel[3].recognized = 1;
    w.reputation[3] = 100;
    int ch = core_buy_chance(&s, &w, 3);
    CHECKF(ch >= 80, "chance %d", ch);
    int ok = 0;
    for (int d = 0; d < 20 && !ok; d++) {                          /* the roll varies by day */
        w.day = 2000 + (uint32_t)d;
        memset(&e, 0, sizeof e);
        ok = core_buy_town(&s, &w, 3, &e, why, sizeof why);
    }
    CHECK(ok == 1 && s.town[3].member == 1 && s.treasury == 1000000 - price);
    CHECK(has_fx(&e, FX_TOWN_TO_NATION, 3, -1) && has_msg(&e, "sells town 3"));
    /* no sale during a war */
    w.town[2].player_property = 1;
    s.rel[3].status = TREATY_WAR;
    CHECK(core_buy_chance(&s, &w, 2) == 0);
    s.rel[3].status = TREATY_PEACE;

    /* petitions: a prosperous town with property asks; accept -> joins with loyalty 70 */
    apply_fx(&w, &e);
    s.stability = 90;
    w.town[5].player_property = 1;
    w.town[5].wealth = 500000;
    int asked = -1;
    for (int m = 0; m < 40 && asked < 0; m++) {
        w.day = s.last_month_day + 30;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        asked = core_petition_town(&s);
    }
    CHECKF(asked >= 0 && !s.town[asked].member, "petition %d", asked);
    CHECK(has_msg(&e, "ask to join Tortuga. Answer them"));
    memset(&e, 0, sizeof e);
    CHECK(core_answer_petition(&s, &w, 1, &e, why, sizeof why) == 1 && s.town[asked].member == 1);
    CHECK(s.town[asked].loyalty == 70 && core_petition_town(&s) == -1);
    CHECK(core_answer_petition(&s, &w, 1, &e, why, sizeof why) == 0);
    /* a declined petition only lapses */
    s.navy.petition = 8;                                           /* town 7 */
    memset(&e, 0, sizeof e);
    CHECK(core_answer_petition(&s, &w, 0, &e, why, sizeof why) == 1 && s.town[7].member == 0 && !s.navy.petition);
    /* the petition survives a save */
    s.navy.petition = 6;
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(core_deserialize(&back, buf, n) == 1 && core_petition_town(&back) == 5);
}

/* Officials in member towns serve the player (the own-town officials change); everywhere else vanilla. */
static void test_officials(void)
{
    NationState s;
    core_init(&s);
    CHECK(!core_officials_serve(&s, 3, NATION_ID));          /* no nation yet */
    s.founded = 1;
    s.town[3].member = 1;
    s.town[7].member = 1;
    CHECK(core_officials_serve(&s, 3, NATION_ID));           /* member town, byte 5 */
    CHECK(core_officials_serve(&s, 7, NATION_ID));
    CHECK(!core_officials_serve(&s, 4, NATION_ID));          /* nation-5 town not ours (vanilla own town) */
    CHECK(!core_officials_serve(&s, 3, 2));                  /* retaken by Holland: vanilla */
    CHECK(!core_officials_serve(&s, 4, 3));                  /* a Spanish town */
    CHECK(!core_officials_serve(&s, -1, NATION_ID));
    CHECK(!core_officials_serve(&s, MAX_TOWNS, NATION_ID));
    CHECK(!core_officials_serve(NULL, 3, NATION_ID));
    /* survives a save round trip */
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(core_deserialize(&back, buf, n) == 1 && core_officials_serve(&back, 7, NATION_ID));
}

/* Town info of a member town (the conquered-town info fix): loyalty word and the town's role */
static void test_town_info_labels(void)
{
    TownState ts;
    char b[48];
    memset(&ts, 0, sizeof ts);
    ts.loyalty = 72;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == 1 && !strcmp(b, "loyal (72)"));
    ts.loyalty = 50;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == 1 && !strcmp(b, "loyal (50)"));
    ts.loyalty = 49;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == 0 && !strcmp(b, "calm (49)"));
    ts.loyalty = 20;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == 0 && !strcmp(b, "calm (20)"));
    ts.loyalty = 18;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == -1 && !strcmp(b, "restless (18)"));
    ts.loyalty = 35;
    ts.unrest = 1;                                    /* a month below 20 already counted */
    CHECK(core_loyalty_label(&ts, b, sizeof b) == -1 && !strcmp(b, "restless (35)"));
    ts.unrest = 2;
    CHECK(core_loyalty_label(&ts, b, sizeof b) == -1 && !strcmp(b, "in unrest"));
    CHECK(core_loyalty_label(NULL, b, sizeof b) == 0 && b[0] == 0);
    CHECK(core_loyalty_label(&ts, b, 4) == -1 && !strcmp(b, "in "));   /* truncated, terminated */

    NationState s;
    core_init(&s);
    CHECK(!core_town_role(&s, 3, b, sizeof b) && b[0] == 0);          /* no nation */
    s.founded = 1;
    snprintf(s.name, sizeof s.name, "<the player's nation>");
    s.capital = 3;
    s.town[3].member = 1;
    s.town[9].member = 1;
    CHECK(core_town_role(&s, 3, b, sizeof b) && !strcmp(b, "Capital of <the player's nation>"));
    CHECK(core_town_role(&s, 9, b, sizeof b) && !strcmp(b, "Town of <the player's nation>"));
    CHECK(!core_town_role(&s, 4, b, sizeof b) && b[0] == 0);          /* a power's town */
    CHECK(!core_town_role(&s, -1, b, sizeof b) && !core_town_role(&s, MAX_TOWNS, b, sizeof b));
}

/* ---- PRM: building permit in the nation's own towns ---------------------- */
static int count_fx(const Effects *e, FxKind k, int a, int b)
{
    int n = 0;
    for (int i = 0; i < e->n; i++)
        if (e->fx[i].kind == k && (a < 0 || e->fx[i].a == a) && (b < 0 || e->fx[i].b == b)) n++;
    return n;
}

static void test_permit(void)
{
    printf("PRM-01..05 building permit: granted on joining, restored on leaving, old saves\n");
    Config c; World w; NationState s, r; Effects e; char why[160];
    static uint8_t buf[sizeof(NationState) + 16];
    core_default_config(&c);

    /* PRM-01 founding grants the capital's permit; it was not held before */
    make_world(&w);
    memset(&e, 0, sizeof e);
    core_init(&s);
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 2, 1, &e, why, sizeof why) == 1);
    CHECK(s.town[0].permit_before == PERMIT_HAD_NONE);
    CHECK(count_fx(&e, FX_PERMIT, 0, 1) == 1 && count_fx(&e, FX_PERMIT, -1, -1) == 1);
    CHECK(has_msg(&e, "You may build there without a permit"));
    apply_fx(&w, &e);
    CHECK(w.town[0].permit == 1);
    /* a capital where the player had bought the permit: remembered, nothing to grant */
    make_world(&w);
    w.town[0].permit = 1;
    memset(&e, 0, sizeof e);
    core_init(&s);
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 2, 1, &e, why, sizeof why) == 1);
    CHECK(s.town[0].permit_before == PERMIT_HAD && count_fx(&e, FX_PERMIT, -1, -1) == 0);
    /* a refused founding grants nothing */
    make_world(&w); w.player_gold = 10;
    memset(&e, 0, sizeof e); core_init(&s);
    CHECK(core_found(&s, &w, &c, 0, "Tortuga", "Tortugan", 2, 1, &e, why, sizeof why) == 0 && e.n == 0);

    /* PRM-02 every way of joining grants the permit at once (conquest, treaty/purchase, petition) */
    make_world(&w);
    found_ok(&s, &w, &c);
    w.town[3].permit = 1;                         /* earned in town 3 before it joins */
    memset(&e, 0, sizeof e);
    CHECK(annex_conq(&s, &w, 2, &e) == 1);
    CHECK(s.town[2].permit_before == PERMIT_HAD_NONE && count_fx(&e, FX_PERMIT, 2, 1) == 1);
    CHECK(has_msg(&e, "has joined Tortuga by conquest. You may now build there."));
    CHECK(core_annex(&s, &w, 3, 1, &e) == 1);
    CHECK(s.town[3].permit_before == PERMIT_HAD && count_fx(&e, FX_PERMIT, 3, -1) == 0);
    CHECK(core_annex(&s, &w, 4, 2, &e) == 1);
    CHECK(s.town[4].permit_before == PERMIT_HAD_NONE && count_fx(&e, FX_PERMIT, 4, 1) == 1);
    apply_fx(&w, &e);
    CHECK(w.town[2].permit && w.town[3].permit && w.town[4].permit);
    CHECK(!w.town[5].permit && !w.town[6].permit);    /* PRM-05 foreign towns untouched */
    /* a sync right after joining has nothing to do */
    memset(&e, 0, sizeof e);
    CHECK(core_permit_sync(&s, &w, &e) == 0 && e.n == 0);

    /* PRM-03 leaving restores the state from before joining; property stays */
    memset(&e, 0, sizeof e);
    CHECK(core_lose_town(&s, &w, 2, 3, &e) == 1);
    CHECK(count_fx(&e, FX_PERMIT, 2, 0) == 1 && s.town[2].permit_before == PERMIT_UNKNOWN);
    CHECK(core_lose_town(&s, &w, 3, 3, &e) == 1);
    CHECK(count_fx(&e, FX_PERMIT, 3, -1) == 0);       /* earned before: kept */
    apply_fx(&w, &e);
    CHECK(!w.town[2].permit && w.town[3].permit && w.town[2].player_property == 1);
    /* earned before, given up while a member, then lost: the earned permit comes back */
    CHECK(core_annex(&s, &w, 3, 1, &e) == 1 && s.town[3].permit_before == PERMIT_HAD);
    w.town[3].permit = 0;
    memset(&e, 0, sizeof e);
    CHECK(core_lose_town(&s, &w, 3, 0, &e) == 1 && count_fx(&e, FX_PERMIT, 3, 1) == 1);
    apply_fx(&w, &e);
    CHECK(w.town[3].permit == 1);
    /* a town the game reports as retaken by a power (core_daily) is restored too */
    CHECK(s.town[4].member && s.town[4].permit_before == PERMIT_HAD_NONE && w.town[4].permit);
    w.town[4].power = 0;
    w.day = s.last_month_day + 1;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(!s.town[4].member && count_fx(&e, FX_PERMIT, 4, 0) == 1);
    apply_fx(&w, &e);
    CHECK(!w.town[4].permit);

    /* PRM-04 a save from before this feature: members carry PERMIT_UNKNOWN (old padding = 0) */
    make_world(&w);
    found_ok(&s, &w, &c);
    memset(&e, 0, sizeof e);
    core_annex(&s, &w, 2, 1, &e);
    core_annex(&s, &w, 3, 1, &e);
    w.town[0].permit = w.town[2].permit = 0;          /* the old mod granted nothing */
    w.town[3].permit = 1;                             /* bought there by the player */
    for (int t = 0; t < MAX_TOWNS; t++) s.town[t].permit_before = PERMIT_UNKNOWN;
    s.town[7].permit_before = 0x5A;                   /* stray value in a non-member's padding */
    s.town[2].permit_before = 0x17;                   /* and in a member's */
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(core_deserialize(&r, buf, n) == 1);
    CHECK(r.town[7].permit_before == PERMIT_UNKNOWN && r.town[2].permit_before == PERMIT_UNKNOWN);
    memset(&e, 0, sizeof e);
    CHECK(core_permit_sync(&r, &w, &e) == 2);         /* on load */
    CHECK(count_fx(&e, FX_PERMIT, 0, 1) == 1 && count_fx(&e, FX_PERMIT, 2, 1) == 1);
    CHECK(count_fx(&e, FX_PERMIT, 3, -1) == 0 && count_fx(&e, FX_PERMIT, -1, 0) == 0);
    CHECK(r.town[0].permit_before == PERMIT_HAD_NONE && r.town[2].permit_before == PERMIT_HAD_NONE);
    CHECK(r.town[3].permit_before == PERMIT_HAD && r.town[7].permit_before == PERMIT_UNKNOWN);
    apply_fx(&w, &e);
    /* the recorded state survives a save round trip and is not re-recorded */
    n = core_serialize(&r, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState) && core_deserialize(&s, buf, n) == 1 && same_state(&s, &r));
    CHECK(s.town[0].permit_before == PERMIT_HAD_NONE && s.town[3].permit_before == PERMIT_HAD);
    memset(&e, 0, sizeof e);
    CHECK(core_permit_sync(&s, &w, &e) == 0);
    CHECK(core_lose_town(&s, &w, 2, 3, &e) == 1 && count_fx(&e, FX_PERMIT, 2, 0) == 1);

    /* the day after the player gives a member town's permit up, it is granted again */
    w.town[0].permit = 0;
    w.day = s.last_month_day + 2;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(count_fx(&e, FX_PERMIT, 0, 1) == 1 && count_fx(&e, FX_PERMIT, -1, -1) == 1);

    /* PRM-05 no nation: nothing happens anywhere */
    NationState u; core_init(&u);
    memset(&e, 0, sizeof e);
    CHECK(core_permit_sync(&u, &w, &e) == 0 && e.n == 0);
    /* a full effect queue never overflows */
    make_world(&w);
    found_ok(&s, &w, &c);
    for (int t = 2; t < w.n_towns; t++) { s.town[t].member = 1; s.town[t].permit_before = PERMIT_UNKNOWN; }
    memset(&e, 0, sizeof e);
    e.n = 60;
    core_permit_sync(&s, &w, &e);
    CHECK(e.n == 64);
}

static void test_ledger(void)
{
    printf("ECO-03 national accounts by category: booked, forecast, closed at the month end, saved\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    s.town[0].loyalty = 80;
    s.treasury = 0;
    memset(&s.ledger, 0, sizeof s.ledger);
    memset(&e, 0, sizeof e);
    CHECK(core_donate(&s, &w, 50000, &e) == 1);
    memset(&e, 0, sizeof e);
    CHECK(core_withdraw(&s, &w, 10000, &e) == 1);
    CHECK(s.ledger.month[1][LG_DONATION] == 50000 && s.ledger.month[1][LG_WITHDRAWAL] == -10000);
    core_refund(&s, 2000, LG_TOWERS);
    CHECK(s.ledger.month[1][LG_TOWERS] == 2000 && s.treasury == 42000);

    int64_t f[LEDGER_CATS];
    core_ledger_forecast(&s, &w, &c, f);
    CHECK(f[LG_TAX] == core_monthly_tax_estimate(&s, &w) && f[LG_TAX] == 7740);
    CHECK(f[LG_ADMIN] == -2000 && f[LG_DONATION] == 50000 && f[LG_FLEET_UPKEEP] == 0);
    int64_t sum = 0;
    for (int k = 0; k < LEDGER_CATS; k++) sum += f[k];
    CHECK(sum == 50000 - 10000 + 2000 + 7740 - 2000);

    w.day = s.last_month_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(s.ledger.month[0][LG_TAX] == s.last_tax_income && s.last_tax_income == 7740);
    CHECK(s.ledger.month[0][LG_ADMIN] == -s.last_upkeep && s.ledger.month[0][LG_DONATION] == 50000);
    int any = 0;
    for (int k = 0; k < LEDGER_CATS; k++) any |= s.ledger.month[1][k];
    CHECK(any == 0);                                         /* a new month starts empty */
    CHECK(strcmp(core_ledger_name(LG_TOWNS), "Towns bought") == 0);

    /* version 3 saves the accounts; a version-2 save loads with empty accounts */
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState) && core_deserialize(&back, buf, n) == 1);
    CHECK(memcmp(back.ledger.month, s.ledger.month, sizeof s.ledger.month) == 0);
    buf[offsetof(NationState, ledger) + 2] ^= 1;
    CHECK(core_deserialize(&back, buf, n) == 0);             /* damaged accounts */
    n = core_serialize(&s, buf, sizeof buf);
    uint16_t v2 = 2, sz2 = NATION_STATE_V2_SIZE;
    memcpy(buf + offsetof(NationState, version), &v2, 2);
    memcpy(buf + offsetof(NationState, size), &sz2, 2);
    {
        uint32_t h = 2166136261u;
        for (size_t i = 0; i < offsetof(NationState, checksum); i++) { h ^= buf[i]; h *= 16777619u; }
        memcpy(buf + offsetof(NationState, checksum), &h, 4);
    }
    CHECK(core_deserialize(&back, buf, NATION_STATE_V2_SIZE) == 1);
    CHECK(back.ledger.month[0][LG_TAX] == 0 && back.navy.order == s.navy.order && strcmp(back.name, "Tortuga") == 0);
}

/* the removal of national convoys: national convoys are off. An older save's counter loads as 0 and is never charged;
   with one town and no fleets or towers the month costs exactly 2,000. */
static void test_no_convoys(void)
{
    printf("ECO-04 national convoys removed: no convoy upkeep, an old save's counter is dropped\n");
#if NATION_CONVOYS
    printf("  (skipped: built with NATION_CONVOYS)\n");
#else
    Config c; World w; NationState s, back; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    s.town[0].loyalty = 80;
    s.national_convoys = 2;                                  /* as an older save would have it */
    static uint8_t buf[sizeof(NationState) + 16];
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n == (int)sizeof(NationState) && core_deserialize(&back, buf, n) == 1);
    CHECK(back.national_convoys == 0 && back.treasury == s.treasury);
    s.national_convoys = 2;                                  /* even if it were still set: not charged */
    int64_t f[LEDGER_CATS];
    core_ledger_forecast(&s, &w, &c, f);
    CHECK(f[LG_ADMIN] == -2000);
    int64_t t0 = s.treasury, est = core_monthly_tax_estimate(&s, &w);
    w.day = s.last_month_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECKF(s.last_upkeep == 2000 && s.treasury == t0 + est - 2000, "upkeep=%d treasury=%lld",
           s.last_upkeep, (long long)s.treasury);
    CHECK(s.ledger.month[0][LG_ADMIN] == -2000 && s.ledger.month[0][LG_FLEET_UPKEEP] == 0 &&
          s.ledger.month[0][LG_TOWER_UPKEEP] == 0);
    CHECK(has_msg(&e, "upkeep -2000") && !has_msg(&e, "convoy"));
#endif
}

static void test_wording(void)
{
    printf("TXT-01 messages: a/an before a word, the nation's name in navy and petition messages\n");
    CHECK(!strcmp(core_article("English", 1), "An") && !strcmp(core_article("Spanish", 1), "A"));
    CHECK(!strcmp(core_article("Alliance", 0), "an") && !strcmp(core_article("Trade agreement", 0), "a"));
    CHECK(!strcmp(core_article("Dutch", 0), "a") && !strcmp(core_article("", 0), "a") && !strcmp(core_article(NULL, 1), "A"));
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    make_world(&w);
    found_ok(&s, &w, &c);
    snprintf(s.adjective, sizeof s.adjective, "%s", "Turk Islands");   /* the panel stores the capital here */
    s.treasury = 1000000;
    s.navy.fleet_target = 2;                                         /* a lost fleet is replaced */
    w.nation_fleets = 1;
    w.day = s.last_month_day + 30;
    memset(&e, 0, sizeof e);
    core_daily(&s, &w, &c, &e);
    CHECK(has_msg(&e, "The naval command of Tortuga fits out a new fleet") && !has_msg(&e, "Turk Islands"));
}

/* ---- WAR-WARN: no war out of nowhere (the Holland war fix) ---------------------------------- */
static char g_trace_buf[64][320];
static int g_trace_n;
static void capture_trace(const char *line)
{
    if (g_trace_n < 64) snprintf(g_trace_buf[g_trace_n++], sizeof g_trace_buf[0], "%s", line);
}
static int traced(const char *a, const char *b)
{
    for (int i = 0; i < g_trace_n; i++)
        if (strstr(g_trace_buf[i], a) && (!b || strstr(g_trace_buf[i], b))) return 1;
    return 0;
}

/* the player's game (the reporter's files the former sovereign of the capital, at peace, relation -38 and still
   recovering, reputation 90, 385 days after the last treaty change, while the nation fights England
   (so the power is Opportunistic: war from -20). Here the former sovereign is Spain (capital town 0). */
static void ferra_world(NationState *s, World *w, const Config *c)
{
    make_world(w);
    found_ok(s, w, c);
    w->reputation[3] = 90;
    s->rel[3].status = TREATY_PEACE; s->rel[3].score = -38; s->rel[3].last_change_day = w->day - 385;
    s->rel[3].threat = THREAT_NONE;
    s->rel[0].status = TREATY_WAR; s->rel[0].score = -90; s->rel[0].last_change_day = w->day - 245;
    s->rel[0].war_exhaustion = 48; g_war[0] = 1;
    s->treasury = 386686;
}

/* runs the game days up to `days`; returns the first day the power declared war (0 = none) and
   the day of its first warning (*warn_day) */
static uint32_t run_until_war(NationState *s, World *w, const Config *c, int p, int days, uint32_t *warn_day,
                              int *eased)
{
    Effects e;
    char needle[64];
    snprintf(needle, sizeof needle, "%s may declare war", core_power_name(p));
    for (int d = 0; d < days; d++) {
        w->day++;
        memset(&e, 0, sizeof e);
        core_daily(s, w, c, &e);
        if (has_msg(&e, needle) && warn_day && !*warn_day) *warn_day = w->day;
        if (eased && has_msg(&e, "eases")) (*eased)++;
        int war = has_fx(&e, FX_SET_WAR, p, 1);
        apply_fx(w, &e);
        if (war) return w->day;
    }
    return 0;
}

/* the New Game crash fix: the human player handle during a New Game's pre-simulation is 0x0009FFFF (index 0xFFFF),
   not 0; the DLL must see "no player" there and never index the CPlayer pool with 0xFFFF */
static void test_player_handle(void)
{
    printf("player handles (the New Game crash fix, research/human_handle_presim.md)\n");
    CHECK(core_player_index(0, 16) == -1);                       /* no game */
    CHECK(core_player_index(0x0009FFFFu, 16) == -1);             /* the pre-simulation value (both machines) */
    CHECK(core_player_index(0x0009FFFFu, 0xFFFFu) == -1);        /* 0xFFFF is never an index, whatever the pool */
    CHECK(core_player_index(0xFFE9FFFFu, 0xFFFFu) == -1);        /* any generation with index 0xFFFF */
    CHECK(core_player_index(0x00090000u, 16) == 0);              /* slot 0, generation 0 */
    CHECK(core_player_index(0x00290003u, 16) == 3);              /* generation 1 */
    CHECK(core_player_index(0x0009000Fu, 16) == 15);
    CHECK(core_player_index(0x00090010u, 16) == -1);             /* beyond the pool's capacity */
    CHECK(core_player_index(0x00090003u, 0) == -1);              /* no pool */
    CHECK(core_player_index(0x00010003u, 16) == -1);             /* a town handle (type 1) */
    CHECK(core_player_index(0x000A0003u, 16) == -1);             /* type 10 */
    CHECK(core_player_tag_ok(0x00090003u, 0x0000));
    CHECK(core_player_tag_ok(0x00290003u, 0x0001));
    CHECK(!core_player_tag_ok(0x00290003u, 0x0002));             /* a reused slot: stale handle */
    CHECK(core_player_tag_ok(0xFFE90003u, 0x07FF));
    CHECK(core_player_tag_ok(0xFFE90003u, 0xFFFF));              /* only 11 bits are compared */
    CHECK(!core_player_tag_ok(0xFFE90003u, 0x07FE));
}

static void test_war_warning(void)
{
    printf("WAR-01 a power at peace warns first and declares war a month later at the earliest\n");
    Config c; World w; NationState s; Effects e;
    core_default_config(&c);
    ferra_world(&s, &w, &c);
    CHECK(core_ai_strategy(&s, &w, 3) == AI_STRAT_OPPORTUNISTIC);
    /* the first AI evaluation: a warning that names the causes, no war */
    int got_warning = 0;
    for (int d = 0; d < 7 && !got_warning; d++) {
        w.day++;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        CHECK(!has_fx(&e, FX_SET_WAR, 3, 1));
        if (has_msg(&e, "Spain may declare war on Tortuga")) {
            got_warning = 1;
            CHECK(has_msg(&e, "relations are unfriendly (-38)") && has_msg(&e, "tied up in its war with England"));
            CHECK(has_msg(&e, "former sovereign of the capital -20") && has_msg(&e, "reputation 90: +20"));
            CHECK(s.rel[3].threat == THREAT_BASE + 1 && s.rel[3].status == TREATY_PEACE);
        }
        apply_fx(&w, &e);
    }
    CHECK(got_warning);
    uint32_t warned = w.day, warn2 = 0;
    uint32_t war = run_until_war(&s, &w, &c, 3, 400, &warn2, NULL);
    CHECKF(war && war >= warned + 7 * THREAT_EVALS, "warned day %u, war day %u", warned, war);
    CHECK(warn2 == 0);                                     /* one warning, not one per evaluation */
    CHECK(s.rel[3].status == TREATY_WAR && s.rel[3].threat == THREAT_NONE);

    printf("WAR-02 the warning lapses when relations improve (a ceasefire with England)\n");
    ferra_world(&s, &w, &c);
    uint32_t wd = 0;
    CHECK(run_until_war(&s, &w, &c, 3, 7, &wd, NULL) == 0 && wd && s.rel[3].threat);
    s.rel[0].status = TREATY_CEASEFIRE; s.rel[0].expiry_day = w.day + 60; g_war[0] = 0;   /* England */
    CHECK(core_ai_strategy(&s, &w, 3) == AI_STRAT_COMMERCIAL);                           /* rep 90 */
    int eased = 0;
    CHECK(run_until_war(&s, &w, &c, 3, 7, NULL, &eased) == 0);
    CHECK(eased == 1 && s.rel[3].threat == THREAT_NONE);
    CHECK(run_until_war(&s, &w, &c, 3, 360, NULL, NULL) == 0);          /* -38 is far above -60 */

    /* a power that goes to war with another power turns defensive: the warning lapses, saying why */
    ferra_world(&s, &w, &c);
    wd = 0;
    run_until_war(&s, &w, &c, 3, 7, &wd, NULL);
    w.power_war[3][1] = w.power_war[1][3] = 1;                 /* Spain fights France now */
    CHECK(core_ai_strategy(&s, &w, 3) == AI_STRAT_DEFENSIVE);
    int lapsed = 0;
    for (int d = 0; d < 7; d++) {
        w.day++;
        memset(&e, 0, sizeof e);
        core_daily(&s, &w, &c, &e);
        if (has_msg(&e, "Spain no longer threatens war on Tortuga: it is at war with France now")) lapsed++;
        apply_fx(&w, &e);
    }
    CHECK(lapsed == 1 && s.rel[3].threat == THREAT_NONE);

    printf("WAR-03 a war needs a fresh warning after the tension eased\n");
    ferra_world(&s, &w, &c);
    wd = 0;
    run_until_war(&s, &w, &c, 3, 7, &wd, NULL);
    s.rel[3].score = 0;                                     /* e.g. a gift of reputation */
    eased = 0;
    run_until_war(&s, &w, &c, 3, 7, NULL, &eased);
    CHECK(eased == 1 && !s.rel[3].threat);
    s.rel[3].score = -38;
    uint32_t w2 = 0;
    uint32_t start = w.day;
    war = run_until_war(&s, &w, &c, 3, 400, &w2, NULL);
    CHECKF(w2 > start && war >= w2 + 7 * THREAT_EVALS, "new warning %u, war %u", w2, war);

    printf("WAR-04 the trace names every relation change and every war decision\n");
    ferra_world(&s, &w, &c);
    g_trace_n = 0;
    core_set_trace(capture_trace);
    w.day = s.last_month_day + 29;                          /* the month end comes tomorrow */
    run_until_war(&s, &w, &c, 3, 8, NULL, NULL);
    core_set_trace(NULL);
    CHECK(traced("REL Spain score -38 -> -36", "monthly drift towards 0 = reputation 90: +20"));
    CHECK(traced("REL Spain score", "former sovereign of the capital -20"));
    CHECK(traced("AI Spain (Opportunistic", "-> WARNING"));
    CHECK(traced("REL England score", "monthly drift"));
    g_trace_n = 0;
    core_set_trace(capture_trace);
    memset(&e, 0, sizeof e);
    core_declare_war(&s, &w, 1, &e);                        /* the player's own declaration */
    core_set_trace(NULL);
    CHECK(traced("REL France score", "the nation declared war on it"));
    int rep_cause = 0;
    for (int i = 0; i < e.n; i++)
        if (e.fx[i].kind == FX_REPUTATION && strstr(e.fx[i].text, "declared war")) rep_cause = 1;
    CHECK(rep_cause);                                       /* reputation effects carry their cause */

    printf("WAR-05 the warning is saved; older saves (padding) have none\n");
    ferra_world(&s, &w, &c);
    s.rel[3].threat = THREAT_BASE + 2;
    s.rel[1].threat = 0x37;                                 /* what stray padding could hold */
    static uint8_t buf[sizeof(NationState) + 16];
    NationState back;
    int n = core_serialize(&s, buf, sizeof buf);
    CHECK(n > 0 && core_deserialize(&back, buf, n) == 1);
    CHECK(back.rel[3].threat == THREAT_BASE + 2 && back.rel[1].threat == THREAT_NONE &&
          back.rel[0].threat == THREAT_NONE);
}

int main(void)
{
    test_wording();
    test_officials();
    test_town_info_labels();
    test_names();
    test_fnd01();
    test_fnd02();
    test_fnd03();
    test_adjective();
    test_ter01_02();
    test_ter03();
    test_dip01();
    test_dip02();
    test_eco01();
    test_eco02();
    test_sav01();
    test_gov();
    test_gov_effects();
    test_ai_strategy();
    test_rebellion();
    test_reg02();
    test_navy();
    test_peaceful();
    test_permit();
    test_ledger();
    test_no_convoys();
    test_war_warning();
    test_player_handle();
    printf("\n%d passed, %d failed\n", g_pass, g_fail);
    return g_fail;
}
