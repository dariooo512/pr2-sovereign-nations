#ifndef PR2N_REPLOG_H
#define PR2N_REPLOG_H
/* Reputation, relation and fleet-battle log (replog.c, the Holland war fix). */
void replog_install(void);                                    /* hooks + core trace, from nation_install_hooks */
void replog_daily(void);                                      /* once per game day: reputation changes */
void replog_reset(void);                                      /* world reset / load */
void replog_mod_change(int power, int delta, const char *why);   /* adapter: FX_REPUTATION */
#endif
