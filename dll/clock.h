#ifndef PR2N_CLOCK_H
#define PR2N_CLOCK_H

/* Redirect GetTickCount/timeGetTime to milliseconds since game start (fixes
 * the hang on PCs up for more than 24.86 days). Call once, at DLL load. */
void clock_install(void);

#endif
