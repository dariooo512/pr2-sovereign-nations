# Flags and other nation art: how PR2 draws them, and how to give the 5th nation its own

This is static reverse engineering only: the game was not launched. Date: 2026-10-12.
Exe = `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). DLLs are in `%USERPROFILE%\PR2-nation-env`.
**[S]** = VERIFIED-STATIC (bytes or addresses read). **[H]** = HYPOTHESIS.
Decoded art is in `art/game_flags/*.png`. Atlas crops are named `<part>__<TexPageN>.png`.
This builds on `userflag.md`, which covers table `0x6E12EC`, `-userflag-`, `Run\0.bmp` and P02.

## TL;DR
* PR2 already has a player **emblem pipeline**. The company logo `%APPDATA%\Ascaron Entertainment\Port Royale 2\Run\0.bmp`
  is a 96x64 24-bit BMP. For **nation 5** (and bit-22 player towns), vanilla already shows it on:
  * waving UI flags (CFlag);
  * convoy lists, the trade window and the interface bar;
  * the sea-map **town marker** and ship icon;
  * the **3D sails and mast flags** of every nation-5 convoy (WalExtPR2 composites it into `Run\Player0.aim`).
  It is also **saved inside the savegame** and restored on load. [S, details in §2]
* **Superseded (2026-10-18, section 8):** the nation's flag is now `Run\7.bmp`; `Run\0.bmp` stays the player's logo.
* **Recommended design:** "nation flag = `Run\0.bmp`".
  * The player picks one of 100 flags. The DLL (or the vanilla Options logo picker) writes it as `Run\0.bmp`.
  * Add one 4-byte runtime data write: the DLL sets `*(char**)0x6E1300` (nation-icon table slot 5) to an absolute path to
    that BMP. This turns the three town UI sites that P02 currently leaves blank into real flags.
  * Optional small patches cover the town-info mini flags, the political map and the INTEXT icon (§5).
* **Not cheap:** the **town-view flagpoles**. They are `Flagge_<N>.aim` frames baked into the per-nation building `.let`
  files, preloaded at boot and chosen by the display (host) nation (§5.4).
* **Art to produce per flag:** one **96x64 24-bit BMP**, no alpha. That is the same format as `DefaultLogos/Logo_xx.bmp`.
  Optional: a 128x64 `.aim` (TILEDIM+BMPRES) if a loose `nation05.aim` is preferred.

---

## 1. Inventory [S unless marked]

There are two storage kinds.
* **Standalone `.aim`.**
* **Atlas parts** `imagesSD\X.aim`. These are rectangles in a page that `CPartMapper::MapPartToTex` resolves
  (import `0x67F340`, A2dLib `0x100454B0`) through:
  * `scripts\Partmap.007` (A2DFILE, 0x782 hashed entries → `.tex`);
  * `scripts\TexPage1..20.tex` (`SH_TEXPG`: count at +0x28, page name at +0x2C, records of 0x11C bytes `{0x11C,x,y,w,h,name}` from 0x138);
  * pages `imagessd\TexPage_a_b.aim`: TILEDIM, 16 tiles of 256², **column-major** (checked visually on TexPage_8_8).
    Page codecs: IMHC4444 = raw ARGB4444, IMHC1555, or BMPRES = embedded 24-bit BMP.

  An unknown part name **throws** (A2dLib `0x10045544`); there is no fallback to a loose file.
  `.anim` = `SH_ANIM`: +0x0C frame count, +0x10 W, +0x14 H, frame records of 0xC18 bytes, first aim path at 0x68.

| asset | size | codec | what it is / who uses it |
|---|---|---|---|
| `images\interface\nation00..03.aim`, `nation_piraten.aim` | 128x64 (art 96x64) | TILEDIM IMSLDXT1, 1-bit alpha | **main nation flag** (Eng/Fra/Hol/Spa/Pirates). Table `0x6E12EC` → CFlag and CDynamicImg widgets. Preloaded 0..3 by `0x58F610` for the sea map |
| `-userflag-` = table slot 5 → `Run\0.bmp` | 96x64 | 24-bit BMP | player emblem (company logo) |
| `DefaultLogos/Logo_00..35.bmp` (arcd) | 96x64 | 24-bit BMP | 36 flag-style logos (`DefaultLogos_sheet.png`). Picker in Options `0x4E3930`, which also lists `My Documents\…\Logos\*` (FilePath kind 2, `FindFirstFileA` `0x4E3576`) |
| `images\Module_Stadtkarte\Flagge_<N>.aim` | 128x512 atlas, 2 cols x 15 rows of 36x29 frames | MIPMCONT 1 mip, IMSLD32 (Eng/Fra/Spa interleaved BGRA, Hol **planar**) | **town-view flagpole animation**. Referenced as `images\module_stadtkarte/Flagge_<N>.aim` (length-prefixed, frame rects 0x24x0x1D) in 32 lets: `gouverneur, vizekoenig, stadtverwaltung, baumeister, hafendock_{no,nw,so,sw}` x 4 nations |
| part `Pr2_Flagge_<N>` (`Pr2_Flagge_<N>.anim`) | 25x15 | BMPRES (TexPage_0_11; TexPage_0_12 copy missing from the dump) | small framed flag. Town info dialog (4 icons, `0x4A4034`), NATION_PAGE, STATISTIC_PAGE, INTEXT_<N> |
| parts `Pr2_Seekarte_SchiffInfo_<N>/_Pirat` | 16x13 | BMPRES | sea-map ship info icon, table `0x6E3514[0..4]` |
| parts `Seekarte_Schiff_Flagge_Blau/_Rot`, + `_<N>`, `_Autohandel` | 16x16 | IMHC4444 | sea-map mini selection (Blau = own, Rot = hostile). `_<N>` and `Autohandel` have no exe refs |
| parts `SM_Konvoi_Nation_<N>/_Pirat/_Spieler/_Gegner` | 16x16 | IMHC4444 | INTEXT inline icons (`Nation_<N>_Intext_Icn.anim`, `Intext_Spieler_Icn.anim`). **A Spieler icon exists** (plain blue) |
| parts `Pr2_Flag_tex_mini` 25x15, `Pr2_Flag_tex_small` 40x20 | | IMHC4444 | frame or cloth **overlays** drawn on top of a CDynamicImg flag: STADT_INFO `SIN_NatFrame_03`, STADT_ENTRY `LOS_nation_Texture`, KONVOI_INFO `IKI_Flag_Tex` |
| part `Pr2_Symbol_Nation_Spieler` | 25x15 | IMHC1555 | empty frame for the logo (STADT_ENTRY `LOS_NationFrame`; preload `0x58F59F`) |
| `Pr2_AnimPiratenflagge_0000..14` | 29x19, 15 frames | IMHC4444 | animated pirate flag (SEEKARTE_NEU) |
| `images\interface\Piraten\pirat00..29.aim`, `spielerpirat.aim` | 128x64 | DXT1 / IMSLD32 | pirate captains' flags (`pirat%02d.aim` `0x68E084`) |
| `run/Segel.aim` (arcd) | 256², 9 mips | MIPMCONT IMSLDXT1 | **3D sail atlas.** Sail cloth plus a mast-flag strip at y=192..223, 32x32 cells at x=64+32n: Eng, Fra, Hol, Spa, Pirate, **(empty = player)** |
| `Run\Player0.aim` (generated in AppData) | 256² DXT1 | MIPMCONT | `Segel.aim` + `0.bmp` pasted at (0,0)-(63,63) (sail emblem) and (224,192)-(255,223) (mast flag). Measured by diffing the decodes |
| `run/Pirat.aim`; `run/K1..K4.aim` | 256² | DXT1 / IMSLD32 | pirate sail; damage overlays (not nation-specific). The `#…` 512² variants have no refs |
| `Pr2_Flagge_{Eng,Fra,Hol,Spa,Pirat,User}_Big.anim` | 66x41/42 | — | **orphans**: no ref in the exe, screens or Lua. Only the `User_Big` part exists (a blank white flag, TexPage_8_8 @409,607) |

**"User" flag [S].** `Pr2_Flagge_User_Big` is an unused blank. The real per-player flag in vanilla is the **company logo**,
chosen in New Game/Options (`OPE_Btn_logo_inc/dec`) and copied to `Run\0.bmp` at Start Game (`0x4F29D0`, `CopyFileA` `0x4F2C04`) or
on an Options change (`0x4E2E40`). It is the only per-player flag choice, and vanilla already uses it for "player nation" (5) visuals.

## 2. How the exe chooses the flag

| element | code | index / byte | nation 5 today |
|---|---|---|---|
| CFlag `0x4C34A0` (waving flag): town info `SID_NationsFlagge_l/r` (`0x4A40CB`), battle dialogs (`0x4F6484` raw byte), `0x4FAB81`, `0x4FB818`, interface bar `IKG_FlaggeAni` | compares the argument with `-userflag-` (`0x4C3556..90`) → `FilePath(4)+"0.bmp"`. Then **always** calls `arc_CreateMemMapped` (`0x4C364A`) and renders 0x40 cloth frames `flag_%s__%i`/`shadow_flag_%s__%i` (`0x4C3793`, `0x4C38C4`). No cache lookup | bit22 → 5, otherwise `nation%6` | logo [S] |
| CDynamicImg `0x4C1CD0` (`0x4C13B0`; `.bmp` hint `0x4C141E`): town top bar `0x4A63CA`, town list `0x4B7D00`, selection panel `0x4860BA` | the bit-22 branch builds `FilePath(4)+"0.bmp"` (`0x4A6306`); otherwise `table[nation%6]` | `+0x390` | `-userflag-` is not translated, so P02 leaves it **blank** [S] |
| town-info mini flags, fn `0x4A3610` | `0x4A3DD8 movzx ebp,[ebx+0x390]`; bit22 → `0x40FC70` (display); `0x4A4034 mov edx,[ecx*4+0x6E1A40]` → `CStatic::Animation` x4, lit count = `0x5D2C10` | raw `+0x390` | **index 5 = `0x6E1A54` → the string "imagesSD\Pr2_Progress_Small_Rot.aim" used as an anim name; index 4 = ptr 0x00FFFFFF.** Not covered by P02/P03 [S]. Result is unknown [H: blank, or a part-mapper throw] |
| convoy flag name `0x50C740` / trade window `0x5949C0` | `nat<4` → table, `==5` → `Run\0.bmp` (`0x50C7BC`, `0x5949F5`) | convoy +0xB8 | logo [S] |
| sea-map ship icon `0x5966C0` | `cmp eax,5` → `0.bmp` (`0x59671C`); 0..3 → `0x6E3514[n]`; 4 → Pirat; cached in `[esi+0xA0]` | convoy nation | logo [S] |
| sea-map **town marker** `CSeekarteStadt` | `SetNation 0x58DE60` maps 5→4; draw `0x5907EF`: idx<4 → holder `[0x701424]+0x258+4n` (nation0N.aim), idx 4 → holder+0x268 = `Run\0.bmp` (loaded `0x590279`) | town nation | logo [S, agent B] |
| 3D sails/mast flag | `0x56FE60` stores sail idx = `nation<4 ? 9 : nation==5 ? 0 : 8` (`cmp cl,5; sete dl; dec edx; and edx,8`). WalExtPR2 `0x1000BDA0`: 0..7 → `Run\Player<k>.aim`, 8 → `run/Pirat.aim`, else `run/Segel.aim`. Compositor `0x1000BAC0`/`0x1000BB54` (`"%s%d.bmp"`, `"%sPlayer%d.aim"`) → `0x1000B290("run/Segel.aim", bmp, out)` | convoy nation | logo [S]. The mast cell chosen by UV is [H] |
| town-view flagpoles | lets registered at boot by `0x530B80/0x530C70/0x530D60/0x530E50` (stepper `0x5205E0..`, `0x52EC30`). Art set for the current town: `SetActCity 0x52D2F0`, `nation<4 ? +0x390 : +0x391` (`0x52D424..35`) → obj+0x1F | display byte | **host flag** [S] |

* No code path uses `Pr2_Flagge_User_Big` [S].
* `0x6E1300` is in `.data` (`0xC0000040`, writable), so the DLL can repoint it at runtime [S].
* The logo travels with saves [S for the calls, H for the roles]:
  * save path `0x5807C0` → `0x5A68D0` reads `Run\0.bmp`;
  * load path `0x581070` → `0x5A6C70` writes the BMP back, then `0x5815E0` copies `Run\1.bmp` → `0.bmp` (`0x5817B3`) and deletes `1.bmp`.

## 3. Loose files and archive priority [S, agent A; Archiver.dll/A2dLib]
* PR2 `0x4042E0` calls `CArchiveManager::EnableDiscSearch(1)` + `SearchDiscFirst(1)`. The container `A2DLIB_CONT` gets flag 1 (**disk first**).
* Archives are appended in this order: arcd, arct, arcs, loca, then the optional **`pr2_patch.cpr`**.
  A later archive replaces an earlier one with the same key.
* Precedence: **loose disk file > pr2_patch > loca > arcs > arct > arcd**.
* Lookup (Archiver `0x10001420`): `CreateFileA` on the name **relative to the current directory**, which is the game folder,
  as the `include.ini` override proves. Keys are case-folded and `/`≡`\`, so `imagesSD` = `imagessd`.
* Every PR2, WalExtPR2 and Lua read goes through this container. Walhalla 3D textures do too [H, strong].
* So loose `images\interface\nation05.aim`, `scripts\*.anim/.tex`, `scripts\Partmap.007`, `run\Segel.aim` and whole
  `imagessd\TexPage_*.aim` **do** override.
* Absolute paths work too. Vanilla maps `C:\…\Run\0.bmp` with `arc_CreateMemMapped`.
* **A single atlas part cannot be overridden on its own.** You must override the whole page, or the `.tex` + `Partmap.007`.
* Files are re-mapped on every load call. There is no name cache in `arc_*`. Widgets hold their own copies.

## 4. Writing `.aim` [S, AIM20.dll serializers, agent A]
* **Top level:** `"AIMRES2.00"`+6×NUL | `u32 fileflags` | 8-byte root tag | body | if `fileflags&0x10`: `u32 n` + n bytes of trailer
  (shipping data: `"IHHW",16,16,1`).
* **TILEDIM** (`0x1001F280`): `u32 8` | `u32 ntiles` | `u32 palflag=0` | ntiles × (tag8 + body) | `u32 W` | `u32 H`.
* **MIPMCONT** (`0x1000B820`): `u32 nmips` | `u32 1` | nmips × (tag8 + body). One mip is fine; Flagge_* ships with 1.
* **Bodies:**
  * IMSLD32 = `u32 mode` (2 = interleaved BGRA, 0 = planar) | `u32 alpha` (0 = X8R8G8B8, otherwise A8R8G8B8) | `u32 w` | `u32 h` | `u32 bloblen` | SLDCOMP blob.
  * IMSLDXT1/3/5 = `w`, `h`, blob.
  * **BMPRES/TGARES/JPGRES** = `w`, `h`, `u32 len`, **plain .bmp/.tga/.jpg file bytes**.
* **SLDCOMP blob:** repeated `u32 blklen` + block, where the blocks sum exactly to bloblen. Block = `u8 1` | `i32 outlen` | `u32 flags` | `u32 nibbles` | payload.
  * `flags=0x80000000`: **raw copy** (`0x1008496F`). Payload starts 12 bytes after the method byte, and `blklen = 13+outlen`.
  * `0xC0000000`: XOR 0x35.
* **Bug in the old `game2/tools/convert/aim_convert.py`:** the raw path reads at `off+8`; it must be `off+12`.
* **Easiest writer** (layout verified in shipping data):
  `AIMRES2.00\0×6 | 02000000 | "TILEDIM " | 8 | 1 | 0 | "BMPRES  " | w | h | len | <BMP file> | W | H`.
  The other option is raw IMSLD32 TILEDIM; agent A's proof encoder `aim_encode.py` passes a strict parse.
* Keep images ≤256 px wide (one tile), which avoids the tile-order question.
* A bare `.bmp` only loads where the caller passes a `.bmp` name: CDynamicImg `0x4C141E`, CFlag, and the sea-map code.
  Those are exactly the flag sites.

## 5. Recommended design

### 5.1 Core: nation flag = `Run\0.bmp` (no exe code; one DLL data write)
1. **Assets.** Ship 100 flags as 96x64 24-bit BMPs (DefaultLogos style, no alpha), e.g. `art/flags/flag_000.bmp`.
   * They may also be copied to `My Documents\Ascaron Entertainment\Port Royale 2\Logos\`. The **vanilla Options logo picker** then
     offers them with zero code, but it writes `Run\0.bmp` itself.
2. **On founding**, the DLL copies the chosen BMP to `FilePath(4)+"0.bmp"` (`CUserFiles` `0x405140`/`0x409830`, or rebuild the path
   with `SHGetFolderPathA(CSIDL_APPDATA)`).
   * Store the flag id in the mod save block.
   * After every load, rewrite the file. Vanilla's load restores the save's embedded logo into `0.bmp`, which already carries the flag if it was saved after founding [H].
3. **DLL init:** `*(const char**)0x6E1300 = g_flag_path` (absolute `…\Run\0.bmp`, static ANSI buffer). Effects:
   * CFlag sites load the path directly; `-userflag-` is no longer needed.
   * The three CDynamicImg sites (top bar, town list, selection panel) show the flag instead of P02's blank.
   * Vanilla bit-22 player towns are unchanged in practice: same file.
   * P02 stays as the safety net for a missing file.
4. **Vanilla gives the rest for free:** player and nation-5 convoys in lists, info bar and trade window; sea-map ship icon;
   sea-map town markers (`0x58DE60` 5→4→`Run\0.bmp`); 3D sails and mast flags of every nation-5 convoy (`Player0.aim`).

### 5.2 Small extra patches (optional, ranked)
* **PF1, town-info mini flags `0x4A3DD8`.** Change disp `0x390→0x391` (P03 style). `[esp+0x10]` is only used as the anim index;
  `0x4A3FEB` just reserves stack. The result is 4 host-power mini flags instead of an invalid anim name.
  Showing the custom flag here would need a new atlas part (§5.3).
* **PF2, political map `0x4DA262` (`cmp cl,4 / jae 0x4DA2A8`).** Add a cave: nation 5 → colour slot `[4]` `0x6E80E0` (initialised to 0x1414AF,
  never read), or a player colour written at `0x689964`. This also fixes the nation-5 pixels in the unzeroed buffer, which are garbage today [H on the visual] (agent B).
* **PF3, INTEXT tooltip** (`0x459BA5`, `0x4D9C5C`, `0x4B1AB6`, `0x4F1EE0`: `nation+3`, raw 5 → `INTEXT_HAUS`). Read `+0x391`, or map 5 →
  the `INTEXT_SPIELER` symbol (art `SM_Konvoi_Nation_Spieler` exists).
* **Lua popups** have no image slot. Embedding `<g:scripts/INTEXT_SPIELER_800x600.screen>` in an `FNN_` body string may render
  the inline icon [H, needs one in-game test].

### 5.3 Atlas parts (only if a custom *static sprite* is wanted)
* For `Pr2_Flagge_<N>`-style 25x15 icons, `SM_Konvoi_*` 16x16, and so on: ship loose overrides of the page `imagessd\TexPage_8_x.aim`
  (raw IMHC4444 tiles, easy to write) with pixels repainted into an **unused** rect.
  Candidate: `Pr2_Flagge_User_Big` 66x42 @409,607 on TexPage_8_8, plus unused `Seekarte_Schiff_Flagge_<N>` cells on TexPage_8_7.
  Then a loose `.anim` points at that part name. Adding new names needs a `Partmap.007` rebuild (hash at A2dLib `0x100454B0` not reversed).
* These are **install-time** assets, so they cannot follow a per-save choice of 100 flags. Prefer the BMP route.

### 5.4 Town-view flagpoles (hard; defer)
* The flag sprite is part of the building `.let`.
* Lets are registered once at boot. The art set per town is chosen by the display byte (`0x52D424`) → host flag.
* Options:
  * (a) Register 8 extra lets per host. These are copies with the length-prefixed path replaced by e.g.
    `images\module_stadtkarte/Flagge_User.aim`, which is trivial to generate. Then hook the obj+0x1F → building-type selection
    for nation-5 towns. The selection reader was **not traced** [H].
  * (b) Swap the pixels of the host's `Flagge_<N>` texture while a nation-5 town is the active city (`SetActCity 0x52D2F0`)
    and restore them on leave. This needs a texture-lock path in A2dLib [H].
* Art needed for either option: one 128x512 IMSLD32 atlas, 30 frames of 36x29 (2 cols x 15 rows, period 36/29).
  It can be **generated** from a flat flag by warping it with the frame masks of `Flagge_England.png`.
* A runtime-chosen flag could be written at founding as a loose file `images\module_stadtkarte\Flagge_User.aim`. Disk-first lookup
  works, but the texture is loaded at boot, so it takes effect on **next game start** [H].

### 5.5 Switching at runtime (after founding, no restart)
* **UI (CFlag, CDynamicImg): yes.** They re-read the file every time they are set. The top bar reloads when the town's nation byte
  changes vs its cache `[edi+0xAC]` (`0x4A62BD`), so it reloads on founding [S].
  Vanilla's in-game logo change refreshes the interface bar via `0x4784F0` → `0x4C1800` (CDynamicImg reset) + `0x4C33E0` (CFlag reset) [S].
  The DLL can call the same function after it writes the file.
* **Sea-map ship icon:** reloads when the nation of the shown ship changes (`[esi+0xA0]`) [S].
* **Sea-map town marker:** `Run\0.bmp` is loaded into a holder at `0x590279`, probably once per sea-map build [H: next load/new sea map].
* **3D ships:** `Player0.aim` is composited by WalExtPR2 when ship textures are created [H]. Expect the new flag after save+load.
  Forcing it at runtime means calling `0x1000BAC0(0)` and reloading textures [H, risky].
* **Town-view flagpoles:** load time only (boot) [H].

## 6. Other nation art: what is worth generating
| prio | visual | asset to make | hook | verdict |
|---|---|---|---|---|
| 1 | flag everywhere in UI, sea map, 3D sails/mast | **96x64 BMP** per flag | §5.1 (data write + file copy) | **do it**: highest visibility, near-zero risk |
| 2 | political map colour | none (an RGB value) | PF2 cave `0x4DA262` | do it: also fixes garbage pixels |
| 3 | town info mini flags / INTEXT icon | none (host flag / Spieler icon) | PF1, PF3 | cheap correctness fixes |
| 4 | sail emblem style | optional: none needed (`Player0.aim` is generated from the BMP) | — | free |
| 5 | town-view flagpole | 128x512 IMSLD32, 30 frames | §5.4 | later; needs let/type RE |
| 6 | recoloured `SM_Konvoi_Nation_Spieler` 16x16, `Pr2_Symbol_Nation_Spieler` 25x15 | IMHC4444/1555 page override | §5.3 | low |
| ✗ | 5th building/soldier set (gouverneur, vizekoenig, kirche, stadtverwaltung, wohnhaus, walls, `lcr` soldiers), governor/viceroy videos (`0x6E1308`, ids 10–21/40–80; annex videos 98–101), NATION_PAGE / NPC_NATIONEN 5th rows, stats chart colour `0x6E777C`, minimap (relation-based), `#`-hi-res sails, `Stadt_07/08` | — | — | not worth it: host-power art works (`0x52D424`), and the fixed 4-row screens and videos are large or brittle |

Per-nation art that exists (all keyed by the display/host nation, 4 sets only):
* `Module_Stadtkarte/{Gouverneur,Vizekoenig,Kirche,Stadtverwaltung}_<N>(_shd/_Bau)`, `Wohnhaus_Stufe01..05_<N>_A..D`,
  `Kleine_Stadtmauer/Stadttor_*_England`;
* soldiers `_X_musketenschuetze/saebeltraeger_<n>`, `#Texpage_Soldat_<N>` (battle anim hard-codes England, `0x591804`);
* player-only art already exists: `Spielerpalast_0/1`, `Lagerhaus_Spieler`.

## 7. Confidence and open items
* High [S]:
  * the vanilla nation-5 → `Run\0.bmp` paths (convoys, sea map, CFlag, sails);
  * the table slot address and its writability;
  * disk-first loose override;
  * the `.aim` layout and raw blocks;
  * asset sizes and codecs.
* Medium [H], needs one in-game check:
  * repointed slot 5 renders correctly in the top bar, town list and selection panel (vanilla already feeds the same widget an absolute `0.bmp` for convoys at `0x52A9B0`);
  * the save/load logo round trip;
  * when `Player0.aim` is regenerated;
  * what the `0x4A4034` index-5 anim name does today.
* Open: the town-view building-type selection from obj+0x1F (needed for §5.4).

---

## 8. Two flags: the player's logo and the nation's flag (the two-flags change, 2026-10-18)

Static RE of `PR2_target.exe` (same SHA-256 as the pinned unpacked exe) and `WalExtPR2.dll`; facts `FL-*` in
the private fact checker; code in `dll/flag.c`; in-game check `tools/flag_probe.py`.

### 8.1 Why the flags were mixed up [S]
* Design 5.1 made the nation's flag the player logo: founding copied `flag_NNN.bmp` over `Run\0.bmp`.
* In vanilla **every** nation-5 convoy draws `Run\0.bmp`. The player's own convoys are nation 5 (type 1), and so are
  the nation's fleets (type 4/9). So both kinds always showed the same file - and both looked wrong for a while
  because the copies of that file are cached at different times:
  * the 3D sails and mast flags use `Run\Player0.aim`, which WalExtPR2 composites from `0.bmp` **once** and caches
    (`0x1000BDA0`, cache slot `this+0x14+4k`) - still the old logo after founding, so the fleets in port flew the
    player's logo;
  * the sea-map ship marker loads `0.bmp` when it is created - so the player's convoys at sea flew the nation's flag.
* The 3D ships are only in the **port scenes** (and sea battles); the sea map is 2D (markers). "At sea" means the
  sea-map marker, the selection panel and the info bar.

### 8.2 The fix: two files, one discriminator
* `Run\0.bmp` stays the player's own logo (new-game choice). The mod never writes it any more.
* `Run\7.bmp` is the nation's flag (copied from `nation_flags\flag_NNN.bmp` on founding, on a flag change and when a
  save is loaded). Slot 7 because WalExtPR2 composites `Run\Player<k>.aim` from `Run\<k>.bmp` for every sail index
  `k = 0..7` (`"%s%d.bmp"` / `"%sPlayer%d.aim"`, `0x1000BAC0`); the game itself only uses 0 and, while loading, 1.
* National = `k[+0xB8] == 5` and (a fleet: type 4/9, or a player convoy designated a national convoy) -
  `sight_is_national()` (dll/sight.c). Everything else of nation 5 is the player's.

| site | what | hook |
|---|---|---|
| `0x50C7CE` | convoy flag name `0x50C740` (convoy lists in port, info bar of a foreign convoy, battle dialogs `0x4F60A3`) | string swap `"0.bmp"`->`"7.bmp"` for a national convoy (esi) |
| `0x485C5E` | selection panel, convoy branch | same (esi = convoy) |
| `0x47D4A0`, `0x47D62B` | interface bar `0x47C930`, the player's own convoy: logo image `bar+0x2C4` | same; convoy = handle `bar+0x1AC` |
| `0x5A2EE9` + `0x596721` | sea-map ship marker: `0x5966C0(nation)` caches the nation (`+0xA0`) and loads the logo once (`+0x141`; `0x596380` releases the old image itself) | feed hook resets `+0xA0`/`+0x141` when the marker's image is of the other kind or older than the file; load hook swaps the name |
| `0x63DEF5` (jmp) | port scene re-flag `0x63DE20(town+0x20, convoyH)` (edi = convoy): sail index 9 (<4) / 0 (5) / 8 | national -> 7, jump to `0x63DF04` |
| `0x570D40` + `0x570EED` (jmp) | port scene ship creation `0x570D40(type, convoy handle, nation, ...)`; the new ship object overwrites the handle's argument slot (`0x570DCD`), so an entry hook keeps the handle | national -> 7, jump to `0x570EF9` |
| `0x4FAB85` | battle dialog convoy flag `0x4FAA60`: nation 5 -> table slot 5 | a player convoy gets `"-userflag-"` back (CFlag -> `Run\0.bmp`), since slot 5 is now the nation's flag |
| `0x6E1300` (data) | nation-icon slot 5 | -> absolute `Run\7.bmp`: town top bar, town list, selection panel (town), town info and siege dialogs of nation-5 towns |
| `0x4A40E8`, `0x4A4143`, `0x4A41C4` | town info dialog: a vanilla player town (bit 22) also takes index 5 | keeps `"-userflag-"` (the player's logo) |
| `0x590289` | sea-map town marker, index 4 = nation 5: image `[0x701424]+0x268`, loaded once | name swap; dropped (left to the engine) when the flag file changes |
| `0x463120`, `0x46314B`, `0x594A0F` | trade window `0x5949C0`: own branch (`+0x6C` or bit 22) pushes 5; a town pushes its nation byte | a nation-5 **town** shows `7.bmp`; the player's side stays `0.bmp` |
| WalExtPR2 `+0xBDA0` | `GetSail(k)`: composite `Player<k>.aim` only when the cache slot is empty | the slot is dropped when `Run\<k>.bmp` was rewritten since it was made (generation counter) |

Vanilla untouched (player's logo): the interface bar's waving flag for the player, the options/new-game logo
selector, the save/load logo round trip (`0x5A68D0`/`0x5A6C70`, `0x5815E0` copies `Run\1.bmp` -> `0.bmp`).

### 8.3 Load order and older saves [S]
* The `Load done` hook (`0x5815CF`, end of `0x581070`) runs **before** vanilla copies the save's logo
  (`Run\1.bmp` -> `0.bmp`, `0x5817B3`). So the after-load step runs three frames later: it compares `Run\0.bmp` with the
  nation's `flag_NNN.bmp`; equal = a save from before this change. Then `Run\0_company_logo.bmp` (kept once by the old
  code before its first overwrite) is copied back if it exists; otherwise the logo stays as it is. Then the interface
  bar is refreshed like the game does after a load (`0x5003D0(*(*0x403360())+0xEC)`), `Player0.aim` is marked stale,
  and every nation-5 convoy in a port is re-flagged (`0x63DE20`).
* The save keeps `Run\0.bmp` (the player's logo) from now on; the nation's flag comes from the mod's save block (flag index).
* Designating or releasing a national convoy re-flags its ships in port at once (`flag_convoy_changed` -> `0x63DE20`)
  and redraws the interface bar (`0x4784F0` reset + `0x47C930`; the bar redraws its flag only when the shown convoy
  changes, `0x47D805`). Verified in game: sail and mast flag switch both ways without a reload.

### 8.4 Known limits
* A flag **change** (`Nation_SetFlag`) reaches new ships at once; ships already built in a port scene keep their
  texture until they are built again (leave and re-enter the town, or load). Widgets that cache by file name (town top
  bar) reload when the town changes.
* Sea battles build their ships with the nation in 3 bits (`0x5675D7`, sail setter `0x567F70`): nation 5 = player sail.
  Only the player's own convoys fight 3D battles; a designated national convoy in a 3D battle shows the player's flag.
* `0x485FF4` (selection panel) compares the flag name with `Run\0.bmp` (cosmetic ordering only).
* Ships lying in a port also fly a large flag of the town's power (Spain in Margarita, the host); that is not the
  convoy's flag and is unchanged.
* The minimap shows dots, not flags (national ships: cyan, the national-ships-on-the-sea-map change).
* Observed (not caused by the flag hooks): while a national convoy is designated, the sea-map marker of the
  nation's fleet loads its logo again on every marker update (~13 loads/s at 20x speed, two marker objects
  alternating, `+0x141` found 0 each time; counter `seaload-again` of `Nation_DevFlags`). The flag shown is right;
  it costs a small file read per update. The fleet alone (no designation) loads once. Probably the per-frame
  relabel/visibility work of the national-ships-on-the-sea-map change resets the marker - left for that code.

### 8.5 Tests
* `tools/flag_probe.py` (FNN 46): FLG-01 logo files after the load (an older save gets the kept logo back),
  FLG-02a the fleet's ships in port get sail 7, FLG-03 sea map, FLG-04 designation, FLG-05 after QuickSave +
  reload. `--found` (FNN 02): FLG-06 founding with flag 12 leaves `Run\0.bmp` alone and writes `Run\7.bmp`.
* `tools/flag_probe2.py` (FNN 46): the screenshot run - harbour before / designated / released, the same at sea,
  then an "older" save (embedded logo = the nation's flag) reloaded. One town-minimap click (a short focus flash)
  moves the town view to Margarita's harbour.
* `Nation_DevFlags()` returns the per-site counters, `Nation_DevView(1|2, town handle)` switches the view (tests).
