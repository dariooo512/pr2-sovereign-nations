# The tabbed info window (Log / "Missions"), and how to build the nation panel with it

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000), done 2026-10-16
with pefile + capstone (scratch scripts in the session scratchpad `agent_tabwin/`: `rt.py` =
disasm/xref/string/vtable helper, `resdump.py` = mission-string table decoder, `hashname.py` =
string-id hash). **[S]** = read from the bytes (VA given). **[H]** = hypothesis / not verified in a
running game. The `.screen` format itself is covered by `screen_format.md` (other agent); this
file covers the C++ side.

## Answer in one paragraph

The Missions window is **not** `INTERFACE_TAB_WINDOW` (that is the lower-left interface panel,
`IBP_*` controls, `0x476AC0`). It is a **`CTabControl`** instance (ctor `0x4DD080`, size `0x1A4`,
vtable `0x694AA8`) that loads `TAB_CONTROL_800x600.screen` (`TAB_BG` parchment, `TAB_Panel`
strip, `TAB_Templ` button template, `TAB_Close`). It is owned by **`CGameMenu`** (`*(app+0xEC)`,
`app = *(void**)0x6E58E4`) and built by **`CGameMenu::OpenLog` `0x507ED0`**, which is bound to
shortcut id `0xA` (the **N** key, `0x512703`) and to the "Log (N)" interface-bar button
(`0x4A120F`). OpenLog first closes every other menu (`CGameMenu::CloseAllMenus 0x507600`),
creates 7 page objects (`CBaseControl`-derived classes, one `.screen` each) and registers 8 tabs
with **`CTabControl::AddTab 0x4DD660(id, page, &offset, &tooltip, iconIdx, 0, 1, 0)`**
(`0x111` messages, `0x222` missions, `0x333`, `0x444`, ... `0x888`). Clicking a tab (or
`SelectTab 0x4DCC70`) runs `0x4DC850`, which hides/destroys the old page, calls the new page's
virtual `Create(parentRoot)` (`vt+0x1C`) on first use, then `Refresh()` (`vt+0x2C`), then emits
the tab-changed signal; CGameMenu turns that into `OnGameMenu(MENU_LOG=1, sub, 1)` with
`sub = SUBMENU_LOG_MISSIONS = 4` for tab `0x222`. The window is an ordinary top-level screen
(no modal layer); it only increments `CGameMenu+0x14C` ("a menu is open"), which some sea-map
click handlers check. A page is just a `CBaseControl` with a vtable, so **the DLL can build its
own page objects with the game's own constructors and a patched copy of a vtable**, and can
receive button clicks through the game's own libsigc slot helpers (`0x4A0C90`/`0x4AFCD0` +
`Signal::connect 0x517640` on `CButton+0x9C`). Recommended: **open a second, private
`CTabControl` with our own tab set** (option b), reuse the scroll-list page base class
(`0x4D4F10`) with `NACHRICHTEN_LISTE` + `NACHRICHTEN_EINTRAG` (the exact Missions card look),
keep the vanilla "one tab window at a time" invariant (CloseAllMenus before opening; close ours
from a hook at `CloseLog 0x5007C0`), and call our open/toggle directly from the existing Ctrl+N
frame poll. Only one hook is required.

---

## 1. The tab window

### 1.1 Who owns it, how it opens [S]

| What | VA | Notes |
|---|---|---|
| App singleton | `*(void**)0x6E58E4` (getter `0x403360` returns `&0x6E58E4`) | `0x42DCC3..0x42DCCC`: `app->+0xEC` is CGameMenu |
| `CGameMenu*` | `*(void**)(app + 0xEC)` | name from the string `CGameMenu::OpenGovernorPalace` (`0x510C97`) |
| `CGameMenu::OpenLog()` | `0x507ED0` (thiscall, no args) | returns at once if `gm+0x74 != 0` (already open) |
| Shortcut N | `0x512703..0x512738`: `ShortcutMgr(*0x6E5914)::Register 0x52B910(0xA, slot(gm, 0x507ED0), 0)` | Chronicle = id 9 (`0x509990`) |
| Interface-bar "Log (N)" button | `0x4A120F..0x4A123D`: slot(`[esi+0x6C]`=gm, `0x507ED0`) connected to `[esi+0x78]+0x9C` (button clicked) | |
| `CGameMenu::CloseLog()` | `0x5007C0` | also the tab control's close handler |
| `CGameMenu::CloseAllMenus(bool)` | `0x507600` (thiscall, ret 4) | first call is `CloseLog` (`0x507604`), then every other menu |
| `CGameMenu::SetMenuOpen(bool)` | `0x5001D0` (thiscall, ret 4) | `++/--gm+0x14C` (clamped at 0) |
| `CGameMenu::IsMenuOpen(menu,sub,a,b)` | `0x501A20` | Lua `Global_IsMenuOpen` (`0x42DC10`); LOG: `gm+0x74 != 0`, and for sub 4: `GetCurrentTabId()==0x222` (`0x501B7A`) |
| `CGameMenu::Update()` | `0x50E880` (called from `0x4032EA`) | calls `CTabControl::UpdatePages(0) 0x4DD9A0` on its open tab windows (`+0x74`, ...) |

Lua has **no** function that opens the log or a tab; only `Global_IsMenuOpen`. Constants
registered at `0x43D080..` [S]: `MENU_LOG=1`, `MENU_CHRONICLE=2`, `MENU_CONVOY=0xE`, ...,
`SUBMENU_ANY=0`, `SUBMENU_CONVOY_SHIPS=1`, `SUBMENU_TAVERN_CAPTAIN=2`, `SUBMENU_TAVERN_NPC=3`,
`SUBMENU_LOG_MISSIONS=4`, `SUBMENU_TRANSFER_SHIPS=5`, ... `SUBMENU_BMASTER_SPECIAL=0x10`.

### 1.2 `CGameMenu::OpenLog 0x507ED0` step by step [S]

```
if (gm->logTab /*+0x74*/) return;
gm->CloseAllMenus(0);                               // 0x507F01  call 0x507600
gm->menuCount /*+0x14C*/ ++;                        // 0x507F06
tab = new(0x1A4) CTabControl(1);                    // 0x507F18 A2dLib operator new; 0x4DD080
gm->logTab = tab;                                   // +0x74
tab->vt[6]/*+0x18 Create*/(string("TAB_CONTROL_800x600.screen"), parent=0);   // 0x507F79
tab->SetupButtons 0x4DC360(&CPoint(0,0), 0, -3, 0, 0, 0);                     // 0x507FCB
gm+0xDC = new(0x15C) CMessagesPage 0x4AF4A0(1)      // messages + missions (one object, two tabs)
gm+0xE0 = new(0x100) CBilanzPage    0x4AC970(1)
gm+0xE4 = new(0x0C0) CCompanyPage   0x4B34B0(1)
gm+0xE8 = new(0x0EC) CProblemsPage  0x4B4AE0(1)     // its +0xD4 signal -> gm 0x500C40
gm+0xEC = new(0x0C8) CSuccessPage   0x4B5F20(1)
gm+0xF0 = new(0x104) CTradeRoutePage 0x4B7EA0(1)
gm+0x100= new(0x0A4) CTreasureMapPage 0x4BB800(1)
tab->AddTab(0x111, gm+0xDC, &pt0, &StrMgr("IDT_LOG_NACHRICHTEN"), 0x20, 0, 1, 0);  // 0x508278
tab->AddTab(0x222, gm+0xDC, ..., "IDT_LOG_MISSIONEN",   0x2D, ...);              // 0x508338
tab->AddTab(0x333, gm+0xE4, ..., "IDT_LOG_UNTERNEHMEN", 0x23, ...);
tab->AddTab(0x444, gm+0xE0, ..., "IDT_LOG_BILANZ",      0x25, ...);
tab->AddTab(0x555, gm+0xE8, ..., "IDT_LOG_PROBLEME",    0x26, ...);
tab->AddTab(0x666, gm+0xEC, ..., "IDT_LOG_ERFOLGE",     0x31, ...);
tab->AddTab(0x777, gm+0xF0, ..., "IDT_LOG_HANDELSROUTE",0x21, ...);
tab->AddTab(0x888, gm+0x100,..., "IDT_LOG_KARTENTEILE", 0x35, ...);             // 0x5087B2
tab->CreateCloseButton 0x4DCCE0(0xF);                // 0x508802 (hook point 0x5087FD, see §4)
tab->SetCloseHandler 0x4DC9B0(slot(gm, CloseLog 0x5007C0));
tab->SetRefreshInterval 0x4DC0D0(2000);              // +0x13C, ms (used by UpdatePages)
tab->tabChanged(+0x6C).connect(slot2(gm, 0x4FFAC0));
PositionWindow 0x4D37A0(tab, false);                 // cdecl
SelectTab 0x4DCC70(page0xDC->PendingMission() ? 0x222 : 0x111);
```

The tab-change slot `0x4FFAC0(tabId, prev)` sets the messages/missions mode on the shared page
(`0x4AF720(mode)`) and posts `OnGameMenu(1, tabId==0x222 ? 4 : 0, 1, -1, -1)`.
`CloseLog 0x5007C0`: `tab->vt[0x28]()` (Destroy), `tab->vt[0](1)` (delete), delete the 7 pages
(`vt[0](1)`), `--gm+0x14C`, post `OnGameMenu(1, 0, 0, -1, -1)`.

Other `TAB_CONTROL_800x600.screen` users, all of which call `CloseAllMenus` first [S]:
Chronicle `0x509990` (`gm+0x7C`, tabs `0x99..0xFF`, pages at `gm+0xCC..0xD8, +0x10C`; it also
posts `OnGameMenu(2,..)` itself), the trade-route editor `0x50C940` (`gm+0xBC`).
`TAB_CONTROL_WIDE` (`TBW_*`) is used by `0x5090E0`. So vanilla never has two `TAB_CONTROL`
windows at the same time (this matters, §2.3).

### 1.3 `CTabControl` (ctor `0x4DD080`, `sizeof 0x1A4`) [S]

Base class `CBaseControl` (§2.1). vtable `0x694AA8` (16 slots), vbtable `0x694AE8` (virtual base
`SigC::ObjectScoped` at `+0x190`), secondary vtable `0x694A94`.

| Slot / method | VA | Meaning |
|---|---|---|
| `vt[0]` | `0x4DD630` | scalar deleting dtor (`flags&1` frees) |
| `vt[6] +0x18 Create(const std::string& screen, CObject* parent)` | `0x4DD440` | `SetupFromFile(parent, screen)` + `0x4DCB00` (finds `TAB_Panel`/`TAB_BG`, connects the radio group to `0x4DC850`) |
| `vt[10] +0x28 Destroy()` | `0x4DD610` | `0x4DD550`: clears signals, for each tab: destroy its button, `page->vt[0x28]()` if the page was created, free the entry; destroys the close button. **Does not delete pages** (the owner does) |
| `vt[15] +0x3C Show(bool)` | `0x4DC140` | shows the current page too |
| `SetupButtons(CPoint* btnOfs, CPoint* firstPos, int spacing, CDrawable* tmpl, CDrawable* closeBtn, CDrawable* userTmpl)` | `0x4DC360` | log: `(&(0,0), 0, -3, 0, 0, 0)`; tmpl 0 = find `TAB_Templ` |
| `AddTab(int id, CBaseControl* page, CPoint* pageOfs, std::wstring* tooltip, int icon, int iconArg, bool radioTab, bool userTmpl)` → `CDrawable* button` | `0x4DD660` (ret `0x20`) | clones `TAB_Templ` as `CIconButton "TAB_Templ_%02i"` (`0x4DD7C1`), `SetIcon(0, icon, iconArg, 1, 1)` (`0x4C4C50`), tooltip via `SetTTip("TTGRP_OPTIONAL", *tooltip)` if non-empty; `radioTab=1`: joins the radio group (`+0x74`), `0`: action button that only emits signals (`0x4DC960`) |
| `CreateCloseButton(int icon)` | `0x4DCCE0` (ret 4) | clones `TAB_Close`, tooltip `IDT_SCHLIESSEN`, click → `0x4DC9F0` = emit `+0x188` |
| `SetCloseHandler(Slot0*)` | `0x4DC9B0` (ret 4) | `+0x188.clear(); +0x188.connect(slot)` |
| `ConnectTabSignal(int id, Slot0*)` | `0x4DCA00` (ret 8) | per-tab "activated" signal (entry `+0x24`) |
| `SelectTab(int id)` | `0x4DCC70` (ret 4) | no-op if already current |
| `GetCurrentTabId()` | `0x4DC0B0` | -1 if none |
| `ActivateIndex(int radioIdx)` | `0x4DC850` | the page switch (below) |
| `UpdatePages(bool force)` | `0x4DD9A0` (ret 4) | every `+0x13C` ms (timeGetTime) calls `page->vt[0x2C]()` (Refresh) of the visible page |
| `SetRefreshInterval(int ms)` | `0x4DC0D0` | writes `+0x13C` |

Fields: `+0x6C` Signal2 tab changed (after), `+0x70` Signal2 (before), `+0x74` radio group,
`+0xEC` button template, `+0xF8..+0xFC` `vector<TabEntry*>`, `+0x104` current entry,
`+0x108` button offset, `+0x118` spacing, `+0x124` alt parent, `+0x13C` refresh ms,
`+0x144` **inactive-page mode** (0 = hide old page with `vt[0x3C](0)`, 1 = **destroy** it with
`vt[0x28]()`; the governor window writes 1 directly at `0x510732`), `+0x148..+0x178` control
names `TAB_Templ`, `TAB_UserTempl`, `TAB_Close`, `TAB_Panel`, `TAB_BG`, `+0x188` Signal0 close,
`+0x18C` close button.

`TabEntry` (0x28 bytes, ctor `0x4DC180`): `+0 id`, `+4 page`, `+8 button`, `+0xC/+0x10 page
offset`, `+0x1D radioTab`, `+0x24` Signal0 activated.

**Page switch `0x4DC850`** [S]: old page → `vt[0x3C](false)` or `vt[0x28]()` (mode `+0x144`);
emit `+0x70(id, prevId)`; new page: if `page+0x44 == 0` → `page->vt[0x1C](tabRoot)` (Create)
else `page->vt[0x3C](true)` (Show); then `page->vt[0x2C]()` (Refresh); `0x4DC600` places the
page root at the AddTab offset (`0x4CEBF0` = SetPos); emit `+0x6C(id, prevId)`; emit entry
`+0x24`.

### 1.4 Tab icons [S]

`iconIdx` indexes a static table at `0x6E77F0` (20-byte entries, filled by the static
initializer at `0x6773E0`; `SetIcon` builds `"scripts\\" + name + ".anim"`, `0x4C4CBF`). Useful
entries: `0x0F Pr2_Icon_Quit` (close X), `0x20 Ausrufezeichen` (!), `0x2D Missionen` (scroll),
`0x23 Bilanz` (chart), `0x25 Gold` (coins), `0x26 Getreide`, `0x31 Order`, `0x21 Autohandel`,
`0x35 Schatzkarte`, **`0x2C Pr2_Icon_Nation`**, `0x4D Goldsack`, `0x5A Staedte_Liste`,
`0x4A Haende`, `0x51 Krone`, `0x50 Schild`, `0x41 Kanonenkugel`, `0x44 Schwertkaempfer`,
`0x49 Piraten`, `0x55 Globus`, `0x2E Muelltonne` (trash, card button), `0x3E Feder`.

### 1.5 Coexistence with the map [S/H]

The tab control is created with `parent = 0` (top-level screen) and there is no modal layer or
input capture in OpenLog [S]. The only global effect is `gm+0x14C` (open-menu count), read by
the sea-map controller (`0x51992F`, `0x51DD2B`, `0x51E6AD`: `if (gm->menuCount > 0) skip`) [S];
[H] those are the click-to-select/command paths, so the map keeps rendering and time keeps
running, but some map clicks are ignored while the panel is open, exactly like the vanilla log.
Our panel should do the same `SetMenuOpen(1/0)`.

## 2. Page classes

### 2.1 `CBaseControl` (ctor `0x4CF150(this, bool mostDerived)`, object `0x80` bytes) [S]

Name from `"CBaseControl::SetupFromFile : Could not load screenfile"` (`0x693F20`). Derives from
`NA2dLib::CObject`; virtual base `SigC::ObjectScoped` at `+0x6C` (vbptr `+0xC` → vbtable
`0x693FC0 = {0, 0x60}`), size `0x14`. vtable `0x693F80`:

| Slot | Base impl | Meaning |
|---|---|---|
| `[0]` | `0x4CF260` | scalar deleting dtor (body `0x4CF090`, frees with `??3CObject 0x67F440`) |
| `[1..5]` | A2dLib `CObject::EventFilter/OnTimer/OnChildEvent/EventHandler/ClassName` | |
| `[6] +0x18` | `0x4CEDA0` | `Create(const std::string& screen, CObject* parent)` → `SetupFromFile` |
| `[7] +0x1C` | `0x5EC6B0` (ret 4) | **page `Create(CDrawable* parentRoot)`**: called by the tab control on first activation |
| `[8] +0x20` | `0x5D2D00` (ret 8) | |
| `[9] +0x24` | `0x4CEE90` | load by path via `CWindowManager::FindDrawable` |
| `[10] +0x28` | `0x4CEDC0` | `Destroy()`: `CDrawable::Destroy(+0x44, +0x48)`, `+0x44 = 0` |
| `[11] +0x2C` | `0x417CE0` (ret) | **`Refresh()`**: after activation and every `+0x13C` ms via UpdatePages |
| `[12] +0x30` | `0x4CEBA0` | clear name / (list: cleanup) |
| `[13]/[14]` | `ret` | OnShow / OnHide |
| `[15] +0x3C` | `0x4CEBB0` | `Show(bool)`: `CDrawable::Show(+0x44)` then `[13]`/`[14]` |

Fields: `+0x44` root `CDrawable*` of the loaded screen, `+0x48` second drawable, `+0x4C/+0x50`
signals, `+0x54` screen name. Helpers: `SetupFromFile(this, CObject* parent, const char* file)
0x4CEC10` (ret 8; `CDrawableFactory::CreateType(parent, file, 0, 0)`, `drawable->vt[0x18]()`,
stores `+0x44`; **throws** `CException` if the file is missing), `GetRoot() 0x4CEB90`
(`return this+0x44`), `SetPos(CPoint*) 0x4CEBF0`.

### 2.2 Scroll-list page base `CListPage` (ctor `0x4D4F10(this, bool mostDerived)`, `0xD0` bytes) [S]

Used by messages/missions (`0x4AF4A0`), chronicle events (`0x4AE210`), chronicle pirates
(`0x4B1F70`), problems (`0x4B4AE0`), chronicle towns (`0x4B7540`), and others. vtable `0x694428`
(24 slots), vbtable `0x68C558 = {0, 0xB0}` → `ObjectScoped` at `+0xBC`.

| Item | VA | Meaning |
|---|---|---|
| `vt[12] +0x30` | `0x4D5070` | list cleanup (remove event filter, clear signals, `ClearAll`) |
| `vt[16] +0x40` | `0x4D3EC0` | stack entries vertically, returns total height |
| `vt[17] +0x44` | `0x417CE0` | sort (messages: `0x4B04A0`) |
| `vt[18] +0x48 FillEntry(Item*)` | `0x5EC6B0` (ret 4) | called per item by `Relayout`; set texts and heights here |
| `vt[0]` | `0x4D58F0` | deleting dtor |
| `InitScroll(CDrawable* scrollObj, CSlider* slider)` | `0x4D5400` | `+0x84` entry parent, `+0x88` slider |
| `SetLayout(int spacing, CPoint* start, bool, bool, bool)` | `0x4D3BC0` (ret 0x14) | messages: `(10, &(0,10), 0, 0, 1)` |
| `SetTemplate(CDrawable* tmpl)` | `0x4D3BB0` | `+0x7C` |
| `AddEntry(int key, Item* item, bool append, bool relayout)` → bool | `0x4D5550` (ret 0x10) | `CreateTypeCopy("CScreen", "Entry_<key>_", parent=+0x84, copyFrom=+0x7C)`; `item+4=key, item+8=drawable` |
| `Relayout()` | `0x4D5220` | `vt[0x44]`, `vt[0x48](item)` for each, `vt[0x40]`, slider |
| `ClearAll()` | `0x4D4DC0` | destroy entry drawables, `item->vt[0](1)`, clear name cache |
| `FindEntryChild(int key, const std::string& name)` → `CDrawable*` | `0x45C660` (thiscall) | looks up `"Entry_%i_%s"` among that entry's children, cached in map `+0x94` |
| Destroy override used by all list pages | `0x46BC40` | `this->vt[0x30](); CBaseControl::Destroy` |

Fields: `+0x6C..+0x70` `vector<Item*>`, `+0x78` spacing, `+0x7C` template, `+0x84` scroll
container, `+0x88` slider. Base item: 0x10 bytes `{vptr 0x68B164 (dtor 0x45AE90 frees with
0x4040B0), key, drawable, extra}`, allocated with the game allocator `0x404070`.

### 2.3 Control conventions [S]

- **Find a control by name**: the window manager is global:
  `wm = (*(Obj**)0x6E5924)->vt[0x1C]()->vt[0x20]()->+0x94`, then
  `CWindowManager::FindDrawable(const char* name, 0)` (IAT `0x67F498`; string overload `0x67F394`).
  The type is checked with `drawable->vt[0x14]()` (ClassName) against `"CTextBox"`,
  `"CTextBoxEx"`, `"CButton"`, `"CIconButton"`, `"CSlider"`, `"CScrollObject"`, `"CStatic"`.
  **Names are global** (first match) [H for first-match]. This is why control names carry a
  per-screen prefix (`LON_`, `CHE_`, `LOB_`, `CHN_`, `TAB_`), and why vanilla keeps one tab
  window at a time. Per-entry children of a list are found with `FindEntryChild` (local, so
  duplicates across entries are fine).
- **Set text, `CTextBox`** (194 inlined sites, e.g. `0x4B01DE..0x4B01FD`): assign the
  `std::wstring` at **`+0x9C`** (IAT `0x67FA24` = `wstring::operator=(const ushort*)`, or
  `0x67FA08` from a wstring), then `*(float*)(+0xE4) = -1.0f; *(uint8_t*)(+0x114) = 1`.
- **Set text, `CTextBoxEx`** (markup, 37/81 verified sites): assign the wstring at **`+0xA4`**,
  then `CTextBoxEx::FuncCreateSubDrawables()` (IAT `0x67F1E0`); the laid-out text height is then
  at **`+0x110`**. Resize the box and its card (`0x4B0360..0x4B03AD`):
  `SetSize(width, +0x110)` and `card.SetSize(cardW, cardH - oldBoxH + newBoxH)`.
- **Rect**: `CDrawable +0x68..+0x74`; height = `|+0x70 - +0x68|`, width = `|+0x74 - +0x6C|`;
  position `+0x78/+0x7C` (x, y) (from `0x4D3EC0`, `0x4B0383`).
- **Show/hide**: `CDrawable::Show(bool)` (IAT `0x67F470`); enable: `Enable(bool)` (`0x67F364`).
- **Image**: `CStatic::Animation(const std::string& anim)` (`0x67F368`), or
  `CStatic::GetAnimation()` (`0x67F2E0`) + `CAnimation::GoTo(frame)` (`0x67F2F4`).
- **Icon button**: `CIconButton::SetIcon(slot=0, iconIdx, 0, 1, 1)` `0x4C4C50` (icon table §1.4).
- **Tooltip**: `CDrawable::SetTTip("TTGRP_OPTIONAL" (0x67FFC4), const std::wstring&)` (`0x67F388`).
- **Strings by id**: `g_pStringMgr = **(void***)0x67F4D0`;
  `std::wstring* vt[0](mgr, std::wstring* out, const std::string* id)` (`0x50823B`).
- **Sub-screens**: `CDrawableFactory::CreateType(parent, "X.screen", 0, 0)` (IAT `0x67F474`,
  factory `**0x67F450`), `CreateTypeCopy(type, newName, parent, copyFrom)` (`0x67F020`).
- **Scroll**: handled by the list base (`InitScroll`, `Relayout` updates the slider).

### 2.4 Page table [S]

| Tab | Page ctor (size) | base | vtable | `Create vt[7]` | `Refresh vt[11]` | screen |
|---|---|---|---|---|---|---|
| LOG 0x111/0x222 | `0x4AF4A0` (0x15C) | list | `0x690F78` | `0x4AFD20` | `0x4B0890` | `NACHRICHTEN_LISTE` + entry `NACHRICHTEN_EINTRAG` |
| LOG 0x333 | `0x4B34B0` (0xC0) | base | `0x6915A8` | `0x4B3CA0` | `0x4B4330` | `UNTERNEHMEN_PAGE` |
| LOG 0x444 | `0x4AC970` (0x100) | base | `0x690A88` | `0x4ADD50` | `0x4ACAD0` | `BILANZ_PAGE` (+ nested `CBaseControl` with `BILANZ_INFO_PAGE`) |
| LOG 0x555 | `0x4B4AE0` (0xEC) | list | `0x691718` | `0x4B5010` | `0x4B5450` | `PRODUKTION_PAGE` |
| LOG 0x666 | `0x4B5F20` (0xC8) | base | `0x6918C8` | `0x4B6400` | `0x4B6B90` | `ERFOLGSPAGE` |
| LOG 0x777 | `0x4B7EA0` (0x104) | base | `0x691B78` | `0x4B9A00` | `0x4BA690` | `HANDELSROUTEN_PAGE` |
| LOG 0x888 | `0x4BB800` (0xA4) | base | `0x691F38` | `0x4BC190` | `0x4BC540` | `SCHATZKARTEN_PAGE` |
| CHR 0x99 | `0x4AE210` (0xDC) | list | `0x690C28` | `0x4AE430` | `0x4AEEE0` | `CHRONIK_ENTRIES` + `CHRONIK_EINTRAG` |
| CHR 0xAA | `0x4B0C40` (0x13C) | base | `0x6911A8` | `0x4B0E80` | `0x4B16B0` | `NATION_PAGE` |
| CHR 0xBB | `0x4B1F70` (0xDC) | list | `0x691358` | `0x4B2410` | `0x4B2830` | `CHRONIK_PIRATEN` |
| CHR 0xCC/0xDD/0xEE | `0x4BC970` (0x148) | base | `0x6920E0` | `0x4BD6F0` | `0x4BEB50` | `STATISTIC_PAGE` (one object, 3 tabs) |
| CHR 0xFF | `0x4B7540` (0xD4) | list | `0x691A58` | `0x4B75E0` | `0x4B7830` | `STAEDTE_PAGE` |

Page `Create` pattern (messages `0x4AFD20`, Bilanz `0x4ADD50`): `SetupFromFile(parent, file)`;
`FindDrawable` each named control, type-check, keep the pointer in a field, throw
`"?::CreateControl : Could not load drawable"` if missing; connect button signals
(`CButton+0x9C` clicked, Signal0) to member slots.

## 3. The Missions page (what the screenshot shows) [S]

- Page `0x4AF4A0`, mode `+0xC8` (0 messages, 1 open missions, 2 done missions), set by
  `0x4AF720(mode)`; caption `LON_Caption` = `IDPR_LON_NACHRICHTEN` / `IDPR_LON_MISSIONEN`;
  the two caption icon buttons are `LON_BtnMissonsOpen` (hand) and `LON_BtnMissonsDone`
  (thumb), slot `0x4AFBA0`.
- `Create 0x4AFD20`: `NACHRICHTEN_LISTE_800x600.screen`; `LON_Scrollbar` (CSlider) and
  `LON_ScrollDrawable` (CScrollObject) → `InitScroll`; `SetLayout(10, (0,10), 0, 0, 1)`;
  template = `CreateType(root, "NACHRICHTEN_EINTRAG_800x600.screen")`, hidden, `SetTemplate`.
- `Refresh 0x4B0890`: walks the player's log records (vt `+0x14` type 1 = message, 3 =
  mission; `+0xC` done flag), skips keys already listed, fills a 0x38-byte item
  (`+0x10` date, `+0x14` caption, `+0x20` place, `+0x2C` text; header/text from the record's
  `vt+0xC/+0x10`, place `0x5E3790`, date `0x5CDDC0`) and calls `AddEntry 0x4B0650`.
- `AddEntry 0x4B0650`: list `AddEntry`; `LON_BtnRemove` (trash, icon `0x2E`) visible in modes
  0/2, click → slot `0x4B0490`(key) bound with `0x4B0100` (deletes the record), tooltip
  `IDT_LOG_EINTRAG_LOESCHEN`.
- `FillEntry 0x4B0140` (vt[18]): `LON_TmplDate` (CTextBox, right plate) = date text
  (`0x407180`), `LON_TmplCaption` (CTextBox, header bar "Ship hunt") = caption,
  `LON_TmplLoka` (CTextBox, left plate "Turk Islands") = place, `LON_TmplText` (CTextBoxEx,
  body) = text, then resize text and card to the text height.
- Card art in `NACHRICHTEN_EINTRAG`: `LON_TmplRahmen`, `LON_BalkenLinks`, `LON_TmplHeadBg`,
  `LON_BalkenRechts` (header bar), the two plates, the body box, `LON_BtnRemove`.
- **Coloured text is markup inside the body string** (`CTextBoxEx`). The two lines are the
  strings `ID_MISSION_ACHIEVED` (`EBCBE218`, appended by Lua `Mission_Complete`, `0x4308A0`):
  `<n><o:0xff008000>Mission accomplished. <o:0xff000000>` and `ID_MISSION_OKGOLD`
  (`F89F542F`, appended by `Global_AddLogGold`, `0x422760`):
  ` You have received <o:0xff1e1eff>%1<o:0xff000000><gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen>.`
  The generic gold format `ID_FORMAT_INTEXT_GOLD` is
  `<o:0xFF000096>%1<o:0xFF131512><gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen>`.
- Markup tags seen in the string tables: `<n>` newline, `<n:px>` paragraph gap, `<t>` tab,
  `<ts:px>` tab stop, `<c>` centre, `<l>`, `<r>`, `<o:0xAARRGGBB>` colour (`<o>` resets),
  `<f:fonts/X.res>` font, `<g:SCREEN.screen>` inline graphic (any `INTEXT_*` screen: `GOLD`,
  `ENGLAND/FRANKREICH/HOLLAND/SPANIEN`, `SOLDAT`, `KANONE`, `SCHIFF`, `EINWOHNER`,
  `PLUS/MINUS`, `PFEIL_HOCH/RUNTER`, `AUSRUF`, `KAPERBRIEF`, ...), `<gs:TEXTFLUSS_KEINEHOEHE>` /
  `<gs:TEXTFLUSS_BASELINE>` (inline graphic vertical alignment).

## 4. Extension strategy

### 4.1 Options

| | (a) Add tab(s) to the vanilla Log window | (b) Our own `CTabControl` with our own tab set |
|---|---|---|
| Hooks | `0x5087FD` (`8B 4E 74 6A 0F`, 5 bytes, PIC): `AddTab` for our page(s) before the close button; `0x5007FB` (`8B 8E DC 00 00 00`, 6 bytes, PIC, after the tab is deleted): delete our pages | `0x5007C0` CloseLog entry (`64 A1 00 00 00 00`, 6 bytes, PIC): close ours (runs at the start of every `CloseAllMenus`); optional `0x4DC9F0` (`81 C1 88 01 00 00`): close button of ours |
| Open/close, position, N key, Log button, counter | all vanilla | replicate ~15 calls of OpenLog/CloseLog in C |
| Ctrl+N | `OpenLog(gm)` then `SelectTab(gm->+0x74, OUR_ID)` | `panel_toggle()` |
| Strip room | already 8 tabs + X; 6 more do not fit [H] | 6 tabs + X, like the Log |
| Requirement fit | nation pages mixed into the Log; tab change posts `OnGameMenu(1,0)` for our ids (harmless) | dedicated "nation panel", exactly the requested look |
| Risk | lowest | low-medium (lifetime and mutual exclusion are ours) |

**Choose (b).** (a) is a cheap extra: one "Nation" tab (icon `0x2C`) in the Log that shows the
Overview page, if wanted later.

### 4.2 Building a page in C (no C++ needed) [S for the calls, H for running them from mingw]

1. Allocate with A2dLib's allocator (the game frees with `??3CObject`):
   `p = ((void*(__cdecl*)(size_t))*(void**)0x67F444)(0x100)`. Construct with the game's list
   base `0x4D4F10(p, 1)` (or `CBaseControl 0x4CF150(p, 1)` for a fixed-layout page). The
   virtual base sits at `+0xBC` (`+0x6C`), so **bytes `0xD0..0xFF` (`0x80..`) are free for DLL
   fields** (nothing in the game reads past the virtual base; delete frees the whole block).
2. Make a DLL copy of the vtable (`0x694428`, 24 slots; `0x693F80`, 16 slots) and replace:
   `[7] Create(parentRoot)`, `[11] Refresh()`, `[18] FillEntry(item)` (list), and
   `[10] = 0x46BC40` (list Destroy). Keep `[0]` (game dtor). Write the copy's address to
   `*(void**)p`. Leave the secondary vtable (in the virtual base) alone: its dtor thunk
   `0x4CF140` jumps straight to the real dtor.
3. `Create(parentRoot)` (list version, mirrors `0x4AFD20`):
   `SetupFromFile 0x4CEC10(p, parentRoot, "NACHRICHTEN_LISTE_800x600.screen")`;
   `slider = FindDrawable("LON_Scrollbar")`, `scroll = FindDrawable("LON_ScrollDrawable")`;
   `InitScroll 0x4D5400(p, scroll, slider)`; `SetLayout 0x4D3BC0(p, 10, &pt(0,10), 0, 0, 1)`;
   `tmpl = CreateType(fab, root, "NACHRICHTEN_EINTRAG_800x600.screen", 0, 0); tmpl->vt[0x18]();
   Show(tmpl, 0); SetTemplate 0x4D3BB0(p, tmpl)`; set `LON_Caption` text; repurpose or hide
   `LON_BtnMissonsOpen/Done` (page-level action buttons; `SetIcon`, `SetTTip`, slot);
   hide `LON_NoEntry_1` / `LON_Image` as needed.
4. `Refresh()`: only rebuild when the DLL's data version changed (it is called every 2 s by
   `UpdatePages` and on every activation). Rebuild = `ClearAll 0x4D4DC0(p)`, then per card:
   `item = 0x404070(0x10); item->vptr = 0x68B164; item->key = k; item->drawable = 0;`
   `AddEntry 0x4D5550(p, k, item, 1, 0)`; finally `Relayout 0x4D5220(p)`.
5. `FillEntry(item)`: `FindEntryChild 0x45C660(p, item->key, std::string("LON_TmplCaption"))`
   etc.; set texts (§2.3, markup for colours/gold icon); resize body and card as in
   `0x4B0360`; set the card button (`LON_BtnRemove`): icon, tooltip, show/hide, connect once.
6. **Clicks back into the DLL** (game helpers, all [S]):
   - 1-arg member slot: `0x4AFCD0(Slot* out, Obj* obj, fn, 0xFFFFFFF4, 0)` (cdecl). Proxy
     `0x596A50` calls `fn` as `__thiscall fn(obj, int)` (this = obj + 0xC + vbtable[0] − 12 =
     obj for every `CBaseControl`).
   - bind the card key: `0x4B0100(Slot* out0, Slot* in1, int key)` (cdecl) → 0-arg slot.
   - 0-arg member slot directly: `0x4A0C90(out, obj, fn, 0xFFFFFFF4, 0)` (proxy `0x49B350`).
   - connect: `Signal::connect 0x517640(signal=button+0x9C, Connection* out, Slot* s)`
     (thiscall, ret 8).
   - free the temporaries: `Connection::~Connection` (IAT `0x67F8AC`),
     `Handle<SlotData>::~Handle` (IAT `0x67F88C`); the connection stays alive and is dropped
     automatically when the page (receiver) or the button (signal) is destroyed.
   - `obj` = our page object; the DLL handler is
     `void __attribute__((thiscall)) on_card(void *page, int key)`; do the action through the
     existing C core (`core.c`/`navy.c`) and bump the data version; never destroy the window
     from inside the handler (set a flag, act next frame).
7. The tab tooltips/captions: build `std::wstring` with the imported ctor (IAT `0x67FA18`,
   `(const ushort*, const allocator&)`) and destroy it with `0x67FA04` after `AddTab` (AddTab
   copies it into the tooltip). Mod strings already registered with the string manager can be
   looked up with `g_pStringMgr->vt[0]`.

### 4.3 Opening, closing and Ctrl+N

```
open():  gm = *(app+0xEC); CloseAllMenus 0x507600(gm, 0);   // also closes ours via the hook
         SetMenuOpen 0x5001D0(gm, 1);
         tab = new(0x1A4) 0x4DD080(tab, 1);
         tab->vt[6](std::string("TAB_CONTROL_800x600.screen"), 0);
         0x4DC360(tab, &pt(0,0), 0, -3, 0, 0, 0);
         *(int*)(tab+0x144) = 1;                            // destroy inactive pages (no name clashes)
         for each page: AddTab 0x4DD660(tab, id, page, &pt(0,0), &tip, icon, 0, 1, 0);
         0x4DCCE0(tab, 0xF);                                // close X
         close: hook 0x4DC9F0 (ecx == tab) or SetCloseHandler 0x4DC9B0(tab, slot0(page0, fn))
         0x4DC0D0(tab, 2000);
         0x4D37A0(tab, 0);                                  // same placement as the Log (§5)
         0x4DCC70(tab, lastTabId);
close(): tab->vt[0x28](); tab->vt[0](1); page->vt[0](1) for each page;
         SetMenuOpen(gm, 0); tab = 0;
```

Ctrl+N: `ui.c poll_hotkey` already runs on the main thread each frame; call `panel_toggle()`
there instead of posting `OnGameMenu(0x4E41)`. Keep the event (and the Lua popups) only for
founding a nation and for the conquest Annex/Withdraw question. [H] Check in game whether the
vanilla N shortcut also fires on Ctrl+N (the shortcut manager at `*0x6E5914` was not decoded
for modifiers): if it does, the Log's `CloseAllMenus` would close our panel in the same frame;
then toggle on the key *release* or suppress the vanilla N while Ctrl is held.

## 5. Resolution and placement [S unless marked]

- All `.screen` files are authored as `*_800x600` and drawn 1:1 in pixels; nothing is scaled.
  Placement uses per-resolution template drawables: resolution index `*0x6E7FF8` (from
  app `+0xF8`, set by `0x4D2C60`) picks the template screen from `0x6E1CAC`
  (`[0] RESOLUTION_1024_768_TMPL_800x600.screen`, `[1] MenuLayout_1280.screen`) and the suffix
  from `0x6E1CBC` (`_1024`, `_1280`). Display sizes (static init `0x679CA0`): `[0] 1024x768`,
  `[1] 1280x1024`; the D3D back buffer is set from that table (`0x4054BC`).
- `PositionWindow 0x4D37A0(ctl, center)` (cdecl): `center=0` (Log, Chronicle): position of
  `TMPL_Dialoge_<sfx>` (`0x4D2A90`, drawable `+0x78`) plus `CPoint(0, (|tpl.r8−tpl.r0| −
  |win.+0x70−win.+0x68|)/2)` (`0x4D38A3..0x4D38D3`), i.e. [H, axis reading] `x = TMPL.x`,
  `y = TMPL.y + (TMPL.h − window.h)/2`; `center=1`: centred on the display size table.
  Using `0x4D37A0(tab, 0)` gives exactly the Log's position in every mode.
- `MenuLayout_1280.screen` is **not in the extracted archives** (`_workdir/arc*`), so [H] retail
  effectively runs the 1024x768 layout. **1280x800 is not a game mode**: it is the outer window
  size forced by `tools/gamehost.py` (`WINDOW = (1280, 800)`); [H] the 1024x768 back buffer is
  stretched into it. Reusing `TAB_CONTROL` + `0x4D37A0` therefore inherits the vanilla
  behaviour at both sizes; test both.

## 6. Recommended implementation

Ordered plan:

1. **`dll/gui.c` primitives** (no hooks): typedefs for the calls in §2.3/§4.2;
   `gui_find(name)`, `gui_set_text(ctrl, wchar*)`, `gui_set_textex(ctrl, wchar*) → height`,
   `gui_show`, `gui_icon`, `gui_tooltip`, `gui_wstring_new/free`, `gui_slot_click(button,
   page, fn, key)`. Null-check every `FindDrawable` result before use: the game's own helpers
   throw MSVC exceptions on missing files/controls, and [H] such a throw would unwind through
   mingw frames without cleanup.
2. **Panel shell** (`dll/panel.c`): `panel_open/close/toggle` exactly as §4.3; per-frame:
   handle a deferred close request, call `UpdatePages 0x4DD9A0(tab, 0)` (CGameMenu only updates
   its own windows), and close the panel if the world is unloading (`ui_reset` path).
3. **Hook H1 `0x5007C0`** (CloseLog entry, `64 A1 00 00 00 00`): if our panel is open, close
   it. This keeps the vanilla invariant "one `TAB_CONTROL` window at a time" (needed because
   `TAB_*`/`LON_*` names are looked up globally).
4. **Hook H2 `0x4DC9F0`** (`81 C1 88 01 00 00`), only if not using `SetCloseHandler`: if
   `ecx == our tab`, set the deferred-close flag.
5. **One list page type** (list base `0x4D4F10`, DLL vtable copy, `NACHRICHTEN_LISTE` +
   `NACHRICHTEN_EINTRAG`), parameterised by a "card provider" callback that returns
   `{key, caption, place, date, body-with-markup, button icon/tooltip/action}`. This already
   gives every page the Missions look: header bar, two plates, body text, green/blue markup with
   the gold icon, scrolling.
6. **Six tabs** (ids e.g. `0x4E01..0x4E06`): Overview `0x2C`, Treasury `0x4D`, Towns `0x5A`,
   Diplomacy `0x4A`, Government `0x51`, Military `0x41`; close `0x0F`.
   Page-level actions use the two caption icon buttons (`LON_BtnMissonsOpen/Done`), for example
   Treasury: Donate / Withdraw (fixed steps, e.g. 10,000 per click [design]); card actions use
   the per-card icon button (`LON_BtnRemove`), for example Diplomacy: declare war / offer peace
   per power, Military: commission / pay off. Every action calls the existing C core, then bumps
   the data version so `Refresh` rebuilds.
7. **Ctrl+N** → `panel_toggle()` (founding flow stays the Lua popup chain when no nation
   exists).
8. Later (needs `screen_format.md`/`screen_dump.py`): own `FNN_*` copies of the list and card
   screens with unique control names and real text buttons (CButton with caption) in place of
   the repurposed icon buttons; optional extra (option a): one Nation tab in the Log via hook
   `0x5087FD`.

Hook list (all displaced bytes position-independent, verified [S]):

| # | VA | Bytes | Purpose | Required |
|---|---|---|---|---|
| H1 | `0x5007C0` | `64 A1 00 00 00 00` | CloseLog entry = start of every CloseAllMenus: close our panel | yes |
| H2 | `0x4DC9F0` | `81 C1 88 01 00 00` | close button of our tab (`ecx == tab`) → deferred close | no (or `SetCloseHandler` slot) |
| H3 | `0x5087FD` | `8B 4E 74 6A 0F` | (option a) add a Nation tab to the Log, `esi = gm` | no |
| H4 | `0x5007FB` | `8B 8E DC 00 00 00` | (option a) delete our Log page after the tab is destroyed, `esi = gm` | with H3 |

Risks to test in game: running UI creation from the A2dLib frame hook [H, the N shortcut does
the same from input processing]; the Ctrl+N vs N shortcut interaction; save/load and returning
to the main menu with the panel open; the 2-second `UpdatePages` refresh must not reset the
scroll position (rebuild only on data change); FNN test saves are unaffected because the panel
keeps no saved state.
