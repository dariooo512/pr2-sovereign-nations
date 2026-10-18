# Player UI for the nation feature: native entry points, without new engine UI

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000) and
`A2dLib-2.20A.dll` (ImageBase 0x10000000), done 2026-10-11 with pefile and capstone.
Every claim is tagged **[S]** (VERIFIED-STATIC: read from the bytes, VA given) or **[H]**
(HYPOTHESIS). Read this together with `lua_bridge.md` (Lua state, error handling, the
`GLOBALS` save, and how the DLL registers C functions and runs Lua on the main thread).

## TL;DR: the recommended design

**A "nation" mission script, defined in a loose `include.ini`, that drives the game's own
mission popups.** The popups are opened by native game-menu events. A DLL hotkey posts the
same event. All text comes from a string table that the DLL registers with the game's own
string manager.

| Piece | How | Evidence |
|---|---|---|
| Script | Loose `lua\config\default\include.ini` (Lua 4, run in the Missions state right after `missions.bin`, at New Game **and** on Load) defines the table `fnn_nation` and calls `Script_Register("fnn_nation","fnn",MTYPE_GLOBAL)`. Add `"fnn"` to `USE_GROUPS`. | [S] §2 |
| Instance | `mstart.ini`: `Global_CreateMission("fnn_nation",-1)`. For older saves, the DLL runs the same call after load; it needs no script context. | [S] §2.3 |
| Trigger | `OnGameMenu(self, menu, sub, opened, p4, p5)` (filter `MEVENT_GAME_MENU`). It fires when the player opens the governor palace (`menu==6`), the town info (`3`), and others. The DLL hotkey posts a synthetic `OnGameMenu` with a private id (`0x4E41`) through the same broadcaster. | [S] §3, §4 |
| Dialogs | `Global_CreatePopup()` → `OnPopupText` returns `hdrId, {bodyIds}, {buttonIds}`. **At most 3 buttons are shown.** `OnPopupClose(self, id, btn)` gets the button that was clicked. Chain popups with a `self.Stage` variable. | [S] §1 |
| Persistent display | `Global_CreateLog(hdr, text, n)` gives a logbook entry. Update it with `Global_ChangeLog` / `Global_AddLogText`. Use `Global_AddMessage(id)` for ticker news and `Global_CreateLetter(hdr, text, n)` for formal notes. | [S] §1.4 |
| Numbers in text | Mission text placeholders `@g$Field$` (gold), `@I$Field$` (integer), `@T$Field$` (town name), `@D$Field$` (date), `@a$Field$` (amount). Each reads a **numeric field of the script's own table**. `<n>` is a line break. | [S] §5.2 |
| New / dynamic text | The DLL builds a `.res` blob (format and hash verified) and calls `CStringManager::Add("FNN", blob, size)`. For changing text (the nation's name), it calls `Remove` and then `Add` again on a second table. | [S] §5 |
| Game state | DLL C functions registered as Lua globals (`FNN_Declare`, `FNN_SetRel`, `FNN_SetTax`, `FNN_GetInfo`, ...). Persistent data goes in `GLOBALS.FNN` (`lua_bridge.md` §2.3). | `lua_bridge.md` |

Recipes for (a) to (e) are in §8.

---

## 1. Popups, letters, logs and messages from Lua

### 1.1 `Global_CreatePopup` (impl `0x42DAE0`) [S]
```
0x42DAE2 call 0x437E40        ; current mission (top of the script stack)
0x42DAEE call 0x417F20        ; its handle
0x42DAF5 call 0x42D020        ; UI request queue (singleton 0x6E7368)
0x42DB01 push 0x15 ; call 0x57E7D0(0x15, handle, 0, 0)
0x42DB08 xor eax,eax          ; 0 Lua results
```
- The function takes **no Lua arguments** and returns nothing. The popup is bound to the
  **calling mission**. All content comes from callbacks into that mission.
- Context is required. `0x437E40` returns 0 when the script stack is empty (`0x437F31`), and
  `0x42DAEE` then dereferences it. So `Global_CreatePopup`, `Global_InstallEventFilter`
  (`0x420D8A`), `Global_CreateLog`/`Letter` (`0x42FAC0`/`0x42FF80`, both start with
  `0x437E40`) **crash if they are called from a bare DLL `lua_dostring`**. Call them only from
  inside a mission callback (§4 shows how the DLL gets into one).

### 1.2 Callback signatures (dispatchers; `self` = the mission instance table) [S]
| Callback | Dispatcher | Lua call |
|---|---|---|
| `OnPopupText(self, popupId)` | `0x44EE90` | `lua_call(.., 2 args, 3 results)` at `0x44EF1F`. Result 1 is the **header id** (`→ ev+0x0C`, `0x44F1A5`). Result 2 is a **table of body ids**, concatenated (`ev+0x18`, loop `0x44F0B4..0x44F165`). Result 3 is a **table of button ids** (`vector<wstring>` `ev+0x24`, loop `0x44EF70..0x44F060`). Every string goes through the mission text resolver `0x436980`. |
| `OnPopupClose(self, popupId, button)` | `0x44E8B0` | `button` = byte `ev+0xC` (`0x44E919`). Ctor `0x44E890`; event type `0x80`. |
| `OnGameMenu(self, menu, sub, opened, p4, p5)` | `0x44DEB0` | Fields `+8,+0xC,(bool)+0x10,+0x14,+0x18`. Ctor `0x44DE70`; type `0x40000`. |
| `OnNPCDlgStart(self, npc)` / `OnNPCDlgEnd(self, npc)` | `0x44E420` / `0x44E350` | 0 results. |
| `OnNPCDlgButton(self, a, b, c)` | `0x44E290` | 3 numbers (`ev+8,+0xC,+0x10`). |
| `OnText(self, a, b)` | `0x450220` | Returns `(number, {ids}, …)`. This is the mission-text system (`MTEXT_STATE=1`, `MTEXT_ACCEPTED=2`). |
| `OnTownBattleEnd(self, t)` | `0x450690` | `t = {attacker, town, land_attack, attacker_wins, annexation}` (`0x4506E4..0x450764`). |

- **Button limit [S].** The popup builder `0x57BEF1..0x57BF99` divides the button vector size
  by 12 (`imul 0x2AAAAAAB`). It switches on 0, 1, 2 and ≥3, and reads at most indices 0..2
  (`call 0x44E950` with index 0/1/2). **A 4th button is ignored.**
- The general dialog template `ALLGEMEINER_DIALOG_800x600.screen` uses dynamic buttons
  (`AGD_Btn_%02d`, builder `0x4D0F40`).
- [H] `button` is the 0-based index into the button table. [H] `popupId` is not a value
  that the script chose: `CreatePopup` returns nothing. Vanilla scripts keep their own
  `PopupId`/`PopupStage` fields, so do the same and keep `self.Stage`.
- [H] You can open the next popup from inside `OnPopupClose`. Vanilla scenario scripts chain
  popups through `PopupStage`.

### 1.3 Callback delivery [S]
- The game makes the call through `CMission::Call(event)` at `0x438170` (thiscall, this = mission):
  1. pushes the mission onto the script stack `0x6E7398` (deque), which is what makes `0x437E40` work;
  2. calls `event->vtbl[1]()` (`0x438216`);
  3. throws `"CMission::Call - Failed to execute event!"` if that returns false;
  4. pops the stack and reads `STATE` (`0x4382E0`).
  **Never set `self.STATE = MSTATE_ENDED (5)`** in the nation script.
- Broadcast events go through `CEventDispatcher::Post(event*)` at `0x450090` (thiscall,
  `ecx = 0x702B0C` = World+0x9CC). They reach every mission that registered a matching mask
  with `Global_InstallEventFilter(mask)` (`0x420D80` → `0x44FDE0(0x702B0C, handle, mask)`).
  Popup callbacks go to the popup's owning mission [H].

### 1.4 Logs, letters and messages (argument checks read from the impls) [S]
| Function | Impl | Lua signature |
|---|---|---|
| `Global_CreateLog(hdrId, textId, n)` | `0x42FAC0` | Returns a log handle. |
| `Global_CreateHiddenLog` | `0x42FC90` | Same shape [H]. |
| `Global_AddLogText(log, textId)` | `0x42F8D0` | |
| `Global_ChangeLog(log, textId)` | `0x423560` | |
| `Global_DeleteLog(log)` | `0x42FE60` | |
| `Global_CreateLetter(hdrId, textId, n)` | `0x42FF80` | Returns a handle. |
| `Global_AddMessage(textId)` / `Global_AddSpecialMessage(textId)` | `0x4306A0` / `0x430780` | 1 string. |
| `Global_LockMessageSystem(n)` | `0x42E470` | |

- Log and letter text goes through the same resolver `0x436980`
  (`0x42FF80` calls `0x436980` twice). [H] `AddMessage` does too.
- [H] The log entry appears in the logbook's mission tab (`SUBMENU_LOG_MISSIONS=4`). It is a
  good place for the permanent "Nation overview".

### 1.5 Literal text
- There is **no raw-string path in Lua** [S]. Every text argument is a *string id*. The
  resolver `0x436980` does this:
  1. calls `g_pStringMgr->vfunc[+8](id, wstr)` (`0x436A1C`);
  2. if the id is found, expands the `@X$field$` placeholders from the mission table;
  3. if not, returns the manager's failure text (`'???'` at `0x684528`, or
     `ERROR LOADING STRING`).
- **None of the 21 placeholder handlers** (jump table `0x437478`, letters A–s) reads a Lua
  *string* field. Each reads type 2 (number) or 5 (table). Free text therefore needs a
  registered string id (§5).

## 2. Can new mission scripts come from loose files?

### 2.1 Loader `CMission::LoadScriptPath` `0x435DF0` [S]
1. Creates `SCRIPT_TABLE` (`0x435E53`).
2. Reads `<lua data dir>/missions.bin` through the archive manager (`arc_CreateFile`, `0x5844C0`)
   and runs it with `lua_dobuffer` (`0x435F1F`).
3. Reads `<script_path>/include.ini` (`0x435FCF`) and runs **it** with `lua_dobuffer` in the
   same state (`0x436076`).
4. Applies `EXCLUDE` (`0x43610D`) and `USE_GROUPS` (`0x436281`): every `SCRIPT_TABLE`
   entry whose `GROUP` is not listed is removed (`lua_next` loop, `0x4367DD..0x43682D`).
- There is **no search for per-mission `.lua` files**. Only `missions.bin` (a single
  `luac` chunk of all `@LUA Mission Source/data/*.lua`) and `include.ini` are loaded.
- **`include.ini` is arbitrary Lua** and runs after `missions.bin`, so it can define and
  register new scripts. Loose files override the archive (`MODDING_GUIDE.md`, verified for
  `mstart.ini`).
- `0x435DF0` also runs on **Load** (`0x43E927`, inside `0x43E8B0`), so the definitions come
  back after loading a save.

### 2.2 `Script_Register(name, group, type)` (`0x41D0F0`) [S]
- It reads the arguments at `top-2, top-1, top`.
- It builds `SCRIPT_TABLE[name] = {TYPE=type, GROUP=group, T_COUNT=0, M_COUNT=1, I_COUNT=0}`.
- `SCRIPT_TABLE` is keyed by the **string** name (lookup `0x433A50`: `pushstring(name);
  gettable`).
- The bytecode constant order in `missions.bin` (`Script_Register`, `shipwrecked`, `seamap`,
  `MTYPE_GLOBAL`) matches `Script_Register("shipwrecked","seamap",MTYPE_GLOBAL)`.
- [S, corrected by the UI implementation] The callbacks live in `SCRIPT_TABLE[name]`, which
  `Script_Register` returns (`0x41D27C`); the engine looks them up there (`_CreateVTbl` `0x4341E0`),
  so scripts write `x = Script_Register(...)` and `function x:OnInit()`. `OnInit` must return a
  non-zero number (`0x433943`), and every dispatched callback must exist. Mission
  instances keep a `vtb` reference to it, which the save writer emits as `" vtb = "` at
  `0x434732`.
- Constants [S] (pushnumber before setglobal in `0x438400..0x43E800`): `MTYPE_GLOBAL=1`,
  `TAVERN=2`, `GOVERNOR=3`; `MSTATE_*` 0..5.

### 2.3 Creating the instance [S]
- `Global_CreateMission(name, n)` (`0x431B50`) makes **no** `0x437E40` call (its whole body
  runs up to `ret` at `0x431CA9`), so the DLL can safely run it from `lua_dostring`.
- `mstart.ini` runs only on New Game (`lua_bridge.md` §2.3), so the DLL must create the
  mission itself for a save that predates the mod. Guard with a flag in `GLOBALS.FNN`.

### 2.4 Using the NPC-dialog framework (tavern, governor) [H]
- `Global_CreateTavernNPC(n, n)` (`0x430EB0`, returns a handle) and the
  `OnNPCDlgStart/Button/End` and `OnText` callbacks would let an "envoy" NPC in the
  capital's tavern carry the diplomacy dialog.
- The `OnText` return contract and the NPC flags are not mapped. Treat this as a **later
  polish** option, not the primary path.
- Governor and viceroy dialogs are vanilla `MTYPE_GOVERNOR` missions. Inserting new options
  into them would mean editing `missions.bin` bytecode, so **don't**.

## 3. Hotkeys

- **Rebindable shortcuts are a fixed set of 15** [S]:
  - name table `0x6E1D9C` (`IDPR_SCUT_FAST … IDPR_SCUT_FIRE`);
  - list loop `cmp edi,0xF` at `0x4E600F`;
  - stored in `options.dat` (`'OPT2'` = `0x3254504F` and version `0x88E` checked at
    `0x5BD1F9`/`0x5BD21F`, then a 0x84-byte block at `0x5BD234`).
  There is no spare slot, and adding one needs engine and options-screen edits.
- **No debug or cheat key hook was found.** A string sweep for
  `cheat|debug|hotkey|shortcut` found only the options screen.
- **DLL polling is the practical path.**
  1. On the per-frame hook (`lua_bridge.md` §4, `0x4038D4`), check
     `GetForegroundWindow()==gameHwnd` and edge-detect `GetAsyncKeyState`, for example
     **Ctrl+N** [H: not one of the 15 defaults].
  2. Post a synthetic game-menu event (§4).

  Pitfalls:
  - The game reads DirectInput, so don't rely on window messages.
  - Ignore keys while an edit box has focus: ship rename `PAL_RenameEdit`, trade route
    `AHS_EditBox`, the gold input `NGE_Edit`, and so on.
  - Ignore keys while the world is loading (`byte[0x700500+0xE44]==0`).
  - Expect focus to be lost on Alt-Tab.
  - Never act from the key thread itself.
  - The user can rebind any of the 15 shortcuts to the same key.

## 4. Getting the DLL into a mission callback (no new UI) [S]

Vanilla posts game-menu events like this (`0x510EF3..0x510F16`, governor menu):
```
push -1; push -1; push 1; push 0; push 6   ; menu=6 (MENU_GOVERNOR), sub=0, opened=1, p4=-1, p5=-1
lea ecx,[ev]; call 0x44DE70                ; GameMenuEvent ctor (ret 0x14), size 0x1C
push eax; mov ecx,0x702B0C; call 0x450090  ; broadcast to filtered missions
```
- The tavern (`0x5104D8`) posts `menu=5` with `p4, p5` = runtime values (town, NPC) [H].
- 48 sites post this event. Menu ids [S]: `LOG=1 CHRONICLE=2 TOWN_INFO=3 TOWN_CONS_INFO=4
  TAVERN=5 GOVERNOR=6 MARKET=7 CHURCH=8 TRADE=9 OFFICE=0xA FACTORY=0xB RESIDENTIAL=0xC
  SHIPYARD=0xD CONVOY=0xE SHIP=0x10 TRANSFER=0x11 BMASTER=0x12 ACTION_TOWN_RCLICK=0x13`.
- **DLL recipe:**
  1. On the main thread, after the load finishes, allocate 0x1C bytes.
  2. Call `0x44DE70(ev, 0x4E41, 0, 1, a, b)` (thiscall).
  3. Call `0x450090(0x702B0C, ev)`.
  4. The nation mission receives `OnGameMenu(self, 0x4E41, 0, 1, a, b)` with the script
     context set.
  Vanilla does not destroy these stack events after posting [S], so no destructor call is
  needed.
- Alternative: call `CMission::Call(mission, ev)` (`0x438170`) directly with your own event
  vtable. That is more work, and only needed for non-broadcast events.

## 5. Text: adding new strings

### 5.1 Where text lives [S]
| Table | Source | Registered |
|---|---|---|
| UI strings (2711, German in this build) | `pr2_arcd.cpr: strings\Original\global\global.res` | A2dLib (`AddScriptDir("scripts")`, `0x4047EC`) [H for the exact path] |
| **Mission/NPC strings** (3548, English: `IDM_*`, `ID_NPC_VICEROY_*`, ...) | **PR2.exe resource `BINARY` #167 (0xA7)**, XOR-chained UTF-16: `out[i]=in[i-1]^in[i]`, `out[0]=in[0]^0x45AD` (`0x404794..0x4047AC`) | `g_pStringMgr->Add("MISSION_NPC_GOODS_INFO", buf, size)` at **`0x4047BF`** |

The id names are in `arcd/scripts/global.h` (2955 names).

### 5.2 `.res` format (decoded both tables; all 2711/3548 entries parse) [S]
```
u32 count
count × { u32 hash; u32 offset /* from byte 4 */; u32 nargs /* distinct %n count */; u32 byteLen }
UTF-16LE text (no terminator)
entries sorted by (int32)hash ascending
```

**Hash** (`A2dLib 0x1002BB30`; `CW32StringManager::LoadStringRes(const string&, wstring&)`):
```c
int32_t h = 0;
for (signed char c : name) h = (h*0x71 + c) % 999999991;   // 0x3B9AC9F7 (verified); 32-bit wrap, C (truncating) %
key = (uint32_t)h;
```
- Verified: `IDA_ALLESTAEDTE` → `0xE6550853` (= HashTable.bin id 0x1000).
- Verified: `ID_NATION_0` → "England".
- Verified: `ID_NPC_VICEROY_HDR` → "Viceroy of %1".

Placeholder letters seen in vanilla text:
- `g` (gold), `I` (int), `T` (town), `D` (date), `a` (amount), `n` (nation), `N`/`F`/`L`
  (names), `P` (pirate), `S` (ship type), `G` (goods), `C` (convoy), `l`/`r`/`M`/`d` (position);
- `@A$USER$` and `@s$USER$` (player address).

Pitfall: C++ `%1` strings, such as the viceroy ones, are **not** expanded by the mission
resolver. Reuse only `%`-free ids.

### 5.3 Registering from the DLL [S]
- Exports of `A2dLib-2.20A.dll`:
  - `?g_pStringMgr@NA2dLib@@3PAVCStringManager@1@A` (data; the exe's IAT is at `0x67F4D0`);
  - `?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z` (`void __thiscall Add(const char* name, const void* data, unsigned size)`; IAT `0x67F4CC`; forwards to vfunc `+0x4C` `AddStringRes`);
  - `?Remove@CStringManager@NA2dLib@@QAEXPBD@Z` (IAT `0x67F4C4`).
- The game frees its own buffer right after `Add` (`0x4047C6`), so Add copies or decodes it
  [S] (keep the buffer alive anyway [H]).
- The lookup **iterates every registered table** (`std::map` at `this+0x10`, loop
  `0x1002C530..0x1002C551`). A new table named `"FNN"` with new ids is found by every
  existing UI path.
- **Dynamic text:** keep a second table `"FNN_DYN"` (nation name, ruler, capital) and
  rebuild it with `Remove("FNN_DYN"); Add("FNN_DYN", ...)` whenever it changes. [H] This is
  safe at runtime on the main thread; vanilla only calls `Remove` at shutdown (`0x4048E6`).
- **Loose `.res` override** of `strings\Original\global\global.res` is possible [H], but it
  replaces the whole UI table and cannot touch the exe-embedded mission table. **Use the DLL
  `Add` instead.**

## 6. Existing native nation UI

| UI | Where | 5th row / player nation? |
|---|---|---|
| Chronicle "Nations" page `NATION_PAGE_800x600.screen` | Built at `0x4B0E9E`. Per-row controls `CHN_Verh_Nat_%i`/`_Ansehen_%i`/`_Flags_%i`/`_Special_%i` (`0x4B11D5..0x4B12FE`) and `CHN_Pop/Strength/Towns/Mili/War_1..4`, all fixed in the binary `.screen`. | **No.** It needs binary `.screen` edits plus code changes. Not cheap. |
| `NPC_NATIONEN_800x600.screen` | 4 fixed buttons `NPN_Btn_00..03` (`0x4D7858`, `0x4D78AC`), labels `ID_NATION_0..3`. A native "pick one of the 4 powers" widget. | It covers exactly the 4 powers diplomacy needs, but it is driven by C++ NPC-dialog code. [H] It is not reachable from Lua. |
| Governor palace | Posts `OnGameMenu(6,0,1,-1,-1)` (`0x510F00`). | Use it as a **trigger**, not as a display. [H] Player-founded towns have no palace, so use `TOWN_INFO (3)` / `ACTION_TOWN_RCLICK (0x13)` there. |
| Viceroy "Your Own Town" strings | `ID_NPC_VICEROY_TOWN_OFFER`, `_TOWN_SELECTED`, `_NEW_LAND_*`, `_ANNEX_*` (exe resource). | The text can be reused, but most of it contains `%1`. Write our own ids. |

## 7. Lua 4 pitfalls (the `missions.bin` header is `1B 4C 75 61 41`, Lua 4.1-work)
- Use `for k,v in t do`, not `pairs`, and `getn(t)`, not `#`. Upvalues use the `%x` syntax.
- `function t:m()` works.
- **Every Lua error is fatal**: `_ERRORMESSAGE` throws (`lua_bridge.md` §1.4). Keep
  `include.ini` code trivial and do the logic in C.
- Store only numbers, strings and tables in `GLOBALS.FNN`.

## 8. Recipes for (a)–(e)

Skeleton (loose `lua\config\default\include.ini`, plus the same lines in any scenario
`include.ini` you support):
```lua
USE_GROUPS = { "tavern", "govern", "global", "seamap", "fnn" }
fnn_nation = {}
Script_Register("fnn_nation", "fnn", MTYPE_GLOBAL)
function fnn_nation:OnCreate()   -- [H] OnCreate runs per instance; OnInit at type level (0x437C06)
  Global_InstallEventFilter(MEVENT_GAME_MENU + MEVENT_TOWNBATTLE_END)
  self.Log = Global_CreateLog("FNN_LOG_HDR", "FNN_LOG_TEXT", 3)
end
function fnn_nation:OnGameMenu(menu, sub, opened, p4, p5)
  if opened == 1 and FNN_WantsMenu(menu, p4) == 1 then   -- C decides: hotkey 0x4E41, own-town info, etc.
    self.Stage = FNN_NextStage(menu); FNN_Fill(self); Global_CreatePopup()
  end
end
function fnn_nation:OnPopupText(id)  return FNN_PopupText(self) end   -- C returns hdr, {body}, {btn<=3}
function fnn_nation:OnPopupClose(id, btn)
  if FNN_OnButton(self, btn) == 1 then FNN_Fill(self); Global_CreatePopup() end  -- chain
end
function fnn_nation:OnTownBattleEnd(t) if FNN_OnConquest(self, t) == 1 then Global_CreatePopup() end end
```
`mstart.ini`: append `Global_CreateMission("fnn_nation", -1)`. `FNN_Fill` writes the numeric
fields used by the placeholders (`self.Treasury`, `self.Towns`, `self.Stab`, `self.Tax`,
`self.Town`).

- **(a) Declare independence.**
  - Trigger: `TOWN_INFO`/`ACTION_TOWN_RCLICK` on an eligible player town, or the hotkey.
  - Popup 1: `FNN_IND_HDR` with body "Found a nation at @T$Town$?" and buttons
    `[name A] [name B] [More…]`. "More…" pages through the preset names, 2 per page plus
    More, or alternatively derived names ("Free State of @T$Town$", "<Player> Republic") built
    by the DLL into `FNN_DYN`.
  - Popup 2: confirm, `[Declare] [Cancel]` → `FNN_Declare(nameIdx, town)`.
  - Typed names have no native Lua path. [H] Fallback: have the player rename a ship to the
    name and let the DLL read it.
- **(b) Overview.**
  - The permanent logbook entry, refreshed monthly via `Global_ChangeLog(self.Log, "FNN_LOG_TEXT")`:
    "Treasury @g$Treasury$ · Towns @I$Towns$ · Stability @I$Stab$ · Tax @I$Tax$%".
  - Also an on-demand popup (hotkey → `[Diplomacy] [Taxes] [Close]`).
  - Relations: 4 body lines `FNN_REL_0..3`, each "England: @n…" or a DLL-generated line in `FNN_DYN`.
- **(c) Diplomacy.**
  - Popup per power, cycling: body "England — at peace", buttons `[Declare war] [Next power] [Close]`.
  - `FNN_SetRel(p, 1|0)` writes `player_rel[p]` (P01/P04).
  - Notify with `Global_AddMessage` and `Global_CreateLetter`.
- **(d) Taxes.**
  - Popup `[Lower] [Raise] [Done]`; the body shows "Tax @I$Tax$% · expected income @g$Income$".
  - Loops via `OnPopupClose` → `FNN_SetTax`.
- **(e) Annex or withdraw.**
  - `OnTownBattleEnd(t)` with `t.attacker_wins==1` and the player as attacker → popup
    "@T$Town$ has fallen" `[Annex to <nation>] [Withdraw]` → `FNN_Annex(t.town)` (the
    `AddToNation(5,1)` path, `0x61BDE0`).
  - [H] Make sure that vanilla's own annexation (`t.annexation`, `0x5BC310`) is not running
    in parallel; see `conquest_transfer.md`.
