/* Thin C wrappers over the game's UI classes (A2dLib + PR2.exe), for the nation
 * panel (research/tab_window.md §2.3, research/text_markup.md). Main thread only. */
#ifndef PR2N_GUI_H
#define PR2N_GUI_H
#include <stdint.h>

typedef struct { int x, y; } GuiPoint;

void *gui_new(unsigned size);                      /* A2dLib CObject::operator new (freed by the game) */
void *gui_alloc(unsigned size);                    /* the game's allocator (0x404070) */
void *gui_find(const char *name);                  /* CWindowManager::FindDrawable, NULL if missing */
void  gui_show(void *drawable, int on);
void  gui_set_size(void *drawable, int w, int h);
void  gui_set_pos(void *drawable, int x, int y);   /* relative to the parent */
void  gui_pos(const void *drawable, int *x, int *y);
void  gui_button_text(void *button, const char *text);  /* CButton caption, all states */
int   gui_width(const void *drawable);
int   gui_height(const void *drawable);
void  gui_set_text(void *textbox, const char *text);          /* CTextBox (plain) */
int   gui_set_textex(void *textboxex, const char *text);      /* CTextBoxEx (markup); returns the text height */
void  gui_icon(void *iconbutton, int icon);                    /* CIconButton::SetIcon (table §1.4) */
void  gui_tooltip(void *drawable, const char *text);
void *gui_create_screen(void *parent, const char *file);       /* CDrawableFactory::CreateType, NULL if missing */
void  gui_icon_at(void *iconbutton, int icon, int size, int dx, int dy);   /* main-menu arrows: 0x57 left, 0x56 right */
void  gui_edit_limit(void *edit, int chars, int px);           /* CEditBox: block typing past chars / pixels */
void  gui_edit_set(void *edit, const char *text);
int   gui_edit_get(const void *edit, char *out, int cap);      /* the typed text (cp1252); its length */
int   gui_image_load(void *dynimg, const char *file);
void  gui_abs_pos(const void *drawable, int *x, int *y);
int   gui_has_focus(const void *drawable);         /* window coordinates */          /* CDynamicImg: a .bmp file; 1 = ok */

/* std::string / std::wstring of the game's STLport (opaque buffers) */
typedef struct { uint8_t raw[64]; } GuiStr;
void gui_str_init(GuiStr *s, const char *text);
void gui_str_free(GuiStr *s);
void gui_wstr_init(GuiStr *s, const char *text);
void gui_wstr_free(GuiStr *s);

/* Connect a button's click (CButton+0x9C) to fn(obj, key) through the game's own
   libsigc helpers; obj must be a CBaseControl-derived object (it owns the connection). */
typedef void (__attribute__((thiscall)) *GuiClickFn)(void *obj, int key);
void gui_on_click(void *button, void *obj, GuiClickFn fn, int key);

#endif
