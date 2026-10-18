/* The nation panel: one persistent in-game window in the style of the game's
 * Log/Missions window (the nation panel change, research/tab_window.md). */
#ifndef PR2N_PANEL_H
#define PR2N_PANEL_H

enum {                         /* api_action() */
    API_DONATE = 1, API_WITHDRAW, API_TAX, API_TARIFF, API_WAR, API_CEASEFIRE, API_PEACE,
    API_GOVERNMENT, API_COMMISSION, API_PAYOFF, API_ORDER, API_RECRUIT, API_TOWER, API_CONVOYS,
    API_TOWN_TAX, API_PROPOSE, API_BUY_TOWN, API_PETITION, API_OFFER_ACCEPT, API_OFFER_DECLINE,
    API_FLEET_ORDER, API_FLEET_TARGET, API_GOTO, API_CONVOY_RELEASE
};
int  api_action(int action, int arg, char *why, int why_len);   /* api.c */
int  api_found(int capital, const char *name, const char *adj, int title, int flag, char *why, int why_len);
int  api_can_found(int capital, char *why, int why_len);
int  api_flag_count(void);
const char *api_flag_name(int i, const char **group);

/* PANEL_FOUND is the only page before founding (the founding-page change) */
enum { PANEL_OVERVIEW = 0, PANEL_TREASURY, PANEL_TOWNS, PANEL_DIPLOMACY, PANEL_GOVERNMENT,
       PANEL_MILITARY, PANEL_PAGES, PANEL_FOUND = PANEL_PAGES, PANEL_KINDS };

#define FOUND_NAME_CHARS 28      /* the longest nation name the founding box takes */

void panel_install(void);        /* hooks; at DLL load */
void panel_frame(void);          /* main thread, every frame */
void panel_reset(void);          /* world reset / load: forget the window */
void panel_toggle(void);         /* Ctrl+N with a founded nation */
int  panel_open(int page);       /* 1 if open afterwards */
void panel_request_close(void);
int  panel_is_open(void);
int  panel_current_page(void);   /* PANEL_* or -1 */
int  panel_card_count(void);
int  panel_button_rect(int card, int slot, int *x, int *y, int *w, int *h);   /* tests */
int  panel_found_info(int *title, int *flag, char *name, int cap, int *x, int *y, int *w, int *h);   /* tests */
const char *panel_card_caption(int i);
const char *panel_card_body(int i);
int  panel_click(int key);       /* test hook: the same as clicking card key (or 1000/1001) */
int  panel_set_mode(int mode);   /* test hooks for the screen/list pages: the page's mode */
int  panel_select(int key);      /* select a list row by its key */
const char *panel_feedback(int *ok);   /* last result (ok 0/1) or the question asked (ok 2) */
int  panel_row(int i, int *key, const char **name, const char **cells);   /* list rows; cells[4] */
int  panel_row_rect(int key, int *x, int *y, int *w, int *h);             /* a row's name cell */
int  panel_dev_wars(int cell, int mask);   /* tests: Overview Wars cell 0..4 shows mask (bits 0..3 powers,
                                              4 "you"); -1 = the real wars again, -2 = ask; returns the
                                              cell's entries at the last refresh */

#endif
