# Why the Overview page lost the nation's flag (the overview page fix)

Report: the reporter's files (18 Apr 1608). The Name row icon and the nation's column head in
*Size and strength* show an empty frame. The earlier `wars_row_misaligned.png` (17 Feb 1607) shows the
flag in both places. The task suspected the petition join of Eleuthera.

## Cause: a stale "already loaded" cache, not the town change

`dll/panel.c` loads the flag into a `CDynamicImg` with `load_flag(img, file, loaded, cap)`. The function
skips the load when `loaded` already names `file`, so the image is not reloaded on every refresh. The
Overview kept that cache in a function-local `static char loaded[2][96]` in `overview_fill`.

The panel's tab control is set to destroy inactive pages (`tab+0x144 = 1` in `panel_open`). Every time a
tab is shown, its page is built again from `FNN_OVERVIEW_800x600.screen`, with new, empty image controls
(`PANEL: page 0 (Your Nation) created` in the log, at every tab click). The static cache outlived the
page. It still said `Run\7.bmp`, so `load_flag` skipped the load and the new controls stayed empty.

So the flag showed only on the **first** Overview page of a game process and vanished on every later one.
The ref log fits this exactly:

- 21:49:37: the first `page 0 (Your Nation) created` of the process. `wars_row_misaligned.png` was taken
  then: at war with England, England still with 10 towns (San Juan was conquered only at 22:22:28).
- 22:33:28, 22:33:48, 22:50:03, 22:54:47: later Overview pages, all with an empty frame. `flag_missing.png`
  shows 6 towns for the nation and 6 for Holland, so it was taken *before* Eleuthera joined (22:55:00,
  which would make 7 and 5). It is one of these later pages.

A load (22:00:01) did not help: the DLL's static survives a load. Only quitting the game cleared it.

What changes ownership (petition, purchase, treaty, conquest) does not touch the flag. Nation-icon slot 5
(`0x6E1300 -> Run\7.bmp`) is set once in `flag_init` and never changes. `Run\7.bmp` is written only by
`flag_apply` (founding, a flag change, a load). A town joining calls neither. On the map the nation's towns
kept their flag all along (Domingo in the screenshot).

The same stale cache sat in the Towns page footer (`towns_footer`, `static char loaded[96]` for
`FNW_SelFlag`). The selected town's flag stayed empty after the Towns tab was opened again with the same
kind of town selected. The list rows were fine: `list_fill` clears each new row's cache.

## Fix

The two caches are now file statics (`g_ov_flag[2]`, `g_sel_flag`). The page's create step clears them:
`overview_setup` and `list_create`, the same way `list_fill` clears a new row's. The next refresh then
loads the flag into the new controls.

## Other places checked

- Town info window: the game's own dialog reads nation-icon slot 5 itself (hooks in `flag.c`). It has no
  DLL cache and was not affected.
- Diplomacy page: shows only the powers' flags (static `Pr2_Flagge_*` anims). There is no nation flag image.
- Top-bar button `TMB_Nation`: an icon (`Pr2_Icon_Nation`), not the flag.
- Navy page rows and Towns page rows: one cache per row, cleared by `list_fill` when the row is made.

## Verified in game (2026-10-19)

a private probe loads the reporter's files and `Autosave 04.pr2` under test names.
It opens the Overview, switches tabs, accepts a petition on the Towns page, annexes towns by treaty and by
conquest, and measures each flag control's pixels against `Run\7.bmp`. The measure is the mean absolute
difference: about 26 to 33 when the flag is drawn, 61 to 73 for an empty frame.

| Build | First Overview | After another tab | After a petition | After a treaty | Towns footer, 2nd time |
|---|---|---|---|---|---|
| before the fix (HEAD b432fe33 sources) | flag (33/26) | **empty** (61/73) | **empty** | **empty** | **empty** (61) |
| with the fix | flag | flag | flag | flag | flag |

`tools/feature_suite.py` UI-08 takes the probe screenshot of the Overview after a petition join in a new
game (`_build/shots/ui_overview_after_petition.png`).

## The marks next to the panel

The marks just outside the panel's right edge and below its bottom edge in `flag_missing.png` are not part
of the panel. They are the sea map's town labels behind it: a label is the name, the owner's flag and a
row of icon tiles under it. At that map position, San Juan and St. Thome lie under the panel. St. Thome's
English flag (white with a red cross) sticks out at the right edge, and the bottom of an icon row sticks out
below. A private probe OVW-07 checks that none of the other pages' 226 controls (FNT_/FNW_/FND_/FNG_/
FNV_/FNF_) is still known to the window manager while the Overview is up. It also takes screenshots with
the panel open and closed (`ovw_*_07_panel_open/closed.png`). With the panel closed, the same labels are
complete.
