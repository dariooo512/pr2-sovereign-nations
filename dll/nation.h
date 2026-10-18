#ifndef PR2N_NATION_H
#define PR2N_NATION_H
/* Nation feature entry points called from main.c. */
void nation_install_hooks(void);   /* once, from DllMain */
void nation_frame(void);           /* every UI frame, main thread */
unsigned long pr2n_frames(void);
#endif
