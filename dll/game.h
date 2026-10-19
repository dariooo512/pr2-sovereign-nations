/* Verified game addresses for PR2.exe 1.1.2.3 unpacked (base sha 9c9250bc...).
 * Sources: research/ notes; byte facts in tools/check_facts.py.
 */
#ifndef PR2N_GAME_H
#define PR2N_GAME_H
#include <stdint.h>

#define G_U8(a)   (*(volatile uint8_t  *)(uintptr_t)(a))
#define G_U16(a)  (*(volatile uint16_t *)(uintptr_t)(a))
#define G_U32(a)  (*(volatile uint32_t *)(uintptr_t)(a))

/* ---- date / time (research/save_hooks.md §4) ---- */
#define GA_WORLD_TIME   0x702C14u   /* u32, 256 ticks per day */
#define GA_DAY_OF_YEAR  0x702C18u   /* u16 */
#define GA_YEAR         0x702C1Au   /* u16 */
#define GA_DAY          0x702C1Cu   /* u8 1..31 */
#define GA_MONTH        0x702C1Du   /* u8 1..12 */

/* ---- nations ---- */
#define GA_NATIONS      0x702B14u   /* CNation* [4] */
/* The patches' .nation section is at 0x9F7000 in PR2_nation.exe and when the in-memory loader
 * (loader/, the player setup) can put it there (Steam exe: over SteamStub's spent .bind page). Where it
 * cannot (a DRM-free exe ends at 0x9F7000), the loader places it elsewhere and says where in
 * PR2NATION_SECTION; g_section_delta (main.c) is that address minus 0x9F7000, else 0. */
extern uint32_t g_section_delta;
#define GA_SECTION      0x9F7000u
#define GA_PLAYER_REL   (GA_SECTION + g_section_delta)   /* P01: u8[4], 1 = war with player nation */

/* ---- save stream: MemStream {u8 *base; u8 *cur; u32 cap} ---- */
typedef struct { uint8_t *base, *cur; uint32_t cap; } MemStream;

/* ---- hook sites (5+ byte, instruction-aligned, verified bytes) ---- */
#define GH_SAVE_AFTER_NATIONS  0x5D11A6u  /* 8B 46 08 85 C0      esi = MemStream* */
#define GH_LOAD_AFTER_NATIONS  0x5D23C3u  /* 8B 46 04 8B 1E      esi = MemStream* */
#define GH_WORLD_RESET         0x5809B3u  /* B9 EC 3A 70 00      after World::Reset */
#define GH_NEWGAME_DONE        0x580E5Eu  /* B8 0B 00 00 00      generator finished */
#define GH_LOAD_DONE           0x5815CFu  /* 81 C4 8C 00 00 00   end of load driver */
#define GH_DAILY               0x5D286Cu  /* 33 F6 8D 9F D4 09 00 00  new-day block */

#endif
