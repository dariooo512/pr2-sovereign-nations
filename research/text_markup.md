# In-text markup of the A2dLib text renderer (CTextBoxEx)

Static RE of PR2.exe 1.1.2.3 + `A2dLib-2.20A.dll` (ImageBase 0x10000000). [S] = read in code/data,
[H] = inferred. Real strings come from the two tables decoded with `tools/check_ui_static.py`
(UI `global.res`, German here; mission table = PR2.exe `BINARY #167`, English).

## Answer in one paragraph

Markup is interpreted only by **`NA2dLib::CTextBoxEx`** (the multi-line rich text box). The parser
runs in `CTextBoxEx::FuncCreateSubDrawables` (export, thunk `0x10005817` -> `0x1007CFC0`). It calls
the Western layouter `0x1007B6B0`, or `0x100794B0` when the static `CTextBoxEx::IsAsian` byte
`0x10149648` is set. Tags have the form `<x>` or `<x:arg>`. Dispatch is on the first one or two
characters of the tag body, case-insensitive (`0x1007BADC..0x1007C76E`). Tags set colour (`<o:0xAARRGGBB>`,
`<o>` resets to the control default), inline graphics (`<g:INTEXT_GOLD_800x600.screen>` plus the
flow mode `<gs:TEXTFLUSS_*>`), line breaks (`<n>`, `<n:px>`), alignment (`<l> <r> <c> <b>`), font
(`<f:fonts/....res>`), tabs (`<ts:x> <t> <tr:x|-1>`), shadow (`<wt:> <ws:> <wc:>`), line height
(`<z:px>`), literal angle brackets (`<al> <ar>`) and a hyphen break (`<->`). Unknown tags are
dropped silently. The string manager, Lua and the mission resolver `0x436980` do **not** touch `<...>`.
They pass it through unchanged, so a string from the mod's `FNN` table that is rewritten with
`Nation_SetText` gets the same markup as soon as a CTextBoxEx displays it. The working `<n>` line
breaks in the current FNN popups (`AGD_TextBox` is a CTextBoxEx) already show this. Plain
**`CTextBox`** controls do *not* parse markup: the Missions header bar, the plates and the
captions are CTextBoxes and take plain text. The Missions colours were measured pixel-exact from
`tasks/img/target-missions-panel.png`:
- green `0xFF008000`;
- blue `0xFF1E1EFF`;
- body `0xFF131512`;
- header `0xFFFFFFFF`.

## 1. Parser mechanics [S]

- Flow (`0x1007B8B5..0x1007BAA4`): find `<` (`0x100F8138`), then `>` (`0x100F8134`). The text in
  between is a run, the body is the tag, and `arg` is everything after the first `:` (`0x100F8130`).
  A `<` without a closing `>` leaves the rest as literal text. Several tags are dispatched on `body[0]`
  and `body[1]` (`gs`, `ts`, `tr`, `wt`, `ws`, `wc`, `al`, `ar`).
- State is a **stack-local parser object** that `FuncCreateSubDrawables` builds per layout
  (`0x1007CFED`). Every SetText therefore starts from the control's defaults:
  - colour `ctrl+0xD8`;
  - shadow colour `+0xDC`;
  - alignment `+0xE0`;
  - shadow type `+0x108`;
  - shadow width `+0x10C`;
  - font `+0xB0`;
  - graphic mode `NORMAL`;
  - no tab stops;
  - line height = font height × 1.125.

  All tag state is **sticky** until changed, including across `<n>`.
- Numbers are parsed with `swscanf(L"%i")`, so decimal and `0x` hex both work. A leading `0` means
  octal, so `<n:010>` = 8.
- Colours are **ARGB**. Proof: `0xFF1E1EFF` renders as RGB (30,30,255) in the screenshot.
- A `<g:>` graphic that fails to load is skipped without an error (`0x1007C2C4`). A graphic wider
  than the rest of the line wraps (`0x1007C306`).

## 2. Complete tag list

| Tag | Effect | Code [S] | Real example (table: id) |
|---|---|---|---|
| `<n>` / `<N>` | line break | `0x1007C6A4` | mission: `ID_MISSION_ACHIEVED` = `<n><o:0xff008000>Mission accomplished. <o:0xff000000>` |
| `<n:K>` | line break, then y += K − fontHeight (advance ≈ K px; `<n:0>` / `<n:00>` = stay on the same row) | `0x1007C73F..0x1007C76B` | UI `3AB817F2`: `<l>Konvois geplündert<n:00><r>%1<n>` (label left, value right on one row); mission `IDT_POLITICAL_MAP`: `<c>%1<n><n:5>%2 (%3)` |
| `<l>` `<r>` `<c>` `<b>` | align left=0 / right=1 / centre=2 / justify=3 (`+0x1C`); applies to the line | `0x1007C68C/698/680/674` | UI `IDPR_LOP_NO_PRODUCTION`: `<c>Ihr besitzt noch keine eigene Produktion.` · `2CF7D85E`: `...<n><n><r>Der Gouverneur von %6` |
| `<o:0xAARRGGBB>` | text colour (`+0x20`) | `0x1007C08A` | UI `ID_FORMAT_INTEXT_GOLD`: `<o:0xff1e1eff>%1<o:0xff000000> <g:INTEXT_GOLD_800x600.screen>` |
| `<o>` | colour back to the control default (`ctrl+0xD8`) | `0x1007C0C2` | mission `IDPR_PLAYER_EIGENSCHAFT_1_DESC`: `inflict <o:0xFFF2FAAD>5%<o> more damage` |
| `<g:FILE.screen>` | inline graphic: any `.screen` loaded through the resource manager (`0x10142078`). Both `INTEXT_X_800x600.screen` and `scripts/INTEXT_X_800x600.screen` appear in vanilla | `0x1007C1AE..0x1007C3D2` | mission `ID_MISSION_OKGOLD`: ` You have received <o:0xff1e1eff>%1<o:0xff000000><gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen>.` |
| `<gs:MODE>` | graphic flow, case-insensitive: `TEXTFLUSS_NORMAL`=1 (default), `_MITTEXT`=2, `_KEINEHOEHE`=3 (icon adds no line height: use for inline icons), `_HINTERGRUND`=4 (+ `,x,y` offset [H]: background, takes no space), `_BASELINE`=5 (sits on the baseline: bullets) | `0x1007C3D7..0x1007C64B` | mission `IDM_SCENARIO_001_LETTER_TEXT`: `<ts:20>...<n><n><gs:TEXTFLUSS_BASELINE><g:INTEXT_AUSRUF_800x600.screen>-<t>There are five...` |
| `<f:fonts/NAME.res>` | font (also `fonts\\NAME.res`); resets line height unless `<z:>` is set | `0x1007C0CD` | mission `IDPR_AKTUELLE_MISSION`: `<f:fonts/Tiepolo_black14x14aaFHk.res>Current mission<n><f:fonts/Tiepolo_bold14x14aaFH.res>` |
| `<ts:X>` | add a tab stop at X px (0 ≤ X ≤ box width, else ignored) | `0x1007BF3D` → `0x10078140` | UI `D84C767B`: `<wt:SHADOW_BR><ws:1><ts:140><ts:270><o:0xff502814><l><t>Letzte Woche<t>Prognose<n><o:0xff000000>Wareneinkauf<t>%1<t>%2<n>...` |
| `<t>` | jump to the next tab stop; past the last stop → next line at the first stop | `0x1007BE01..0x1007BF05` | same |
| `<tr:X>` / `<tr:-1>` | remove the stop at X / all stops | `0x1007BF0A` → `0x10077C30` | UI `DA41F6AE`: `...<n><n><n><tr:-1><ts:140><ts:270><ts:340>...` |
| `<wt:T>` | shadow type, case-sensitive: `SHADOW_NONE`=0, `SHADOW_OUTLINE`=1, `SHADOW_BR`=2, `SHADOW_TL`=3; `<wt>` = default | `0x1007BD48` | UI `CBC4ADD5`: `<o:0xff502814><wt:SHADOW_BR><ws:1><wc:0x80ffffff>Seeman %1 %2 <o:0xff000000><n>bietet...` |
| `<ws:N>` | shadow width (vanilla uses `<ws:2>` for "bold" headings) | `0x1007BCF9` | UI `DFCFD0CC`: `<o:0xff502814><ws:2>Gebäude (Gesamt)<o:0xff000000><ws:1><n>` |
| `<wc:0xAARRGGBB>` | shadow colour | `0x1007BCB6` | `CBC4ADD5` above |
| `<z:N>` / `<z>` | line height N px / back to font × 1.125 | `0x1007C03A` | (unused in vanilla) |
| `<al>` / `<ar>` | literal `<` / `>` | `0x1007BF90` / `0x1007BFE5` | (unused) |
| `<->` | appends `-` and breaks the line | `0x1007BB75` | (unused) |
| anything else | dropped, including its text inside `<>` | fallthrough `0x1007C76E` | mission `IDM_TRADERHUNT_FEEDB_02_01`: `...@D$EndDate$.<.<n><n>...`. The typo eats a `<n>` |

**Not markup.** `@x$Field$` (mission resolver `0x436980`) and `%1` / `%i` (C++ format) are
expanded **before** the text reaches the box. The resolver copies every non-`@` character
through unchanged (`0x436B39..0x436B4E`). `@g$F$` itself emits markup: it formats with
`ID_FORMAT_INTEXT_GOLD` (`0x409750`), and `@a` uses `IDPR_FORMAT_FASS_COL` (`0x409770`).

## 3. Colours

| Use | ARGB | Source |
|---|---|---|
| Good/success (green "Mission accomplished.") | `0xFF008000` | `ID_MISSION_ACHIEVED`; screenshot pixel (0,128,0) |
| Failure (red) | `0xFFC00000` | `ID_MISSION_FAILED` = `<n><o:0xffC00000>Mission not accomplished. <o:0xff000000>` |
| Amounts (blue, before the gold icon) | `0xFF1E1EFF` | `ID_MISSION_OKGOLD`, UI `ID_FORMAT_INTEXT_GOLD`; screenshot (30,30,255) |
| Amounts, dark blue variant | `0xFF000096` | mission-table `ID_FORMAT_INTEXT_GOLD` / `IDPR_FORMAT_FASS_COL` (`@g`, `@a`) |
| Body default (CHE_TmplText, popups) | `0xFF131512` | `.screen` props; screenshot (19,21,18) |
| Table/section headings (brown) | `0xFF502814` | UI `D84C767B`, `DFCFD0CC` |
| Town name blue | `0xFF000AC8` | UI `C7F5A104` |
| Highlight on dark backgrounds | `0xFFF2FAAD`, `0xFFFFE6A0`, `0xFFEBF0A0` | mission `IDPR_PLAYER_*_DESC`, `DBD1233E` |
| Link | `0xFF000078` | `IDPR_FORMAT_MSGBOX_LINK` = `<f:fonts/%1><o:0xFF000078>%2<o><f:fonts/%3>` |

## 4. Missions page controls (`CHRONIK_ENTRIES` / `CHRONIK_EINTRAG_800x600.screen`) [S]

Values come from the SH_DWB property records. The layout was mapped from
`CTextBoxEx::LoadProperties` (`0x100773D0`: hash, colour `+0xD8`, shadow colour `+0xDC`, shadow type
`+0x108`, shadow width `+0x10C`, align `+0xE0`) and `CTextBox::LoadProperties` v3 (`0x100746AD`).
CTextBox field meaning comes from `CTextBox::OnDraw` (`0x10075480`: shadow type `+0xB0`, shadow width
`+0xB4`, shadow colour `+0xCC`, align `+0x10C`); text colour `+0xC8` is [H].

| Control | Class | Font | Text colour | Shadow | Align | Art |
|---|---|---|---|---|---|---|
| `CHE_Caption` ("Missions" title) | CTextBox | `ELGRECO_34x34aaFHk` | `0xFFFFFFFF` | BR, 1, `0xFF000000` | centre | `CHE_CaptionBg` |
| `CHE_TmplHead` ("Ship hunt" bar text) | CTextBox | `Tiepolo_bold18x18aaFHk` | `0xFFFFFFFF` | OUTLINE, 1, `0xAF4B4B4B` | centre | `CHE_TmplHeadBg` 370×20 = `scripts\Pr2_CapBalken_eu_x.anim` |
| `CHE_TmplCaption` (plates: place, date) | CTextBox | `Tiepolo_black14x14aaFHk` | `0xFFFFFFFF` | OUTLINE, 1, `0xAF4B4B4B` | centre | `CHE_TmplCapBg` 164×19 = `scripts\Pr2_CapBalken_nu_s.anim` |
| `CHE_TmplText` (card body) | **CTextBoxEx** | `Tiepolo_bold14x14aaFH` | `0xFF131512` | BR, 1, `0xFFEBEBEB` | left | 255×77 at (120,76); grows to content |
| `CHE_NoEntry_1` | CTextBoxEx | `Tiepolo_bold13x13aaFHk` | `0xFF131512` | BR, 1, `0xFFEBEBEB` | centre | |
| popup body `AGD_TextBox` / `AD2_TextBox` | CTextBoxEx | `Tiepolo_bold14x14aaFH` | `0xFF131512` | BR, 1, `0xFFEBEBEB` | centre | |

Card size is 377×160, and the scroll area is `CHE_ScrollDrawable` 377×363. The card builder
(`0x4AEBF5..0x4AEC84`) does three things:
1. It assigns the entry text to `CTextBoxEx+0xA4` (a wstring, `operator=`).
2. It calls `FuncCreateSubDrawables` (exe IAT `0x67F1E0`), which runs the markup.
3. It sizes the box from `+0x110` (the laid-out height [H]).

A mod panel can do the same. The finished entry text is the mission body plus `ID_MISSION_ACHIEVED`
plus `ID_MISSION_OKGOLD`, appended by `0x430A79..0x430B30`: GetText, concat `0x41F700`, SetText on
the log object.

Lookup order (relevant for overrides) [H]: `CStringManager` returns the first table in its
`std::map` (by name, `0x1002C530`) that holds the id. `FNN` sorts before `MISSION_NPC_GOODS_INFO`,
so FNN ids are found first. Keep FNN ids unique (`IDM_FNN_*`).

## 5. Inline icons that exist (`arcd/scripts/INTEXT_*_800x600.screen`, w×h)

- Inline (≈ text height, use with `<gs:TEXTFLUSS_KEINEHOEHE>`):
  - currency and goods: `GOLD` 20×14, `GOLD_X3` 21×15, `FASS` 14×14, `WARE_00..18` 29×29;
  - flags: `ENGLAND` / `FRANKREICH` / `HOLLAND` / `SPANIEN` 25×15;
  - people and military: `SOLDAT` 20×16, `KANONE` 26×16, `SCHIFF` 20×13, `MANN` 22×16,
    `EINWOHNER` 26×23, `KAPITAEN_RANG_0..4` 14×14, `KAPERBRIEF` 26×26;
  - buildings: `GEBAEUDE` 28×15, `SPIELERGEBAEUDE` 19×18;
  - signs and arrows: `PLUS` / `MINUS` 19×10, `PFEIL_HOCH` / `PFEIL_RUNTER` 15×16, `AUSRUF` 12×26 (bullet,
    `TEXTFLUSS_BASELINE`), `HERZ` 19×17, `HAMMER` 16×20, `KNOTEN` 19×13, `SCHLEICHSYMBOL` 23×17;
  - production: `PRODUCTION` 47×25, `NO_PRODUCTION` 64×25, `SIEDLER_ZUNAHME` 36×28, `SIEDLER_ABNAHME` 46×28.
- Pictures (275×140, own line): `MISSION`, `SCHATZKISTE`, `FLASCHENPOST`, `TREIBGUT`, `SCHIFFBRUECHIGER`,
  `BONUSSCHIFF`; `SCHATZKARTE` 360×125; `ARTEFAKT_01` 135×135.
- Ready-made ids: the 26 names `INTEXT_FASS`, `INTEXT_GOLD`, ... `INTEXT_NATION_ENGLAND`, ...
  (exe table `0x6E0748`, loaded at `0x406700`) resolve to the `<g:...>` markup. For example,
  `INTEXT_NATION_SPANIEN` = `<g:INTEXT_SPANIEN_800x600.screen>`.
- Not present: `INTEXT_BARREL` (referenced by UI `ID_FORMAT_INTEXT_BARREL`, skipped silently). Any
  other `.screen` also works, e.g. `<c><g:scripts/Sub_Betragseingabe_800x600.screen>` (an amount input,
  UI `D6CE4B4C`).
- No nation-5 flag icon exists. Drawing one needs a new `.screen` and art, or a different icon [H].

## 6. How the mod writes a card body

Put the markup straight into the FNN string (`k_defaults` or `Nation_SetText`). Use ASCII only;
strings.c converts it with `CP_UTF8`. Rules:
- Keep `@` and `$` out unless you want the mission resolver to expand them.
- Reset with `<o>`, not `<o:0xff000000>`, so the body keeps its `0xFF131512` default.
- Bars and plates are CTextBoxes: give them plain text.

```text
Green status + blue amount + gold icon (exactly the Missions look):
Attack trading convoys of England and sink 4 ships by 17. February 1603.<n><o:0xff008000>Mission accomplished.<o>  You have received <o:0xff1e1eff>280,000<o><gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen>.

Red failure:
<n><o:0xffC00000>Mission not accomplished.<o>

Two-column money table (label left, value right, same row):
<l>Treasury<n:0><r><o:0xff1e1eff>10,008<o> <gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen><n><l>Last month's taxes<n:0><r><o:0xff008000>+7,008<o><n><l>Upkeep<n:0><r><o:0xffC00000>-2,000<o>

Same with tab stops (box ~255 px wide):
<ts:150><l>Balance<t><o:0xff1e1eff>10,008<o> <gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_GOLD_800x600.screen><n>Expected taxes<t><o:0xff1e1eff>7,087<o><n>Next accounts<t>24 days

Brown section heading inside a body ("bold" = wider shadow), then normal text:
<wt:SHADOW_BR><o:0xff502814><ws:2>Relations<o><ws:1><n>England<t>at war<n>

Centred bold title line inside a CTextBoxEx (imitates the bar text):
<c><f:fonts/Tiepolo_black14x14aaFHk.res>Treasury<n><f:fonts/Tiepolo_bold14x14aaFH.res><l>body text...

Flag + plus/minus icons:
<gs:TEXTFLUSS_KEINEHOEHE><g:INTEXT_SPANIEN_800x600.screen> Spain: relations <g:INTEXT_PLUS_800x600.screen>
```

## 7. Evidence index

| Fact | Address |
|---|---|
| Layout entry `FuncCreateSubDrawables` (IsAsian switch `0x1007D01C`) | A2dLib `0x10005817` → `0x1007CFC0` |
| Western tag parser; tag split; dispatch | `0x1007B6B0`; `0x1007B983..0x1007BA7E`; `0x1007BADC` |
| Asian copy of the parser | `0x100794B0` |
| `TEXTFLUSS_*`, `SHADOW_*` literals | `0x100F827C..0x100F83BC` (UTF-16) |
| No `<` parsing in CTextBox (`0x10073000..0x10076F00`: no `cmp ...,0x3c`, no xref to `L"<"`) | [S] negative search |
| CTextBoxEx property load (record size `0x254`) | `0x100773D0` |
| Card text → `+0xA4` + `FuncCreateSubDrawables` | PR2.exe `0x4AEC44..0x4AEC56` |
| Mission status append (`ID_MISSION_ACHIEVED/FAILED`) | `0x430A79`, `0x430AB6` |
| `@g` → `ID_FORMAT_INTEXT_GOLD`; resolver passes non-`@` through | `0x409750`; `0x436B39` |
| INTEXT id table / loader | `0x6E0748` / `0x406700` |
| String-table lookup loop | A2dLib `0x1002C530..0x1002C551` |
