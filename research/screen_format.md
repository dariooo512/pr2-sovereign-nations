# The `.screen` UI layout format (A2dLib, PR2 1.1.2.3)

Static RE of `A2dLib-2.20A.dll` (ImageBase `0x10000000`, from `%USERPROFILE%\PR2-nation-env\`) and
`reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase `0x400000`), done 2026-10-16 with
pefile + capstone. Every claim is tagged **[S]** (read from the bytes; VA given) or **[H]**
(hypothesis, usually a field name guessed from the values in the 254 vanilla screens).
A2dLib VAs are given as *function body* addresses; the exported names resolve through
incremental-link `jmp` thunks (e.g. export `?LoadProperties@CTextBox@…` = thunk `0x100043C7` →
body `0x100742F0`). RVA = VA − ImageBase (A2dLib RVA `0x742F0`).

Tool: `tools/screen_dump.py` (parse, tree dump, JSON export/import, Python
editing API, writer). **Round trip: 254 / 254 vanilla `arcd\scripts\*.screen` files and 6 / 6
localised `loca\scripts\*.screen` files re-encode byte-identically, both directly and through
the JSON form** (`python screen_dump.py verify`; 4,326 + 334 controls).

## TL;DR

* A `.screen` is a 28-byte `A2DFILE` header followed by **one serialized drawable tree**
  (normally a `CScreen` root). Every drawable is **`SH_DWFAB` (0x1A0) + `SH_DWB` (0x130) +
  a fixed-size class block** (+ children for `CScreen` / `CSlider` / `CListBox`). All blocks
  are fixed-size C structs dumped with `fwrite`, strings are fixed `char[N]` fields, so the
  format is trivially re-writable.
* A screen **never references another screen**. Composition happens in PR2 code: a page
  screen is loaded with `CreateType(parent, "X_800x600.screen")`; list entries are a second
  screen loaded once as a hidden template and cloned (`CreateTypeCopy`); `CDrawable`
  placeholders (`*_Posider`, `TMPL_*`) only carry a rectangle for code to use.
* The game's tabbed info window is **`TAB_CONTROL_800x600.screen`** (parchment
  `TAB_BG`, button strip `TAB_Panel`, `TAB_Close`, tab template `TAB_Templ`) driven by PR2's tab
  control (`0x4DD660` AddTab). The **Missions** page is **`NACHRICHTEN_LISTE_800x600.screen`
  in "missions mode"** and every mission card is a clone of
  **`NACHRICHTEN_EINTRAG_800x600.screen`** (header bar, trash button, two label plates, body).
* Coordinates are 1:1 pixels of a **1024×768 back buffer**; there is no scaling in A2dLib.
  The `_800x600` suffix is historical (every file has it). Root placement comes from
  placeholder rectangles named `TMPL_<x>_1024` in `RESOLUTION_1024_768_TMPL_800x600.screen`.
* New files: put `FNN_*_800x600.screen` under `data/scripts/` →
  deployed to `<game>\scripts\` (loose files win over the archives) and load them with
  `CDrawableFactory::CreateType(parent, "FNN_…_800x600.screen", 0, 0)`.

---

## 1. File layout

```
A2DFILE header (0x1C)                 [S] written by CA2dFile::Open (write mode, 0x1004E14D..0x1004E17F);
                                      [H] the read side takes Version() from +0x0C
  +0x00 char[8] "A2DFILE\0"
  +0x08 u32     header size = 0x1C
  +0x0C u32     version: 14 (224 files) or 13 (30 files); A2dLib's current version is
                14 (tagVersionInfo at 0x10125E7C, used by CreateType(file) 0x10040DED)
  +0x10 12 zero bytes
drawable (root)                       recursive, see 1.1
EOF                                   nothing follows the root
```

### 1.1 One drawable

```
SH_DWFAB  0x1A0 bytes   factory record: class, name, PR2 subclass
SH_DWB    0x130 bytes   CDrawable base: rect, flags, tooltip, colour-op, sound count
sound[n]  n × 0x218     (v14; 0x110 in v13). n = DWB+0x124. No vanilla screen has any.
class block             fixed size per class (table 1.4); CDrawable has none
children                CScreen:  u32 count, then count drawables
                        CSlider:  exactly 4 drawables (background, +, -, drag)
                        CListBox: entry_count × {i32 col, i32 row, drawable},
                                  template_count × {i32 col, i32 row, drawable},
                                  then 2 drawables (vertical, horizontal slider)
```

Reader chain [S]: `CDrawableFactory::CreateType(CObject* parent, CA2dFile&, name, cls)`
body `0x10040AA0` reads `SH_DWFAB` (v≥11 branch `0x10040BE4`, size check `0x1A0`), creates the
object through the registered type (tries `ext_class` first, `0x10040C64`; **throws** when that
name is set but not registered, `0x10040CCE`), then the object's virtual `LoadProperties`
reads everything else. Every class `LoadProperties` first calls
`CDrawable::LoadProperties` (`0x1001D0A0`), then reads its own block.

### 1.2 `SH_DWFAB` (0x1A0) [S] `0x10040BE4..0x10040D60`

| Off | Type | Field | Notes |
|---|---|---|---|
| 0x000 | char[8] | tag | `"SH_DWFAB"` |
| 0x008 | u32 | size | 0x1A0 |
| 0x00C | i32 | fab_id | always -1 |
| 0x010 | char[64] | **class** | A2dLib class (`CScreen`, `CStatic`, `CButton`, …) |
| 0x050 | char[256] | **name** | control name; PR2 finds controls by it (`FindDrawable`) |
| 0x150 | i32 ×2 | reserved | always -1, -1 |
| 0x158 | char[64] | **ext_class** | PR2-registered subclass created instead (`CIconButton`, `CScrollObject`, …); empty = use `class` |
| 0x198 | 8 bytes | | zero |

`ext_class` values used by vanilla screens (all registered by PR2.exe): `CIconButton` (189),
`CStaticEx` (174), `CScrollObject` (16), `CDynamicImg` (31), `CColorStatic` (28),
`CProgressBarEx` (15), `CFlag` (11), `CPolyTextButton` (8), `CMinimap` (5), `CTransferSlider`,
`CDrawClient`, `CSpecialTextBox`, `CHourglas`, `CXPBar`, `CTownMap`, `CTreasureMap`,
`CWerftSchiff`, `CWindrose`, `CSeekarteKreuz`, `CKonvoiZustand`, `CInterfaceCreature`,
`CMoonrakerDiagramm`. A mod can reuse any of these names but cannot invent new ones.

### 1.3 `SH_DWB` (0x130) — common to every control [S] v14 branch `0x1001D7A6..0x1001D8FD`

| Off | Type | Field | Evidence |
|---|---|---|---|
| 0x000 | char[8] | tag `"SH_DWB"` | `0x1001D7B0` |
| 0x008 | u32 | size 0x130 | check `0x1001D82B` |
| 0x00C, 0x010 | i32 | **x, y** (relative to the parent) | `SetPos` `0x1001D869` |
| 0x014, 0x018 | i32 | **w, h** | `SetSize` `0x1001D854` |
| 0x01C | u32 | **flags**: bit0 enabled, bit1 visible (3 = normal, 1 = hidden) | `Enable` `0x1001D87F`, `Show` `0x1001D895` |
| 0x020 | i32 | tooltip string hash (-1 = none) | `SetTTip(DEFAULT_TTIP_GROUP, this, hash)` `0x1001D8C3` |
| 0x024 | char[256] | tooltip string id (name of the hash) | [S] hash verified, §1.6 |
| 0x124 | u32 | number of sound records that follow | loop `0x1001D8E7` |
| 0x128 | i32 | colour op (Walhalla `R2D_COLOROPS`; 7 in 4,279 controls, 6 in 44) | `SetColorOp` `0x1001D83F` |
| 0x12C | i32 | not read by the loader (editor leftovers) | — |

### 1.4 Class blocks

Sizes [S] (each loader compares the first dword with the constant): `CScreen` 0x238
(`SH_SCRN`), `CStatic` 0x10C, `CStaticImg` 0x11C, `CTextBox` 0x258, `CTextBoxEx` 0x254,
`CButton` 0xC60, `CSlider` 0x220, `CEditBox` 0x368, `CProgressBar` 0x218, `CVideoSKS` 0x110,
`CListBox` 0x40, `CDrawable` none.

**CScreen** — `LoadProperties` `0x1006D390`: `SH_SCRN` block (tag + size 0x238, rest zero),
then `u32 child_count` (`0x1006D3FA`) and `child_count` × `CreateType(this, file)` (`0x1006D413`).

**CStatic** (image / animation) — `0x10072AF0`

| Off | Field |
|---|---|
| 0x000 | size 0x10C |
| 0x004 | char[264] **anim**: `scripts\X.anim` or `-none-` (`RESNAME_NONE`) → `CAnimation::Load` `0x10072BBD`, then sized to the control rect |

**CTextBox** (single-line label) — `0x100742F0`, v14 branch `0x100746AD`, member map
`0x100746D0..0x1007477C`; semantics from `OnDraw` `0x10075480` and `DrawBorders` `0x100741C0`.

| Off | Field | Notes |
|---|---|---|
| 0x004 | char[256] **font** | `fonts\X.res` or `-none-` → `CreateRes` `0x10074822` |
| 0x104 | char[256] **text** | string id; `ID_NONE` = text set by code |
| 0x204 | i32 text_hash | → `g_pStringMgr->vfunc[0x14](hash, &text)` `0x100747A1` |
| 0x208 | i32 | unused (0) |
| 0x20C, 0x210 | i32 text_dx, text_dy | added to the computed origin `0x10075738` |
| 0x214 | ARGB **color** | text colour |
| 0x218 | ARGB effect_color | colour of the outline/shadow passes (`ebx` for every effect `DrawText`) |
| 0x21C | ARGB bg_color | filled first when alpha ≠ 0 (`0x100754DA`) |
| 0x220 | i32 **effect** | `0x100757D4`: 0 none, 1 outline (several offset passes), 2 shadow (+d,+d), 3 shadow (−d,−d) |
| 0x224 | i32 effect_size | d in pixels (also widens the text box) |
| 0x228 | i32 **halign** | jump table `0x10076234`: 0 left, 1 right, 2 centre, 3 justify (`CalcSpaceWidth`) |
| 0x22C | i32 **valign** | `0x10075686`: 0 centre, 1 top, 2 bottom |
| 0x230..0x23C | ARGB ×4 border colours | order top, right, bottom, left (`DrawBorders`) |
| 0x240..0x24C | i32 ×4 border widths | same order; top/left also inset the text |

**CTextBoxEx** (multi-line, word-wrapped rich text; renders itself as a set of CTextBox
sub-drawables) — `0x100773D0`, size check `0x10077441`, member map `0x1007746F..0x10077508`.

| Off | Field | Notes |
|---|---|---|
| 0x004 | char[256] font | |
| 0x104 | char[256] text | string id |
| 0x204 | i32 text_hash | `0x10077524` |
| 0x208 | ARGB color | [H] default text colour (#FF131512 = PR2 body brown-black in 275 boxes) |
| 0x20C | ARGB effect_color | [H] (#FFEBEBEB light glow) |
| 0x210 | ARGB bg_color | [H] |
| 0x214, 0x218 | i32 effect, effect_size | [H] same meaning as CTextBox |
| 0x21C, 0x220 | i32 margins / line spacing | [H] |
| 0x224 | i32 align | [H] |
| 0x228 | i32 | [H] flag |
| 0x22C..0x238 | ARGB ×4 border colours | [S] copied to the border sub-box `0x1007727A..0x100772A4` |
| 0x23C..0x248 | i32 ×4 border widths | [S] same, `0x100772AA..0x100772F2` |

**CButton** — `0x10051040`, v14 branch `0x100513C8` (size check `0x100513F5`), map
`0x10051423..0x100516C1`; draw `0x100508B0`.

| Off | Field | Notes |
|---|---|---|
| 0x008, 0x00C | i32 text_dx, text_dy | member 0x9D8 |
| 0x010..0x01C | i32 ×4 label hashes | states **dis, nr, pr, hl** (`0x10051480` loop of 4) |
| 0x020..0x41F | char[256] ×4 label ids | same order |
| 0x420..0x42C | ARGB ×4 label colours | per state; +0x430 a 5th colour (often garbage) |
| 0x434 | ARGB effect_color | used by every effect pass `0x10050B75` |
| 0x438 | char[256] font | |
| 0x538, 0x638, 0x738, 0x838 | char[256] **anim_dis, anim_nr, anim_pr, anim_hl** | 7-slot loop `0x100515A0`, `CAnimation::Load` `0x100515EE` |
| 0x938, 0xA38 | char[256] anim slots 4, 5 | [H] rarely used |
| 0xB38 | char[256] anim slot 6 = **checked overlay** | `Pr2_CheckBox_on.anim` etc. |
| 0xC38 | i32 | member 0x9D4, tested `==1` in OnDraw `0x100509D0` [H] |
| 0xC3C, 0xC40 | i32 halign, valign | [H] |
| 0xC44 | i32 effect | member 0xA00 |
| 0xC48 | i32 effect_size | used as a signed byte (0x9FC) |
| 0xC4C | i32 toggle | ==1 sets bit0 of the button flags [H: toggle] |
| 0xC54, 0xC58 | i32 press_dx, press_dy | label shift while pressed (0xA34/0xA38, `0x10050B0D`) |

For tabs, PR2 uses the **pressed** anim `Pr2_IconBtn_ch.anim` as the "selected" look
(`TAB_Templ`, `IBP_Btn`).

**CSlider** — `0x1006F600`: block 0x220 then **4 child drawables** created with
`CreateType(this, file)`: Background, IncreaseButton, DecreaseButton, DragButton [S, error
strings at `0x1006F8CF..0x1006F9A2`]. Block fields: +0x04 [H] value, +0x08/+0x0C min/max
(`0x1000532B` → `RecalcIncrement`), +0x10 [H] position, +0x14 [H] page, +0x18/+0x118
char[256] resource names (`-none-`), +0x218/+0x21C [H] small/large step.

**CListBox** — `0x10064F10`, v≥8 branch `0x10065559`: block 0x40 (`0x1005EE60`), then
`entry_count` (+0x30) × {CPoint, drawable} (`0x10065620`), `template_count` (+0x34) ×
{CPoint, drawable} registered as `<name>_template[col][row]` (`0x100657ED`), then the vertical
and horizontal slider drawables (`0x100659D6`, `0x10065A1C`). Vanilla files have only templates.
+0x08/+0x0C and +0x14/+0x18 [H] column/row counts; +0x28 [H] flags (member 0x118).

**CStaticImg** (full-screen `.aim` picture, menus) 0x11C: +0x04 char[264] `images\X.aim`,
+0x10C/+0x110 [H] image h/w. **CEditBox** 0x368, **CProgressBar** 0x218, **CVideoSKS** 0x110:
layouts in `screen_dump.py` with [H] names; they are not needed for the nation panel.

A2dLib also registers `CComboBox`, `CSpinner`, `CDiagram`, `CButtonPullDown`,
`CProgressControl`, `C3DScene` and `CTTipSimple`, but no vanilla screen contains them, so
their blocks are not mapped. `screen_dump.py` refuses unknown classes.

### 1.5 Strings and colours

* Fixed `char[N]` fields, NUL-terminated; bytes after the NUL are kept verbatim by the tool.
* `-none-` = no resource (`RESNAME_NONE`); `ID_NONE` = no string (hash -1).
* Colours are little-endian `0xAARRGGBB`; alpha 0 means "do not draw".
* Paths are relative to the game folder and use `\`: `scripts\X.anim`, `fonts\X.res`,
  `images\X.aim`.

### 1.6 String-id hash [S]

`res_hash` in `screen_dump.py` (= `strings_hash` in `dll/strings.c`: `h = (h*0x71 + (signed
char)c) % 999999991`, `ID_NONE` → -1). It matches **every** stored pair in the vanilla
screens (4,326 tooltips, 1,092 CTextBox, 377 CTextBoxEx, 4 × 585 button labels). The engine
uses only the hash; the name is for humans. So a screen can name the mod's own ids: [H] the
hash of e.g. `IDPR_FNN_TITLE` should resolve through the same `CStringManager` that holds the
table `PR2Nation.dll` registers (`"FNN"`, `ui_entry.md` §5), provided it is registered first. (EditBox +0x260 is not a hash.)

### 1.7 Control types in vanilla screens

| Class | Count | Use |
|---|---|---|
| `CStatic` | 1,656 | every image: backgrounds, bars, plates, icons, separators |
| `CTextBox` | 1,092 | one-line labels/values; also borders/frames (font `-none-` + border) |
| `CButton` | 585 | buttons, checkboxes, icon buttons (`ext_class CIconButton`) |
| `CTextBoxEx` | 377 | multi-line body text |
| `CScreen` | 254 | file roots (sub-screens appear only through code) |
| `CDrawable` | 228 | empty placeholders (`*_Posider`, `TMPL_*`), PR2 custom drawables via `ext_class` (scroll area, minimap, flags) |
| `CSlider` | 54 | scrollbars (with 4 element children) |
| `CEditBox` | 52 | text input |
| `CStaticImg` | 13 | full-screen menu backgrounds |
| `CListBox` | 9 | grids with inline templates (options/key lists) |
| `CVideoSKS` | 4 | video panes |
| `CProgressBar` | 2 | loading bars |

### 1.8 `.anim` files (what `CStatic.anim` / button anims point to)

`SH_ANIM` header (tag, 0x20, version 1, **w, h** at +0x10/+0x14, …), then part slots of 0x158
bytes, each with an `imagesSD\X.aim` part name (resolved through `scripts\Partmap.007` to a
texture page, `flags.md` §1). [H from the data] Static 3,220-byte anims have 9 slots at
`0x68 + k·0x158` laid out as a 3×3 nine-slice (k = 0 TL … 4 centre … 8 BR):
`Pr2_Bg_Dialog.anim` (440×450) uses slots 1/4/7 = `Pr2_Bg_Dialog_se`, `_se_mid`,
`_se_bottom` (vertical three-slice, stretches to any height), `Pr2_TabCtrlBtnPanel_se.anim`
(46×162) likewise; single images (`Pr2_CapBalken_*`, icons) use slot 0. Animated anims are
longer (frames). The tool does not edit anims; reuse existing ones.

---

## 2. How screens are composed (no in-file references)

A `.screen` contains no reference to any other `.screen` [S: the only file-reading call in
the whole loader is `CreateType(parent, CA2dFile&)` on the *same* file]. PR2 composes UIs in
code:

1. **Page = file loaded under a parent.** `CBaseControl::SetupFromFile(parent, file)`
   `0x4CEC10` → `CDrawableFactory::CreateType(parent, file, 0, 0)` (`0x10040DD0`), stores the
   root at `[this+0x44]` (getter `0x4CEB90`).
2. **File lookup** [S] `0x10040DD0`: `CA2dFile::Open(file)` first; if that fails,
   factory path + file, where the path defaults to `CDrawableFactory::STR_SCRIPTPATH =
   "scripts\\"` (`0x100EE5AB`). So `"FNN_X_800x600.screen"` resolves to `scripts\FNN_X_800x600.screen`.
   Reads go through the archive container, **loose disk file first**, then
   pr2_patch > loca > arcs > arct > arcd (`flags.md` §3). `pr2_loca.cpr` holds 6 localised
   screens (`ERFOLGSPAGE`, `UNTERNEHMEN_PAGE`, …) that replace the arcd ones.
3. **List entries = template file cloned per row.** Chronicle (`0x4AE430`): loads
   `CHRONIK_ENTRIES_800x600.screen` (`0x4AE44D`), looks up `CHE_ScrollDrawable` (a
   `CDrawable` with `ext_class CScrollObject`) and `CHE_Scrollbar` (`CSlider`), then loads
   `CHRONIK_EINTRAG_800x600.screen` **as a hidden child** (`0x4AE578..0x4AE5A8`, kept at
   `[this+0xC4]`) and clones it for every entry. The Missions/Messages page does the same
   with `NACHRICHTEN_LISTE` + `NACHRICHTEN_EINTRAG` (`0x4AFD40`).
4. **Tabs = cloned button.** The logbook (`0x507F00`) loads `TAB_CONTROL_800x600.screen`
   (`0x507F4F`) and calls AddTab `0x4DD660` eight times. AddTab clones `TAB_Templ` with
   `CreateTypeCopy("CIconButton", "<name>_%02i", parent, template)` (`0x4DD81C`), then sets
   the icon with `CIconButton::SetIcon(slot 0, iconIndex, …)` `0x4C4C50` (5 stack args,
   `0x4DD83D..0x4DD848`), which loads `"scripts\\" + iconTable[iconIndex] + ".anim"`
   (table of std::strings at `0x6E77F0`, stride 0x14, built at `0x677450..0x679880`).
5. **Placeholders.** Empty `CDrawable`s (`LOB_Posider`, `CHE_GraphicPosider`, `TMPL_*`) only
   provide a rectangle that code reads (`FindDrawable`, `+0x68..0x74` = top, left, bottom, right).
6. **Inline templates** exist only in `CListBox` (`<name>_template[c][r]`).
7. [H, `flags.md`] `CTextBoxEx` rich text can embed `<g:scripts/X.screen>`.

Logbook tabs [S: the pushed constants at `0x508209..0x5087B2`; H: which AddTab argument is the icon index — the order !, scroll, chart, coins … matches the screenshot]:

| Tab | Tooltip | Icon index → anim | Page screen |
|---|---|---|---|
| 0x111 | `IDT_LOG_NACHRICHTEN` | 32 `Pr2_Icon_Ausrufezeichen` | `NACHRICHTEN_LISTE` (messages mode) |
| 0x222 | `IDT_LOG_MISSIONEN` | 45 `Pr2_Icon_Missionen` | `NACHRICHTEN_LISTE` (missions mode: caption `IDPR_LON_MISSIONEN` `0x4AFADB`, filter buttons `IDT_LOG_AKTUELLE/BEENDETE_MISSIONEN` `0x4AFA4A/0x4AF9D0`) |
| 0x333 | `IDT_LOG_UNTERNEHMEN` | 35 `Pr2_Icon_Bilanz` | `UNTERNEHMEN_PAGE` |
| 0x444 | `IDT_LOG_BILANZ` | 37 `Pr2_Icon_Gold` | `BILANZ_PAGE` |
| 0x555 | `IDT_LOG_PROBLEME` | 38 `Pr2_Icon_Getreide` | `PRODUKTION_PAGE` [H] |
| 0x666 | `IDT_LOG_ERFOLGE` | 49 `Pr2_Icon_Order` | `ERFOLGSPAGE` |
| 0x777 | `IDT_LOG_HANDELSROUTE` | 33 `Pr2_Icon_Autohandel` | `HANDELSROUTEN_PAGE` [H] |
| 0x888 | `IDT_LOG_KARTENTEILE` | 53 `Pr2_Icon_Schatzkarte` | `SCHATZKARTEN_PAGE` [H] |

Useful icon indexes for the nation tabs: 44 `Pr2_Icon_Nation`, 81 `Pr2_Icon_Krone`,
37 `Pr2_Icon_Gold`, 77 `Pr2_Icon_Goldsack`, 16 `Pr2_Icon_Lagerhaus`, 57 `Pr2_Icon_Gebaeude`,
85 `Pr2_Icon_Globus`, 74 `Pr2_Icon_Haende`, 62 `Pr2_Icon_Feder`, 80 `Pr2_Icon_Schild`,
65 `Pr2_Icon_Kanonenkugel`, 56 `Pr2_Icon_Schiffe`, 15 `Pr2_Icon_Quit`, 46 `Pr2_Icon_Muelltonne`
(full list in §6).

---

## 3. Resolutions

* [S] PR2 knows two layout modes, index `[0x6E7FF8]`: back-buffer sizes `0x6E8000` =
  {**1024×768**, 1280×1024} (initialised at `0x679CAC`, copied into the D3D present
  parameters at `0x4054BC`).
* [S] `SetResolution(idx)` `0x4D2C60` loads layout file `0x6E1CAC[idx]`:
  idx 0 = **`RESOLUTION_1024_768_TMPL_800x600.screen`**, idx 1 = `MenuLayout_1280.screen`
  (**not shipped in any archive**); main-menu layouts `0x6E1CB4[idx]`
  (`MAINMENU_LAYOUT_1024_768_800x600.screen`, none for idx 1).
* [S] Placement: `GetTemplatePos(name)` `0x4D2A90` / `GetTemplateRect(name)` `0x4D2B90` append
  the suffix `0x6E1CBC[idx]` (`"_1024"` / `"_1280"`) and look the name up with
  `CWindowManager::FindDrawable`. Example: the bottom tab window
  (`INTERFACE_TAB_WINDOW`, `0x476BD8`) goes to `TMPL_InterfaceTabWindow_1024`
  = (260,288) 450×480; modal dialogs are centred in `TMPL_Dialoge_1024` = (260,29) 450×534
  (`0x4D37F9..0x4D39C7`, `SetAbsPos`), which puts the logbook at ≈(263,73) as in the screenshot.
* **Nothing scales.** All 254 screens are authored for the 1024×768 back buffer (the
  `_800x600` name is a leftover). The 1280×800 window used by the test host
  (`tools/gamehost.py` forces the window size) shows the same 1024×768 back buffer
  stretched [H]. So one `FNN_*_800x600.screen` works for both acceptance sizes; only the root
  position matters (use `TMPL_Dialoge_1024`, or (263,73) like the logbook).
* `LAYOUT_800x600.screen` holds tooltip templates (`TMPL_Tooltip*`, `0x4D3A1F`).

---

## 4. Dumps (tree, from `screen_dump.py dump`)

Format: `Class<ext_class> "name" @(x,y) wxh [HIDDEN|DISABLED] key properties`; `align=H/V`
(L/R/C/J, C/T/B), `effect=mode/size #colour`. Use `dump --all` for every field.

### INTERFACE_TAB_WINDOW_800x600.screen — bottom-docked info window frame (not the logbook)

```
CScreen "INTERFACE_TAB_WINDOW" @(0,0) 450x481
  CStatic "ITW_Bg" @(0,0) 450x481  anim=scripts\Pr2_Dialog_BG.anim
```

### TAB_CONTROL_800x600.screen — **the tabbed panel frame** used by the logbook (and two other tab dialogs, `0x509A0D`, `0x50C9A7`)

```
CScreen "TAB_CONTROL" @(0,0) 510x450
  CStatic "TAB_BG" @(0,0) 440x450  anim=scripts\Pr2_Bg_Dialog.anim
  CStatic "TAB_Panel" @(437,1) 46x125  anim=scripts\Pr2_TabCtrlBtnPanel_se.anim
  CButton<CIconButton> "TAB_Templ" @(439,7) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "TAB_Close" @(439,44) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_pr.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
```

### INTERFACE_BUTTON_PANEL_800x600.screen — side buttons of INTERFACE_TAB_WINDOW

```
CScreen "INTERFACE_BUTTON_PANEL" @(0,0) 50x209
  CButton<CIconButton> "IBP_Btn" @(6,6) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "IBP_Close" @(6,49) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_pr.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "IBP_UserBtn" @(6,108) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_pr.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
```

### NACHRICHTEN_LISTE_800x600.screen — **Missions page** (= Messages page in missions mode)

```
CScreen "NACHRICHTEN_LISTE" @(0,0) 440x450
  CDrawable<CScrollObject> "LON_ScrollDrawable" @(32,63) 377x359
  CSlider "LON_Scrollbar" @(394,62) 27x360
    [bg] CStatic "LON_Scrollbar_Background" @(4,12) 20x336  anim=scripts\Pr2_Slider_Bg.anim
    [inc] CButton "LON_Scrollbar_Button +" @(1,338) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_unten_nr.anim|Pr2_BtnDragStep_unten_hl.anim|Pr2_BtnDragStep_unten_pr.anim|Pr2_BtnDragStep_unten_dis.anim
    [dec] CButton "LON_Scrollbar_Button -" @(1,0) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_oben_nr.anim|Pr2_BtnDragStep_oben_hl.anim|Pr2_BtnDragStep_oben_pr.anim|Pr2_BtnDragStep_oben_dis.anim
    [drag] CButton "LON_Scrollbar_Button Drag" @(0,48) 26x17  anims(nr/hl/pr/dis)=Pr2_Slider_DragBtn_nr.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_nr.anim
  CStatic "LON_CaptionBg_" @(41,27) 358x24  anim=scripts\Pr2_CapBalken_du_x.anim
  CTextBox "LON_Caption" @(95,7) 251x41  font=ELGRECO_34x34aaFHk.res text=IDPR_LON_NACHRICHTEN color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CButton<CIconButton> "LON_BtnMissonsDone" @(367,24) 27x26  anims(nr/hl/pr/dis)=Pr2_BtnLong_mini_nr.anim|Pr2_BtnLong_mini_hl.anim|Pr2_BtnLong_mini_ch.anim|Pr2_BtnLong_mini_dis.anim
  CButton<CIconButton> "LON_BtnMissonsOpen" @(338,24) 27x26  anims(nr/hl/pr/dis)=Pr2_BtnLong_mini_nr.anim|Pr2_BtnLong_mini_hl.anim|Pr2_BtnLong_mini_ch.anim|Pr2_BtnLong_mini_dis.anim
  CStatic "LON_MsgBg" @(96,195) 248x38 HIDDEN  anim=scripts\Pr2_FrachtHandelTextFeld.anim
  CTextBoxEx "LON_NoEntry_1" @(44,150) 346x50  font=Tiepolo_bold14x14aaFH.res text=IDPR_KEIN_EINTRAG color=#FF131512 effect=2/1 #FFEBEBEB
  CStatic "LON_Image" @(21,190) 398x160  anim=scripts\Pr2_Img_Schatzkarte.anim
```

### NACHRICHTEN_EINTRAG_800x600.screen — **mission card template**, cloned per entry

```
CScreen "NACHRICHTEN_EINTRAG" @(0,0) 377x130
  CTextBox "LON_TmplRahmen" @(4,5) 368x122 HIDDEN  font=-none- text=ID_NONE color=#FF000000 align=C/C
  CStatic "LON_BalkenLinks" @(192,46) 170x19  anim=scripts\Pr2_CapBalken_nu_s.anim
  CStatic "LON_TmplHeadBg" @(3,14) 370x20  anim=scripts\Pr2_CapBalken_eu_x.anim
  CStatic "LON_BalkenRechts" @(13,46) 170x19  anim=scripts\Pr2_CapBalken_nu_s.anim
  CTextBox "LON_TmplDate" @(191,43) 170x22  font=Tiepolo_black14x14aaFHk.res text=IDPR_TEST_08 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBoxEx "LON_TmplText" @(14,76) 348x52  font=Tiepolo_bold14x14aaFH.res text=IDPR_TEST_05 color=#FF131512 effect=2/1 #FFEBEBEB
  CTextBox "LON_TmplLoka" @(11,43) 170x21  font=Tiepolo_black14x14aaFHk.res text=IDPR_TEST_07 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBox "LON_TmplCaption" @(41,7) 295x28  font=Tiepolo_bold18x18aaFHk.res text=IDPR_TEST_06 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CButton<CIconButton> "LON_BtnRemove" @(13,10) 27x26  anims(nr/hl/pr/dis)=Pr2_BtnLong_mini_nr.anim|Pr2_BtnLong_mini_hl.anim|Pr2_BtnLong_mini_pr.anim|Pr2_BtnLong_mini_dis.anim
```

### CHRONIK_ENTRIES_800x600.screen — Chronicle list page

```
CScreen "CHRONIK_ENTRIES" @(0,0) 440x450
  CDrawable<CScrollObject> "CHE_ScrollDrawable" @(19,60) 377x363
  CSlider "CHE_Scrollbar" @(395,60) 27x363
    [bg] CStatic "CHE_Scrollbar_Background" @(4,12) 20x341  anim=scripts\Pr2_Slider_Bg.anim
    [inc] CButton "CHE_Scrollbar_Button +" @(1,341) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_unten_nr.anim|Pr2_BtnDragStep_unten_hl.anim|Pr2_BtnDragStep_unten_pr.anim|Pr2_BtnDragStep_unten_dis.anim
    [dec] CButton "CHE_Scrollbar_Button -" @(1,0) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_oben_nr.anim|Pr2_BtnDragStep_oben_hl.anim|Pr2_BtnDragStep_oben_pr.anim|Pr2_BtnDragStep_oben_dis.anim
    [drag] CButton "CHE_Scrollbar_Button Drag" @(0,48) 26x17  anims(nr/hl/pr/dis)=Pr2_Slider_DragBtn_nr.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_nr.anim
  CStatic "CHE_CaptionBg" @(41,27) 358x24  anim=scripts\Pr2_CapBalken_du_x.anim
  CTextBox "CHE_Caption" @(136,6) 168x42  font=ELGRECO_34x34aaFHk.res text=IDPR_CHRONIK color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CStatic "CHE_MsgBg" @(96,206) 248x38  anim=scripts\Pr2_FrachtHandelTextFeld.anim
  CTextBoxEx "CHE_NoEntry_1" @(104,209) 232x32  font=Tiepolo_bold13x13aaFHk.res text=IDPR_KEIN_EINTRAG color=#FF131512 effect=2/1 #FFEBEBEB
```

### CHRONIK_EINTRAG_800x600.screen — Chronicle card template

```
CScreen "CHRONIK_EINTRAG" @(0,0) 377x160
  CDrawable "CHE_GraphicPosider" @(0,35) 120x120
  CStatic "CHE_TmplHeadBg" @(3,9) 370x20  anim=scripts\Pr2_CapBalken_eu_x.anim
  CStatic "CHE_TmplCapBg" @(153,47) 164x19  anim=scripts\Pr2_CapBalken_nu_s.anim
  CTextBox "CHE_TmplCaption" @(114,42) 253x25  font=Tiepolo_black14x14aaFHk.res text=IDPR_TEST_06 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBox "CHE_TmplHead" @(53,4) 295x24  font=Tiepolo_bold18x18aaFHk.res text=IDPR_TEST_08 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CStatic "CHE_ImageTmpl" @(11,47) 90x90  anim=-none-
  CTextBoxEx "CHE_TmplText" @(120,76) 255x77  font=Tiepolo_bold14x14aaFH.res text=IDPR_TEST_05 color=#FF131512 effect=2/1 #FFEBEBEB
```

### NATION_PAGE_800x600.screen — Chronicle "Nations" table page

```
CScreen "NATION_PAGE" @(0,0) 440x450
  CStatic "S0000_Kopie6Auf_TAB_BG" @(0,0) 440x450  anim=scripts\Pr2_Bg_Dialog.anim
  CStatic "CHN_Noname_15" @(28,319) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CStatic "CHN_Noname_14" @(28,385) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CStatic "CHN_Noname_13" @(28,352) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CTextBox "CHN_Noname_12" @(27,291) 386x30  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#46FFFFFF
  CStatic "CHN_Noname_11" @(25,288) 390x133  anim=scripts\Pr2_DoppelRahmen.anim
  CTextBox "CHN_Noname_10" @(27,389) 386x30  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#46FFFFFF
  CTextBox "CHN_Noname_05" @(27,91) 386x18  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#46FFFFFF
  CTextBox "CHN_Noname_04" @(27,207) 386x41  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#46FFFFFF
  CStatic "CHN_Noname_03" @(28,203) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CStatic "CHN_Noname_02" @(28,105) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CStatic "CHN_Noname_01" @(28,105) 384x7  anim=scripts\Pr2_Tabellenlinie_horizontal.anim
  CStatic "CHN_Noname_00" @(25,89) 390x162  anim=scripts\Pr2_DoppelRahmen.anim
  CStatic "CHN_Bg1" @(35,64) 370x20  anim=scripts\Pr2_CapBalken_eu_x.anim
  CStatic "CHN_Bg2" @(35,263) 370x20  anim=scripts\Pr2_CapBalken_eu_x.anim
  CTextBox "CHN_Txt6" @(73,60) 295x24  font=Tiepolo_black17x17aaFHk.res text=IDPR_CHN_GROESSE_STAERKE color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBox "CHN_Txt5" @(73,259) 295x24  font=Tiepolo_black17x17aaFHk.res text=IDPR_CHN_VERH_NATIONEN color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBox "CHN_Txt1" @(28,120) 105x20  font=Tiepolo_bold14x14aaFH.res text=IDPR_CHN_EINWOHNER color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Txt2" @(28,141) 105x20  font=Tiepolo_bold14x14aaFH.res text=IDPR_CHN_STAEDTE color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Txt_4" @(28,183) 105x20  font=Tiepolo_bold14x14aaFH.res text=IDPR_CHN_STAERKE color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Txt4" @(33,218) 75x20  font=Tiepolo_bold14x14aaFH.res text=IDPR_CHN_KRIEGE color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Pop_1" @(131,123) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Strength_1" @(131,184) 60x20  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Towns_1" @(131,143) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Pop_2" @(202,123) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Strength_2" @(202,184) 60x20  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Towns_2" @(202,143) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Pop_3" @(273,123) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Strength_3" @(273,184) 60x20  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Towns_3" @(273,143) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Pop_4" @(344,123) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Strength_4" @(344,184) 60x20  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Towns_4" @(344,143) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Verh_Nat_1" @(30,295) 75x20  font=Tiepolo_bold14x14aaFH.res text=ID_NATION_0 color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Verh_Nat_2" @(30,328) 75x20  font=Tiepolo_bold14x14aaFH.res text=ID_NATION_0 color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Verh_Nat_3" @(30,362) 75x20  font=Tiepolo_bold14x14aaFH.res text=ID_NATION_0 color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Verh_Nat_4" @(30,394) 75x20  font=Tiepolo_bold14x14aaFH.res text=ID_NATION_0 color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Verh_Ansehen_1" @(105,298) 110x16  font=Tiepolo_bold13x13aaFHk.res text=ID_ANSEHEN_3 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Verh_Ansehen_2" @(105,331) 110x16  font=Tiepolo_bold13x13aaFHk.res text=ID_ANSEHEN_3 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Verh_Ansehen_3" @(105,365) 110x16  font=Tiepolo_bold13x13aaFHk.res text=ID_ANSEHEN_3 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Verh_Ansehen_4" @(105,397) 110x16  font=Tiepolo_bold13x13aaFHk.res text=ID_ANSEHEN_3 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CDrawable "CHN_Nat_1" @(148,102) 25x15
  CDrawable "CHN_Nat_2" @(218,102) 25x15
  CDrawable "CHN_Nat_3" @(289,102) 25x15
  CDrawable "CHN_Nat_4" @(360,102) 25x15
  CStatic "CHN_Nation_Tmpl_4" @(51,98) 25x15  anim=scripts\Pr2_Flagge_Spanien.anim
  CStatic "CHN_Nation_Tmpl_3" @(51,98) 25x15  anim=scripts\Pr2_Flagge_Holland.anim
  CStatic "CHN_Nation_Tmpl_2" @(51,98) 25x15  anim=scripts\Pr2_Flagge_Frankreich.anim
  CStatic "CHN_Nation_Tmpl_1" @(51,98) 25x15  anim=scripts\Pr2_Flagge_England.anim
  CTextBoxEx "CHN_War_2" @(203,213) 60x40  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_War_3" @(274,213) 60x40  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_War_4" @(345,213) 60x40  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_War_1" @(132,213) 60x40  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CStatic "CHN_CaptionBg" @(41,27) 358x24  anim=scripts\Pr2_CapBalken_du_x.anim
  CTextBox "CHN_Caption" @(112,8) 216x43  font=ELGRECO_34x34aaFHk.res text=IDPR_CHN_NATIONEN color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CTextBoxEx "CHN_Verh_Flags_4" @(204,396) 110x19  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_Verh_Flags_3" @(204,364) 110x19  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_Verh_Flags_2" @(204,330) 110x19  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_Verh_Flags_1" @(204,298) 110x17  font=Tiepolo_black13x13aaFHk.res text=ID_NONE color=#FF000000
  CTextBoxEx "CHN_Verh_Special_1" @(293,295) 120x25  font=Tiepolo_bold13x13aaFHk.res text=IDPR_CHN_KAPERBRIEF color=#FF131512 effect=2/1 #FFFFFFFF
  CTextBoxEx "CHN_Verh_Special_2" @(293,328) 120x25  font=Tiepolo_bold13x13aaFHk.res text=IDPR_CHN_KAPERBRIEF color=#FF131512 effect=2/1 #FFFFFFFF
  CTextBoxEx "CHN_Verh_Special_3" @(293,360) 120x25  font=Tiepolo_bold13x13aaFHk.res text=IDPR_CHN_KAPERBRIEF color=#FF131512 effect=2/1 #FFFFFFFF
  CTextBoxEx "CHN_Verh_Special_4" @(293,393) 120x25  font=Tiepolo_bold13x13aaFHk.res text=IDPR_CHN_KAPERBRIEF color=#FF131512 effect=2/1 #FFFFFFFF
  CTextBox "CHN_Txt_3" @(28,162) 105x20  font=Tiepolo_bold14x14aaFH.res text=IDPR_CHN_MILTAERKONVOIS color=#FF131512 align=R/C effect=2/1 #DCE6E6E6
  CTextBox "CHN_Mili_1" @(131,165) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Mili_2" @(202,165) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Mili_3" @(273,165) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBox "CHN_Mili_4" @(344,165) 60x15  font=Tiepolo_bold13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
```

### BILANZ_PAGE_800x600.screen — Logbook balance page

```
CScreen "BILANZ_PAGE" @(0,0) 440x450
  CStatic "S0000_Kopie11Auf_TAB_BG" @(0,0) 440x450 HIDDEN  anim=scripts\Pr2_Bg_Dialog.anim
  CTextBox "LOB_Bg_Shadow_01" @(163,75) 114x325  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#14231400
  CTextBox "LOB_Bg_Shadow_00" @(284,75) 114x325  font=-none- text=ID_NONE color=#FF000000 align=C/C bg=#14231400
  CTextBox "LOB_gesamt" @(40,378) 110x22  font=Tiepolo_black14x14aaFHk.res text=IDPR_GESAMT color=#FF131512 align=C/C effect=2/1 #FFEBEBEB
  CTextBoxEx "LOB_Row1_13" @(157,376) 125x24  font=Tiepolo_black13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 effect=2/1 #FFEBEBEB
  CTextBoxEx "LOB_Row2_13" @(279,376) 125x24  font=Tiepolo_black13x13aaFHk.res text=IDPR_TEST_01 color=#FF131512 effect=2/1 #FFEBEBEB
  CStatic "LOB_Icn_11" @(35,379) 21x21  anim=scripts\Pr2_Symbol_Plus.anim
  CStatic "LOB_Stuff_03" @(284,59) 114x19  anim=scripts\Pr2_Textfeld_dunkel_small.anim
  CStatic "LOB_Stuff_02" @(163,59) 114x19  anim=scripts\Pr2_Textfeld_dunkel_small.anim
  CStatic "LOB_Stuff_01" @(17,101) 406x11  anim=scripts\Pr2_Absatzlinie.anim
  CStatic "LOB_Stuff_00" @(17,369) 406x11  anim=scripts\Pr2_Absatzlinie.anim
  CTextBox "LOB_Cap_Row1" @(167,54) 103x26  font=Tiepolo_black14x14aaFHk.res text=IDPR_LOB_LETZTE_TAGE color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CTextBox "LOB_Cap_Row2" @(289,54) 103x26  font=Tiepolo_black14x14aaFHk.res text=IDPR_LOB_PROGNOSE color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CStatic "LOB_blaa_" @(210,86) 20x15  anim=scripts\Geld_Icon_01.anim
  CStatic "LOB_Cap_00" @(41,27) 358x24  anim=scripts\Pr2_CapBalken_du_x.anim
  CTextBox "LOB_Cap_01" @(136,4) 168x46  font=ELGRECO_34x34aaFHk.res text=IDPR_LOB_BILANZ color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CButton "LOB_kredite" @(142,406) 157x26  anims(nr/hl/pr/dis)=Pr2_BtnLong_nr.anim|Pr2_BtnLong_hl.anim|Pr2_BtnLong_pr.anim|Pr2_BtnLong_dis.anim text=IDPR_LOB_KREDITE font=Tiepolo_bold14x14aaFH.res
  CDrawable "LOB_Posider" @(21,111) 400x260
  CStatic "LOB_Gold" @(331,86) 20x15  anim=scripts\Geld_Icon_01.anim
  CStatic "LOB_Uhr" @(330,84) 18x18  anim=scripts\Pr2_Symbol_Uhr1.anim
```


### 4.1 What draws what in the Missions panel (target screenshot)

| Visual element | Control | File | Asset / style |
|---|---|---|---|
| Parchment page + ornate border | `TAB_BG` (CStatic 440×450) | TAB_CONTROL | `Pr2_Bg_Dialog.anim` (3-slice `Pr2_Bg_Dialog_se*.aim`). Pages may carry their own copy (`S0000_Kopie…_TAB_BG`, hidden in BILANZ_PAGE) |
| Vertical tab strip background | `TAB_Panel` (CStatic 46×125 @437,1) | TAB_CONTROL | `Pr2_TabCtrlBtnPanel_se.anim` (3-slice, code sets the height) |
| Close (X) button | `TAB_Close` (CIconButton 40×40) | TAB_CONTROL | `Pr2_IconBtn_nr/hl/pr/dis`; icon set by code |
| Tab icon buttons | clones `TAB_Templ_%02i` of `TAB_Templ` | TAB_CONTROL | `Pr2_IconBtn_nr/hl/dis`, selected = pressed `Pr2_IconBtn_ch`; icon = `Pr2_Icon_Missionen.anim`, `Pr2_Icon_Ausrufezeichen.anim`, … via `SetIcon` |
| Ornate title bar | `LON_CaptionBg_` (CStatic 358×24 @41,27) | NACHRICHTEN_LISTE | `Pr2_CapBalken_du_x.anim` |
| Title "Missions" | `LON_Caption` (CTextBox) | NACHRICHTEN_LISTE | `ELGRECO_34x34aaFHk.res`, white, shadow 2/1 black, centred |
| Hand / thumb buttons right of the title | `LON_BtnMissonsOpen`, `LON_BtnMissonsDone` (CIconButton 27×26) | NACHRICHTEN_LISTE | `Pr2_BtnLong_mini_*`, icons by code |
| Scroll area / scrollbar | `LON_ScrollDrawable` (CDrawable<CScrollObject>), `LON_Scrollbar` (CSlider) | NACHRICHTEN_LISTE | `Pr2_Slider_*`, `Pr2_BtnDragStep_*` |
| "No entries" text | `LON_NoEntry_1` (CTextBoxEx) | NACHRICHTEN_LISTE | |
| **Card** (one per mission, 377×130) | clone of the `NACHRICHTEN_EINTRAG` root | NACHRICHTEN_EINTRAG | |
| Section header bar ("Ship hunt") | `LON_TmplHeadBg` (CStatic 370×20 @3,14) | NACHRICHTEN_EINTRAG | `Pr2_CapBalken_eu_x.anim` |
| Header text | `LON_TmplCaption` (CTextBox 295×28) | NACHRICHTEN_EINTRAG | `Tiepolo_bold18x18aaFHk.res`, white, outline 1 px `#AF4B4B4B`, centred |
| Trash button left of the header | `LON_BtnRemove` (CIconButton 27×26 @13,10) | NACHRICHTEN_EINTRAG | `Pr2_BtnLong_mini_*`, icon `Pr2_Icon_Muelltonne` by code |
| Label plates (place, date) | `LON_BalkenRechts` @13,46 and `LON_BalkenLinks` @192,46 (CStatic 170×19) | NACHRICHTEN_EINTRAG | `Pr2_CapBalken_nu_s.anim` (note: "Rechts" is the left one) |
| Plate texts | `LON_TmplLoka` (place), `LON_TmplDate` (date) (CTextBox 170×21/22) | NACHRICHTEN_EINTRAG | `Tiepolo_black14x14aaFHk.res`, white, outline 1 px |
| Body text incl. coloured runs | `LON_TmplText` (CTextBoxEx 348×52 @14,76) | NACHRICHTEN_EINTRAG | `Tiepolo_bold14x14aaFH.res`, `#FF131512`, glow 2/1 `#FFEBEBEB`; green/blue runs and the coin icon come from the string's rich-text markup |
| Card highlight frame | `LON_TmplRahmen` (hidden CTextBox, 1 px borders `#C8131512`) | NACHRICHTEN_EINTRAG | |

The Chronicle variant (`CHRONIK_EINTRAG`) adds a 90×90 picture (`CHE_ImageTmpl`) and one plate
(`CHE_TmplCapBg` + `CHE_TmplCaption`); NATION_PAGE / BILANZ_PAGE show the "table" style
(`Pr2_DoppelRahmen.anim` frames, `Pr2_Tabellenlinie_horizontal.anim` rules, translucent
`#46FFFFFF` CTextBox rows, `Pr2_Absatzlinie.anim` separators, `Pr2_Textfeld_dunkel_small.anim`
column heads, `Geld_Icon_01.anim` coin icon, `Pr2_BtnLong_*` long button).

`INTERFACE_TAB_WINDOW` (450×481, `Pr2_Dialog_BG.anim` = `Pr2_Pergament_oben/mitte/unten`)
is the *bottom-docked* window above the interface bar (ship/convoy info), placed at
`TMPL_InterfaceTabWindow_1024`, with the side buttons of `INTERFACE_BUTTON_PANEL`
(`IBP_Btn`, `IBP_Close`, `IBP_UserBtn`). It is not the Missions panel.

---

## 5. Recipe: author `FNN_NATION_PANEL` and `FNN_CARD`

### 5.1 Generator (tested: both files re-parse; dumps below)

Put this in e.g. `tools/make_fnn_screens.py` (output into
`data/scripts/`):

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "found-new-nation", "tools"))
from screen_dump import Screen, dump
S = os.path.join(ROOT, r"reverse-engineering\_workdir\arcd\scripts")
OUT = os.path.join(ROOT, r"data\scripts")
os.makedirs(OUT, exist_ok=True)

# panel = TAB_CONTROL frame + close + 6 tabs + NACHRICHTEN_LISTE caption/content
panel = Screen.load(os.path.join(S, "TAB_CONTROL_800x600.screen"))
lst = Screen.load(os.path.join(S, "NACHRICHTEN_LISTE_800x600.screen"))
root = panel.root.rename("FNN_NATION_PANEL")
bg, strip, tmpl, close = (root.find(n) for n in ("TAB_BG", "TAB_Panel", "TAB_Templ", "TAB_Close"))
for n in (bg, strip, tmpl, close):
    n.rename("FNP_" + n.name[4:])
STEP = 37                                   # vanilla spacing (TAB_Templ y=7, TAB_Close y=44)
close.set("y", 7)                           # X on top, as in the Missions panel
tabs = [tmpl.clone("FNP_Tab_%02d" % i).set("y", 7 + STEP * (i + 1)) for i in range(6)]
strip.set("h", 7 + STEP * 7 + 12)           # 3-slice anim stretches vertically
content = []
for name in ("LON_CaptionBg_", "LON_Caption", "LON_ScrollDrawable", "LON_Scrollbar", "LON_NoEntry_1"):
    n = lst.find(name).clone()
    n.rename_children("LON_", "FNP_")
    content.append(n)
root.children = [bg, strip] + content + [close] + tabs     # [H] later children draw on top
root.find("FNP_Caption").set_text_id("text", "IDPR_FNN_TITLE")     # sets id + hash
root.find("FNP_NoEntry_1").set_text_id("text", "IDPR_FNN_EMPTY")
panel.save(os.path.join(OUT, "FNN_NATION_PANEL_800x600.screen"))

# card = NACHRICHTEN_EINTRAG (header bar + 2 plates + body), without the trash button
card = Screen.load(os.path.join(S, "NACHRICHTEN_EINTRAG_800x600.screen"))
card.root.rename("FNN_CARD").rename_children("LON_", "FNC_")
card.root.remove("FNC_BtnRemove")
card.find("FNC_TmplCaption").set_text_id("text", "IDPR_FNN_CARD_HEAD")
card.save(os.path.join(OUT, "FNN_CARD_800x600.screen"))
```

Result (`screen_dump.py dump`):

```
CScreen "FNN_NATION_PANEL" @(0,0) 510x450
  CStatic "FNP_BG" @(0,0) 440x450  anim=scripts\Pr2_Bg_Dialog.anim
  CStatic "FNP_Panel" @(437,1) 46x278  anim=scripts\Pr2_TabCtrlBtnPanel_se.anim
  CStatic "FNP_CaptionBg_" @(41,27) 358x24  anim=scripts\Pr2_CapBalken_du_x.anim
  CTextBox "FNP_Caption" @(95,7) 251x41  font=ELGRECO_34x34aaFHk.res text=IDPR_FNN_TITLE color=#FFFFFFFF align=C/C effect=2/1 #FF000000
  CDrawable<CScrollObject> "FNP_ScrollDrawable" @(32,63) 377x359
  CSlider "FNP_Scrollbar" @(394,62) 27x360
    [bg] CStatic "FNP_Scrollbar_Background" @(4,12) 20x336  anim=scripts\Pr2_Slider_Bg.anim
    [inc] CButton "FNP_Scrollbar_Button +" @(1,338) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_unten_nr.anim|Pr2_BtnDragStep_unten_hl.anim|Pr2_BtnDragStep_unten_pr.anim|Pr2_BtnDragStep_unten_dis.anim
    [dec] CButton "FNP_Scrollbar_Button -" @(1,0) 26x22  anims(nr/hl/pr/dis)=Pr2_BtnDragStep_oben_nr.anim|Pr2_BtnDragStep_oben_hl.anim|Pr2_BtnDragStep_oben_pr.anim|Pr2_BtnDragStep_oben_dis.anim
    [drag] CButton "FNP_Scrollbar_Button Drag" @(0,48) 26x17  anims(nr/hl/pr/dis)=Pr2_Slider_DragBtn_nr.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_hl.anim|Pr2_Slider_DragBtn_nr.anim
  CTextBoxEx "FNP_NoEntry_1" @(44,150) 346x50  font=Tiepolo_bold14x14aaFH.res text=IDPR_FNN_EMPTY color=#FF131512 effect=2/1 #FFEBEBEB
  CButton<CIconButton> "FNP_Close" @(439,7) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_pr.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_00" @(439,44) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_01" @(439,81) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_02" @(439,118) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_03" @(439,155) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_04" @(439,192) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
  CButton<CIconButton> "FNP_Tab_05" @(439,229) 40x40  anims(nr/hl/pr/dis)=Pr2_IconBtn_nr.anim|Pr2_IconBtn_hl.anim|Pr2_IconBtn_ch.anim|Pr2_IconBtn_dis.anim font=Tiepolo_black13x13aaFHk.res
```

```
CScreen "FNN_CARD" @(0,0) 377x130
  CTextBox "FNC_TmplRahmen" @(4,5) 368x122 HIDDEN  font=-none- text=ID_NONE color=#FF000000 align=C/C
  CStatic "FNC_BalkenLinks" @(192,46) 170x19  anim=scripts\Pr2_CapBalken_nu_s.anim
  CStatic "FNC_TmplHeadBg" @(3,14) 370x20  anim=scripts\Pr2_CapBalken_eu_x.anim
  CStatic "FNC_BalkenRechts" @(13,46) 170x19  anim=scripts\Pr2_CapBalken_nu_s.anim
  CTextBox "FNC_TmplDate" @(191,43) 170x22  font=Tiepolo_black14x14aaFHk.res text=IDPR_TEST_08 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBoxEx "FNC_TmplText" @(14,76) 348x52  font=Tiepolo_bold14x14aaFH.res text=IDPR_TEST_05 color=#FF131512 effect=2/1 #FFEBEBEB
  CTextBox "FNC_TmplLoka" @(11,43) 170x21  font=Tiepolo_black14x14aaFHk.res text=IDPR_TEST_07 color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
  CTextBox "FNC_TmplCaption" @(41,7) 295x28  font=Tiepolo_bold18x18aaFHk.res text=IDPR_FNN_CARD_HEAD color=#FFFFFFFF align=C/C effect=1/1 #AF4B4B4B
```

Variations: drop `FNP_ScrollDrawable`/`FNP_Scrollbar` and place N card slots directly when no
scrolling is needed (a `CScrollObject` needs PR2's scroll code to be driven); add in-panel
buttons by cloning `LOB_kredite` (BILANZ_PAGE, `Pr2_BtnLong_*`, 157×26) and setting
`text_nr/text_hl/text_pr/text_dis` with `set_text_id`; add table rows by cloning
NATION_PAGE's `CHN_Txt1` (label, right-aligned) / `CHN_Pop_1` (value) / `CHN_Noname_00`
(frame). Colour a whole value with `set("color", 0xFF2E7D32)` (green) or `0xFF1F3FBF` (blue).
Hand-editing alternative: `screen_dump.py json X.screen x.json` → edit
`dwb`/`props` values → `screen_dump.py build x.json X.screen` (changed string ids get their
hash recomputed; untouched bytes stay identical).

### 5.2 Where the files go and how they are loaded

1. Write them to `data/scripts/FNN_NATION_PANEL_800x600.screen` and
   `…/FNN_CARD_800x600.screen`. The private test installer copies everything under `data/`
   (`data_files()`, `rglob`) to the same relative path in the game folder, so they land in
   `<game>\scripts\`. Loose files win over the archives (§2.2), and new names need no archive
   change. (All referenced `.anim`/`.res` files are vanilla.)
2. Load from `PR2Nation.dll` on the main thread (A2dLib exports, already imported by PR2):
   `CDrawableFactory* f = *g_pDrawableFab;`
   `root = f->CreateType(parent, "FNN_NATION_PANEL_800x600.screen", NULL, NULL)` (thiscall,
   export `?CreateType@CDrawableFactory@NA2dLib@@QAEPAVCDrawable@2@PAVCObject@2@PBD11@Z`,
   PR2 import slot `[0x67F474]`; PR2's own wrapper is `0x4CEC10`).
   Load the card once as a hidden child the same way (as PR2 does for `CHRONIK_EINTRAG`,
   `0x4AE578..0x4AE5A8`) and clone it per entry with `CreateTypeCopy(cls, newName, parent,
   template)` (`0x100407A0`, PR2 import `[0x67F020]`), then `SetPos`/`Show`.
3. Find controls with `CWindowManager::FindDrawable(name, 0)` (`[0x67F394]`, used by
   `0x4D2A90`); position the root with `SetAbsPos` (`[0x67F330]`) at the
   `TMPL_Dialoge_1024` rectangle (or (263,73)); there is no darkened modal background unless
   code adds one, so the map stays live.
4. Tab icons: either call PR2's `CIconButton::SetIcon(0, iconIndex, …)` `0x4C4C50` on each
   `FNP_Tab_xx` (exactly what AddTab does at `0x4DD83D`), or — no code — add a `CStatic` per tab
   with `anim = scripts\Pr2_Icon_Nation.anim` etc. centred on the button and `flags = 2`
   (visible, not enabled) so it does not take the click [H].
5. Text: string ids in the file resolve at load time through the string manager, so the
   `FNN` table must be registered **before** the screen is created; dynamic text is then set
   by code (as PR2 does for every `ID_NONE`/`IDPR_TEST_*` control).

---

## 6. `CIconButton` icon table [S]

`SetIcon` index → `scripts\Pr2_Icon_<name>.anim`; names starting with `MiniIcon_`, `Symbol_`, `Uhr`, `AH_` or `Anim` map to `scripts\Pr2_<name>.anim`;
std::strings at `0x6E77F0 + 0x14·index`, built by the static initializer `0x6773DC..0x679879`
(each `push <name>` … `mov ecx, 0x6E77F0+0x14·i`):

0 Warenliste, 1 Schiffsliste, 2 Mannschaft, 3 Steuerrad, 4 Angriffsmodus, 5 Doppelpfeil, 6 Logbuch, 7 Muenze, 8 Back, 9 Baumenu, 10 Optionen, 11 Anker, 12 MiniIcon_Hammer, 13 MiniIcon_Kopf, 14 Uhr__31, 15 Quit, 16 Lagerhaus, 17 Kran, 18 Tausch, 19 Symbol_Lagerhaus_AH, 20 Symbol_Produktion, 21 Symbol_Gesperrt, 22 Symbol_Stadt_AH, 23 Symbol_Hammer, 24 AH_Btn_IconSep, 25 Quit_Small, 26 Hoch, 27 Runter, 28 RechtsLinks, 29 Pfeil_Rechts, 30 Pfeil_Links, 31 Auge, 32 Ausrufezeichen, 33 Autohandel, 34 Bier, 35 Bilanz, 36 Knochi, 37 Gold, 38 Getreide, 39 Hand, 40 Hand2, 41 Einkauf, 42 Verkauf, 43 InfoFass, 44 Nation, 45 Missionen, 46 Muelltonne, 47 InfoHaus, 48 InfoKopf, 49 Order, 50-52 Person_1..3, 53 Schatzkarte, 54 Symbol_Uhr, 55 Abc, 56 Schiffe, 57 Gebaeude, 58 Betriebe, 59 Sondergebaeude, 60 Captain, 61 Baumeister, 62 Feder, 63 Streukugeln, 64 Kettenkugeln, 65 Kanonenkugel, 66 Autohandel, 67 Rueckzug, 68 Schwertkaempfer, 69 Musketen, 70 Enterhaken, 71 Wuerfel, 72 Kapitaen, 73 Piraten, 74 Haende, 75 Cruz, 76 Beten, 77 Goldsack, 78 Frau, 79 Schatztruhe, 80 Schild, 81 Krone, 82 Pfeil_geschwungen, 83 NavRad, 84 Konvoiliste, 85 Globus, 86/87 MM_Pfeil_right/left, 88 Laden, 89 Speichern, 90 Staedte_Liste, 91 AnimPiratenflagge_0014, 92 Entermesser, 93/94 Glocke_active/inactive, 95 verlassen

Find controls by asset/name across all screens:
`python tools/screen_dump.py grep "Pr2_Icon_Missionen|CapBalken_eu"`.
