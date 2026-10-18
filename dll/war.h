/* War and conquest hooks for the player nation (research/conquest_transfer.md).
 *
 *  - The player cannot attack towns of their own nation (nation byte 5).
 *  - A player victory over a power's town while the nation is at war with that
 *    power becomes a pending conquest; the UI then asks Annex / Withdraw.
 *  - A power's military convoy that wins a land assault on a nation-5 town
 *    takes the town (core_lose_town).
 */
#ifndef PR2N_WAR_H
#define PR2N_WAR_H

void war_install(void);    /* once, from nation_install_hooks() */
void war_frame(void);      /* every UI frame, main thread (deferred work + messages) */
void war_reset(void);      /* world wiped / new game / load: drop pending conquests */

/* Returns 1 and fills town (staedte.ini index) and former (power 0..3) when a
   conquest is waiting for the player's decision. A conquest is reported only
   after its battle object has ended. */
int  war_pending_conquest(int *town, int *former);

/* Resolve the conquest war_pending_conquest() reported:
   annex != 0 -> core_annex(reason 0) + effects; annex == 0 -> withdraw
   (the town stays with its power). */
/* Decide the pending conquest. town >= 0 selects that town's entry even while
   its battle object is still being torn down (the Lua popup opens from
   OnTownBattleEnd); returns 1 if an entry was resolved and, for annex, accepted. */
int  war_resolve_conquest(int annex, int town);

#endif
