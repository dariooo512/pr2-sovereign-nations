#ifndef PR2N_TOWNINFO_H
#define PR2N_TOWNINFO_H
/* The nation's own towns in the game's town info dialog and in the game's
   nation-name helper (towninfo.c, research/town_info_owner.md, the conquered-town info fix). */
void towninfo_install(void);

/* test install: what the open town info dialog shows. Returns 1 when one is
   open; the texts are read back from its controls (cp1252). mode = 1 when the
   nation section replaced the vanilla relationship line. */
typedef struct {
    int  town, mode, flag_ok, hidden;
    char heading[96], relation[64], role[128];
} TownInfoView;
int  towninfo_dev(TownInfoView *v);
/* test install: the game's nation-name helper 0x4081B0 for a nation index (cp1252) */
int  towninfo_dev_nation_name(int nation, char *out, int cap);
#endif
