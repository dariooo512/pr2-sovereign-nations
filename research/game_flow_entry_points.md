# PR2 game-flow entry points (static RE)

Target: `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). Every VA below was
disassembled from the real bytes with capstone (helper: scratch `agent_flow/pe.py`).
Labels: **VERIFIED-STATIC** = checked in the bytes. **HYPOTHESIS** = inferred, not proven.
The game was not run.

## 0. Singletons and objects you need

| What | How to get `this` | Evidence |
|---|---|---|
| App (`CW32WalhallaClient` subclass, "PortRoyale2") | `app = *(DWORD*)0x6E5958` (lazy accessor `0x405A20` returns `&0x6E5958`; ctor `0x4056C0`, size 0x10C, vtable 0x680440) | VERIFIED-STATIC |
| **Main-menu controller** ("CMenu", size 0x78, ctor `0x521210`) | `menu = *(DWORD*)(app + 0xE8)`. It is created in the app's `Enter` override `0x4057B0` (only if null) and then initialised by `0x525D60(menu, inGame=0, 0, 0)` | VERIFIED-STATIC |
| In-game menu controller (same class) | Created lazily by `0x507DD0` into `[iface+0x5C]` and initialised with `0x525D60(…, inGame=1, …)`. Which global holds `iface` is unresolved. `[[*0x6E58E4]+0xF0]` is the best guess (that pointer feeds `0x51CAA0`, which looks like the same class) | HYPOTHESIS |
| **Game/session object** (save, load, sim clock, speed) | **Static object at 0x700500** in .data. It is **not** a pointer: use `ecx = 0x700500` directly | VERIFIED-STATIC (every call site does `mov ecx,0x700500`) |
| Game-settings block written by the setup screen | static at `0x701E48..0x701EB0` (names at 0x701E4C/0x701E58, nation 0x701E7C, start town 0x701EAC, etc.) | VERIFIED-STATIC (writes in `0x4F29D0`) |
| Other lazy singletons | `0x403360` returns `&0x6E58E4` (main game obj, 0x120 B). `0x4033E0` returns `&0x6E58EC` (0x1D0 B, settings/options). `0x405140` returns `&0x6E5938` (path manager; `0x409830` builds the save directory) | VERIFIED-STATIC |

### Menu controller layout (offsets used below)
`+0x04` main-menu screen, `+0x08` button bar, `+0x0C` loading-task queue (created in menu state 12, ctor `0x4F4860`), `+0x10` byte **inGame** (0 = main-menu instance), `+0x11` byte scenario mode, `+0x1C` **free-game setup screen** (SPIELEINSTELLUNGEN, created in state 6), `+0x3C` **current menu state**, `+0x48` step sequencer (`0x526F20` add step, `0x526A70` run, `0x526CD0` clear), `+0x54` sequencer wake time, `+0x5A` keep-setup-screen flag. VERIFIED-STATIC.

### Menu state machine: `0x522CD0` `void __thiscall Menu::SetState(int state)` (ret 4)
It is a switch with jump table `0x5257DC` over states 1..13. The table below maps each button to the slot it is bound to (button text ID → slot VA). VERIFIED-STATIC.

| state | buttons → slot |
|---|---|
| 1 main menu | FREEGAME→`0x522460`, SZENARIO→`0x51FDF0`(→state 4), LOAD→`0x521E60`, OPTIONS→`0x51FCF0`, CREDITS→`0x51FDE0`, EXIT→`0x521850`. Also sets `+0x10=0`, `+0x11=0` |
| 2 in-game menu | QUICKSAVE→`0x522730`, LOAD/SAVELOAD→`0x521E60`, OPTIONS, QUIT→`0x521B60`, EXIT, BACK_TO_GAME→`0x521760` |
| 3 save/load list | LOAD→`0x4EDEB0`, SAVE→`0x4EC810`, DELETE→`0x4EDA40`, BACK |
| 4 scenario | sets `+0x11=1`; EINSTELLUNGEN→`0x522460` |
| 6 **free-game setup** | STARTGAME→**`0x522A60`**, GAMEPLAY→`0x51FF00`(→state 10, keeps setup screen), BACK. Creates the setup screen into `[menu+0x1C]` if it is null (`0x524376`) |
| 12 | loading/GAMESTART state (creates the task queue `[menu+0xC]`) |

Every state switch first calls `0x5202A0`, which **destroys `[menu+0x1C]`** unless `+0x5A` is set.

---

## 1. Start a new free-play game (default settings)

Click path: main menu "Free game" (`IDPR_MM_FREEGAME`) → setup state 6 → "Start game" (`IDPR_MM_STARTGAME`).

### 1a. `0x522460`: Menu::OnFreeGame (FREEGAME button). VERIFIED-STATIC
- `void __thiscall (Menu* this)`, no args, plain `ret`.
- `this = menu = *(DWORD*)(*(DWORD*)0x6E5958 + 0xE8)`.
- Clears the sequencer, then queues these steps and starts them with `0x526A70`:
  1. `0x4E8590` slides out the main-menu screen.
  2. `0x51FF30(100)` waits 100 ms.
  3. `0x522CD0(6)` switches to the setup state, which creates the setup screen in `[menu+0x1C]`.
  4. `0x4E8140` shows the setup panel.
- **The steps run asynchronously on later frames.** The call returns immediately, so the debugger must resume the game. Then poll until `[menu+0x3C]==6 && [menu+0x1C]!=0`.
- Alternative: call `0x522CD0(menu, 6)` directly (thiscall, 1 int arg, ret 4). This is synchronous but skips the slide-out animation (HYPOTHESIS: harmless).

### 1b. `0x522A60`: Menu::OnStartGame (STARTGAME button). **Best "new game" entry.** VERIFIED-STATIC
- `void __thiscall (Menu* this)`, no args, plain `ret` (0x522CC4).
- **Hard precondition:** `[menu+0x1C]` (setup screen) must be non-null. The function does `mov ecx,[esi+0x1C]; call 0x4F29D0` with no null check. `0x4F29D0` (SetupScreen::Commit) copies name, nation, start town, capital and difficulty from the widgets into the settings block at 0x701E48. **Calling 0x522A60 from state 1 will null-deref.** Do 1a first and wait for state 6. The "default settings" are whatever the setup screen pre-fills.
- Queued steps (async, sequencer `[menu+0x48]`):
  1. `0x51FE10`: `0x700500.0x57E9A0()` (session init: autosave interval 600000 ms, autosave name, registry watchdog), then switches the app state to "MainGame" through `[0x6E5924]->vf1C()->vf0("MainGame")`.
  2. `0x4E8590` fades the menu.
  3. `0x51FF30(250)` waits 250 ms.
  4. `0x51FF60`.
  5. `0x522CD0(12)` switches to the loading screen.
  6. `0x522800` queues the world-creation tasks on `[menu+0xC]`: `0x580C20` on 0x700500 with arg "" (an 11-phase incremental world generator; phase counter `[0x700500+0x40]`), `0x57F310` on 0x700500 (first sim tick), `0x51FE00` and `0x520520`.
- **Everything after the call happens over many frames inside the main loop.** Do not hold the main thread. A good completion signal is the sim-clock running flag `byte [0x700500+0xE44]` turning 1 (see item 4) or the loading screen going away (HYPOTHESIS).
- Cross-check: `0x51FE10` and `0x580C20` appear in `record-replay-tests/out/create_game_targets.tsv` (create-game-only functions) and `0x57E9A0` (its callee) is in there too. That agrees with this path. VERIFIED (file contents).

**Recipe:** `menu=*(*(0x6E5958)+0xE8)` → `call 0x522460 (ecx=menu)` → resume, poll `[menu+0x3C]==6` and `[menu+0x1C]!=0` → `call 0x522A60 (ecx=menu)` → resume.

Risks:
- Must be in main-menu state 1 (or 6) with no modal dialog open.
- Re-entrancy: both functions clear and rebuild the shared step sequencer. Never call a second menu action while a sequence is still running.
- The string/allocator state is STLport (`stlport_vc745.dll`). These two calls take no string args, so they are safe.

---

## 2. Save the game to a named slot

### Lua binding `Global_SaveGame` impl `0x424D20` (cdecl `int f(lua_State*)`). VERIFIED-STATIC
Registered at 0x43A7B0 (`push 0; push 0x424D20; …; push "Global_SaveGame"`). It takes the name as a string from Lua (arg 1):
- If the name is `""` (literal at 0x67FB81), it calls **`0x57ECC0`** with `ecx=0x700500` (rotating autosave).
- Otherwise it translates the name through `0x437E40`→`0x436980` (string-manager lookup into a wide string), narrows it with `0x401290`, copies it into a by-value `std::string`, and calls **`0x580E70`** with `ecx=0x700500`.

### Core: `0x580E70` `bool __thiscall Session::SaveGame(std::string name)` (**ret 0xC**). VERIFIED-STATIC
- `ecx = 0x700500`. **The arg is a 12-byte STLport `basic_string<char>` passed by value** (`_M_start, _M_finish, _M_end_of_storage`). The **callee destroys it**: at 0x58104E it calls the string destructor on `[esp+0x48]`.
- It serialises with `0x5807C0` (twice, to size and then fill), compresses with `0x581AC0`, and builds the path `0x405140()->0x409830(&dir,0)` + name + `".pr2"` (`[0x6E4368]`). It writes with `fopen("w+b")`/`fwrite`/`fclose`. It returns `AL=1` on success.
- The name is the bare file stem (no dir, no `.pr2`), e.g. `"agent_test"`.
- **How to call from the debugger:**
  1. Allocate 12 bytes and run the STLport ctor import `[0x67F9B8]` (`basic_string(const char*, const allocator&)`, thiscall, `ecx=buf`, push `&dummyAllocByte`, push `char* name`, callee cleans 8).
  2. Copy those 12 bytes onto the stack as the argument and call `0x580E70` with `ecx=0x700500`.
  3. Do **not** destroy the string yourself (the callee frees it through the STLport allocator).
  A hand-made struct pointing at debugger-allocated memory would be freed by the wrong allocator: **heap-corruption risk.**
- Precondition: a game must be loaded (in-game). It does not pause by itself. The UI wrapper `0x4EC810` also handles overwrite prompts, a thumbnail and a timer.

### Simpler no-arg alternatives (same `ecx=0x700500`). VERIFIED-STATIC
- **`0x57EE90` QuickSave():** no args, plain `ret`. It localises `IDPR_SCHNELLSPEICHERN_NAME` and calls `0x580E70`. The in-game menu QUICKSAVE slot `0x522730` calls this and then shows the "IDPR_MM_SPIEL_GESPEICHERT" message.
- **`0x57ECC0` AutoSave():** no args, plain `ret`. It saves only if `0x5CE9A0(ecx=0x702140)` returns true (an iterate-and-check, HYPOTHESIS: "no blocking state"). It cycles the counter byte `0x6E3344` from 1 to 4 and builds the name with `sprintf([0x700500+0xE4C], n)`, where `+0xE4C` is the `IDPR_AUTOSAVE_NAME` pattern set up by `0x57E9A0`. It then calls `0x580E70`.

Risk: these hit the disk synchronously on the calling thread (fine on the main thread). Saving during the create-game sequence or a sea battle is untested (HYPOTHESIS: unsafe).

---

## 3. Load a saved game by name

From the save/load list, LOAD → `0x4EDEB0` (list screen handler; it may first show the "IDPR_SGO_BEENDEN_LADEN" confirmation). It then calls:

### `0x526470` `void __thiscall Menu::StartFromFile(const std::string& name)` (ret 4). **Best load entry.** VERIFIED-STATIC
- The only direct call is at 0x4EE1B4: `ecx=[screen+0xE4]` (the menu), arg = `&selectedEntry->name` (entry+0x18).
- The arg is a **const std::string\*** (passed to the STLport copy-ctor `[0x67F9C4]`, so it is copied immediately). A hand-built 12-byte struct `{p, p+len, p+len+1}` over debugger memory is **safe** here because it is only read. Name = bare stem (".pr2" and the save dir are added by `0x580470` / `0x5815E0`).
- It branches on `byte [menu+0x10]`:
  - **0 (main-menu instance, `menu=*(app+0xE8)`):** steps `0x51FE10` (session init + "MainGame"), fade, wait 250 ms, `0x51FF60`, `0x522CD0(12)`, then `0x525FD0(name)`. `0x525FD0` queues the incremental loader **`0x581940`** on `0x700500` (`(std::string name)` by value, ret 0xC; phase counter `+0x40`). That loader opens the file via `0x580470` (archive `arc_CreateMemMapped` on `<savedir>\name.pr2`).
  - **≠0 (in-game instance):** steps `0x521760` (back-to-game), fade, `0x51FD00`, wait 100 ms, then **`0x5261C0(name)`**. `0x5261C0` tears down the current world (interface/sea/town objects), calls `0x5815E0(ecx=0x700500, const char* name)` (a synchronous LoadFile, ret 4, AL=ok), and then rebuilds.
- **Recipe (from the main menu):** build the string struct → `call 0x526470 (ecx=menu, push &str)` → resume the main loop. The rest is async (loading screen tasks).
- Preconditions: main menu idle (state 1), no sequence running, the file must exist. Error handling for a missing or corrupt file is not traced: `0x581940` returns -1 and resets on open failure (HYPOTHESIS: the menu may hang on the loading screen).
- **Do not** call `0x5815E0` directly while in game. It is only one step of the teardown/rebuild in `0x5261C0`.
- Loading from in-game needs the in-game menu instance (see §0, HYPOTHESIS pointer). Its pointer is unresolved, so loading from the main menu is the safer route.
- Note: the hinted addresses 0x449E98 / 0x4B6F59 are **not** load code. Both are `0x5D83C0(ecx=0x702CB8)` calls after `0x43EDD0`. VERIFIED-STATIC.

---

## 4. Game speed / pause

### Lua `Global_SetGameSpeed` impl `0x41F4F0` (cdecl `int f(lua_State*)`). VERIFIED-STATIC
Registered at 0x43A67B. It does `lua_tonumber(L,-1)` then `0x57F550(ecx=0x700500, idx)`.

### `0x57F550` `void __thiscall Session::SetGameSpeed(BYTE idx)` (ret 4). VERIFIED-STATIC
- `ecx=0x700500`. If `idx>=5`, idx becomes 1. Then `[0x700500+0x20] = speedTable[idx]`.
- The table is at `0x6A500C` (WORD): `[8000, 800, 160, 80, 40, 0, 8]`.
- `[+0x20]` is **milliseconds per sim tick**: `0x57F110` divides elapsed time by it and runs at most 8 ticks per frame.
- Speeds: idx 1 = 800 ms is the default/normal (the clamp target), 2 = 5×, 3 = 10×, 4 = 20×, 0 = 10× slower.
- Related functions: `0x57ED80` (speed up one step), `0x57EDB0` (slow down one step), `0x57F570(bool)` fast-forward (sets `+0x44`, saves the speed in `+0x24`, forces table[6]=8 ms).

### Pause / unpause (sim clock running flag `byte [0x700500+0xE44]`). VERIFIED-STATIC
- `0x57F280` (per-frame tick) runs the simulation only while `+0xE44 != 0`.
- **Unpause/run: `0x57EFD0`** `void __thiscall ()` (ecx=0x700500, plain ret). It returns without doing anything unless the list from `0x42D020()` (`*[obj+4]`) is empty (HYPOTHESIS: open modal/blocking requests). Otherwise it sets `+0xE44=1`, resets the clock base `+0xE3C=timeGetTime()` and posts a pause-changed event (`0x44E710`, which feeds Lua `OnPauseGame`) to queue 0x702B0C.
- **Pause: `0x57EDF0`** (ecx=0x700500, plain ret). It sets `+0xE44=0` and posts the event.
- App focus hooks in vtable 0x67FF58/0x67FF5C: `0x402B70` (resume = `jmp 0x57EFD0`) and `0x402B80` (fast-forward off + pause).

**Recipe:** `call 0x57EFD0 (ecx=0x700500)` then `call 0x57F550 (ecx=0x700500, push idx)`. Check `byte [0x700500+0xE44]==1` afterwards. If it is still 0, a modal is open and blocking the resume.

Risks: calling while not in game is harmless for the speed setter (it only writes a field). Resuming while a dialog expects the game paused may desync the UI (HYPOTHESIS).

---

## General debugger-call rules
- Run every call on the main/UI thread. Menu and game objects are not thread-safe.
- Menu actions (1a, 1b, 3) only **queue** sequencer steps or loading tasks. Return and let the message loop run. Never block inside the call waiting for completion.
- STLport strings: by-reference args can be hand-built. **By-value args must be built with the STLport ctor import `0x67F9B8`**, because the callee frees them.
- All functions use thiscall (`ecx=this`, callee cleans: `ret N`). Lua impls are cdecl.
