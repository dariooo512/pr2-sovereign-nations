/* Thin C wrappers over the game's UI classes. Calling conventions and offsets:
 * research/tab_window.md §2.3 / §4.2, research/text_markup.md. The game's helpers
 * throw C++ exceptions on missing files or controls, so every lookup is
 * null-checked before use. */
#include <windows.h>
#include <string.h>
#include "gui.h"
#include "log.h"

#define IAT(a)  (*(void **)(uintptr_t)(a))
#define TC      __attribute__((thiscall))

typedef void *(__cdecl *New_t)(unsigned);
typedef void  (TC *StrCtor_t)(void *self, const char *s, const void *alloc);
typedef void  (TC *WStrCtor_t)(void *self, const uint16_t *s, const void *alloc);
typedef void  (TC *Dtor_t)(void *self);
typedef void *(TC *WAssign_t)(void *self, const uint16_t *s);
typedef void *(TC *Find_t)(void *wm, const char *name, unsigned long flags);
typedef void  (TC *Bool_t)(void *self, int on);
typedef void  (TC *Size_t)(void *self, int w, int h);
typedef void  (TC *TTip_t)(void *self, const char *group, const void *wstr);
typedef void  (TC *Icon_t)(void *btn, int slot, int icon, int arg, int a, int b);
typedef void *(TC *Create_t)(void *fab, void *parent, const char *type, const char *a, const char *b);
typedef void *(TC *Vfn0_t)(void *self);
typedef void *(__cdecl *MkSlot_t)(void *out, void *obj, void *fn, int adj, int zero);
typedef void *(__cdecl *Bind_t)(void *out, void *in, int key);
typedef void  (TC *Connect_t)(void *signal, void *conn_out, void *slot);

#define P_ALLOC        ((New_t)0x00404070)
#define I_NEW          0x0067F444      /* NA2dLib::CObject::operator new */
#define I_STR_CTOR     0x0067F9B8      /* basic_string<char>(const char*, const allocator&) */
#define I_STR_DTOR     0x0067F9CC
#define I_WSTR_CTOR    0x0067FA18      /* basic_string<ushort>(const ushort*, const allocator&) */
#define I_WSTR_DTOR    0x0067FA04
#define I_WSTR_ASSIGN  0x0067FA24      /* basic_string<ushort>::operator=(const ushort*) */
#define I_FIND         0x0067F498      /* CWindowManager::FindDrawable(const char*, ulong) */
#define I_SHOW         0x0067F470      /* CDrawable::Show(bool) */
#define I_SETSIZE      0x0067F02C      /* CDrawable size setter (w, h), as at 0x4B0383 */
#define I_SETPOS       0x0067F014      /* CDrawable::SetPos(int, int) */
#define I_POS          0x0067F054      /* CDrawable::Pos(tagPOINT*) const */
#define I_TTIP         0x0067F388      /* CDrawable::SetTTip(const char*, const wstring&) */
#define I_SUBDRAW      0x0067F1E0      /* CTextBoxEx::FuncCreateSubDrawables */
#define I_CREATETYPE   0x0067F474      /* CDrawableFactory::CreateType(parent, type, 0, 0) */
#define I_FAB          0x0067F450      /* &NA2dLib::g_pDrawableFab */
#define I_CONN_DTOR    0x0067F8AC      /* SigC::Connection::~Connection */
#define I_HANDLE_DTOR  0x0067F88C      /* SigC::Handle<SlotData>::~Handle */
#define TTGRP_OPTIONAL ((const char *)0x0067FFC4)
#define P_SETICON      ((Icon_t)0x004C4C50)
#define P_MKSLOT1      ((MkSlot_t)0x004AFCD0)   /* member slot fn(obj, int) */
#define P_BINDKEY      ((Bind_t)0x004B0100)     /* bind the int -> 0-arg slot */
#define P_CONNECT      ((Connect_t)0x00517640)

static const uint8_t g_alloc_dummy[8];           /* std::allocator is empty */

void *gui_new(unsigned size) { return ((New_t)IAT(I_NEW))(size); }
void *gui_alloc(unsigned size) { return P_ALLOC(size); }

void gui_str_init(GuiStr *s, const char *text)
{
    memset(s, 0, sizeof *s);
    ((StrCtor_t)IAT(I_STR_CTOR))(s, text, g_alloc_dummy);
}
void gui_str_free(GuiStr *s) { ((Dtor_t)IAT(I_STR_DTOR))(s); }

static void widen(const char *text, uint16_t *out, int cap)
{
    int n = MultiByteToWideChar(1252, 0, text, -1, (LPWSTR)out, cap);
    if (n <= 0) out[0] = 0;
    out[cap - 1] = 0;
}

void gui_wstr_init(GuiStr *s, const char *text)
{
    static uint16_t w[2048];
    widen(text, w, 2048);
    memset(s, 0, sizeof *s);
    ((WStrCtor_t)IAT(I_WSTR_CTOR))(s, w, g_alloc_dummy);
}
void gui_wstr_free(GuiStr *s) { ((Dtor_t)IAT(I_WSTR_DTOR))(s); }

static void *window_manager(void)
{
    void *app = *(void **)0x006E5924;
    if (!app) return NULL;
    void *a = ((Vfn0_t)(*(void ***)app)[7])(app);          /* vt+0x1C */
    if (!a) return NULL;
    void *b = ((Vfn0_t)(*(void ***)a)[8])(a);              /* vt+0x20 */
    return b ? *(void **)((uint8_t *)b + 0x94) : NULL;
}

void *gui_find(const char *name)
{
    void *wm = window_manager();
    return wm ? ((Find_t)IAT(I_FIND))(wm, name, 0) : NULL;
}

void gui_set_pos(void *d, int x, int y) { if (d) ((Size_t)IAT(I_SETPOS))(d, x, y); }

typedef void (TC *Pos_t)(const void *self, POINT *out);
void gui_pos(const void *d, int *x, int *y)
{
    POINT pt = {0, 0};
    if (d) ((Pos_t)IAT(I_POS))(d, &pt);
    *x = pt.x;
    *y = pt.y;
}

/* A CButton keeps one caption per state (normal, highlighted, pressed, disabled) as
   std::wstrings at +0xB4 + 12*i (read from TMB_Plus in game: "+" at +0xB4 and +0xC0). */
void gui_button_text(void *btn, const char *text)
{
    static uint16_t w[256];
    if (!btn) return;
    widen(text, w, 256);
    for (int i = 0; i < 4; i++)
        ((WAssign_t)IAT(I_WSTR_ASSIGN))((uint8_t *)btn + 0xB4 + 12 * i, w);
}

void gui_show(void *d, int on) { if (d) ((Bool_t)IAT(I_SHOW))(d, on ? 1 : 0); }
void gui_set_size(void *d, int w, int h) { if (d) ((Size_t)IAT(I_SETSIZE))(d, w, h); }

int gui_height(const void *d)
{
    if (!d) return 0;
    int v = *(const int *)((const uint8_t *)d + 0x70) - *(const int *)((const uint8_t *)d + 0x68);
    return v < 0 ? -v : v;
}
int gui_width(const void *d)
{
    if (!d) return 0;
    int v = *(const int *)((const uint8_t *)d + 0x74) - *(const int *)((const uint8_t *)d + 0x6C);
    return v < 0 ? -v : v;
}

void gui_set_text(void *box, const char *text)
{
    static uint16_t w[1024];
    if (!box) return;
    widen(text, w, 1024);
    ((WAssign_t)IAT(I_WSTR_ASSIGN))((uint8_t *)box + 0x9C, w);
    *(float *)((uint8_t *)box + 0xE4) = -1.0f;
    *((uint8_t *)box + 0x114) = 1;
}

int gui_set_textex(void *box, const char *text)
{
    static uint16_t w[4096];
    if (!box) return 0;
    widen(text, w, 4096);
    ((WAssign_t)IAT(I_WSTR_ASSIGN))((uint8_t *)box + 0xA4, w);
    ((Dtor_t)IAT(I_SUBDRAW))(box);
    return *(int *)((uint8_t *)box + 0x110);
}

void gui_icon(void *btn, int icon) { if (btn) P_SETICON(btn, 0, icon, 0, 1, 1); }

void gui_tooltip(void *d, const char *text)
{
    if (!d) return;
    GuiStr w;
    gui_wstr_init(&w, text);
    ((TTip_t)IAT(I_TTIP))(d, TTGRP_OPTIONAL, &w);
    gui_wstr_free(&w);
}

void *gui_create_screen(void *parent, const char *file)
{
    void *fab = *(void **)IAT(I_FAB);
    if (!fab) return NULL;
    return ((Create_t)IAT(I_CREATETYPE))(fab, parent, file, NULL, NULL);
}

void gui_on_click(void *button, void *obj, GuiClickFn fn, int key)
{
    if (!button || !obj) return;
    uint8_t slot1[32], slot0[32], conn[32];
    memset(slot1, 0, sizeof slot1);
    memset(slot0, 0, sizeof slot0);
    memset(conn, 0, sizeof conn);
    void *s1 = P_MKSLOT1(slot1, obj, (void *)fn, -12, 0);     /* as AddEntry 0x4B0762..0x4B0781 */
    void *s0 = P_BINDKEY(slot0, s1, key);
    P_CONNECT((uint8_t *)button + 0x9C, conn, s0);
    ((Dtor_t)IAT(I_CONN_DTOR))(conn);
    ((Dtor_t)IAT(I_HANDLE_DTOR))(slot1);
    ((Dtor_t)IAT(I_HANDLE_DTOR))(slot0);
}

/* ---- CIconButton with the main-menu arrow look (OPE_Btn_logo_dec / _inc, 0x4E40F0..0x4E4174:
   +0xBC8 = 90, then SetIcon(0, icon, CPoint(5, 6), 1, 1); 0x57 = left, 0x56 = right) ---- */
void gui_icon_at(void *btn, int icon, int size, int dx, int dy)
{
    if (!btn) return;
    GuiPoint pt = {dx, dy};
    *(int *)((uint8_t *)btn + 0xBC8) = size;
    ((Icon_t)P_SETICON)(btn, 0, icon, (int)(uintptr_t)&pt, 1, 1);
}

/* ---- CEditBox (WKR_RenameEdit: 0x467642 MaxLengthPx(0xA0); text std::wstring at +0x23C,
   0x462FAA / 0x465344; vt+0xE0 sets it, 0x46304D) ---- */
#define I_EDIT_MAXCH 0x0067F05C        /* CEditBox::MaxLengthCh(int) */
#define I_EDIT_MAXPX 0x0067F348        /* CEditBox::MaxLengthPx(int) */
typedef void (TC *Int_t)(void *self, int v);
typedef void (TC *SetW_t)(void *self, const void *wstr);

void gui_edit_limit(void *edit, int chars, int px)
{
    if (!edit) return;
    if (chars > 0) ((Int_t)IAT(I_EDIT_MAXCH))(edit, chars);
    if (px > 0) ((Int_t)IAT(I_EDIT_MAXPX))(edit, px);
}

void gui_edit_set(void *edit, const char *text)
{
    if (!edit) return;
    GuiStr w;
    gui_wstr_init(&w, text);
    ((SetW_t)(*(void ***)edit)[0xE0 / 4])(edit, &w);
    gui_wstr_free(&w);
}

int gui_edit_get(const void *edit, char *out, int cap)
{
    if (cap <= 0) return 0;
    out[0] = 0;
    if (!edit) return 0;
    const uint16_t *b = *(const uint16_t *const *)((const uint8_t *)edit + 0x23C);
    const uint16_t *e = *(const uint16_t *const *)((const uint8_t *)edit + 0x240);
    if (!b || e < b || e - b > 1024) return 0;
    int n = WideCharToMultiByte(1252, 0, (LPCWSTR)b, (int)(e - b), out, cap - 1, "?", NULL);
    if (n < 0) n = 0;
    out[n] = 0;
    return n;
}

/* CDrawable::AbsPos(CPoint &) */
#define I_ABSPOS 0x0067F3A4
void gui_abs_pos(const void *d, int *x, int *y)
{
    POINT pt = {0, 0};
    if (d) ((Pos_t)IAT(I_ABSPOS))(d, &pt);
    *x = pt.x;
    *y = pt.y;
}

/* CDrawable::HasFocus() */
typedef char (TC *HasFocus_t)(const void *self);
int gui_has_focus(const void *d) { return d && ((HasFocus_t)IAT(0x0067F064))(d) != 0; }

/* ---- CDynamicImg::Load(const std::string &file, slot) 0x4C1CD0 (the logo selector, 0x4E138D) ---- */
typedef char (TC *ImgLoad_t)(void *self, const void *str, void *slot);
int gui_image_load(void *img, const char *file)
{
    if (!img || !file) return 0;
    GuiStr s;
    gui_str_init(&s, file);
    char ok = ((ImgLoad_t)0x004C1CD0)(img, &s, NULL);
    gui_str_free(&s);
    return ok != 0;
}
