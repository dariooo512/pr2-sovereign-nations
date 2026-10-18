#ifndef PR2N_OFFICIALS_H
#define PR2N_OFFICIALS_H
/* Treasurer, commander, governor and building master serve the player in
   the nation's own towns (officials.c, research/officials.md). */
void officials_install(void);
/* test install: run an official's enter-dialog code in a town.
   kind 0 treasurer, 1 commander, 2 building master. 1 = ok. */
int  officials_dev_probe(int town, int kind, int *state, int *nation, int *tier);
#endif
