# '-userflag-': why a nation-5 town crashes the UI, and how to fix it

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000), done
2026-10-11 with pefile and capstone. Every claim is tagged **[S]** (VERIFIED-STATIC: read
directly from the bytes, VA and instruction given) or **[H]** (HYPOTHESIS).
The import names come from the PE import table.

## TL;DR

* `'-userflag-'` is **slot 5** of the nation-icon pointer table `0x6E12EC`. Index 5 is
  `SPIELER_NATION`, the player. This sentinel is understood **only** by the `CFlag` widget
  setter `0x4C34A0`, which swaps it for `%APPDATA%\Ascaron Entertainment\Port Royale 2\Run\0.bmp`
  (the player's company logo).
* Three UI sites index the table with `nation % 6`. They expect every town with nation 5 to
  also have the "player town" bit (CStadt+0x40 bit 22). When that bit is clear they send
  the raw `'-userflag-'` to a **different** widget setter, `0x4C1CD0`, which has no special case.
  The archive lookup fails. `0x4C13B0` still **returns true** with a null handle, and
  `0x4C1D9F mov eax,[ecx]` faults.
* Recommended fix: **P1**, a 2-byte patch that makes the not-found case return false
  (stops the crash for every caller). Add **P2a** (the three sites use the display nation, so
  the town shows its host power's flag) or **P2b** (nation-5 towns show the user logo, the way
  vanilla already does for player convoys).

---

## Q1. Where nation 5 becomes '-userflag-', and who passes it to 0x4C1CD0

### The table [S]
Pointer table at `.data 0x6E12EC` (bytes `009a6800 e0996800 c0996800 a0996800 7c996800 70996800`):

| idx | ptr | string |
|---|---|---|
| 0 | 0x689A00 | `images\interface\nation00.aim` |
| 1 | 0x6899E0 | `images\interface\nation01.aim` |
| 2 | 0x6899C0 | `images\interface\nation02.aim` |
| 3 | 0x6899A0 | `images\interface\nation03.aim` |
| 4 | 0x68997C | `images\interface\nation_piraten.aim` |
| 5 | **0x689970** | **`-userflag-`** |

The binary has no `nation%02d.aim` format string; the names are literal. The strings have no
code xrefs. They are reached only through the table, which has 11 code refs:
`0x485E96, 0x4A413F, 0x4A41C0, 0x4A63B5, 0x4B7C8C, 0x4F649E, 0x4FAB81, 0x4FB818, 0x50C7A8, 0x58F613, 0x594AA8`.

### What each table user does

| site (fn) | UI element (identified from strings) | index | widget setter | nation-5 town w/o bit 22 |
|---|---|---|---|---|
| `0x4A639F` (fn 0x4A5E70, vtable slot 0x69045C) | **Town top bar** (`IDT_TOP_BAULIZENZ_FORTSCHRITT`, tooltip group). Loops over 4 image widgets at `edi+0x94` and re-runs when `[town+0x390] != [edi+0xAC]` (`0x4A62BD`) | `movzx eax,[esi+0x390]; cdq; mov ecx,6; idiv ecx; mov edx,[edx*4+0x6E12EC]` after `test dl,1 / je 0x4A639F` on bit 22 (`0x4A62F7..0x4A6300`) | **0x4C1CD0** at `0x4A63CA` | **CRASH** [S] |
| `0x4B7C76` (fn 0x4B7A60, vtable slot 0x691AA0) | **Town list** (`LOS_StadtName`, `LOS_Nation`, `LOS_Einwohner`, `LOS_Wohlstand`) | same `%6` pattern, bit-22 guard at `0x4B7BC6..0x4B7BD7` | **0x4C1CD0** at `0x4B7D00` | **CRASH** [S] |
| `0x485E84` (fn 0x485BD0 = "flag name for selected map object") | Used by `0x485EF0` → `0x4C1CD0` at `0x4860BA`. Reached through vtable `0x68DF14` (class whose siblings load `INTERFACE_SCHIFFE_800x600.screen` / `SMALL_SCHIFF_INFO_800x600.screen`) and through `0x4861B0`←`0x47C440`. This is the **ship/selection info panel** when the selected object is a town | town branch: `call 0x633480` (→CStadt), `test [eax+0x40] bit22` at `0x485DDC..0x485DE5`, then `%6` | **0x4C1CD0** at `0x4860BA` | **CRASH when the town is selected/hovered** [S for the code path; the "selected" trigger is H] |
| `0x4A413C`, `0x4A41BD` (fn 0x4A3610, vtable slot 0x690154) | **Town info dialog** (`SID_*`, `IDPR_SID_SPIELERSTADT_%02d`, `CFlag`) | `0x4A40CB`: bit 22 → index 5, else `nation % 6` | `0x4C34A0` (CFlag) | OK: resolves to Run\0.bmp |
| `0x4F649B` (fn 0x4F6250) | Sea-battle dialogs (`SAD_/SBD_NationsFlagge_05_l/r`) | `movzx eax,al` of `[town+0x390]`, **no mod, no bound** | `0x4C34A0` | OK for 5. Bytes ≥ 6 would read past the table [S] |
| `0x4FAB81` (0x4FAA60), `0x4FB818` (0x4FB770 `SST_NationsFlagge_05`) | battle / pirate flag widgets | convoy/town nation | `0x4C34A0` | OK |
| `0x50C7A5` (fn 0x50C740 "convoy flag name") | used by the IFB info bar (`0x47D728`), convoy lists (`0x52A99F/0x52A9FA`), etc. | `nat<4` → table; **`nat==5` → Run\0.bmp** (`0x50C7BC cmp al,5`); `nat==4` → pirate art | 0x4C34A0 / 0x4C1CD0 | never returns `-userflag-` [S] |
| `0x594AA5` (fn 0x5949C0, called at 0x46315E) | trade-window flag | `==5` → Run\0.bmp (`0x5949F5 cmp al,5`), `<4` → table | | never returns `-userflag-` [S] |
| `0x58F610` (fn 0x58F200) | preloads `table[0..3]` (`cmp esi,4 / jl`) plus `imagesSD\Pr2_Symbol_Nation_Spieler.aim` | 0..3 only | | safe [S] |

Conclusion [S]: vanilla code assumes **"town nation byte == 5 ⇔ CStadt+0x40 bit 22 set"**.
Bit 22 is the **player town (Spielerstadt)** flag. Proof: the Lua binding
`Town_IsPlayerTown` (name 0x686450, registered at `0x43AFD8`, impl `0x4273E0`) returns
`(([town+0x38]+8) >> 0x16) & 1` (`0x427450 add eax,0x38; 0x427453 mov eax,[eax+8]; 0x427456 shr eax,0x16; and eax,1`).
A town byte poked to 5 without bit 22 breaks that assumption. The three `%6` sites then emit
`'-userflag-'` into 0x4C1CD0.

Which of the three crashed in your run [H]: most likely the top bar (`0x4A63CA`). It runs every
frame and re-loads as soon as the nation byte differs from its cache `[edi+0xAC]`, which fits
"crashes within one frame". To confirm, the return address in 0x4C1CD0's frame
(`[ebp+4]`) will be `0x4A63CF` (top bar), `0x4B7D05` (town list) or `0x4860BF` (ship/selection panel).

### Why 0x4C1CD0 dereferences null [S]
* `0x4C1D0C call 0x4C13B0(name, &h)` → `test al,al / je 0x4C1E6C` (clean failure exit exists).
* `0x4C13B0` calls `arc_CreateMemMapped(arc, name, &p, &sz)` (`0x4C1407`; thunk `0x64C7A4 jmp [0x67F520]`).
  When that returns 0, `0x4C1411 je 0x4C14EB` jumps to code that only stores the name at `this+0xF8`
  and **returns `al=1`** (`0x4C1502 mov al,1`). `h` stays null.
* Back in 0x4C1CD0, `0x4C1D9C mov ecx,[ebp-0x14]` (null) → `0x4C1D9F mov eax,[ecx]` → AV.
* 0x4C13B0 has exactly one caller, `0x4C1D0C` [S]. Its catch-continuation `0x4C1525` already returns `al=0`.
* The widget's draw `0x4C1570` null-checks the image (`0x4C15E6 mov eax,[esi+0x9C]; test eax,eax; je 0x4C17C7`) [S],
  so "no image" is a state the widget handles safely.

---

## Q2. What 0x4C34A0 is, and what FilePath(…,4) returns

### 0x4C34A0 = `CFlag::SetImage(std::string name)` (name inferred) [S for behaviour]
* `__thiscall`, takes an STLport `std::string` by value (`[ebp+8]` = begin, `[ebp+0xC]` = end).
  Callers are the "CFlag" controls: `0x47D7B4, 0x4A415F, 0x4A41E0, 0x4F60AF, 0x4F64B3, 0x4F6563,
  0x4F9FEA, 0x4FA023, 0x4FA07C, 0x4FA0D0, 0x4FAB62, 0x4FAB98, 0x4FB825`. Each sits in a dialog
  whose strings include `CFlag` (town info, battle dialogs, pirate view, convoy info bar).
* `0x4C3556..0x4C3590`: `length("-userflag-")` must equal the string length, and `compare(...)==0`.
  - If they match, `name = CUserFiles::FilePath(4) + "0.bmp"`: `0x4C35B2 call 0x405140` (CUserFiles singleton `0x6E5938`),
    `0x4C35C1 call 0x409830(&tmp,4)`, `0x4C35D1 call 0x405550` (string + const char*), assign.
  - Then `0x4C364A arc_CreateMemMapped(...)` → load image into `this+0x9C`.
* It does **not** register any global resource called `-userflag-`. It rewrites its own argument.
  Calling it cannot help a 0x4C1CD0 widget [S].
* When it runs: any time a CFlag control is (re)populated with table index 5. In vanilla that
  means the town info dialog of a player town (`0x4A40D2`: bit 22 → index 5) and the battle
  dialogs (`0x4F6484`) for towns with byte 5. It is not a game-start or "flag designer" routine.

### CUserFiles::FilePath(out, kind) = `0x409830` [S]
* Jump table `0x40998C`: kinds 0,1,2,3,5 → `0x40987C add esi,0x104` (My-Documents base);
  **kind 4 → `0x409882`** (AppData base, no `+0x104`). Kinds above 5 go to the default branch at `0x409938`.
* Subdir table `0x6E0888`: `[0]Save\ [1]Autoroute\ [2]Logos\ [3]Logos\Small\ [4]Run\ [5]Screenshots\`.
* Bases, from the ctor `0x4099B0`: `this+0` = `SHGetFolderPathA(CSIDL_APPDATA|CREATE=0x801A)` (helper `0x409790`)
  + `"\Ascaron Entertainment\Port Royale 2\"` (string `0x681260` via `0x6E0884`).
  `this+0x104` = `SHGetFolderPathA(CSIDL_PERSONAL|CREATE=0x8005)` + the same suffix.
* After building the path, FilePath calls `MakeSureDirectoryPathExists` (`0x4098A4`) and throws
  `"CUserFiles::FilePath - failed to locate or create data folder!"` if that fails.

**So the user flag file is `%APPDATA%\Ascaron Entertainment\Port Royale 2\Run\0.bmp`** [S].
(On Win11: `C:\Users\<u>\AppData\Roaming\Ascaron Entertainment\Port Royale 2\Run\0.bmp`.)

---

## Q4. Vanilla user-flag flow

The user flag is the player's **company logo**, not a nation flag designer.
* Logo choice happens in the **Options → Gameplay** screen `0x4E3930` (`OPTIONEN_GAMEPLAYEINSTELLUNGEN_800x600.screen`,
  `OPE_Btn_logo_inc/dec`, `OPE_LogoDisplay1/2`, `OPE_Help_logo`), which also appears in `PRIVATESPIELEINSTELLUNGEN_800x600.screen`.
  It cycles BMPs from `My Documents\...\Logos\` (FilePath kind 2/3), and the chosen source path is kept in the global `[0x70200C]` [S].
* **Start game**: main-menu handler `0x522A60` (reached from the `IDPR_MM_STARTGAME` setup at `0x523FE8`) calls
  `0x4F29D0` at `0x522A89`. That function stores the player and company names (`0x701E4C`, `0x701E58`) and then
  `CopyFileA([0x70200C], FilePath(4)+"0.bmp", FALSE)` (`0x4F2C04`). If the copy fails it extracts
  `DefaultLogos/Logo_00.bmp` from the archive (`0x4F2C8E`) and writes it with `fopen("w+b")/fwrite` (`0x4F2D0F..0x4F2D94`).
  If even that fails it throws `"writing defaultlogo failed!"`. So **after any New Game, Run\0.bmp exists** [S].
  `0x4E2E40` (the options screen) has the same copy/default-write logic for in-game logo changes [S].
* On exit `0x406560` deletes `Run\1.bmp` (`0x4065F3 push "1.bmp"` … `DeleteFileA`). It does **not** delete `0.bmp` [S],
  so the file persists between sessions [H: unless the user cleans AppData].
* Consumers: player convoys (convoy nation 5) through `0x50C740`/`0x485C4C`/`0x5949C0`, player towns (bit 22) through the
  bit-22 branches, and CFlag index 5 through `0x4C34A0`.
* Vanilla player towns: `Town_IsPlayerTown`, `IDPR_SID_SPIELERSTADT_00..03` (global.h 5519–5522), `videos/13_Spielerstadt.wmv`,
  and the `verstecke.ini` comment "Gruppe der Spielerstadt" [S: strings exist]. How bit 22 gets set was not located.
  A search for `or …,0x400000`, `shl …,0x16`, `bts` and byte `0x40` at `+0x42` found no setter. It is probably copied as a
  whole flags dword (template or save) [H]. `0x61BDE0` ("found town at site": `0x61CCE0(id,1)`,
  then `AddToNation(nation, force=1)` at `0x61BE8A`) and its caller `0x61C8A8` are the best candidates for the
  player-town founding path [H].
* `Pr2_Flagge_User_Big.anim` → `imagesSD\Pr2_Flagge_User_Big.aim` is a static art asset. It is unrelated to Run\0.bmp.

---

## Q3. Fix options, ranked by risk (lowest first)

### P1: harden 0x4C13B0 so not-found returns false (RECOMMENDED, always apply) [S]
`0x4C1411: 0F 84 D4 00 00 00` (je 0x4C14EB) → `0F 84 0E 01 00 00` (je **0x4C1525**).
* `0x4C1525` is the existing "return false" tail: `mov ecx,[ebp-0xC]; pop edi; pop esi; xor al,al; mov fs:[0],ecx; pop ebx; mov esp,ebp; pop ebp; ret 8`.
  At `0x4C1411` esp points at the saved edi (`add esp,0x10` at `0x4C140C` balanced the call). The EH state is 1 with
  `[ebp-0x28]=0`, so no destructor is skipped (the original not-found path destroys nothing either).
* The only caller (`0x4C1CD0`) already handles false: `0x4C1E6C` releases `[ebp-0x14]` if set and returns 0.
  `0x4E1380` (a loop at `0x4E13A0..0x4E13BA`) *expects* false for missing files.
  The other 0x4C1CD0 callers ignore the return value, and the draw path null-checks `+0x9C`.
* Effect: any missing image name in this widget class leaves the old or empty image instead of an AV.
  The top bar keeps its previous flag or shows nothing.
* Risk: very low. It changes a path that was always a guaranteed crash on the very next instruction (`0x4C1D9F`).
  Exception: the name cache `this+0xF8` is no longer updated on failure [S]. That is harmless, because callers
  compare names before reloading.

### P2a: the three `%6` sites use the display nation (in-place, no cave for B and C) [S for bytes]
`0x40FC70` = `CStadtLager::GetEffectiveNation`: `mov al,[ecx+0x358]; cmp al,4; jb ret; mov al,[ecx+0x359]; ret` [S]
(clobbers only `al`; its single caller today is `0x4A3DED`).

* **Top bar `0x4A639F`** (26 bytes; the only jump into the range targets its start, `0x4A6300`):
  old `0f b6 86 90 03 00 00 99 b9 06 00 00 00 f7 f9 8d 4c 24 2c 8b 14 95 ec 12 6e 00`
  new `8d 4e 38 e8 c9 98 f6 ff 0f b6 d0 83 e2 03 8d 4c 24 2c 8b 14 95 ec 12 6e 00 90`
  (`lea ecx,[esi+0x38]; call 0x40FC70; movzx edx,al; and edx,3; lea ecx,[esp+0x2C]; mov edx,[edx*4+0x6E12EC]; nop`)
* **Town list `0x4B7C76`** (26 bytes; the only jump in is `0x4B7BD7` to the start):
  old `0f b6 87 90 03 00 00 99 b9 06 00 00 00 f7 f9 8d 4c 24 1c 8b 14 95 ec 12 6e 00`
  new `8d 4f 38 e8 f2 7f f5 ff 0f b6 d0 83 e2 03 8d 4c 24 1c 8b 14 95 ec 12 6e 00 90`
* **Selection panel `0x485E84`**: **do not patch in place.** `0x485D64 jmp 0x485E8B` (convoy branch, eax=nation)
  lands *inside* the range [S]. Patch only the 7-byte `movzx eax,[eax+0x390]` at `0x485E84` →
  `E9 <cave> 90 90`. The cave holds `lea ecx,[eax+0x38]; call 0x40FC70; movzx eax,al; and eax,3; jmp 0x485E8B`
  (16 bytes). Put it in the zero-filled `.text` slack `0x67E455..0x67EFFF` (2987 bytes of 0x00, inside RawSize 0x27E000) [S],
  or use `tools/pe_patch.py` `PatchBuilder.place/detour`.
* Vanilla equivalence: these instructions run only when bit 22 is clear, and for nation 0..3 `0x40FC70` returns the byte
  unchanged. Only towns with byte ≥ 4 and no bit 22 change, and those crashed (5) or would show the pirate icon (4) [S].
  `and …,3` guards a display byte of `0xFF` [H: such towns may exist as unfounded Spezial sites].
* Risk: low. Result: the nation-5 town shows its host power's (display nation's) flag.

### P2b: the three sites send nation 5 to the user-logo branch (matches vanilla player convoys) [S for semantics, needs caves]
Replace the bit-22 tests (`0x4A62F7` 15 B: `mov edx,[esi+0x40]; shr edx,0x16; test dl,1; je 0x4A639F`;
`0x4B7BC6` similar with edi; `0x485DDC` with eax) with `jmp cave` + nops. Each cave does:
`test byte [reg+0x42],0x40; jnz <0.bmp branch>; cmp byte [reg+0x390],5; je <0.bmp branch>; jmp <table branch>`.
The 0.bmp branches are `0x4A6306`, `0x4B7BDD` and `0x485DEB`.
Watch out at 0x4B7BC6: the original interleaves `mov dword [esp+0x60],5` (EH state) between test and jcc, and the cave must keep it.
* Result: player-nation towns show `Run\0.bmp`, the same logo vanilla already shows for the player's own convoys
  (`0x50C7BC`, `0x485C4C`) [S]. This depends on Run\0.bmp existing, which is guaranteed after any New Game (Q4).
  With P1 a missing file only gives a blank flag.
* Risk: low-medium (more bytes and caves). It is the most "native" look for a player nation.

### P3: data-only, repoint table slot 5 [S]
Write `0x6E1300` (4 bytes) `70 99 68 00` → e.g. `a0 99 68 00` (nation03) or a new string.
Fixes all 0x4C1CD0 sites at once with no code change. **Side effect:** vanilla CFlag users of index 5 (town info dialog of
real player towns, battle dialogs) lose the user logo. They are not crashes, but this is a visible vanilla regression, and it
shows a fixed nation rather than the host power. Risk: very low for crashes, medium for cosmetics.

### P4: set bit 22 on the town (no exe patch) [H]
Making the town a "Spielerstadt" sends every bit-22-guarded UI site to Run\0.bmp. But bit 22 is read at about 60 places
(production `0x5F9267`, AI/economy `0x61BC77`, `0x6140AC..`, naming `IDPR_SID_SPIELERSTADT_%02d` at `0x4A3F51`, Lua
`Town_IsPlayerTown`, …), so it changes gameplay semantics. The town-name lookup by `%02d` may be out of range for an
arbitrary town [H]. Risk: medium-high until those readers are audited.

### Rejected
* **(a) "call 0x4C34A0 to register -userflag-"**: there is nothing to register. 0x4C34A0 rewrites its own argument and
  loads into its own widget [S].
* **(b) "provide a file"**: Run\0.bmp already exists after any New Game, and 0x4C1CD0 never translates the sentinel. It asks
  the archive layer for the literal name `-userflag-`. That only works if `arc_CreateMemMapped` falls back to a loose
  relative file and the loader (hint `0`, because the name lacks `.bmp`: `0x4C141E strstr(name,".bmp")`) accepts its format.
  Both are unknown [H]. Not recommended.

---

## Other places a nation-5 town can hit

* **Same null-handle pattern [S]:** all three `%6` sites above (top bar `0x4A63CA`, town list `0x4B7D00`, selection
  panel `0x4860BA`). P1 covers every current and future 0x4C1CD0 user. No other function calls 0x4C13B0.
* **0x4C1CD0 callers that are not nation-related [S]:** `0x4B3436` (pirate hideout `CHP_*`, pirate art), `0x4DB73F`
  (political map `POLITISCHE_KARTE`, loads `images/interface/autohandelkarte.aim`), `0x4E138D/0x4E13B3` (fallback
  loop), `0x52A9B0/0x52AA0B` (names from 0x50C740, never `-userflag-`).
* **Unbounded table index [S]:** `0x4F6484` (battle dialogs) indexes `0x6E12EC` with the raw byte and no `%6`.
  Fine for 5, out of bounds for ≥ 6. Never write bytes ≥ 6.
* **Per-nation 8-byte rows at `0x6A5174` [S/H]:** `0x5A80B0`, `0x5A822C` (fn 0x5A7F40) and `0x5C6A86` (fn 0x5C6A40)
  index `[row(nation)*8 + (x&7)]` without a bound. Rows 0–3 hold sensible data (`00 01 02 03 05 07 08 0a`, …). Row 5 is the
  bytes `32 00 00 00 05 0d 10 15` of whatever follows. This does not crash, but it gives odd values for a nation-5 town
  (meaning of the table unknown) [H].
* The heuristic scan of all 159 `byte [reg+0x390]` reads found no other unguarded `*4/*8` table index [S, heuristic:
  linear-sweep capstone, next 9 instructions].
* Not covered here: the sea-map town marker (no nation-table use found in the sea-map draw paths; the minimap/political
  map do not use 0x6E12EC) [H]. Other per-nation arrays guarded by `cmp x,4` are listed in the private feasibility study [N0-guards].

## Tooling note
The scratch scripts (`uf.py` disasm/xref helper with numpy call index, `d2.py` annotated disasm, `fstr.py` per-function
string refs, `mkpatch.py` patch-byte builder and verifier) are in
`%TEMP%\claude\...\scratchpad\agent_userflag\`.
