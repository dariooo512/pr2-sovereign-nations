#ifndef PR2N_NAVY_H
#define PR2N_NAVY_H
#include <stdint.h>
#include "core.h"

/* National navy: nation-5 military convoys driven by the game's military AI. */
void navy_install(void);              /* at DLL load, after the other hooks */
void navy_after_load_nations(void);   /* World::Load, right after the four CNations are read */
void navy_world_ready(void);          /* new game / load complete */
void navy_frame(void);                /* main thread, every frame */
void navy_daily(uint32_t day);        /* new game day: the powers' war fleets against the nation */
int  navy_fleet_count(void);          /* military convoys of nation 5 in the world */
int  navy_list_count(void);           /* ... registered in the nation's CNation */
int  navy_ready(void);
void navy_effect(const Effect *e);    /* FX_FLEET_* / FX_GARRISON / FX_TOWER */
void navy_disband(int n);
void navy_apply_order(int order);
void navy_town_defence(int town, int *soldiers, int *towers, int *soldier_budget);
/* per-fleet orders (the Navy tab); FLEET_STANDING follows the nation's standing order */
enum { FLEET_STANDING = 0, FLEET_GUARD, FLEET_RAID, FLEET_CAMPAIGN, FLEET_ORDER_COUNT };
typedef struct { uint32_t handle; int ships, sailors, town, state, order, target, dest; } FleetInfo;
int  navy_fleets(FleetInfo *out, int max);            /* the nation's fleets, in pool order */
int  navy_fleet_next_order(uint32_t handle, char *why, int why_len);
int  navy_fleet_next_target(uint32_t handle, char *why, int why_len);
int  navy_save_orders(uint8_t *buf, int cap);         /* PFLT block body; returns bytes */
void navy_load_orders(const uint8_t *buf, int len);
int  navy_dev_sail(int town);         /* test install: first fleet sails to the town */
int  navy_dev_soldiers(int town, int n);

#endif
