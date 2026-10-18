#ifndef PR2N_SIGHT_H
#define PR2N_SIGHT_H
#include <stdint.h>

/* National ships on the sea map (the national-ships-on-the-sea-map change,
 * research/sea_map_sight.md): the nation's fleets light up the fog of war like
 * the player's convoys, every national ship can be centred on the sea map
 * ("Go to", Ctrl+Shift+N cycles), and national convoys are real convoys of the
 * player designated by handle -- switched off in this version (NATION_CONVOYS 0,
 * core.h): then only the fleets are national ships and natc_* designate nothing. */
void sight_install(void);              /* at DLL load */
void sight_frame(void);                /* main thread, every frame */
void sight_reset(void);                /* world reset: forget designations and pending jumps */
void sight_world_ready(void);          /* new game / load complete */

/* Go to: centre the sea map on the ship (leaves a town view first). Queued: runs next frame. */
int  sight_goto(uint32_t handle, char *why, int why_len);
int  sight_cycle(void);                /* the hotkey: the next national ship; 0 if there is none */

/* national convoys: the player's own convoys designated national (handles are kept in the save) */
typedef struct {
    uint32_t handle;
    int ships, state, town, dest, autotrade;
    char name[24];
} NatConvoy;
int  sight_is_national(const void *convoy);   /* a fleet of the nation or a designated national convoy */
int  natc_count(void);
int  natc_list(NatConvoy *out, int max);
int  natc_designate(char *why, int why_len);   /* the selected convoy, else the first eligible one */
int  natc_release(uint32_t handle);            /* 0 = the last one */
int  natc_set_count(int n);                    /* designate or release until n; returns the count */
int  natc_save(uint8_t *buf, int cap);
void natc_load(const uint8_t *buf, int len);

/* tests (dev console) */
int  sight_reveal_enabled(int on);             /* -1 = query */
int  sight_last_goto(uint32_t *handle, int *x, int *y, int *view);
int  sight_ship_info(int i, uint32_t *handle, int *x, int *y, int *visible, int *at_sea, int *fleet);
int  sight_ship_count(void);
int  sight_visible_near(int x, int y, int radius, int *total, int *own);   /* convoys marked visible there */
int  sight_view(int *scroll_x, int *scroll_y);

#endif
