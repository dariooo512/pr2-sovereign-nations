/* The nation panel: one persistent window in the style of the game's Log /
 * Missions window (the nation panel change).
 *
 * It is the game's own CTabControl (TAB_CONTROL_800x600.screen: parchment frame,
 * vertical icon tab strip, close X), opened like CGameMenu::OpenLog 0x507ED0
 * does it, with six tabs. Every page is the game's scrolling list page
 * (CListPage 0x4D4F10) on the Missions page's screens
 * (NACHRICHTEN_LISTE: title bar + list) with the mod's card FNN_CARD (the Missions
 * card with header bar, two label plates, a markup body, plus two text buttons), with a DLL copy of
 * its vtable for Create / Refresh / FillEntry (research/tab_window.md §4.2).
 * Card texts use the game's markup (research/text_markup.md): green/red status,
 * blue amounts with the gold icon. Buttons call api_action() (the same core
 * calls as the Lua API); the panel never destroys itself inside a click.
 *
 * Only one TAB_CONTROL window may exist (control names are global): opening
 * closes every vanilla menu first (CloseAllMenus), and the hook on CloseLog
 * 0x5007C0 (the first thing CloseAllMenus does) closes ours.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "panel.h"
#include "gui.h"
#include "hook.h"
#include "log.h"
#include "adapter.h"
#include "engine.h"
#include "navy.h"
#include "lua.h"
#include "flag.h"
#include "sight.h"

#define TC __attribute__((thiscall))

/* ---- game calls --------------------------------------------------------------- */
typedef void  (TC *V0_t)(void *self);
typedef void  (TC *V1_t)(void *self, int a);
typedef void  (TC *VP_t)(void *self, void *a);
typedef int   (TC *I0_t)(void *self);
typedef int   (TC *Setup_t)(void *self, void *parent, const char *file);
typedef void  (TC *P2_t)(void *self, void *a, void *b);
typedef void  (TC *Layout_t)(void *self, int spacing, GuiPoint *start, int a, int b, int c);
typedef char  (TC *AddEntry_t)(void *self, int key, void *item, int append, int relayout);
typedef void *(TC *FindChild_t)(void *self, int key, GuiStr *name);
typedef void  (TC *TabCreate_t)(void *self, GuiStr *screen, void *parent);
typedef void  (TC *SetupBtns_t)(void *self, GuiPoint *ofs, GuiPoint *first, int spacing, void *t, void *c, void *u);
typedef void *(TC *AddTab_t)(void *self, int id, void *page, GuiPoint *ofs, GuiStr *tip, int icon, int arg, int radio, int user);
typedef void  (__cdecl *Position_t)(void *ctl, int center);

#define ListCtor        ((V1_t)0x004D4F10)
#define TabCtor         ((V1_t)0x004DD080)
#define SetupFromFile   ((Setup_t)0x004CEC10)
#define InitScroll      ((P2_t)0x004D5400)
#define SetLayout       ((Layout_t)0x004D3BC0)
#define SetTemplate     ((VP_t)0x004D3BB0)
#define ClearAll        ((V0_t)0x004D4DC0)
#define AddEntry        ((AddEntry_t)0x004D5550)
#define Relayout        ((V0_t)0x004D5220)
#define FindEntryChild  ((FindChild_t)0x0045C660)
#define SetupButtons    ((SetupBtns_t)0x004DC360)
#define AddTab          ((AddTab_t)0x004DD660)
#define CreateCloseBtn  ((V1_t)0x004DCCE0)
#define SetRefreshMs    ((V1_t)0x004DC0D0)
#define PositionWindow  ((Position_t)0x004D37A0)
#define SelectTab       ((V1_t)0x004DCC70)
#define UpdatePages     ((V1_t)0x004DD9A0)
#define CloseAllMenus   ((V1_t)0x00507600)
#define SetMenuOpen     ((V1_t)0x005001D0)
#define LIST_VTABLE     ((void **)0x00694428)      /* CListPage, 24 slots */
#define LIST_DESTROY    ((void *)0x0046BC40)
#define ITEM_VTABLE     0x0068B164u
#define PAGE_SIZE       0x100                      /* CListPage 0xD0 + our fields */
#define PG_KIND         0xD0
#define PG_HASH         0xD4
#define PG_ROOT         0x44
#define TAB_ID0         0x4E01

static void *game_menu(void)
{
    uint8_t *app = *(uint8_t **)0x006E58E4;
    return app ? *(void **)(app + 0xEC) : NULL;
}

/* ---- cards -------------------------------------------------------------------- */
typedef struct {
    char label[40];                    /* text on the button */
    int action, arg;                   /* api_action(); -1 confirm, -2 cancel */
    char tip[120];
} CardBtn;

typedef struct {
    char caption[80], left[80], right[80];
    char body[1400];
    CardBtn btn[2];                    /* FNC_Btn1 / FNC_Btn2 under the body (FNN_CARD_800x600.screen) */
    uint32_t go_to;                    /* a national ship: the eye button FNC_BtnRemove centres the sea map on it */
} Card;

#define MAX_CARDS 48
static Card g_cards[MAX_CARDS];
static int g_ncards;
static struct { int icon, action, arg; char tip[120]; } g_pbtn[2];
static const char *const k_title[PANEL_KINDS] = {
    "Your Nation", "National Treasury", "Towns of the Nation", "Diplomacy", "Form of Government", "Navy and Defence",
    "Found a Nation"};
static const char *const k_tab_tip[PANEL_KINDS] = {
    "Overview", "Treasury", "Towns", "Diplomacy", "Government", "Navy and defence", "Found a nation"};
static const int k_tab_icon[PANEL_KINDS] = {44, 77, 57, 85, 81, 56, 44};

/* pending confirmation and the last action's result */
static int g_confirm_action, g_confirm_arg;
static char g_confirm_text[300];
static char g_feedback[300];
static int g_feedback_ok, g_feedback_page = -1;

#define GREEN  "<o:0xff008000>"
#define RED    "<o:0xffc00000>"
#define BLUE   "<o:0xff1e1eff>"
#define RESET  "<o>"
#define GOLD   "<gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen>"

/* the game's thousands separator: IDPR_FORMAT_LOCALE_SEP, a std::wstring at 0x6E72F0 (begin,
   end pointers) that fmt_number 0x408D70 uses ("." in this game, "," in some tables) */
static char thousands_sep(void)
{
    static char sep;
    if (!sep) {
        const uint16_t *b = *(const uint16_t *const *)0x006E72F0, *e = *(const uint16_t *const *)0x006E72F4;
        if (!b || e != b + 1 || b[0] < 0x20 || b[0] > 0x7E) return ',';   /* not loaded yet: ask again later */
        sep = (char)b[0];
    }
    return sep;
}

static const char *num(int64_t v)
{
    static char buf[32][32];
    static int k;
    char *o = buf[k++ & 31], tmp[32], sep = thousands_sep();
    int neg = v < 0, n = 0, digits = 0;
    uint64_t u = neg ? (uint64_t)(-v) : (uint64_t)v;
    do {
        if (digits && digits % 3 == 0) tmp[n++] = sep;
        tmp[n++] = (char)('0' + u % 10);
        digits++;
        u /= 10;
    } while (u && n < 30);
    int j = 0;
    if (neg) o[j++] = '-';
    while (n) o[j++] = tmp[--n];
    o[j] = 0;
    return o;
}

static const char *gold(int64_t v)
{
    static char buf[16][96];
    static int k;
    char *o = buf[k++ & 15];
    snprintf(o, 96, BLUE "%s" RESET GOLD, num(v));
    return o;
}

static Card *add_card(const char *caption, const char *left, const char *right)
{
    if (g_ncards >= MAX_CARDS) return NULL;
    Card *c = &g_cards[g_ncards++];
    memset(c, 0, sizeof *c);
    snprintf(c->caption, sizeof c->caption, "%s", caption);
    snprintf(c->left, sizeof c->left, "%s", left);
    snprintf(c->right, sizeof c->right, "%s", right);
    return c;
}

static void body(Card *c, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static void body(Card *c, const char *fmt, ...)
{
    if (!c) return;
    size_t n = strlen(c->body);
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(c->body + n, sizeof c->body - n, fmt, ap);
    va_end(ap);
}

/* the next free text button of a card */
static void add_btn(Card *c, const char *label, int action, int arg, const char *tip)
{
    if (!c) return;
    for (int i = 0; i < 2; i++) {
        CardBtn *b = &c->btn[i];
        if (b->action) continue;
        snprintf(b->label, sizeof b->label, "%s", label);
        b->action = action;
        b->arg = arg;
        snprintf(b->tip, sizeof b->tip, "%s", tip);
        return;
    }
}


static void town_name(int t, char *out, int cap) { ui_town_label(t, out, cap); }

static const char *const k_status[6] = {"At peace", "Trade agreement", "Non-aggression pact", "Alliance",
                                        "At war", "Ceasefire"};
static const char *const k_tariff_name[4] = {"Free trade", "Low", "Moderate", "Protectionist"};
static const int k_tariff_pct[4] = {0, 5, 10, 20};

static void top_cards(int page)
{
    if (g_confirm_action) {
        Card *c = add_card("Please confirm", "", "");
        body(c, "%s", g_confirm_text);
        add_btn(c, "Confirm", -1, 0, "Carry it out");
        add_btn(c, "Cancel", -2, 0, "Do nothing");
    }
    if (g_feedback[0] && g_feedback_page == page) {
        Card *c = add_card(g_feedback_ok ? "Done" : "Not possible", "", "");
        body(c, "%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
    }
}






/* where a national ship is, and where it is heading (state 9 = battle, research/military_ai.md) */
static void ship_where(int state, int town, char *out, int cap)
{
    if (state == 9) { snprintf(out, cap, "in battle"); return; }
    if (town >= 0) { char nm[48]; town_name(town, nm, sizeof nm); snprintf(out, cap, "in %s", nm); return; }
    snprintf(out, cap, "at sea");
}



/* ---- the founding page (the founding-page change) ------------------------
   One card (FNN_FOUND_800x600.screen, art/make_found.py): form of state, name and flag,
   then Found / Cancel. The arrows change the card in place (no rebuild), so the name being
   typed keeps its focus; a rebuild (new status text) puts the typed name back. */
static void *child(void *p, int key, const char *name);
static void TC on_click(void *page, int key);
#define FOUND_NAME_PX   230      /* pixels in the box's font: fits the panel caption and the town header */
#define FK_TITLE_PREV   100
#define FK_TITLE_NEXT   101
#define FK_FLAG_PREV    102
#define FK_FLAG_NEXT    103
#define FK_FOUND        104
#define FK_CANCEL       105
#define N_STATE_TITLES  8

static struct {
    int capital, title, flag;
    char name[64];                  /* the name in the box, kept across rebuilds */
    char suggestion[64];            /* what the box was last prefilled with */
    char status[300];
    int status_ok;
    void *page;                     /* the founding page and its card key while it is shown */
    int key;
} g_fd = {-1, 0, 0, "", "", "", 0, NULL, -1};
static int g_reopen = -1;           /* open this page next frame (after founding) */

static void found_suggest(char *out, int cap)
{
    char town[64] = "";
    if (g_fd.capital >= 0) town_name(g_fd.capital, town, sizeof town);
    snprintf(out, cap, "%s of %s", core_title_name(g_fd.title), town[0] ? town : "...");
}

/* the typed name without spaces at either end */
static void found_trim(char *t)
{
    size_t n = strlen(t), i = 0;
    while (n && (t[n - 1] == ' ' || t[n - 1] == '\t')) t[--n] = 0;
    while (t[i] == ' ' || t[i] == '\t') i++;
    if (i) memmove(t, t + i, n - i + 1);
}

static void *found_child(const char *name)
{
    return g_fd.page && g_fd.key >= 0 ? child(g_fd.page, g_fd.key, name) : NULL;
}

static void found_read_name(void)
{
    void *e = found_child("FNF_NameEdit");
    if (e) gui_edit_get(e, g_fd.name, sizeof g_fd.name);
}

static void found_show_title(void)
{
    gui_set_text(found_child("FNF_FormValue"), core_title_name(g_fd.title));
}

static void found_show_flag(void)
{
    int n = api_flag_count();
    if (n <= 0) return;
    g_fd.flag = (g_fd.flag % n + n) % n;
    const char *group, *name = api_flag_name(g_fd.flag, &group);
    char t[160];
    snprintf(t, sizeof t, "No. %d of %d: %s (%s)", g_fd.flag + 1, n, name, group);
    gui_set_text(found_child("FNF_FlagName"), t);
    void *img = found_child("FNF_FlagImg");
    if (img && !gui_image_load(img, flag_bmp_path(g_fd.flag)))
        log_line("PANEL: flag %d image did not load (%s)", g_fd.flag, flag_bmp_path(g_fd.flag));
}

/* a new form of state: a name the player has not changed follows it */
static void found_set_title(int title)
{
    found_read_name();
    char t[64];
    snprintf(t, sizeof t, "%s", g_fd.name);
    found_trim(t);
    g_fd.title = (title % N_STATE_TITLES + N_STATE_TITLES) % N_STATE_TITLES;
    found_show_title();
    if (!t[0] || !strcmp(t, g_fd.suggestion)) {
        found_suggest(g_fd.suggestion, sizeof g_fd.suggestion);
        snprintf(g_fd.name, sizeof g_fd.name, "%s", g_fd.suggestion);
        gui_edit_set(found_child("FNF_NameEdit"), g_fd.name);
    }
}

/* a fresh founding page: the town the player is in, the suggestion, the current flag */
static void found_begin(void)
{
    int t = -1;
    if (!plua_eval_int("fnn_current_town()", &t)) t = -1;
    g_fd.capital = t;
    g_fd.flag = adapter_state()->flag;
    found_suggest(g_fd.suggestion, sizeof g_fd.suggestion);
    snprintf(g_fd.name, sizeof g_fd.name, "%s", g_fd.suggestion);
    g_fd.status[0] = 0;
    log_line("PANEL: founding page for town %d", t);
}

static void build_found(const NationState *s)
{
    char town[64] = "", why[256] = "";
    if (g_fd.capital >= 0) town_name(g_fd.capital, town, sizeof town);
    char cap[96];
    snprintf(cap, sizeof cap, "Capital: %s", town[0] ? town : "none yet");
    Card *c = add_card(cap, "", "");
    if (s->founded) {
        body(c, GREEN "You already lead the %s." RESET, s->name);
        return;
    }
    if (g_fd.status[0]) {
        body(c, "%s%s" RESET, g_fd.status_ok ? GREEN : RED, g_fd.status);
    } else if (g_fd.capital < 0) {
        body(c, RED "Open the town that should become your capital (or select a convoy lying there), "
                "then open this page again." RESET);
    } else if (!api_can_found(g_fd.capital, why, sizeof why)) {
        body(c, RED "%s" RESET, why);
    } else {
        body(c, "%s leaves its power and becomes your capital. Names: up to %d letters.", town,
             FOUND_NAME_CHARS);
    }
    add_btn(c, "Found the nation", FK_FOUND, 0, "Declare independence with these choices");
    add_btn(c, "Cancel", FK_CANCEL, 0, "Close without founding");
}

/* the controls of the founding card, after AddEntry created it */
static void found_setup(void *p, int key)
{
    g_fd.page = p;
    g_fd.key = key;
    static const struct { const char *name; int icon, fk; const char *tip; } arrows[4] = {
        {"FNF_FormPrev", 0x57, FK_TITLE_PREV, "Previous form of state"},
        {"FNF_FormNext", 0x56, FK_TITLE_NEXT, "Next form of state"},
        {"FNF_FlagPrev", 0x57, FK_FLAG_PREV, "Previous flag"},
        {"FNF_FlagNext", 0x56, FK_FLAG_NEXT, "Next flag"}};
    for (int i = 0; i < 4; i++) {
        void *b = found_child(arrows[i].name);
        if (!b) continue;
        gui_icon_at(b, arrows[i].icon, 0x5A, 5, 6);
        gui_tooltip(b, arrows[i].tip);
        gui_on_click(b, p, on_click, arrows[i].fk);
    }
    gui_set_text(found_child("FNF_FormCap"), "Form of state");
    gui_set_text(found_child("FNF_NameCap"), "Name of the nation");
    gui_set_text(found_child("FNF_FlagCap"), "Flag");
    void *e = found_child("FNF_NameEdit");
    gui_edit_limit(e, FOUND_NAME_CHARS, FOUND_NAME_PX);
    gui_edit_set(e, g_fd.name);
    found_show_title();
    found_show_flag();
    for (int b = 0; b < 2; b++) {
        void *btn = found_child(b ? "FNF_Btn2" : "FNF_Btn1");
        const CardBtn *cb = &g_cards[key].btn[b];
        if (!btn) continue;
        gui_show(btn, cb->action != 0);
        if (!cb->action) continue;
        gui_button_text(btn, cb->label);
        gui_tooltip(btn, cb->tip);
        gui_on_click(btn, p, on_click, cb->action);
    }
    gui_show(found_child("FNF_BtnRemove"), 0);
}

static void found_do(void)
{
    char name[64], adj[64] = "", why[256] = "";
    found_read_name();
    snprintf(name, sizeof name, "%s", g_fd.name);
    found_trim(name);
    g_fd.status_ok = 0;
    if (!name[0]) {
        snprintf(g_fd.status, sizeof g_fd.status, "Enter a name for the nation.");
        return;
    }
    if (g_fd.capital < 0) {
        snprintf(g_fd.status, sizeof g_fd.status, "Open the town that should become your capital first.");
        return;
    }
    town_name(g_fd.capital, adj, sizeof adj);
    if (!api_found(g_fd.capital, name, adj, g_fd.title, g_fd.flag, why, sizeof why)) {
        snprintf(g_fd.status, sizeof g_fd.status, "%s", why[0] ? why : "The nation could not be founded.");
        return;
    }
    snprintf(g_feedback, sizeof g_feedback, "The %s is born! %s is its capital. The nation button in the top "
             "bar opens this window at any time.", name, adj);
    g_feedback_ok = 1;
    g_feedback_page = PANEL_OVERVIEW;
    g_fd.status[0] = 0;
    g_reopen = PANEL_OVERVIEW;                     /* the nation's own tabs, next frame */
}

static void build_cards(int page)
{
    const NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    g_ncards = 0;
    memset(g_pbtn, 0, sizeof g_pbtn);
    top_cards(page);
    if (page == PANEL_FOUND) {
        build_found(s);
        return;
    }
    if (!s->founded) {
        Card *c = add_card("No nation yet", "", "");
        body(c, "Found a nation first: open the town that should become your capital and press Ctrl+N.");
        return;
    }
}

static uint32_t cards_hash(void)
{
    uint32_t h = 2166136261u;
    for (int i = 0; i < g_ncards; i++) {
        const uint8_t *p = (const uint8_t *)&g_cards[i];
        for (size_t k = 0; k < sizeof g_cards[i]; k++) { h ^= p[k]; h *= 16777619u; }
    }
    for (int i = 0; i < 2; i++) { h ^= (uint32_t)g_pbtn[i].action * 31u + (uint32_t)g_pbtn[i].arg; h *= 16777619u; }
    return h ? h : 1;
}

/* ---- the panel window ------------------------------------------------------------ */
static void *g_tab;
static void *g_pages[PANEL_KINDS];
static void *g_vt[24];
static int g_close_req, g_dirty, g_last_page;

/* ---- pages on their own screen ---------------------------------------------------------
   A page whose look is a vanilla window other than the Missions list is a plain CBaseControl
   (ctor 0x4CF150, vtable 0x693F80) on a screen cloned from that window by art/make_*.py, with
   a DLL copy of the vtable: vt[7] Create loads the screen, vt[11] Refresh fills it (every 2 s
   through UpdatePages, and after a click). Control names carry the page's prefix (FNT_ ...);
   only one panel page exists at a time, so gui_find finds them. */
#define BaseCtor        ((V1_t)0x004CF150)
#define BASE_VTABLE     ((void **)0x00693F80)      /* CBaseControl, 16 slots */
static void *g_svt[16];
static void do_action(int page, int action, int arg);

static const char *spage_screen(int kind)
{
    return kind == PANEL_TREASURY ? "FNN_TREASURY_800x600.screen" :
           kind == PANEL_OVERVIEW ? "FNN_OVERVIEW_800x600.screen" :
           kind == PANEL_GOVERNMENT ? "FNN_GOVERNMENT_800x600.screen" : NULL;
}
static int screen_page(int kind) { return spage_screen(kind) != NULL; }
static void overview_setup(void);
static void overview_fill(void);
static void gov_setup(void *p);
static void gov_fill(void);

static void set_tip(const char *name, const char *tip)
{
    void *d = gui_find(name);
    if (d) gui_tooltip(d, tip);
}

static void set_text(const char *name, const char *text) { gui_set_text(gui_find(name), text); }
static void set_textex(const char *name, const char *text) { gui_set_textex(gui_find(name), text); }
/* a text block that starts at its top (a CTextBoxEx centres its text vertically): fit the box to the text */
static void set_textex_top(const char *name, const char *text)
{
    void *d = gui_find(name);
    if (!d) return;
    gui_set_size(d, gui_width(d), gui_set_textex(d, text));
    gui_set_textex(d, text);                                  /* laid out again in the fitted box */
}

static void wire(const char *name, void *page, int key, const char *tip)
{
    void *b = gui_find(name);
    if (!b) return;
    gui_on_click(b, page, on_click, key);
    if (tip) gui_tooltip(b, tip);
}

/* The Treasury page: the Log window's Balance tab (art/make_treasury.py). Mode 0 is the
   national balance by category, "last month" and "forecast"; the long button switches to
   mode 1, taxes and finances, as the Balance tab's button switches to the loans. */
#define TK_MODE         3000
#define TK_TAX_PREV     3001
#define TK_TAX_NEXT     3002
#define TK_TARIFF_PREV  3003
#define TK_TARIFF_NEXT  3004
#define TK_AMOUNT_PREV  3005
#define TK_AMOUNT_NEXT  3006
#define TK_DONATE       3007
#define TK_WITHDRAW     3008
static int g_tr_mode, g_tr_amount = 2;
static const int k_amounts[] = {1000, 5000, 10000, 50000, 100000, 500000, 1000000};
#define N_AMOUNTS ((int)(sizeof k_amounts / sizeof k_amounts[0]))
static const char *const k_ledger_tip[LEDGER_CATS] = {
    "Taxes of the member towns, paid at the month end",
    "Duty on imports into the member towns, paid at the month end",
    "Raids of a pirate republic at war, paid at the month end",
    "Gold the navy takes from towns it storms",
    "Your own gold, given to the treasury",
    "Running the member towns, at the month end",
    "Pay and supplies of the nation's fleets, at the month end",
    "Upkeep of the cannon towers the treasury bought, at the month end",
    "Fitting out new fleets (and fleets that replace losses)",
    "Soldiers recruited for the garrisons",
    "Cannon towers built for the member towns",
    "Towns the nation bought from a power",
    "Public money you took for your own purse"};

static int tariff_index(int pct)
{
    for (int i = 0; i < 4; i++)
        if (k_tariff_pct[i] == pct) return i;
    return 0;
}

static void treasury_setup(void *p)
{
    static const struct { const char *name; int icon, key; const char *tip; } arrows[6] = {
        {"FNT_TaxPrev", 0x57, TK_TAX_PREV, "Lower the national tax by 5%"},
        {"FNT_TaxNext", 0x56, TK_TAX_NEXT, "Raise the national tax by 5%"},
        {"FNT_TariffPrev", 0x57, TK_TARIFF_PREV, "A lower import tariff"},
        {"FNT_TariffNext", 0x56, TK_TARIFF_NEXT, "A higher import tariff"},
        {"FNT_AmountPrev", 0x57, TK_AMOUNT_PREV, "A smaller amount"},
        {"FNT_AmountNext", 0x56, TK_AMOUNT_NEXT, "A larger amount"}};
    for (int i = 0; i < 6; i++) {
        void *b = gui_find(arrows[i].name);
        if (!b) continue;
        gui_icon_at(b, arrows[i].icon, 0x5A, 5, 6);
        wire(arrows[i].name, p, arrows[i].key, arrows[i].tip);
    }
    wire("FNT_kredite", p, TK_MODE, NULL);
    wire("FNT_Donate", p, TK_DONATE, NULL);
    wire("FNT_Withdraw", p, TK_WITHDRAW, NULL);
    set_text("FNT_Cap_Row1", "Last month");
    set_text("FNT_Cap_Row2", "Forecast");
    set_tip("FNT_Cap_Row1", "The accounts of the last finished month");
    set_tip("FNT_Cap_Row2", "This month so far, plus what the coming month end will book");
    set_text("FNT_gesamt", "Total");
    set_text("FNT_TaxCap", "National tax");
    set_text("FNT_TariffCap", "Import tariff");
    set_text("FNT_AmountCap", "Move gold between your purse and the treasury");
    gui_show(gui_find("FNT_Uhr"), 0);
    char name[16];
    for (int i = 0; i < LEDGER_CATS; i++) {
        snprintf(name, sizeof name, "FNT_Line_%02d", i);
        set_textex(name, core_ledger_name(i));
        set_tip(name, k_ledger_tip[i]);
    }
}

static void treasury_fill(void)
{
    const NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    int fin = g_tr_mode == 1;
    gui_show(gui_find("FNT_Balance"), !fin);
    gui_show(gui_find("FNT_Finance"), fin);
    set_text("FNT_Cap_01", fin ? "Taxes and Finances" : "National Balance");
    gui_button_text(gui_find("FNT_kredite"), fin ? "Balance" : "Taxes and finances");
    gui_tooltip(gui_find("FNT_kredite"), fin ? "Back to the national balance" :
                                               "National tax, import tariff, donations and withdrawals");
    char name[16], t[400];
    if (!fin) {
        int64_t f[LEDGER_CATS], sum0 = 0, sum1 = 0;
        core_ledger_forecast(s, &w, adapter_config(), f);
        for (int i = 0; i < LEDGER_CATS; i++) {
            snprintf(name, sizeof name, "FNT_Row1_%02d", i);
            set_textex(name, num(s->ledger.month[0][i]));
            snprintf(name, sizeof name, "FNT_Row2_%02d", i);
            set_textex(name, num(f[i]));
            sum0 += s->ledger.month[0][i];
            sum1 += f[i];
        }
        snprintf(t, sizeof t, "%s" GOLD, num(sum0));
        set_textex("FNT_Row1_13", t);
        snprintf(t, sizeof t, "%s" GOLD, num(sum1));
        set_textex("FNT_Row2_13", t);
        int days = (int)(s->last_month_day + 30) - (int)adapter_day();
        snprintf(t, sizeof t, "Treasury: %s gold. The month ends in %d day%s.", num(s->treasury), days < 0 ? 0 : days,
                 days == 1 ? "" : "s");
        set_tip("FNT_gesamt", t);
        return;
    }
    snprintf(t, sizeof t, "%d%%", s->default_tax_pct);
    set_text("FNT_TaxValue", t);
    snprintf(t, sizeof t, "Expected taxes this month: %s. Applies to every town without a rate of its own; "
             "higher taxes cost loyalty.", gold(core_monthly_tax_estimate(s, &w)));
    set_textex("FNT_TaxNote", t);
    int ti = tariff_index(s->tariff_pct);
    snprintf(t, sizeof t, "%s: %d%%", k_tariff_name[ti], k_tariff_pct[ti]);
    set_text("FNT_TariffValue", t);
    set_textex("FNT_TariffNote", ti == 0 ? "No import duty. Trading powers like you best." :
                                 ti == 1 ? "A small duty on imports into your towns." :
                                 ti == 2 ? "A noticeable duty; the powers grow cooler." :
                                           "The most revenue, but the powers like you clearly less.");
    g_tr_amount = g_tr_amount < 0 ? 0 : g_tr_amount >= N_AMOUNTS ? N_AMOUNTS - 1 : g_tr_amount;
    int amount = k_amounts[g_tr_amount];
    set_text("FNT_AmountValue", num(amount));
    snprintf(t, sizeof t, "Treasury: %s   Your purse: %s", gold(s->treasury), gold(eng_player_gold()));
    set_textex("FNT_AmountNote", t);
    void *don = gui_find("FNT_Donate"), *wd = gui_find("FNT_Withdraw");
    if (g_confirm_action == API_WITHDRAW) {
        gui_button_text(don, "Take it");
        gui_tooltip(don, "Move the gold to your purse");
        gui_button_text(wd, "Cancel");
        gui_tooltip(wd, "Leave the treasury as it is");
        set_textex("FNT_Status", g_confirm_text);
        return;
    }
    snprintf(t, sizeof t, "Donate %s", num(amount));
    gui_button_text(don, t);
    gui_tooltip(don, "Give gold of your own to the treasury");
    snprintf(t, sizeof t, "Withdraw %s", num(amount));
    gui_button_text(wd, t);
    gui_tooltip(wd, "Take gold from the treasury (costs stability; at most half the treasury)");
    if (g_feedback[0] && g_feedback_page == PANEL_TREASURY)
        snprintf(t, sizeof t, "%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
    else
        t[0] = 0;
    set_textex("FNT_Status", t);
}

static int treasury_key(int key)
{
    const NationState *s = adapter_state();
    int amount = k_amounts[g_tr_amount < 0 || g_tr_amount >= N_AMOUNTS ? 2 : g_tr_amount];
    int pending = g_confirm_action == API_WITHDRAW;
    if (key != TK_DONATE && key != TK_WITHDRAW) g_confirm_action = 0;
    switch (key) {
    case TK_MODE:        g_tr_mode ^= 1; g_feedback[0] = 0; break;
    case TK_TAX_PREV:    if (s->default_tax_pct >= 5) do_action(PANEL_TREASURY, API_TAX, s->default_tax_pct - 5); break;
    case TK_TAX_NEXT:    if (s->default_tax_pct <= 45) do_action(PANEL_TREASURY, API_TAX, s->default_tax_pct + 5); break;
    case TK_TARIFF_PREV: if (tariff_index(s->tariff_pct) > 0)
                             do_action(PANEL_TREASURY, API_TARIFF, k_tariff_pct[tariff_index(s->tariff_pct) - 1]);
                         break;
    case TK_TARIFF_NEXT: if (tariff_index(s->tariff_pct) < 3)
                             do_action(PANEL_TREASURY, API_TARIFF, k_tariff_pct[tariff_index(s->tariff_pct) + 1]);
                         break;
    case TK_AMOUNT_PREV: if (g_tr_amount > 0) g_tr_amount--; g_feedback[0] = 0; break;
    case TK_AMOUNT_NEXT: if (g_tr_amount < N_AMOUNTS - 1) g_tr_amount++; g_feedback[0] = 0; break;
    case TK_DONATE:
        if (pending) {
            int a = g_confirm_arg;
            g_confirm_action = 0;
            do_action(PANEL_TREASURY, API_WITHDRAW, a);
        } else {
            do_action(PANEL_TREASURY, API_DONATE, amount);
        }
        break;
    case TK_WITHDRAW:
        if (pending) {                                           /* Cancel */
            g_confirm_action = 0;
            g_feedback[0] = 0;
        } else {                                                 /* ask first, as the dialogs did */
            g_confirm_action = API_WITHDRAW;
            g_confirm_arg = amount;
            g_feedback[0] = 0;
            snprintf(g_confirm_text, sizeof g_confirm_text, "Take %s gold from the national treasury for your own "
                     "purse? Public money costs at least 2 stability.", num(amount));
        }
        break;
    default: return 0;
    }
    g_dirty = 1;
    return 1;
}

static void TC spage_refresh(void *p)
{
    if (!*(void **)((uint8_t *)p + PG_ROOT)) return;
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    if (kind == PANEL_TREASURY) treasury_fill();
    else if (kind == PANEL_OVERVIEW) overview_fill();
    else if (kind == PANEL_GOVERNMENT) gov_fill();
}

static void TC spage_create(void *p, void *parent_root)
{
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    if (!SetupFromFile(p, parent_root, spage_screen(kind))) {
        log_line("PANEL: %s could not be loaded", spage_screen(kind));
        return;
    }
    if (kind == PANEL_TREASURY) { g_tr_amount = 2; treasury_setup(p); }        /* each opening: 10,000 */
    else if (kind == PANEL_OVERVIEW) overview_setup();
    else if (kind == PANEL_GOVERNMENT) gov_setup(p);
    g_last_page = kind;
    log_line("PANEL: page %d (%s) created", kind, k_title[kind]);
}

static void *make_screen_page(int kind)
{
    uint8_t *p = gui_new(PAGE_SIZE);
    if (!p) return NULL;
    memset(p, 0, PAGE_SIZE);
    BaseCtor(p, 1);
    if (!g_svt[0]) {
        memcpy(g_svt, BASE_VTABLE, sizeof g_svt);
        g_svt[7] = (void *)spage_create;
        g_svt[11] = (void *)spage_refresh;
    }
    *(void ***)p = g_svt;
    *(int *)(p + PG_KIND) = kind;
    return p;
}

/* ---- list pages: a CListPage on a cloned vanilla screen, rows selected by a click ----------
   The Towns (Chronicle town list), Diplomacy (Chronicle nations) and Navy (convoy list) pages.
   Rows that touch (SetLayout spacing 0); the list's own mouse slots select a row: SetHover
   0x4D3DF0(1) turns them on, vt[19]/[20] press / release (the pressed item, list+0xA4),
   vt[21]/[22] hover on / off (list+0xA0), each (this, item). Every row screen uses the same
   control names (FNR_Name, FNR_C1..C4, FNR_Nation flag image, FNR_Flag_0..3 power flags,
   FNR_Sel / FNR_Hover tints); a page's builder fills g_lrows, its footer shows the selected
   row. Rows are rebuilt only when the set of keys changes, else updated in place, so the
   scroll position stays. */
#define SetHover        ((V1_t)0x004D3DF0)
#define OpenTownInfo    ((V1_t)0x0050B8F0)         /* CGameMenu, (town handle) */
#define ImageFit        ((VP_t)0x004C1540)         /* CDynamicImg: draw into this rect */
typedef struct {
    int key, ref;                                 /* ref: the town / power / fleet of the row */
    char name[64], cell[4][64];
    const char *flag;                             /* image file for FNR_Nation, or NULL */
    int flag_anim;                                /* or the power flag FNR_Flag_<n> to show; -1 = none */
    int sym;                                      /* fleet rows: 1 in port, 2 at sea, 3 in battle */
    char flag_loaded[96];                         /* what the row's image holds now */
} LRow;
#define MAX_LROWS 72
static LRow g_lrows[MAX_LROWS];
static int g_nlrows;
static int g_lsel[PANEL_KINDS] = {-1, -1, -1, -1, -1, -1, -1}, g_lmode[PANEL_KINDS];
static uint32_t g_lrows_hash;
static void *g_lvt[24];
static void *g_navy_tmpl[2];                      /* Navy page: fleet row, town row */
static int g_open_town = -1;

static LRow *lrow(int key)
{
    for (int i = 0; i < g_nlrows; i++)
        if (g_lrows[i].key == key) return &g_lrows[i];
    return NULL;
}

static LRow *lrow_add(int key, int ref, const char *name)
{
    if (g_nlrows >= MAX_LROWS) return NULL;
    LRow *r = &g_lrows[g_nlrows++];
    memset(r, 0, sizeof *r);
    r->key = key;
    r->ref = ref;
    r->flag_anim = -1;
    snprintf(r->name, sizeof r->name, "%s", name);
    return r;
}

/* loaded: the file this image control holds now. The cache belongs to one control: a page is
   created anew each time its tab is shown (new, empty images), so the page's create step clears
   the caches of its fixed images (g_ov_flag, g_sel_flag), as list_fill does for a new row. */
static void load_flag(void *img, const char *file, char *loaded, int cap)
{
    if (!img || !file || !strcmp(loaded, file)) return;
    if (gui_image_load(img, file)) ImageFit(img, (uint8_t *)img + 0x68);
    snprintf(loaded, cap, "%s", file);
}
static char g_ov_flag[2][96];                     /* Overview: FNO_Flag, FNO_ColFlag */
static char g_sel_flag[96];                       /* Towns footer: FNW_SelFlag */

static void show_power_flag(const char *fmt, int power)     /* fmt: "XXX_%d", one static per power */
{
    char n[40];
    for (int i = 0; i < 4; i++) {
        snprintf(n, sizeof n, fmt, i);
        gui_show(gui_find(n), i == power);
    }
}

static const char *power_flag(int power)
{
    static const char *const k[4] = {"images\\interface\\nation00.aim", "images\\interface\\nation01.aim",
                                     "images\\interface\\nation02.aim", "images\\interface\\nation03.aim"};
    return power >= 0 && power < 4 ? k[power] : "images\\interface\\nation_piraten.aim";
}

static void list_fill_row(void *p, int kind, LRow *r)
{
    static const char *const cell[4] = {"FNR_C1", "FNR_C2", "FNR_C3", "FNR_C4"};
    gui_set_textex(child(p, r->key, "FNR_Name"), r->name);
    for (int i = 0; i < 4; i++) gui_set_textex(child(p, r->key, cell[i]), r->cell[i]);
    gui_show(child(p, r->key, "FNR_Sel"), r->key == g_lsel[kind]);
    if (r->flag) load_flag(child(p, r->key, "FNR_Nation"), r->flag, r->flag_loaded, sizeof r->flag_loaded);
    if (r->sym) {
        gui_show(child(p, r->key, "FNR_SymPort"), r->sym == 1);
        gui_show(child(p, r->key, "FNR_SymSea"), r->sym == 2);
        gui_show(child(p, r->key, "FNR_SymBattle"), r->sym == 3);
    }
    if (r->flag_anim >= 0)
        for (int i = 0; i < 4; i++) {
            char n[16];
            snprintf(n, sizeof n, "FNR_Flag_%d", i);
            gui_show(child(p, r->key, n), i == r->flag_anim);
        }
}

/* per page: its screens, the row builder, the footer, and whether a row is selected by default */
static void towns_build(const NationState *s, const World *w);
static void towns_footer(const NationState *s, const World *w);
static void diplo_build(const NationState *s, const World *w);
static void diplo_footer(const NationState *s, const World *w);
static void navy_build(const NationState *s, const World *w);
static void navy_footer(const NationState *s, const World *w);
static void navy_template(void *p);
typedef struct {
    const char *screen, *row, *scroll, *slider;
    void (*build)(const NationState *, const World *);
    void (*footer)(const NationState *, const World *);
} ListKind;

static const ListKind *list_kind(int kind)
{
    static const ListKind towns = {"FNN_TOWNS_800x600.screen", "FNN_TOWN_ROW_800x600.screen", "FNW_ScrollDrawable",
                                   "FNW_Scrollbar", towns_build, towns_footer};
    static const ListKind diplo = {"FNN_DIPLOMACY_800x600.screen", "FNN_POWER_ROW_800x600.screen",
                                   "FND_ScrollDrawable", "FND_Scrollbar", diplo_build, diplo_footer};
    static const ListKind navy = {"FNN_NAVY_800x600.screen", "FNN_FLEET_ROW_800x600.screen", "FNV_ScrollDrawable",
                                  "FNV_Scrollbar", navy_build, navy_footer};
    return kind == PANEL_TOWNS ? &towns : kind == PANEL_DIPLOMACY ? &diplo : kind == PANEL_MILITARY ? &navy : NULL;
}

static int list_page(int kind) { return list_kind(kind) != NULL; }

static void TC list_refresh(void *p)
{
    if (!*(void **)((uint8_t *)p + PG_ROOT)) return;
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    const ListKind *k = list_kind(kind);
    if (!k) return;
    const NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    g_nlrows = 0;
    if (kind == PANEL_MILITARY) navy_template(p);
    k->build(s, &w);
    if (!lrow(g_lsel[kind])) g_lsel[kind] = g_nlrows && !g_lmode[kind] ? g_lrows[0].key : -1;
    uint32_t h = 2166136261u ^ (uint32_t)(kind * 16 + g_lmode[kind]);
    for (int i = 0; i < g_nlrows; i++) { h ^= (uint32_t)g_lrows[i].key + 1; h *= 16777619u; }
    if (h != g_lrows_hash) {
        g_lrows_hash = h;
        ClearAll(p);
        for (int i = 0; i < g_nlrows; i++) {
            uint32_t *item = gui_alloc(0x10);
            if (!item) break;
            item[0] = ITEM_VTABLE;
            item[1] = (uint32_t)g_lrows[i].key;
            item[2] = item[3] = 0;
            AddEntry(p, g_lrows[i].key, item, 1, 0);
        }
        Relayout(p);                                           /* FillEntry for every row */
    } else {
        for (int i = 0; i < g_nlrows; i++) list_fill_row(p, kind, &g_lrows[i]);
    }
    k->footer(s, &w);
}

static void TC list_fill(void *p, void *item)
{
    LRow *r = lrow(((int *)item)[1]);
    if (!r) return;
    r->flag_loaded[0] = 0;                                     /* a new row: its image is empty */
    list_fill_row(p, *(int *)((uint8_t *)p + PG_KIND), r);
}

static void TC list_press(void *p, void *item)
{
    int kind = *(int *)((uint8_t *)p + PG_KIND), key = ((int *)item)[1];
    if (key == g_lsel[kind]) return;
    if (lrow(g_lsel[kind])) gui_show(child(p, g_lsel[kind], "FNR_Sel"), 0);
    g_lsel[kind] = key;
    gui_show(child(p, key, "FNR_Sel"), 1);
    g_feedback[0] = 0;
    g_confirm_action = 0;
    g_dirty = 1;
}

static void TC list_release(void *p, void *item) { (void)p; (void)item; }
static void TC list_hover_on(void *p, void *item) { gui_show(child(p, ((int *)item)[1], "FNR_Hover"), 1); }
static void TC list_hover_off(void *p, void *item) { gui_show(child(p, ((int *)item)[1], "FNR_Hover"), 0); }

static void list_wire(int kind, void *p);

static void TC list_create(void *p, void *parent_root)
{
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    const ListKind *k = list_kind(kind);
    if (!k || !SetupFromFile(p, parent_root, k->screen)) {
        log_line("PANEL: page %d screen could not be loaded", kind);
        return;
    }
    void *slider = gui_find(k->slider), *scroll = gui_find(k->scroll);
    if (slider && scroll) InitScroll(p, scroll, slider);
    GuiPoint start = {0, 0};
    SetLayout(p, 0, &start, 0, 0, 0);                          /* rows touch, as in the town list */
    void *root = *(void **)((uint8_t *)p + PG_ROOT);
    void *tmpl = gui_create_screen(root, k->row);
    if (tmpl) {
        ((V0_t)(*(void ***)tmpl)[6])(tmpl);
        gui_show(tmpl, 0);
        SetTemplate(p, tmpl);
    }
    if (kind == PANEL_MILITARY) {
        g_navy_tmpl[0] = tmpl;
        g_navy_tmpl[1] = gui_create_screen(root, "FNN_TOWN_ROW_800x600.screen");
        if (g_navy_tmpl[1]) {
            ((V0_t)(*(void ***)g_navy_tmpl[1])[6])(g_navy_tmpl[1]);
            gui_show(g_navy_tmpl[1], 0);
        }
    }
    SetHover(p, 1);
    list_wire(kind, p);
    g_lrows_hash = 0;
    g_sel_flag[0] = 0;                                         /* the new footer's image is empty */
    g_last_page = kind;
    log_line("PANEL: page %d (%s) created", kind, k_title[kind]);
}

static void *make_list_page(int kind)
{
    uint8_t *p = gui_new(PAGE_SIZE);
    if (!p) return NULL;
    memset(p, 0, PAGE_SIZE);
    ListCtor(p, 1);
    if (!g_lvt[0]) {
        memcpy(g_lvt, LIST_VTABLE, sizeof g_lvt);
        g_lvt[7] = (void *)list_create;
        g_lvt[10] = LIST_DESTROY;
        g_lvt[11] = (void *)list_refresh;
        g_lvt[18] = (void *)list_fill;
        g_lvt[19] = (void *)list_press;
        g_lvt[20] = (void *)list_release;
        g_lvt[21] = (void *)list_hover_on;
        g_lvt[22] = (void *)list_hover_off;
    }
    *(void ***)p = g_lvt;
    *(int *)(p + PG_KIND) = kind;
    return p;
}

/* ---- Towns (art/make_towns.py): mode 0 the member towns, mode 1 towns for sale and a petition */
#define TW_DEC          3100
#define TW_INC          3101
#define TW_BTN1         3102
#define TW_BTN2         3103
#define TW_MODE         3104
#define TW_PETITION_KEY 100                       /* row key of a petitioning town: 100 + town */

static void towns_build(const NationState *s, const World *w)
{
    if (g_lmode[PANEL_TOWNS] == 0) {
        for (int pass = 0; pass < 2; pass++)              /* the capital first */
            for (int t = 0; t < MAX_TOWNS; t++) {
                const TownState *ts = &s->town[t];
                if (!ts->member || (pass == 0) != (t == s->capital)) continue;
                char nm[64];
                town_name(t, nm, sizeof nm);
                LRow *r = lrow_add(t, t, nm);
                if (!r) return;
                int soldiers, towers, budget;
                navy_town_defence(t, &soldiers, &towers, &budget);
                int own = ts->tax_pct != 0xFF;
                snprintf(r->cell[0], sizeof r->cell[0], "%s", t < w->n_towns && w->town[t].exists ?
                         num(w->town[t].population) : "-");
                snprintf(r->cell[1], sizeof r->cell[1], "%s%d" RESET,
                         ts->unrest >= 2 || ts->loyalty < 20 ? RED : ts->loyalty >= 50 ? GREEN : "", ts->loyalty);
                snprintf(r->cell[2], sizeof r->cell[2], "%d%%%s", own ? ts->tax_pct : s->default_tax_pct, own ? "*" : "");
                snprintf(r->cell[3], sizeof r->cell[3], "%d / %d", soldiers, towers);
                r->flag = flag_nation_path();
            }
        return;
    }
    int pt = core_petition_town(s);
    if (pt >= 0 && pt < w->n_towns) {
        char nm[64];
        town_name(pt, nm, sizeof nm);
        LRow *r = lrow_add(TW_PETITION_KEY + pt, pt, nm);
        if (r) {
            snprintf(r->cell[0], sizeof r->cell[0], "%s", num(w->town[pt].population));
            snprintf(r->cell[1], sizeof r->cell[1], GREEN "free" RESET);
            snprintf(r->cell[2], sizeof r->cell[2], GREEN "asks" RESET);
            snprintf(r->cell[3], sizeof r->cell[3], "%d", w->town[pt].garrison);
            r->flag = power_flag(w->town[pt].power);
        }
    }
    for (int t = 0; t < w->n_towns; t++) {
        int ch = core_buy_chance(s, w, t);
        if (!ch) continue;
        char nm[64];
        town_name(t, nm, sizeof nm);
        LRow *r = lrow_add(t, t, nm);
        if (!r) return;
        int64_t price = core_town_price(s, w, t);
        snprintf(r->cell[0], sizeof r->cell[0], "%s", num(w->town[t].population));
        snprintf(r->cell[1], sizeof r->cell[1], "%s%s" RESET, s->treasury < price ? RED : "", num(price));
        snprintf(r->cell[2], sizeof r->cell[2], "%d%%", ch);
        snprintf(r->cell[3], sizeof r->cell[3], "%d", w->town[t].garrison);
        r->flag = power_flag(w->town[t].power);
    }
}

static void towns_footer(const NationState *s, const World *w)
{
    LRow *r = lrow(g_lsel[PANEL_TOWNS]);
    int member = g_lmode[PANEL_TOWNS] == 0, petition = r && r->key >= TW_PETITION_KEY;
    char t[400], name[64];
    set_text("FNW_Cap_01", member ? "Towns of the Nation" : "Towns for Sale");
    gui_button_text(gui_find("FNW_Mode"), member ? "Towns for sale" : "Member towns");
    gui_tooltip(gui_find("FNW_Mode"), member ? "Towns the nation could buy, and towns that ask to join"
                                             : "Back to the towns of the nation");
    static const char *const tips[2][4] = {
        {"Inhabitants", "Loyalty to the nation (below 20: unrest)", "Tax (* = a rate of its own)",
         "Garrison: soldiers / cannon towers"},
        {"Inhabitants", "Price the power asks", "Chance that the power sells", "Soldiers in the town"}};
    for (int i = 0; i < 4; i++) {
        snprintf(name, sizeof name, "FNW_HeadA_%d", i);
        gui_show(gui_find(name), member);
        set_tip(name, tips[0][i]);
        snprintf(name, sizeof name, "FNW_HeadB_%d", i);
        gui_show(gui_find(name), !member);
        set_tip(name, tips[1][i]);
        snprintf(name, sizeof name, "FNW_Head_%d", i);
        set_tip(name, tips[!member][i]);
    }
    int show_tax = member && r;
    const char *ctl[4] = {"FNW_TaxCap", "FNW_TaxDec", "FNW_TaxValue", "FNW_TaxInc"};
    for (int i = 0; i < 4; i++) gui_show(gui_find(ctl[i]), show_tax);
    gui_show(gui_find("FNW_SelFrame"), r != NULL);
    gui_show(gui_find("FNW_SelFlag"), r != NULL);
    void *b1 = gui_find("FNW_Btn1"), *b2 = gui_find("FNW_Btn2");
    gui_show(b2, petition);
    gui_show(b1, r != NULL);
    t[0] = 0;
    if (!r) {
        int64_t pop = 0;
        int n = 0;
        for (int i = 0; i < MAX_TOWNS; i++)
            if (s->town[i].member && i < w->n_towns && w->town[i].exists) { pop += w->town[i].population; n++; }
        set_textex("FNW_SelName", "");
        if (member) snprintf(t, sizeof t, "%d town%s, %s inhabitants. Click a town for its details and its tax.",
                             n, n == 1 ? "" : "s", num(pop));
        else snprintf(t, sizeof t, "%s", g_nlrows ? "Click a town to see the offer." :
                      "No town is for sale: the nation can buy towns where you own property, no viceroy seat, "
                      "from a power it is not at war with.");
    } else {
        set_textex("FNW_SelName", r->name);
        load_flag(gui_find("FNW_SelFlag"), r->flag, g_sel_flag, sizeof g_sel_flag);
        int town = r->ref;
        if (member) {
            const TownState *ts = &s->town[town];
            int soldiers, towers, budget;
            navy_town_defence(town, &soldiers, &towers, &budget);
            int own = ts->tax_pct != 0xFF;
            set_textex("FNW_TaxCap", "Tax here");
            snprintf(name, sizeof name, "%d%%", own ? ts->tax_pct : s->default_tax_pct);
            set_text("FNW_TaxValue", name);
            set_tip("FNW_TaxValue", own ? "A rate of its own" : "The national rate");
            const char *mood = ts->unrest >= 2 ? RED "open unrest" RESET : ts->unrest == 1 ? RED "unrest is coming" RESET
                               : ts->loyalty >= 50 ? GREEN "calm" RESET : "calm";
            snprintf(t, sizeof t, "%s, loyalty %d, %s. Garrison: %d soldiers, %d cannon tower%s.",
                     town == s->capital ? "Capital" : ts->conquered ? "Conquered" : "Member", ts->loyalty, mood,
                     soldiers, towers, towers == 1 ? "" : "s");
            gui_button_text(b1, "Town info");
            gui_tooltip(b1, "The game's town window: inhabitants, soldiers, goods");
        } else if (petition) {
            snprintf(t, sizeof t, "The citizens of %s want to join %s (loyalty 70); %s would like you less. "
                     "The petition stands until the month end.", r->name, s->name,
                     core_power_name(w->town[town].power));
            gui_button_text(b1, "Accept");
            gui_tooltip(b1, "Welcome the town into the nation");
            gui_button_text(b2, "Decline");
            gui_tooltip(b2, "Turn the petition down");
        } else {
            int64_t price = core_town_price(s, w, town);
            snprintf(t, sizeof t, "%s may sell %s for %s (chance %d%%). Treasury: %s.", core_power_name(w->town[town].power),
                     r->name, gold(price), core_buy_chance(s, w, town), gold(s->treasury));
            snprintf(name, sizeof name, "Offer %s", num(price));
            gui_button_text(b1, name);
            gui_tooltip(b1, "Offer the price from the treasury");
        }
    }
    if (g_feedback[0] && g_feedback_page == PANEL_TOWNS) {
        size_t n = strlen(t);
        snprintf(t + n, sizeof t - n, "%s%s%s" RESET, n ? "<n>" : "", g_feedback_ok ? GREEN : RED, g_feedback);
    }
    set_textex_top("FNW_SelInfo", t);
}

static int towns_key(int key)
{
    const NationState *s = adapter_state();
    LRow *r = lrow(g_lsel[PANEL_TOWNS]);
    int mode = g_lmode[PANEL_TOWNS];
    switch (key) {
    case TW_MODE:
        g_lmode[PANEL_TOWNS] ^= 1;
        g_lsel[PANEL_TOWNS] = -1;
        g_feedback[0] = 0;
        break;
    case TW_DEC:
    case TW_INC:
        if (r && mode == 0) {
            int own = s->town[r->ref].tax_pct, tax = own != 0xFF ? own : s->default_tax_pct;
            tax += key == TW_INC ? 5 : -5;
            if (tax >= 0 && tax <= 50) do_action(PANEL_TOWNS, API_TOWN_TAX, r->ref * 1000 + tax);
        }
        break;
    case TW_BTN1:
        if (!r) break;
        if (mode == 0) g_open_town = r->ref;                    /* next frame: not inside the click */
        else if (r->key >= TW_PETITION_KEY) do_action(PANEL_TOWNS, API_PETITION, 1);
        else do_action(PANEL_TOWNS, API_BUY_TOWN, r->ref);
        break;
    case TW_BTN2:
        if (r && r->key >= TW_PETITION_KEY) do_action(PANEL_TOWNS, API_PETITION, 0);
        break;
    default: return 0;
    }
    g_dirty = 1;
    return 1;
}

/* ---- Diplomacy (art/make_diplomacy.py): the Chronicle nations page's relation rows, one per power */
#define TD_BTN1         3200
#define TD_BTN2         3201
static const char *const k_treaty_next[6] = {"Trade agreement", "Non-aggression pact", "Alliance", "", "", ""};

static const char *relation_word(int score)
{
    return score <= -50 ? RED "hostile" RESET : score < -15 ? RED "unfriendly" RESET : score < 15 ? "neutral"
         : score < 50 ? GREEN "friendly" RESET : GREEN "very friendly" RESET;
}

static int pending_offer(const Relation *r, const World *w)
{
    return r->expiry_day && w->day <= r->expiry_day && (r->status == TREATY_WAR || r->status == TREATY_PEACE);
}

static int next_treaty(const Relation *r)
{
    return r->status == TREATY_PEACE ? TREATY_TRADE : r->status == TREATY_TRADE ? TREATY_NONAGGRESSION
         : r->status == TREATY_NONAGGRESSION ? TREATY_ALLIANCE : -1;
}

static void diplo_build(const NationState *s, const World *w)
{
    for (int p = 0; p < N_POWERS; p++) {
        const Relation *r = &s->rel[p];
        LRow *row = lrow_add(p, p, core_power_name(p));
        if (!row) return;
        row->flag_anim = p;
        int st = r->status <= TREATY_CEASEFIRE ? r->status : 0;
        snprintf(row->cell[0], sizeof row->cell[0], "%s%s" RESET,
                 r->status == TREATY_WAR ? RED : r->status >= TREATY_TRADE && r->status <= TREATY_ALLIANCE ? GREEN : "",
                 k_status[st]);
        snprintf(row->cell[1], sizeof row->cell[1], "%s %+d", relation_word(r->score), r->score);
        snprintf(row->cell[2], sizeof row->cell[2], "%s%s", pending_offer(r, w) ? GREEN "offer!" RESET " " :
                 r->threat ? RED "threat!" RESET " " : "", core_ai_strategy_name(core_ai_strategy(s, w, p)));
        snprintf(row->cell[3], sizeof row->cell[3], "%s", r->recognized ? GREEN "yes" RESET : "no");
    }
}

static void diplo_footer(const NationState *s, const World *w)
{
    int p = g_lsel[PANEL_DIPLOMACY];
    void *b1 = gui_find("FND_Btn1"), *b2 = gui_find("FND_Btn2");
    char t[700], lab[64];
    t[0] = 0;
    show_power_flag("FND_SelFlag_%d", p);
    gui_show(b1, 0);
    gui_show(b2, 0);
    if (p < 0 || p >= N_POWERS) {
        set_textex("FND_SelName", "");
        set_textex_top("FND_SelInfo", "Click a power for its relation to the nation and what you can propose.");
        return;
    }
    const Relation *r = &s->rel[p];
    set_textex("FND_SelName", core_power_name(p));
    int st = r->status <= TREATY_CEASEFIRE ? r->status : 0, n = 0;
    n += snprintf(t + n, sizeof t - n, "%s. Relation %+d (%s). %s %s you. Their mood: %s.", k_status[st], r->score,
                  relation_word(r->score), core_power_name(p), r->recognized ? "recognizes" : "does not recognize",
                  core_ai_strategy_name(core_ai_strategy(s, w, p)));
    {   /* where the relation is heading and why (the Holland war fix: a war never comes out of nowhere) */
        char why[200];
        int tgt = core_relation_target(s, w, p, why, sizeof why);
        n += snprintf(t + n, sizeof t - n, " It drifts towards %+d (%s).", tgt, why);
        if (r->threat)
            n += snprintf(t + n, sizeof t - n, "<n>%s%s threatens war: improve relations or expect an attack." RESET,
                          RED, core_power_name(p));
    }
    if (g_confirm_action == API_WAR && g_confirm_arg == p) {
        snprintf(t + n, sizeof t - n, "<n>%s%s" RESET, RED, g_confirm_text);
        gui_button_text(b1, "Declare war");
        gui_tooltip(b1, "War it is");
        gui_button_text(b2, "Cancel");
        gui_tooltip(b2, "Keep the peace");
        gui_show(b1, 1);
        gui_show(b2, 1);
        set_textex_top("FND_SelInfo", t);
        return;
    }
    if (pending_offer(r, w)) {
        int war = r->status == TREATY_WAR;
        n += snprintf(t + n, sizeof t - n, "<n>%s%s offers %s (open for %d more days)." RESET, GREEN, core_power_name(p),
                      war ? "a ceasefire" : "a trade agreement", (int)(r->expiry_day - w->day));
        gui_button_text(b1, "Accept offer");
        gui_tooltip(b1, war ? "Accept the ceasefire" : "Accept the trade agreement");
        gui_button_text(b2, "Decline");
        gui_tooltip(b2, "Turn the offer down (they like you a little less)");
        gui_show(b1, 1);
        gui_show(b2, 1);
    } else if (r->status == TREATY_WAR) {
        int ch = core_acceptance_chance(s, w, p, TREATY_CEASEFIRE);
        n += snprintf(t + n, sizeof t - n, "<n>War exhaustion %d. Chance they accept a ceasefire: %d%%.",
                      r->war_exhaustion, ch);
        gui_button_text(b1, "Offer ceasefire");
        snprintf(lab, sizeof lab, "Offer %s a ceasefire (%d%% chance)", core_power_name(p), ch);
        gui_tooltip(b1, lab);
        gui_show(b1, 1);
    } else if (r->status == TREATY_CEASEFIRE) {
        int ch = core_acceptance_chance(s, w, p, TREATY_PEACE);
        n += snprintf(t + n, sizeof t - n, "<n>Ceasefire. Chance they accept peace: %d%%.", ch);
        gui_button_text(b1, "Propose peace");
        snprintf(lab, sizeof lab, "Propose peace to %s (%d%% chance)", core_power_name(p), ch);
        gui_tooltip(b1, lab);
        gui_show(b1, 1);
    } else {
        int next = next_treaty(r);
        if (next > 0) {
            int ch = core_acceptance_chance(s, w, p, (Treaty)next);
            n += snprintf(t + n, sizeof t - n, "<n>Chance they accept %s %s: %d%%.",
                          core_article(k_treaty_next[next - 1], 0), k_treaty_next[next - 1], ch);
            snprintf(lab, sizeof lab, "Propose %s", next == TREATY_ALLIANCE ? "an alliance" :
                     next == TREATY_TRADE ? "trade" : "non-aggression");
            gui_button_text(b1, lab);
            snprintf(lab, sizeof lab, "Propose %s %s to %s (%d%% chance)", core_article(k_treaty_next[next - 1], 0),
                     k_treaty_next[next - 1], core_power_name(p), ch);
            gui_tooltip(b1, lab);
            gui_show(b1, 1);
        }
        gui_button_text(b2, "Declare war");
        gui_tooltip(b2, "Declare war (asks first)");
        gui_show(b2, 1);
    }
    if (g_feedback[0] && g_feedback_page == PANEL_DIPLOMACY)
        snprintf(t + n, sizeof t - n, "<n>%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
    set_textex_top("FND_SelInfo", t);
}

static int diplo_key(int key)
{
    const NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    int p = g_lsel[PANEL_DIPLOMACY];
    if (p < 0 || p >= N_POWERS || (key != TD_BTN1 && key != TD_BTN2)) return 0;
    const Relation *r = &s->rel[p];
    int confirm = g_confirm_action == API_WAR && g_confirm_arg == p;
    g_confirm_action = 0;
    if (confirm) {
        if (key == TD_BTN1) do_action(PANEL_DIPLOMACY, API_WAR, p);
        else g_feedback[0] = 0;
    } else if (pending_offer(r, &w)) {
        do_action(PANEL_DIPLOMACY, key == TD_BTN1 ? API_OFFER_ACCEPT : API_OFFER_DECLINE, p);
    } else if (r->status == TREATY_WAR) {
        if (key == TD_BTN1) do_action(PANEL_DIPLOMACY, API_CEASEFIRE, p);
    } else if (r->status == TREATY_CEASEFIRE) {
        if (key == TD_BTN1) do_action(PANEL_DIPLOMACY, API_PEACE, p);
    } else if (key == TD_BTN1) {
        int next = next_treaty(r);
        if (next > 0) do_action(PANEL_DIPLOMACY, API_PROPOSE, p * 10 + next);
    } else {                                                    /* ask first, as the dialogs did */
        g_confirm_action = API_WAR;
        g_confirm_arg = p;
        g_feedback[0] = 0;
        snprintf(g_confirm_text, sizeof g_confirm_text, "Declare war on %s? Its fleets and towns will treat you "
                 "as an enemy.", core_power_name(p));
    }
    g_dirty = 1;
    return 1;
}

/* ---- Navy and defence (art/make_navy.py): mode 0 the fleets (convoy-list rows), 1 naval
   command (standing order, commissioning), 2 town defence (town-list rows). The list swaps
   its row template with the mode. */
#define TV_BTN1         3300
#define TV_BTN2         3301
#define TV_MODE         3302
#define TV_GOTO         3303
#define TV_ORDER_PREV   3304
#define TV_ORDER_NEXT   3305
static const char *const k_navy_mode_name[3] = {"Fleets", "Naval command", "Town defence"};
static const char *const k_order_desc[NAVY_ORDER_COUNT] = {
    "Guard the harbours; strike at weak enemy ports while at war.",
    "Cruise off enemy ports and attack their convoys; plunder goes to the treasury.",
    "Attack enemy towns; a won land assault annexes the town."};

static void fleet_order_text(const FleetInfo *f, int standing, int brief, char *out, int cap)
{
    char tgt[48] = "";
    if (f->target >= 0) town_name(f->target, tgt, sizeof tgt);
    if (f->order == FLEET_GUARD) snprintf(out, cap, brief ? "Guard %s" : "Own order: guard %s.", tgt);
    else if (f->order == FLEET_CAMPAIGN) snprintf(out, cap, brief ? "Campaign: %s" : "Own order: war campaign against %s.", tgt);
    else if (f->order == FLEET_RAID) snprintf(out, cap, brief ? "Raid enemy trade" : "Own order: raid enemy trade.");
    else snprintf(out, cap, brief ? "%s (standing)" : "Follows the standing order (%s).", core_navy_order_name(standing));
}

static void navy_build(const NationState *s, const World *w)
{
    int mode = g_lmode[PANEL_MILITARY];
    if (mode == 0 && navy_ready()) {
        FleetInfo fl[16];
        int nf = navy_fleets(fl, 16);
        for (int i = 0; i < nf; i++) {
            char nm[32];
            snprintf(nm, sizeof nm, "Fleet %d", i + 1);
            LRow *r = lrow_add((int)fl[i].handle, i, nm);
            if (!r) return;
            fleet_order_text(&fl[i], s->navy.order, 1, r->cell[0], sizeof r->cell[0]);
            snprintf(r->cell[1], sizeof r->cell[1], "%d", fl[i].ships);
            snprintf(r->cell[2], sizeof r->cell[2], "%d", fl[i].sailors);
            r->sym = fl[i].state == 9 ? 3 : fl[i].town >= 0 ? 1 : 2;
        }
    } else if (mode == 2) {
        for (int t = 0; t < MAX_TOWNS; t++) {
            if (!s->town[t].member) continue;
            char nm[64];
            town_name(t, nm, sizeof nm);
            LRow *r = lrow_add(t, t, nm);
            if (!r) return;
            int soldiers, towers, budget;
            navy_town_defence(t, &soldiers, &towers, &budget);
            snprintf(r->cell[0], sizeof r->cell[0], "%d", soldiers);
            snprintf(r->cell[1], sizeof r->cell[1], "%d / 10", towers);
            snprintf(r->cell[2], sizeof r->cell[2], "%d", s->navy.towers_bought[t]);
            snprintf(r->cell[3], sizeof r->cell[3], "%s", budget >= 1000 ? num(budget) : "-");
            r->flag = flag_nation_path();
        }
    }
    (void)w;
}

static void navy_footer(const NationState *s, const World *w)
{
    const Config *cf = adapter_config();
    int mode = g_lmode[PANEL_MILITARY], rank = core_naval_rank(s, w), cap = core_fleet_cap(s, w);
    char t[700], lab[96];
    set_text("FNV_Cap_01", mode == 2 ? "Town Defence" : "Navy and Defence");
    if (!navy_ready())
        snprintf(t, sizeof t, "%sThe national navy is unavailable in this game build." RESET, RED);
    else
        snprintf(t, sizeof t, "%s: %d of %d fleet%s. Standing order: %s.", core_naval_rank_name(rank), w->nation_fleets,
                 cap, cap == 1 ? "" : "s", core_navy_order_name(s->navy.order));
    set_textex("FNV_Head", mode == 2 ? "" : t);             /* town defence: the column heads sit there */
    gui_show(gui_find("FNV_ScrollDrawable"), mode != 1);
    gui_show(gui_find("FNV_Scrollbar"), mode != 1);
    gui_show(gui_find("FNV_Command"), mode == 1);
    char n[24];
    for (int i = 0; i < 4; i++) {
        snprintf(n, sizeof n, "FNV_HeadT_%d", i);
        gui_show(gui_find(n), mode == 2);
        snprintf(n, sizeof n, "FNV_HeadTI_%d", i);
        gui_show(gui_find(n), mode == 2);
    }
    void *b1 = gui_find("FNV_Btn1"), *b2 = gui_find("FNV_Btn2"), *b3 = gui_find("FNV_Btn3");
    gui_button_text(b3, k_navy_mode_name[(mode + 1) % 3]);
    snprintf(lab, sizeof lab, "Show %s", mode == 0 ? "the standing order and new fleets" : mode == 1 ?
             "the defence of the member towns" : "the fleets");
    gui_tooltip(b3, lab);
    gui_show(b1, 0);
    gui_show(b2, 0);
    gui_show(gui_find("FNV_GoTo"), 0);
    LRow *r = lrow(g_lsel[PANEL_MILITARY]);
    size_t m = 0;
    t[0] = 0;
    if (mode == 1) {
        set_textex("FNV_SelName", "");
        set_text("FNV_OrderCap", "Standing order for every fleet");
        set_text("FNV_OrderValue", core_navy_order_name(s->navy.order));
        int need = core_order_min_rank(s->navy.order);
        snprintf(t, sizeof t, "%s%s", k_order_desc[s->navy.order], rank < need ? RED " Needs a higher rank." RESET : "");
        set_textex("FNV_OrderNote", t);
        set_text("FNV_FleetsCap", "Fleets in service");
        m = (size_t)snprintf(t, sizeof t, "%d of %d (%s). A new fleet costs %s, then %s a month. Last month the navy "
                             "and forts cost %s. Plunder brought home so far: %s.", w->nation_fleets, cap,
                             core_naval_rank_name(rank), gold(cf->fleet_cost), gold(cf->fleet_upkeep),
                             gold(s->navy.last_military), gold(s->navy.plunder_total));
        if (g_feedback[0] && g_feedback_page == PANEL_MILITARY)
            snprintf(t + m, sizeof t - m, "<n><n>%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
        set_textex_top("FNV_FleetsNote", t);
        set_textex_top("FNV_SelInfo", "");
        if (navy_ready()) {
            gui_button_text(b1, "Commission");
            gui_tooltip(b1, "Fit out a new fleet in the capital");
            gui_show(b1, 1);
            if (w->nation_fleets > 0) {
                gui_button_text(b2, "Pay off one");
                gui_tooltip(b2, "Pay off one fleet to save its upkeep");
                gui_show(b2, 1);
            }
        }
        return;
    }
    if (!r) {
        set_textex("FNV_SelName", "");
        snprintf(t, sizeof t, "%s", mode == 0 ? (g_nlrows ? "Click a fleet for its orders." :
                 "The nation has no fleet yet: Naval command commissions one.") : "Click a town for its defence.");
    } else if (mode == 0) {
        FleetInfo fl[16];
        int nf = navy_fleets(fl, 16), i = r->ref;
        if (i < nf && fl[i].handle == (uint32_t)r->key) {
            char where[64], ord[96];
            ship_where(fl[i].state, fl[i].town, where, sizeof where);
            snprintf(lab, sizeof lab, "%s (%s)", r->name, where);
            set_textex("FNV_SelName", lab);
            fleet_order_text(&fl[i], s->navy.order, 0, ord, sizeof ord);
            m = (size_t)snprintf(t, sizeof t, "%d ships, %d sailors. %s", fl[i].ships, fl[i].sailors, ord);
            if (fl[i].state != 9 && fl[i].dest >= 0 && fl[i].dest != fl[i].town) {
                town_name(fl[i].dest, where, sizeof where);
                m += (size_t)snprintf(t + m, sizeof t - m, " Heading for %s.", where);
            }
            gui_show(gui_find("FNV_GoTo"), 1);
            gui_button_text(b1, "Next order");
            gui_tooltip(b1, "Standing order, guard a town, raid, or a campaign (by rank)");
            gui_show(b1, 1);
            if (fl[i].order == FLEET_GUARD || fl[i].order == FLEET_CAMPAIGN) {
                gui_button_text(b2, "Next target");
                gui_tooltip(b2, "Choose the next town for this order");
                gui_show(b2, 1);
            }
        }
    } else {
        int soldiers, towers, budget;
        navy_town_defence(r->ref, &soldiers, &towers, &budget);
        snprintf(lab, sizeof lab, "Defence of %s", r->name);
        set_textex("FNV_SelName", lab);
        m = (size_t)snprintf(t, sizeof t, "%d soldiers, %d of 10 cannon towers (%d paid by the treasury). Recruits: %s for "
                             "about 20 soldiers. A tower: %s, then %s a month.", soldiers, towers,
                             s->navy.towers_bought[r->ref], gold(cf->garrison_cost), gold(cf->tower_cost),
                             gold(cf->tower_upkeep));
        if (budget >= 1000) m += (size_t)snprintf(t + m, sizeof t - m, " %s waits for recruits.", gold(budget));
        gui_button_text(b1, "Recruit");
        gui_tooltip(b1, "Recruit soldiers here from the treasury");
        gui_show(b1, 1);
        if (towers < 10) {
            gui_button_text(b2, "Build tower");
            gui_tooltip(b2, "Build a cannon tower here from the treasury");
            gui_show(b2, 1);
        }
    }
    if (g_feedback[0] && g_feedback_page == PANEL_MILITARY)
        snprintf(t + m, sizeof t - m, "%s%s%s" RESET, m ? "<n>" : "", g_feedback_ok ? GREEN : RED, g_feedback);
    set_textex_top("FNV_SelInfo", t);
}

static void navy_template(void *p)
{
    void *want = g_navy_tmpl[g_lmode[PANEL_MILITARY] == 2];
    if (want) SetTemplate(p, want);
}

static int navy_key(int key)
{
    const NationState *s = adapter_state();
    LRow *r = lrow(g_lsel[PANEL_MILITARY]);
    int mode = g_lmode[PANEL_MILITARY];
    switch (key) {
    case TV_MODE:
        g_lmode[PANEL_MILITARY] = (mode + 1) % 3;
        g_lsel[PANEL_MILITARY] = -1;
        g_feedback[0] = 0;
        break;
    case TV_ORDER_PREV:
    case TV_ORDER_NEXT: {
        int o = (s->navy.order + (key == TV_ORDER_NEXT ? 1 : NAVY_ORDER_COUNT - 1)) % NAVY_ORDER_COUNT;
        do_action(PANEL_MILITARY, API_ORDER, o);
        break;
    }
    case TV_GOTO:
        if (r && mode == 0) do_action(PANEL_MILITARY, API_GOTO, r->key);
        break;
    case TV_BTN1:
        if (mode == 1) do_action(PANEL_MILITARY, API_COMMISSION, 0);
        else if (r && mode == 0) do_action(PANEL_MILITARY, API_FLEET_ORDER, r->key);
        else if (r && mode == 2) do_action(PANEL_MILITARY, API_RECRUIT, r->ref);
        break;
    case TV_BTN2:
        if (mode == 1) do_action(PANEL_MILITARY, API_PAYOFF, 0);
        else if (r && mode == 0) do_action(PANEL_MILITARY, API_FLEET_TARGET, r->key);
        else if (r && mode == 2) do_action(PANEL_MILITARY, API_TOWER, r->ref);
        break;
    default: return 0;
    }
    g_dirty = 1;
    return 1;
}

static void list_wire(int kind, void *p)
{
    if (kind == PANEL_TOWNS) {
        wire("FNW_TaxDec", p, TW_DEC, "Lower the tax in this town by 5%");
        wire("FNW_TaxInc", p, TW_INC, "Raise the tax in this town by 5%");
        wire("FNW_Btn1", p, TW_BTN1, NULL);
        wire("FNW_Btn2", p, TW_BTN2, NULL);
        wire("FNW_Mode", p, TW_MODE, NULL);
    } else if (kind == PANEL_DIPLOMACY) {
        wire("FND_Btn1", p, TD_BTN1, NULL);
        wire("FND_Btn2", p, TD_BTN2, NULL);
        gui_show(gui_find("FND_Scrollbar"), 0);                  /* four rows always fit */
        set_text("FND_Caption", "Diplomacy");
        set_text("FND_Txt5", "Relations with the powers");
        set_textex("FND_Head_0", "Treaty");
        set_textex("FND_Head_1", "Relation");
        set_textex("FND_Head_2", "Mood");
    } else if (kind == PANEL_MILITARY) {
        wire("FNV_Btn1", p, TV_BTN1, NULL);
        wire("FNV_Btn2", p, TV_BTN2, NULL);
        wire("FNV_Btn3", p, TV_MODE, NULL);
        wire("FNV_GoTo", p, TV_GOTO, "Go to: centre the sea map on this fleet");
        gui_icon(gui_find("FNV_GoTo"), 31);                     /* Pr2_Icon_Auge */
        static const struct { const char *name; int icon, key; const char *tip; } arrows[2] = {
            {"FNV_OrderPrev", 0x57, TV_ORDER_PREV, "The previous standing order"},
            {"FNV_OrderNext", 0x56, TV_ORDER_NEXT, "The next standing order"}};
        for (int i = 0; i < 2; i++) {
            gui_icon_at(gui_find(arrows[i].name), arrows[i].icon, 0x5A, 5, 6);
            wire(arrows[i].name, p, arrows[i].key, arrows[i].tip);
        }
        static const char *const tips[4] = {"Soldiers in the garrison", "Cannon towers",
                                            "Towers the treasury paid (their upkeep is national)",
                                            "Gold waiting for recruits"};
        char n[24];
        for (int i = 0; i < 4; i++) {
            snprintf(n, sizeof n, "FNV_HeadT_%d", i);
            set_tip(n, tips[i]);
            snprintf(n, sizeof n, "FNV_HeadTI_%d", i);
            set_tip(n, tips[i]);
        }
    }
}

/* The Overview page (art/make_overview.py): the facts in the Successes page's look, then the
   Chronicle's "Size and strength" with the nation next to the four powers. */
/* The Wars row. In-text flags (<g:INTEXT_*>) cannot be lined up: a TEXTFLUSS_KEINEHOEHE icon adds
   no line height and hangs from the line, so a cell of flags only sat lower than one with "you"
   in it, and the 40 px cells reached below the row. Each cell has static flags
   FNO_WarFlag_<k>_<p> and a "you" box FNO_WarYou_<k> (art/make_overview.py), placed here round
   the centre of the cell's "-" box FNO_Wars_<k> (the "Wars" label's line, under the column's
   header flag): one or two entries on one line, three or four on two lines of two, each line
   centred, the block centred on the row. */
#define WAR_W   25                                /* a flag, 25x15; "you" takes a flag's place */
#define WAR_H   15
#define WAR_GAP 3
#define WAR_YOU (1u << N_POWERS)                  /* entry bits: 0..3 the powers, 4 "you" */
static int g_dev_wars[5] = {-1, -1, -1, -1, -1};  /* tests (Nation_DevWarsRow): a cell's entries */
static int g_wars_shown[5] = {-1, -1, -1, -1, -1};

/* tests: mask >= 0 shows those entries in the cell, -1 the real wars again, -2 only asks;
   returns what the cell showed at the last refresh (-1 = the page was not up) */
int panel_dev_wars(int cell, int mask)
{
    if (cell < 0 || cell >= 5) return -1;
    if (mask >= -1) {
        g_dev_wars[cell] = mask < 0 ? -1 : mask & 0x1F;
        g_dirty = 1;
    }
    return g_wars_shown[cell];
}

static void overview_wars(int k, unsigned mask)
{
    char n[32];
    snprintf(n, sizeof n, "FNO_Wars_%d", k);
    void *cell = gui_find(n), *ent[N_POWERS + 1];
    int ne = 0;
    g_wars_shown[k] = (int)mask;
    for (int e = 0; e <= N_POWERS; e++) {
        if (e < N_POWERS) snprintf(n, sizeof n, "FNO_WarFlag_%d_%d", k, e);
        else snprintf(n, sizeof n, "FNO_WarYou_%d", k);
        void *d = gui_find(n);
        int on = d && cell && (mask >> e & 1);
        gui_show(d, on);
        if (!on) continue;
        ent[ne++] = d;
        if (e == N_POWERS) gui_set_textex(d, RED "you" RESET);   /* FNO_WarYou_<k> is a CTextBoxEx */
    }
    if (!cell) return;
    gui_set_textex(cell, ne ? "" : "-");
    int x, y;
    gui_pos(cell, &x, &y);
    int cx = x + gui_width(cell) / 2, cy = y + gui_height(cell) / 2;
    int lines = ne > 2 ? 2 : 1, top = cy - (lines * WAR_H + (lines - 1) * WAR_GAP) / 2;
    for (int i = 0; i < ne; i++) {
        int line = i / 2, in_line = line ? ne - 2 : ne < 2 ? ne : 2;
        int left = cx - (in_line * WAR_W + (in_line - 1) * WAR_GAP) / 2 + (i % 2) * (WAR_W + WAR_GAP);
        int ly = top + line * (WAR_H + WAR_GAP);
        gui_set_pos(ent[i], left + (WAR_W - gui_width(ent[i])) / 2, ly + (WAR_H - gui_height(ent[i])) / 2);
    }
}

static void overview_setup(void)
{
    g_ov_flag[0][0] = g_ov_flag[1][0] = 0;                     /* a new page: its flag images are empty */
    static const char *const cap[7] = {"Name", "Form of state", "Capital", "Stability", "Treasury", "Naval rank",
                                       "Recognition"};
    char n[24];
    for (int i = 0; i < 7; i++) {
        snprintf(n, sizeof n, "FNO_Cap_%d", i);
        set_text(n, cap[i]);
    }
    set_text("FNO_Caption", "Your Nation");
    set_text("FNO_Txt6", "Size and strength");
    set_text("FNO_Row_Pop", "Inhabitants");
    set_text("FNO_Row_Towns", "Towns");
    set_text("FNO_Row_Rel", "Relation");
    set_text("FNO_Row_Wars", "Wars");
    set_tip("FNO_Row_Rel", "How each power stands towards the nation");
    set_tip("FNO_Row_Wars", "Who is at war with whom");
    set_tip("FNO_ColFlag", "Your nation");
    for (int p = 0; p < N_POWERS; p++) {
        snprintf(n, sizeof n, "FNO_ColFlag_%d", p);
        set_tip(n, core_power_name(p));
    }
}

static void overview_fill(void)
{
    const NationState *s = adapter_state();
    World w;
    adapter_snapshot(&w);
    char t[700], cap[64];
    load_flag(gui_find("FNO_Flag"), flag_nation_path(), g_ov_flag[0], sizeof g_ov_flag[0]);
    load_flag(gui_find("FNO_ColFlag"), flag_nation_path(), g_ov_flag[1], sizeof g_ov_flag[1]);
    set_textex("FNO_Val_0", s->name);
    int cd = core_government_cooldown(s);
    snprintf(t, sizeof t, "%s%s", core_government_name(core_government(s)), cd > 0 ? " (reform in a while)" : "");
    if (cd > 0) snprintf(t, sizeof t, "%s (reform in %d month%s)", core_government_name(core_government(s)), cd,
                         cd == 1 ? "" : "s");
    set_textex("FNO_Val_1", t);
    if (s->capital < MAX_TOWNS) town_name(s->capital, cap, sizeof cap);
    set_textex("FNO_Val_2", s->capital < MAX_TOWNS ? cap : RED "none: the nation governs in exile" RESET);
    snprintf(t, sizeof t, "%s%d" RESET " / 100", s->stability >= 60 ? GREEN : s->stability < 35 ? RED : "", s->stability);
    set_textex("FNO_Val_3", t);
    snprintf(t, sizeof t, "%s%s" RESET GOLD, s->treasury < 0 ? RED : "", num(s->treasury));
    set_textex("FNO_Val_4", t);
    int rank = core_naval_rank(s, &w);
    snprintf(t, sizeof t, "%s, %d of %d fleet%s", core_naval_rank_name(rank), w.nation_fleets, core_fleet_cap(s, &w),
             core_fleet_cap(s, &w) == 1 ? "" : "s");
    set_textex("FNO_Val_5", t);
    int rec = 0, wars = 0;
    for (int p = 0; p < N_POWERS; p++) {
        rec += s->rel[p].recognized;
        wars += s->rel[p].status == TREATY_WAR;
    }
    snprintf(t, sizeof t, "by %d of 4 powers", rec);
    set_textex("FNO_Val_6", t);

    /* the comparison: column 0 the nation, 1..4 the powers */
    int64_t pop[5] = {0};
    int towns[5] = {0};
    for (int i = 0; i < w.n_towns && i < MAX_TOWNS; i++) {
        if (!w.town[i].exists) continue;
        int col = s->town[i].member ? 0 : w.town[i].power < N_POWERS ? w.town[i].power + 1 : -1;
        if (col < 0) continue;
        pop[col] += w.town[i].population;
        towns[col]++;
    }
    char n[24];
    for (int k = 0; k < 5; k++) {
        snprintf(n, sizeof n, "FNO_Pop_%d", k);
        set_textex(n, num(pop[k]));
        snprintf(n, sizeof n, "FNO_Towns_%d", k);
        set_textex(n, num(towns[k]));
        snprintf(n, sizeof n, "FNO_Rel_%d", k);
        set_textex(n, k ? relation_word(s->rel[k - 1].score) : "-");
        unsigned mask = 0;
        for (int q = 0; q < N_POWERS; q++)
            if (k == 0 ? s->rel[q].status == TREATY_WAR : q != k - 1 && w.power_war[k - 1][q]) mask |= 1u << q;
        if (k && s->rel[k - 1].status == TREATY_WAR) mask |= WAR_YOU;
        overview_wars(k, g_dev_wars[k] >= 0 ? (unsigned)g_dev_wars[k] : mask);
    }

    /* what needs attention */
    size_t m = 0;
    t[0] = 0;
    int pt = core_petition_town(s);
    if (pt >= 0) {
        town_name(pt, cap, sizeof cap);
        m += snprintf(t + m, sizeof t - m, "%s%s asks to join the nation (Towns, Towns for sale)." RESET "<n>", GREEN, cap);
    }
    for (int p = 0; p < N_POWERS; p++)
        if (pending_offer(&s->rel[p], &w))
            m += snprintf(t + m, sizeof t - m, "%s%s makes you an offer (Diplomacy)." RESET "<n>", GREEN, core_power_name(p));
    int unrest = 0;
    for (int i = 0; i < MAX_TOWNS; i++) unrest += s->town[i].member && s->town[i].unrest >= 1;
    if (unrest) m += snprintf(t + m, sizeof t - m, "%s%d town%s in unrest (Towns)." RESET "<n>", RED, unrest,
                              unrest == 1 ? " is" : "s are");
    if (wars) m += snprintf(t + m, sizeof t - m, "%sAt war with %d power%s." RESET "<n>", RED, wars, wars == 1 ? "" : "s");
    if (s->treasury < 0) m += snprintf(t + m, sizeof t - m, "%sThe treasury is empty: fleets desert after two unpaid "
                                       "months." RESET "<n>", RED);
    if (!m) snprintf(t, sizeof t, "%sThe nation is at peace and in good order." RESET, wars ? "" : GREEN);
    if (g_feedback[0] && g_feedback_page == PANEL_OVERVIEW) {
        m = strlen(t);
        snprintf(t + m, sizeof t - m, "%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
    }
    set_textex_top("FNO_Notice", t);
}

/* The Government page (art/make_government.py): the new-game feature selector for the five forms. */
#define TG_PREV         3400
#define TG_NEXT         3401
#define TG_ADOPT        3402
static int g_gov_sel = -1, g_gov_confirm;
static const char *const k_gov_long[GOV_COUNT] = {
    "The plain form of a young state: taxes, tariffs, upkeep, garrisons and diplomacy all work at their "
    "normal values.<n><n>" GREEN "Strengths:" RESET " none.<n>" RED "Weaknesses:" RESET " none.",
    "A state run by its merchants.<n><n>" GREEN "Strengths:" RESET " better tax collection, a quarter more "
    "tariff income; the powers accept trade agreements, peace and ceasefires more readily.<n>"
    RED "Weaknesses:" RESET " every month at war costs more stability.",
    "A crown with a strong hand.<n><n>" GREEN "Strengths:" RESET " garrisons count more for loyalty and "
    "collection, the nation is more stable.<n>" RED "Weaknesses:" RESET " a quarter more upkeep for the court "
    "and the garrisons; conquered towns settle slowly.",
    "A state of privateers.<n><n>" GREEN "Strengths:" RESET " privateering brings gold every month from every "
    "power at war with you; war costs little stability.<n>" RED "Weaknesses:" RESET " every power likes you "
    "less (at once on the reform, and every month), alliances and treaties are harder; conquered towns resist "
    "longer.",
    "A league of free towns.<n><n>" GREEN "Strengths:" RESET " loyal towns; unrest only breaks out below "
    "loyalty 15; non-aggression pacts come easier.<n>" RED "Weaknesses:" RESET " weaker tax collection, and a "
    "rebelling town secedes a month sooner."};

static void gov_fill(void)
{
    const NationState *s = adapter_state();
    int cur = core_government(s), cool = core_government_cooldown(s);
    if (g_gov_sel < 0 || g_gov_sel >= GOV_COUNT) g_gov_sel = cur;
    char t[400];
    set_text("FNG_Caption", "Form of Government");
    if (cool > 0) snprintf(t, sizeof t, "In force: %s (reform in %d month%s)", core_government_name(cur), cool,
                           cool == 1 ? "" : "s");
    else snprintf(t, sizeof t, "In force: %s", core_government_name(cur));
    set_text("FNG_InForce", t);
    set_text("FNG_SelCap", "Forms of government");
    set_text("FNG_Value", core_government_name(g_gov_sel));
    set_textex_top("FNG_Desc", k_gov_long[g_gov_sel]);
    void *adopt = gui_find("FNG_Adopt");
    int can = g_gov_sel != cur;
    gui_show(adopt, can);
    if (g_gov_confirm && can) {
        snprintf(t, sizeof t, "%sAdopt the %s? The reform costs %d stability; the next one is possible in %d months."
                 RESET, RED, core_government_name(g_gov_sel), GOV_CHANGE_STABILITY, GOV_COOLDOWN_MONTHS);
        gui_button_text(adopt, "Confirm reform");
    } else {
        g_gov_confirm = 0;
        if (g_feedback[0] && g_feedback_page == PANEL_GOVERNMENT)
            snprintf(t, sizeof t, "%s%s" RESET, g_feedback_ok ? GREEN : RED, g_feedback);
        else if (!can) snprintf(t, sizeof t, "%sThe form in force." RESET, GREEN);
        else if (cool > 0) snprintf(t, sizeof t, "%sA reform is possible in %d month%s." RESET, RED, cool,
                                    cool == 1 ? "" : "s");
        else snprintf(t, sizeof t, "A reform costs %d stability and is possible every %d months.",
                      GOV_CHANGE_STABILITY, GOV_COOLDOWN_MONTHS);
        gui_button_text(adopt, "Adopt");
    }
    gui_tooltip(adopt, "Adopt this form of government");
    set_textex("FNG_Status", t);
}

static void gov_setup(void *p)
{
    static const struct { const char *name; int icon, key; const char *tip; } arrows[2] = {
        {"FNG_Prev", 0x57, TG_PREV, "The previous form"}, {"FNG_Next", 0x56, TG_NEXT, "The next form"}};
    for (int i = 0; i < 2; i++) {
        gui_icon_at(gui_find(arrows[i].name), arrows[i].icon, 0x5A, 5, 6);
        wire(arrows[i].name, p, arrows[i].key, arrows[i].tip);
    }
    wire("FNG_Adopt", p, TG_ADOPT, NULL);
    g_gov_sel = -1;
    g_gov_confirm = 0;
}

static int gov_key(int key)
{
    switch (key) {
    case TG_PREV: g_gov_sel = (g_gov_sel + GOV_COUNT - 1) % GOV_COUNT; g_gov_confirm = 0; g_feedback[0] = 0; break;
    case TG_NEXT: g_gov_sel = (g_gov_sel + 1) % GOV_COUNT; g_gov_confirm = 0; g_feedback[0] = 0; break;
    case TG_ADOPT:
        if (!g_gov_confirm) { g_gov_confirm = 1; g_feedback[0] = 0; break; }
        g_gov_confirm = 0;
        do_action(PANEL_GOVERNMENT, API_GOVERNMENT, g_gov_sel);
        break;
    default: return 0;
    }
    g_dirty = 1;
    return 1;
}

/* Town info: the game's town window for a member town (OpenTownInfo closes every menu, ours too) */
static void towns_open_pending(void)
{
    int t = g_open_town;
    g_open_town = -1;
    uint32_t h = t >= 0 ? eng_town_handle(t) : 0;
    void *gm = game_menu();
    if (!h || !gm) return;
    log_line("PANEL: town info for town %d", t);
    OpenTownInfo(gm, (int)h);
}

static void *visible_page(void);
static int visible_kind(void);
static void *visible_page(void)
{
    for (int i = 0; i < PANEL_KINDS; i++)
        if (g_pages[i] && *(void **)((uint8_t *)g_pages[i] + PG_ROOT)) return g_pages[i];
    return NULL;
}

static void TC on_click(void *page, int key);

static void configure_button(void *btn, void *page, int key, int icon, int action, const char *tip)
{
    if (!btn) return;
    if (!action) { gui_show(btn, 0); return; }
    gui_show(btn, 1);
    gui_icon(btn, icon);
    gui_tooltip(btn, tip);
    gui_on_click(btn, page, on_click, key);
}

static void *child(void *p, int key, const char *name)
{
    GuiStr nm;
    gui_str_init(&nm, name);
    void *d = FindEntryChild(p, key, &nm);
    gui_str_free(&nm);
    return d;
}

static const char *const k_btn_name[2] = {"FNC_Btn1", "FNC_Btn2"};

static void TC page_refresh(void *p)
{
    if (!*(void **)((uint8_t *)p + PG_ROOT)) return;
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    build_cards(kind);
    uint32_t h = cards_hash();
    if (*(uint32_t *)((uint8_t *)p + PG_HASH) == h) return;       /* unchanged: keep the scroll position */
    *(uint32_t *)((uint8_t *)p + PG_HASH) = h;
    if (kind == PANEL_FOUND) found_read_name();                 /* the card is about to be recreated */
    g_fd.page = NULL;
    g_fd.key = -1;
    ClearAll(p);
    for (int i = 0; i < g_ncards; i++) {
        uint32_t *item = gui_alloc(0x10);
        if (!item) break;
        item[0] = ITEM_VTABLE;
        item[1] = (uint32_t)i;
        item[2] = 0;
        item[3] = 0;
        if (!AddEntry(p, i, item, 1, 0)) continue;
        if (kind == PANEL_FOUND) {
            found_setup(p, i);
            continue;
        }
        void *eye = child(p, i, "FNC_BtnRemove");
        if (g_cards[i].go_to) configure_button(eye, p, 2000 + i, 31, API_GOTO,      /* Pr2_Icon_Auge */
                                               "Go to: centre the sea map on this ship");
        else gui_show(eye, 0);
        for (int b = 0; b < 2; b++) {
            void *btn = child(p, i, k_btn_name[b]);
            const CardBtn *cb = &g_cards[i].btn[b];
            if (!btn) continue;
            if (!cb->action) { gui_show(btn, 0); continue; }
            gui_show(btn, 1);
            gui_button_text(btn, cb->label);
            gui_tooltip(btn, cb->tip);
            gui_on_click(btn, p, on_click, i * 2 + b);
        }
    }
    for (int i = 0; i < 2; i++)
        configure_button(gui_find(i ? "LON_BtnMissonsDone" : "LON_BtnMissonsOpen"), p, 1000 + i,
                         g_pbtn[i].icon, g_pbtn[i].action, g_pbtn[i].tip);
    gui_show(gui_find("LON_NoEntry_1"), g_ncards == 0);
    Relayout(p);
}

/* The card: body under the plates, the buttons under the body, the card sized to fit. */
static void TC page_fill(void *p, void *item)
{
    int key = ((int *)item)[1];
    void *card = ((void **)item)[2];
    if (key < 0 || key >= g_ncards || !card) return;
    Card *c = &g_cards[key];
    if (*(int *)((uint8_t *)p + PG_KIND) == PANEL_FOUND) {
        gui_set_text(child(p, key, "FNF_TmplCaption"), c->caption);
        gui_set_text(child(p, key, "FNF_TmplLoka"), c->left);
        gui_set_text(child(p, key, "FNF_TmplDate"), c->right);
        gui_set_textex(child(p, key, "FNF_TmplText"), c->body);
        return;
    }
    gui_set_text(child(p, key, "FNC_TmplCaption"), c->caption);
    gui_set_text(child(p, key, "FNC_TmplLoka"), c->left);
    gui_set_text(child(p, key, "FNC_TmplDate"), c->right);
    void *text = child(p, key, "FNC_TmplText");
    if (!text) return;
    int tx, ty, w = gui_width(text);
    gui_pos(text, &tx, &ty);
    int h = gui_set_textex(text, c->body);
    gui_set_size(text, w, h);
    int bottom = ty + h + 4, any = 0;
    for (int b = 0; b < 2; b++) {
        void *btn = child(p, key, k_btn_name[b]);
        if (!btn || !c->btn[b].action) continue;
        int bx, by;
        gui_pos(btn, &bx, &by);
        gui_set_pos(btn, bx, bottom + 2);
        any = 1;
    }
    if (any) bottom += 2 + 26 + 4;
    gui_set_size(card, gui_width(card), bottom + 2);
}

static void TC page_create(void *p, void *parent_root)
{
    int kind = *(int *)((uint8_t *)p + PG_KIND);
    if (!SetupFromFile(p, parent_root, "NACHRICHTEN_LISTE_800x600.screen")) {
        log_line("PANEL: NACHRICHTEN_LISTE could not be loaded");
        return;
    }
    void *slider = gui_find("LON_Scrollbar"), *scroll = gui_find("LON_ScrollDrawable");
    if (slider && scroll) InitScroll(p, scroll, slider);
    GuiPoint start = {0, 10};
    SetLayout(p, 10, &start, 0, 0, 1);
    void *root = *(void **)((uint8_t *)p + PG_ROOT);
    void *tmpl = gui_create_screen(root, kind == PANEL_FOUND ? "FNN_FOUND_800x600.screen" : "FNN_CARD_800x600.screen");
    if (tmpl) {
        ((V0_t)(*(void ***)tmpl)[6])(tmpl);                      /* vt+0x18: finish loading */
        gui_show(tmpl, 0);
        SetTemplate(p, tmpl);
    }
    gui_set_text(gui_find("LON_Caption"), k_title[kind]);
    gui_show(gui_find("LON_Image"), 0);
    *(uint32_t *)((uint8_t *)p + PG_HASH) = 0;
    g_last_page = kind;
    log_line("PANEL: page %d (%s) created", kind, k_title[kind]);
}

static void *make_page(int kind)
{
    if (screen_page(kind)) return make_screen_page(kind);
    if (list_page(kind)) return make_list_page(kind);
    uint8_t *p = gui_new(PAGE_SIZE);
    if (!p) return NULL;
    memset(p, 0, PAGE_SIZE);
    ListCtor(p, 1);
    if (!g_vt[0]) {
        memcpy(g_vt, LIST_VTABLE, sizeof g_vt);
        g_vt[7] = (void *)page_create;
        g_vt[10] = LIST_DESTROY;
        g_vt[11] = (void *)page_refresh;
        g_vt[18] = (void *)page_fill;
    }
    *(void ***)p = g_vt;
    *(int *)(p + PG_KIND) = kind;
    return p;
}

int panel_is_open(void) { return g_tab != NULL; }

static void close_now(void)
{
    void *tab = g_tab;
    if (!tab) return;
    g_tab = NULL;                              /* g_last_page is kept by page_create */
    ((V0_t)(*(void ***)tab)[10])(tab);                            /* Destroy */
    ((V1_t)(*(void ***)tab)[0])(tab, 1);                          /* delete */
    for (int i = 0; i < PANEL_KINDS; i++) {
        if (g_pages[i]) ((V1_t)(*(void ***)g_pages[i])[0])(g_pages[i], 1);
        g_pages[i] = NULL;
    }
    g_fd.page = NULL;
    g_fd.key = -1;
    void *gm = game_menu();
    if (gm) SetMenuOpen(gm, 0);
    g_close_req = 0;
    g_confirm_action = 0;
    log_line("PANEL: closed");
}

int panel_open(int page)
{
    int founded = adapter_state()->founded;
    if (g_tab) {
        if (founded && page >= 0 && page < PANEL_PAGES) SelectTab(g_tab, TAB_ID0 + page);
        return 1;
    }
    void *gm = game_menu();
    if (!gm) return 0;
    CloseAllMenus(gm, 0);
    SetMenuOpen(gm, 1);
    uint8_t *tab = gui_new(0x1A4);
    if (!tab) { SetMenuOpen(gm, 0); return 0; }
    memset(tab, 0, 0x1A4);
    TabCtor(tab, 1);
    GuiStr scr;
    gui_str_init(&scr, "TAB_CONTROL_800x600.screen");
    ((TabCreate_t)(*(void ***)tab)[6])(tab, &scr, NULL);
    gui_str_free(&scr);
    GuiPoint zero = {0, 0};
    SetupButtons(tab, &zero, NULL, -3, NULL, NULL, NULL);
    *(int *)(tab + 0x144) = 1;                                   /* destroy inactive pages: names stay unique */
    g_tab = tab;
    int first = founded ? 0 : PANEL_FOUND, last = founded ? PANEL_PAGES - 1 : PANEL_FOUND;
    if (!founded) found_begin();
    for (int i = first; i <= last; i++) {
        g_pages[i] = make_page(i);
        GuiStr tip;
        gui_wstr_init(&tip, k_tab_tip[i]);
        AddTab(tab, TAB_ID0 + i, g_pages[i], &zero, &tip, k_tab_icon[i], 0, 1, 0);
        gui_wstr_free(&tip);
    }
    CreateCloseBtn(tab, 15);
    SetRefreshMs(tab, 2000);
    PositionWindow(tab, 0);
    if (!founded) page = PANEL_FOUND;
    else if (page < 0 || page >= PANEL_PAGES) page = g_last_page < PANEL_PAGES ? g_last_page : PANEL_OVERVIEW;
    SelectTab(tab, TAB_ID0 + page);
    log_line("PANEL: opened on page %d", page);
    return 1;
}

void panel_request_close(void) { if (g_tab) g_close_req = 1; }

void panel_toggle(void)
{
    if (g_tab) panel_request_close();
    else panel_open(-1);
}

/* The radio group's "current" query (0x4DC0B0) throws when no tab is selected (after the
   close X), so the panel tracks the visible page itself. */
int panel_current_page(void)
{
    void *p = g_tab ? visible_page() : NULL;
    return p ? *(int *)((uint8_t *)p + PG_KIND) : -1;
}

int panel_card_count(void)
{
    int kind = visible_kind();
    return !g_tab ? 0 : list_page(kind) ? g_nlrows : g_ncards;
}

/* a card button's place in layout pixels (1024x768), for tests that click it like a player */
int panel_button_rect(int card, int slot, int *x, int *y, int *w, int *h)
{
    *x = *y = *w = *h = 0;
    void *p = g_tab ? visible_page() : NULL;
    if (!p || card < 0 || card >= g_ncards || slot < 0 || slot > 1 || !g_cards[card].btn[slot].action) return 0;
    void *b = child(p, card, k_btn_name[slot]);
    if (!b) return 0;
    gui_abs_pos(b, x, y);
    *w = gui_width(b);
    *h = gui_height(b);
    return 1;
}

int panel_found_info(int *title, int *flag, char *name, int cap, int *x, int *y, int *w, int *h)
{
    *title = g_fd.title;
    *flag = g_fd.flag;
    *x = *y = *w = *h = 0;
    name[0] = 0;
    void *e = found_child("FNF_NameEdit");
    if (!e) return 0;
    gui_edit_get(e, name, cap);
    gui_abs_pos(e, x, y);
    *w = gui_width(e);
    *h = gui_height(e);
    return gui_has_focus(e) ? 2 : 1;
}
const char *panel_card_caption(int i) { return i >= 0 && i < g_ncards ? g_cards[i].caption : ""; }
const char *panel_card_body(int i) { return i >= 0 && i < g_ncards ? g_cards[i].body : ""; }

/* ---- test hooks for the screen and list pages (tools/scenarios.py, feature_suite.py) ---- */
static int visible_kind(void)
{
    void *p = g_tab ? visible_page() : NULL;
    return p ? *(int *)((uint8_t *)p + PG_KIND) : -1;
}

int panel_set_mode(int mode)
{
    int kind = visible_kind();
    if (kind < 0) return 0;
    g_confirm_action = 0;
    g_feedback[0] = 0;
    if (kind == PANEL_TREASURY) g_tr_mode = mode ? 1 : 0;
    else if (kind == PANEL_GOVERNMENT) { g_gov_sel = mode >= 0 && mode < GOV_COUNT ? mode : -1; g_gov_confirm = 0; }
    else if (list_page(kind)) { g_lmode[kind] = mode; g_lsel[kind] = -1; }
    else return 0;
    g_dirty = 1;
    return 1;
}

int panel_select(int key)
{
    int kind = visible_kind();
    if (kind < 0 || !list_page(kind) || !lrow(key)) return 0;
    g_lsel[kind] = key;
    g_confirm_action = 0;
    g_feedback[0] = 0;
    g_dirty = 1;
    return 1;
}

const char *panel_feedback(int *ok)
{
    if (g_confirm_action) { *ok = 2; return g_confirm_text; }
    *ok = g_feedback_ok;
    return g_feedback;
}

int panel_row(int i, int *key, const char **name, const char **cells)
{
    int kind = visible_kind();
    if (kind < 0 || !list_page(kind) || i < 0 || i >= g_nlrows) return 0;
    *key = g_lrows[i].key;
    *name = g_lrows[i].name;
    for (int c = 0; c < 4; c++) cells[c] = g_lrows[i].cell[c];
    return 1;
}

int panel_row_rect(int key, int *x, int *y, int *w, int *h)
{
    *x = *y = *w = *h = 0;
    void *p = g_tab ? visible_page() : NULL;
    int kind = visible_kind();
    if (!p || !list_page(kind) || !lrow(key)) return 0;
    void *d = child(p, key, "FNR_Name");
    if (!d) return 0;
    gui_abs_pos(d, x, y);
    *w = gui_width(d);
    *h = gui_height(d);
    return 1;
}

/* ---- clicks ------------------------------------------------------------------------ */
static void do_action(int page, int action, int arg)
{
    char why[256];
    int ok = api_action(action, arg, why, sizeof why);
    g_feedback_page = page;
    g_feedback_ok = ok;
    if (ok) {
        switch (action) {
        case API_DONATE:     snprintf(g_feedback, sizeof g_feedback, "You donated %s gold to the treasury.", num(arg)); break;
        case API_WITHDRAW:   snprintf(g_feedback, sizeof g_feedback, "%s gold went from the treasury to your purse.", num(arg)); break;
        case API_TAX:        snprintf(g_feedback, sizeof g_feedback, "The national tax is now %d%%.", arg); break;
        case API_TARIFF:     snprintf(g_feedback, sizeof g_feedback, "The import tariff is now %d%%.", arg); break;
        case API_WAR:        snprintf(g_feedback, sizeof g_feedback, "You are at war with %s.", core_power_name(arg)); break;
        case API_CEASEFIRE:  snprintf(g_feedback, sizeof g_feedback, "%s accepts a ceasefire.", core_power_name(arg)); break;
        case API_PEACE:      snprintf(g_feedback, sizeof g_feedback, "%s makes peace with you.", core_power_name(arg)); break;
        case API_GOVERNMENT: snprintf(g_feedback, sizeof g_feedback, "The nation is now %s %s.",
                                      core_article(core_government_name(arg), 0), core_government_name(arg)); break;
        case API_COMMISSION: snprintf(g_feedback, sizeof g_feedback, "A new fleet is being fitted out in the capital."); break;
        case API_PAYOFF:     snprintf(g_feedback, sizeof g_feedback, "One fleet is paid off."); break;
        case API_ORDER:      snprintf(g_feedback, sizeof g_feedback, "New standing order: %s.", core_navy_order_name(arg)); break;
        case API_RECRUIT:    snprintf(g_feedback, sizeof g_feedback, "Recruiting has begun; soldiers join over the next days."); break;
        case API_TOWER:      snprintf(g_feedback, sizeof g_feedback, "A cannon tower is going up."); break;
        case API_CONVOYS:    snprintf(g_feedback, sizeof g_feedback, "National convoys: %d.", natc_count()); break;
        case API_TOWN_TAX: {
            char nm[64];
            town_name(arg / 1000, nm, sizeof nm);
            snprintf(g_feedback, sizeof g_feedback, "The tax in %s is now %d%%.", nm, arg % 1000);
            break;
        }
        case API_PROPOSE:    snprintf(g_feedback, sizeof g_feedback, "%s accepts your proposal.", core_power_name(arg / 10)); break;
        case API_BUY_TOWN: {
            char nm[64];
            town_name(arg, nm, sizeof nm);
            snprintf(g_feedback, sizeof g_feedback, "%s now belongs to the nation.", nm);
            break;
        }
        case API_OFFER_ACCEPT: snprintf(g_feedback, sizeof g_feedback, "You accept the offer of %s.", core_power_name(arg)); break;
        case API_OFFER_DECLINE: snprintf(g_feedback, sizeof g_feedback, "You decline the offer of %s.", core_power_name(arg)); break;
        case API_FLEET_ORDER:  snprintf(g_feedback, sizeof g_feedback, "The fleet has a new order."); break;
        case API_FLEET_TARGET: snprintf(g_feedback, sizeof g_feedback, "The fleet has a new target."); break;
        case API_CONVOY_RELEASE: snprintf(g_feedback, sizeof g_feedback, "The convoy is released from national service."); break;
        case API_GOTO:       g_feedback[0] = 0; g_close_req = 1; break;   /* the sea map shows the ship */
        case API_PETITION:   snprintf(g_feedback, sizeof g_feedback, arg ? "The town joins the nation." : "The petition is declined."); break;
        default:             snprintf(g_feedback, sizeof g_feedback, "Done."); break;
        }
    } else {
        snprintf(g_feedback, sizeof g_feedback, "%s", why[0] ? why : "That is not possible right now.");
    }
}

static int found_key(int key)
{
    switch (key) {
    case FK_TITLE_PREV: found_set_title(g_fd.title - 1); return 1;
    case FK_TITLE_NEXT: found_set_title(g_fd.title + 1); return 1;
    case FK_FLAG_PREV:  g_fd.flag--; found_show_flag(); return 1;
    case FK_FLAG_NEXT:  g_fd.flag++; found_show_flag(); return 1;
    case FK_FOUND:      found_do(); g_dirty = 1; return 1;
    case FK_CANCEL:     g_close_req = 1; return 1;
    }
    return 0;
}

static int handle_key(int page, int key)
{
    if (page == PANEL_FOUND) return found_key(key);
    if (page == PANEL_TREASURY && key >= TK_MODE) return treasury_key(key);
    if (page == PANEL_TOWNS && key >= TW_DEC) return towns_key(key);
    if (page == PANEL_DIPLOMACY && key >= TD_BTN1) return diplo_key(key);
    if (page == PANEL_MILITARY && key >= TV_BTN1) return navy_key(key);
    if (page == PANEL_GOVERNMENT && key >= TG_PREV) return gov_key(key);
    int action = 0, arg = 0;
    if (key >= 1000 && key < 1002) {
        action = g_pbtn[key - 1000].action;
        arg = g_pbtn[key - 1000].arg;
    } else if (key >= 2000 && key - 2000 < g_ncards && g_cards[key - 2000].go_to) {
        action = API_GOTO;
        arg = (int)g_cards[key - 2000].go_to;
    } else if (key >= 0 && key < 2000 && key / 2 < g_ncards) {
        action = g_cards[key / 2].btn[key % 2].action;
        arg = g_cards[key / 2].btn[key % 2].arg;
    }
    if (!action) return 0;
    if (action == -1) {                                          /* Confirm */
        int a = g_confirm_action, b = g_confirm_arg;
        g_confirm_action = 0;
        if (a) do_action(page, a, b);
    } else if (action == -2) {                                   /* Cancel */
        g_confirm_action = 0;
    } else if (action == API_WITHDRAW || action == API_WAR) {    /* ask first, as the dialogs did */
        g_confirm_action = action;
        g_confirm_arg = arg;
        g_feedback[0] = 0;
        if (action == API_WITHDRAW)
            snprintf(g_confirm_text, sizeof g_confirm_text, "Transfer %s gold from the national treasury to your "
                     "own purse? Taking public money costs at least 2 stability.", num(arg));
        else
            snprintf(g_confirm_text, sizeof g_confirm_text, "Declare war on %s? Its fleets and towns will treat you "
                     "as an enemy.", core_power_name(arg));
    } else {
        g_confirm_action = 0;
        do_action(page, action, arg);
    }
    g_dirty = 1;
    return 1;
}

static void TC on_click(void *page, int key)
{
    int kind = page ? *(int *)((uint8_t *)page + PG_KIND) : -1;
    log_line("PANEL click page %d key %d", kind, key);
    handle_key(kind, key);                     /* the cards are rebuilt next frame, not inside the click */
}

int panel_click(int key)
{
    void *p = visible_page();
    return p ? handle_key(*(int *)((uint8_t *)p + PG_KIND), key) : 0;
}

/* ---- the top-bar button (data/scripts/TOPMENUBAR_800x600.screen, art/make_topbar.py) ----
   TMB_Nation is a clone of the coin button TMB_Gold. Its click reaches the DLL through a
   small CBaseControl that only serves as the slot's receiver. */
#define CBaseCtor ((V1_t)0x004CF150)
static void *g_tb_btn, *g_tb_owner;
static int g_tb_poll;

static void TC on_topbar(void *obj, int key)
{
    (void)obj; (void)key;
    log_line("PANEL: top-bar nation button");
    panel_toggle();                                      /* before founding: the founding page */
}

static void topbar_poll(void)
{
    if (++g_tb_poll % 30) return;
    void *btn = gui_find("TMB_Nation");
    if (!btn || btn == g_tb_btn) return;
    if (!g_tb_owner) {
        g_tb_owner = gui_new(0x80);
        if (!g_tb_owner) return;
        memset(g_tb_owner, 0, 0x80);
        CBaseCtor(g_tb_owner, 1);
    }
    gui_icon(btn, 44);                                   /* Pr2_Icon_Nation */
    gui_tooltip(btn, "Your nation");
    gui_on_click(btn, g_tb_owner, on_topbar, 0);
    g_tb_btn = btn;
    log_line("PANEL: top-bar nation button ready");
}

/* ---- frame, hooks ---------------------------------------------------------------------- */
void panel_frame(void)
{
    topbar_poll();
    if (g_reopen >= 0) {
        int page = g_reopen;
        g_reopen = -1;
        close_now();
        panel_open(page);
        return;
    }
    if (!g_tab) return;
    if (g_open_town >= 0) { towns_open_pending(); return; }      /* closes the panel */
    if (g_close_req) { close_now(); return; }
    void *p = visible_page();
    if (p && g_dirty) {
        g_dirty = 0;
        ((V0_t)(*(void ***)p)[11])(p);                          /* Refresh */
    }
    UpdatePages(g_tab, 0);
}

void panel_reset(void)
{
    if (g_tab) log_line("PANEL: world reset with the panel open; window forgotten");
    g_tab = NULL;                                  /* the world teardown owns the window now */
    g_tb_btn = NULL;                               /* the top bar may be rebuilt: connect again */
    for (int i = 0; i < PANEL_KINDS; i++) g_pages[i] = NULL;
    g_fd.page = NULL;
    g_fd.key = -1;
    g_reopen = -1;
    g_open_town = -1;
    g_close_req = g_dirty = 0;
    g_confirm_action = 0;
    g_feedback[0] = 0;
}

static void on_close_log(Regs *r)                       /* CloseAllMenus closes ours too */
{
    if (!g_tab) return;
    const uint32_t *sp = (const uint32_t *)(uintptr_t)r->esp;
    char buf[400];
    int n = 0;
    for (int i = 0; i < 160 && n < 380; i++)
        if (sp[i] > 0x401000 && sp[i] < 0x67E455) n += snprintf(buf + n, sizeof buf - n, " %X", sp[i]);
    log_line("PANEL: CloseLog, code addresses on the stack:%s", buf);
    close_now();
}
/* The game's key bindings also fire while a text box has focus: "W" opened another window
   (0x50D700 -> 0x50F160 -> CloseAllMenus) and closed the panel mid-name. Every binding goes through
   the key mapper's SetKeyState(key, down) 0x52B840 (bindings at +0x44, 0x14 bytes, key at +4); while
   the founding name box has focus the key is swapped for one no binding uses. */
static void on_key_state(Regs *r)
{
    void *e = g_tab ? found_child("FNF_NameEdit") : NULL;
    if (e && gui_has_focus(e)) ((uint32_t *)(uintptr_t)r->esp)[1] = 0x7FFFFFFF;
}

static void on_tab_close_btn(Regs *r) { if (g_tab && r->ecx == (uint32_t)(uintptr_t)g_tab) g_close_req = 1; }

void panel_install(void)
{
    static const uint8_t h1[] = {0x64, 0xA1, 0x00, 0x00, 0x00, 0x00};   /* CloseLog: mov eax, fs:[0] */
    static const uint8_t h2[] = {0x81, 0xC1, 0x88, 0x01, 0x00, 0x00};   /* tab close: add ecx, 0x188 */
    hook_install("panel.CloseLog", 0x005007C0, h1, sizeof h1, on_close_log);
    hook_install("panel.TabClose", 0x004DC9F0, h2, sizeof h2, on_tab_close_btn);
    static const uint8_t h3[] = {0x55, 0x8B, 0xE9, 0x8B, 0x45, 0x48};   /* push ebp; mov ebp, ecx; mov eax, [ebp+0x48] */
    hook_install("panel.KeyState", 0x0052B840, h3, sizeof h3, on_key_state);
}
