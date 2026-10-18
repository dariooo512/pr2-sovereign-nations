/* The player's flag and the nation's flag, kept apart (flag.c, research/flags.md section 8). */
#ifndef PR2N_FLAG_H
#define PR2N_FLAG_H
#include <stdint.h>

void flag_install(void);             /* the drawing-site hooks (DLL load) */
void flag_init(void);                /* every frame: slot 5 -> the nation's flag (once), after-load step */
void flag_reset(void);               /* world reset: the nation's flag is off until the next apply */
void flag_world_ready(int founded, int index);   /* new game / load complete */
int  flag_apply(int index);          /* nation_flags\flag_NNN.bmp -> Run\7.bmp (the nation's flag); 1 = ok */

const char *flag_logo_path(void);    /* Run\0.bmp: the player's own flag (company logo); never written */
const char *flag_nation_path(void);  /* the nation's flag image: Run\7.bmp, or its nation_flags source
                                        while no nation flag is set up; 96x64 24-bit BMP either way */
int  flag_nation_ready(void);        /* 1 = the game draws the nation's flag for national ships and towns */
const char *flag_bmp_path(int index);   /* <game>\nation_flags\flag_NNN.bmp */

void flag_convoy_changed(void *convoy);  /* a convoy joined or left national service: re-flag its ships in port */
int  flag_dev(unsigned long *hits, int n);   /* tests: per-site counters; returns flag_nation_ready() */
int  flag_dev_view(int view, uint32_t town_handle);   /* tests: 1 sea map, 2 that town's view (next frame) */

#endif
