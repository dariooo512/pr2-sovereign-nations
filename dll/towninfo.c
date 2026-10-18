/* The nation's own towns in the town info dialog (the conquered-town info fix, research/town_info_owner.md).
 *
 * Bug: the town info dialog of a member town said "Your relationship with Holland"
 * (Dutch flags, "hostile"), for a town that was never Dutch. The dialog's Create
 * 0x4A3610 loads the town's nation into ebp / [esp+0x10] (0x4A3DD8) and uses it for
 *   - the heading: 0x4081B0(nation) -> "IDPR_SID_VERH..." "Your relationship with %1";
 *   - the relation word: CPlayer::ReputationTier 0x5D2C10(player, nation) -> 0x407330;
 *   - the four mini flags SID_Nat_00..03: anim table 0x6E1A40[nation], lit up to the tier.
 * Patch P07 makes 0x4A3DD8 read the display byte (+0x391) instead of the nation byte,
 * so that a nation-5 town does not index past the 4-entry anim table. A member town's
 * display byte is the nation's host power (towns.c eng_town_to_nation: the former power
 * of the capital at founding, NationState.host_power), so every member town showed the
 * host power - Holland when the capital was Dutch - and the player's real reputation
 * with it.
 *
 * Fix, after vanilla filled the section (hook at 0x4A40CB, esi = dialog, [esp+0x1C] =
 * town): for a member town (core_officials_serve: founded, member, byte 5)
 *   - SID_VerhaeltnisZu (dialog+0xC0) "Your nation";
 *   - SID_Verhaeltniss (+0xCC) the loyalty as on the Towns page ("loyal (72)", ...);
 *   - SID_Nat_00..03 (+0x7C..+0x88) hidden; the nation's flag (Run\7.bmp) in a small
 *     child screen FNN_TINFO_NATION (art/make_towninfo.py) where the last one was;
 *   - SID_StadtTyp (+0xC4) "Capital of <nation>" / "Town of <nation>" (vanilla asks for
 *     IDPR_SID_KOLONIE_05, which does not exist: the line was empty).
 * Every other town keeps the vanilla section untouched.
 *
 * The game's nation-name helper 0x4081B0 (cdecl: wstring *out, nation) answers
 * L"Invalid" for any nation >= 4. Its callers that pass a raw town byte (political map
 * tooltip 0x4D9C2F, sea battle dialogs 0x4F6645) therefore named a member town's owner
 * "Invalid"; a hook at its >= 4 branch (0x40822F) gives nation 5 the nation's name once
 * a nation is founded.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "adapter.h"
#include "core.h"
#include "engine.h"
#include "flag.h"
#include "gui.h"
#include "hook.h"
#include "log.h"
#include "towninfo.h"

#define TC __attribute__((thiscall))
typedef void (TC *V0_t)(void *self);
typedef void (TC *VP_t)(void *self, void *a);
#define ImageFit        ((VP_t)0x004C1540)    /* CDynamicImg: draw into this rect */

#define T_NATION        0x390
#define D_ROOT          0x44                  /* CBaseControl: the screen root */
#define D_TOWN          0x78                  /* town handle */
#define D_NAT0          0x7C                  /* SID_Nat_xx statics, 4 pointers */
#define D_HEADING       0xC0                  /* SID_VerhaeltnisZu (CTextBox) */
#define D_ROLE          0xC4                  /* SID_StadtTyp (CTextBox) */
#define D_RELATION      0xCC                  /* SID_Verhaeltniss (CTextBox) */

static struct { void *dlg; int town, mode, flag_ok; } g_last;

static int town_index(const uint8_t *town)
{
    int n = eng_town_count();
    for (int i = 0; i < n; i++)
        if (eng_town_ptr(i) == town) return i;
    return -1;
}

/* 0x4A40CB: the relationship section is filled (heading, word, mini flags) */
static void on_section(Regs *r)
{
    uint8_t *dlg = (uint8_t *)(uintptr_t)r->esi;
    uint8_t *town = *(uint8_t **)(uintptr_t)(r->esp + 0x1C);
    if (!dlg || !town) return;
    int idx = town_index(town);
    const NationState *s = adapter_state();
    g_last.dlg = dlg;
    g_last.town = idx;
    g_last.mode = 0;
    g_last.flag_ok = 0;
    if (!core_officials_serve(s, idx, town[T_NATION])) return;      /* a power's town: vanilla */

    char role[128], loyal[48];
    core_town_role(s, idx, role, sizeof role);
    core_loyalty_label(&s->town[idx], loyal, sizeof loyal);
    gui_set_text(*(void **)(dlg + D_HEADING), "Your nation");
    gui_set_text(*(void **)(dlg + D_ROLE), role);
    void *rel = *(void **)(dlg + D_RELATION);
    gui_set_text(rel, loyal);
    if (rel) gui_set_size(rel, 160, gui_height(rel) ? gui_height(rel) : 20);   /* "restless (18)" */
    for (int i = 0; i < 4; i++) gui_show(*(void **)(dlg + D_NAT0 + 4 * i), 0);

    void *root = *(void **)(dlg + D_ROOT);
    void *cell = root ? gui_create_screen(root, "FNN_TINFO_NATION_800x600.screen") : NULL;
    if (cell) {
        ((V0_t)(*(void ***)cell)[6])(cell);                         /* vt+0x18: finish loading */
        void *img = gui_find("FNI_Flag");
        if (img && gui_image_load(img, flag_nation_path())) {
            ImageFit(img, (uint8_t *)img + 0x68);
            g_last.flag_ok = 1;
        }
        gui_show(cell, 1);
    }
    g_last.mode = 1;
    log_line("TOWNINFO %s (town %d): nation section 'Your nation' / '%s', '%s'; flag %s "
             "(vanilla would show the display power %d)", eng_town_name(idx), idx, loyal, role,
             g_last.flag_ok ? "shown" : cell ? "NOT loaded" : "screen missing", town[T_NATION + 1]);
}

/* 0x40822F in the nation-name helper's >= 4 branch: [esp] = L"Invalid" (the argument of
   wstring::operator=), [esp+0x24] = the nation byte */
static void on_nation_name(Regs *r)
{
    static uint16_t w[64];
    if ((*(const uint8_t *)(uintptr_t)(r->esp + 0x24)) != NATION_ID) return;
    const NationState *s = adapter_state();
    if (!s || !s->founded || !s->name[0]) return;
    int n = MultiByteToWideChar(1252, 0, s->name, -1, (LPWSTR)w, 64);
    if (n <= 0) return;
    w[63] = 0;
    *(uint32_t *)(uintptr_t)r->esp = (uint32_t)(uintptr_t)w;
}

void towninfo_install(void)
{
    static int done;
    if (done) return;
    done = 1;
    static const uint8_t sec_b[]  = {0x8B, 0x44, 0x24, 0x1C, 0x8B, 0x48, 0x40};   /* mov eax,[esp+1C]; mov ecx,[eax+40] */
    static const uint8_t name_b[] = {0xFF, 0x15, 0x24, 0xFA, 0x67, 0x00};         /* call [0x67FA24] (wstring =) */
    if (!hook_install("towninfo.Section", 0x004A40CB, sec_b, sizeof sec_b, on_section))
        log_line("TOWNINFO hook not installed: member towns show the vanilla relationship line");
    hook_install("towninfo.NationName", 0x0040822F, name_b, sizeof name_b, on_nation_name);
}

/* ---- tests ---- */
static void read_box(const char *name, char *out, int cap)
{
    out[0] = 0;
    const uint8_t *box = gui_find(name);
    if (!box) return;
    const uint16_t *b = *(const uint16_t *const *)(box + 0x9C), *e = *(const uint16_t *const *)(box + 0xA0);
    if (!b || e < b || e - b > 400) return;
    static uint16_t tmp[401];
    int n = (int)(e - b);
    memcpy(tmp, b, (size_t)n * 2);
    tmp[n] = 0;
    if (WideCharToMultiByte(1252, 0, (LPCWSTR)tmp, -1, out, cap, NULL, NULL) <= 0) out[0] = 0;
    out[cap - 1] = 0;
}

int towninfo_dev(TownInfoView *v)
{
    memset(v, 0, sizeof *v);
    v->town = -1;
    if (!gui_find("SID_VerhaeltnisZu")) return 0;
    read_box("SID_VerhaeltnisZu", v->heading, sizeof v->heading);
    read_box("SID_Verhaeltniss", v->relation, sizeof v->relation);
    read_box("SID_StadtTyp", v->role, sizeof v->role);
    v->town = g_last.town;
    v->mode = g_last.mode;
    v->flag_ok = g_last.flag_ok;
    v->hidden = g_last.mode ? 4 : 0;
    return 1;
}

typedef void *(__cdecl *NationName_t)(void *out, int nation);
#define NationName ((NationName_t)0x004081B0)
#define I_WSTR_DEFAULT 0x0067FA0C          /* basic_string<ushort>() */
#define I_WSTR_DTOR    0x0067FA04

int towninfo_dev_nation_name(int nation, char *out, int cap)
{
    GuiStr ws;
    memset(&ws, 0, sizeof ws);
    out[0] = 0;
    ((V0_t)(*(void **)(uintptr_t)I_WSTR_DEFAULT))(&ws);
    NationName(&ws, nation & 0xFF);
    const uint16_t *b = *(const uint16_t *const *)ws.raw, *e = *(const uint16_t *const *)(ws.raw + 4);
    if (b && e >= b && e - b < 200) {
        static uint16_t tmp[201];
        int n = (int)(e - b);
        memcpy(tmp, b, (size_t)n * 2);
        tmp[n] = 0;
        WideCharToMultiByte(1252, 0, (LPCWSTR)tmp, -1, out, cap, NULL, NULL);
        out[cap - 1] = 0;
    }
    ((V0_t)(*(void **)(uintptr_t)I_WSTR_DTOR))(&ws);
    return out[0] != 0;
}
