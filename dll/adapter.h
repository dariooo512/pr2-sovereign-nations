/* Engine adapter: everything that touches game memory or game functions.
 * core.c stays pure; adapter.c snapshots the game into a World, runs the core
 * and applies the core's Effects back to the game. Main thread only. */
#ifndef PR2N_ADAPTER_H
#define PR2N_ADAPTER_H
#include "core.h"

NationState *adapter_state(void);
const Config *adapter_config(void);

/* lifecycle (called from persist.c hooks) */
void adapter_on_reset(void);          /* world wiped: back to "no nation" */
void adapter_on_loaded_state(void);   /* state just came from a save */
void adapter_on_world_ready(void);    /* new game or load finished, towns valid */
void adapter_daily(void);             /* once per game day */
void adapter_frame(void);             /* every UI frame (input, deferred UI) */
int  adapter_world_ready(void);       /* 1 between new game / load complete and the next reset */

/* game snapshot + effects */
void adapter_snapshot(World *w);
void adapter_apply(const Effects *fx);

/* UI */
void adapter_message(const char *text);   /* shown to the player (queued, main thread) */

/* game day counter derived from the world clock (256 ticks/day) */
uint32_t adapter_day(void);

#endif
