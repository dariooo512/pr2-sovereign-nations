/* Low-level game access used by adapter.c (implemented in towns.c, player.c,
 * ui.c). All functions run on the game's main thread. */
#ifndef PR2N_ENGINE_H
#define PR2N_ENGINE_H
#include <stdint.h>
#include "core.h"

/* towns: index = staedte.ini order (0..59) */
int  eng_town_count(void);
int  eng_town_snapshot(int idx, TownSnap *out);
extern uint8_t g_dev_property[64];                           /* test install: pretend property */            /* 0 if missing */
int  eng_town_to_nation(int idx, int host_power);           /* nation byte 5, display host */
int  eng_town_to_power(int idx, int power);                 /* back to a power 0..3 */
const char *eng_town_name(int idx);
uint32_t eng_town_handle(int idx);                           /* game town handle, 0 if none */
uint8_t *eng_town_ptr(int idx);                              /* CStadt*, NULL if none */
int  eng_town_unrest(int idx, int on);                       /* on: start a strike */
int  eng_town_permit(int idx);                               /* 1/0 player's building permit, -1 no town */
int  eng_town_set_permit(int idx, int on);                   /* grant (1) / take back (0) */
void towns_install(void);                                    /* hooks (master builder permit value) */

/* player */
int64_t eng_player_gold(void);
int  eng_player_add_gold(int64_t delta);                    /* 0 if refused (insufficient) */
void eng_player_fleet(uint16_t *ships, uint16_t *warships);
int  eng_player_reputation(int power);                      /* 0..100 */
void eng_player_add_reputation(int power, int delta);
int  eng_player_rank(void);

/* powers */
int  eng_power_war(int a, int b);                           /* vanilla power-vs-power war */
int  eng_power_town_count(int power);

/* UI */
void ui_init(void);
void ui_frame(void);                                        /* process input + queued UI */
void ui_message(const char *text);
void ui_reset(void);
void ui_open_nation_menu(void);                             /* the nation dialog (founding) */
void ui_conquest_popup(int town);                         /* ask Annex/Withdraw for a won town */                                        /* drop queued messages (world reset) */
void ui_town_label(int idx, char *out, int cap);              /* "PortofSpain" -> "Port of Spain" */                          /* queue a message for the player */

#endif
