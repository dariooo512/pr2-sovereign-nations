# The "freeze after the autosave" (the idle-fleets-and-freeze report): it was the Quit sequence

The report (a player's report, build 4a14899e) said the game froze right after an autosave: no
response and 0 CPU, with 8 national fleets and an English war fleet at sea. This note covers what
the log shows, what was run to reproduce it, and what changed.

Static facts are from `PR2_target.exe` (capstone, `tools/check_facts.py` QT-*). Runtime results are
from a private probe in the test install.

## 1. What the reporter's log says

```
00:25:44 SAVE: nation '<the player's nation>' written (1064 bytes)      <- Quick Save
00:25:57 SAVE: nation '<the player's nation>' written (1064 bytes)      <- "Autosave 01"
00:25:57 WAR reset: pending conquests cleared                       <- Session::Clear #1
00:25:57 WAR reset: pending conquests cleared                       <- Session::Clear #2
(nothing more)
```

- **Free play has no periodic autosave.** `Autosave 0x57ECC0` (it writes "Autosave 01" to "04" in
  turn, `[0x6E3344]`) has only three callers:
  - `0x424DC7`: Lua `Global_SaveGame("")`, used only by the scenario missions (`missions.bin`);
  - `0x521DBF`: the *Leave to the start menu?* dialog (`IDPR_MM_SURE_LEAVE`, `0x521B60`), which
    saves when the dialog opens;
  - `0x521B26`: **the Quit -> Yes handler** (`0x521850`, `IDPR_MM_SURE_QUIT`). It runs
    `0x5CE9A0` ("can save": no battle running), then the autosave, then the game state's leave
    `[edx+0xC]` = `0x4037A0`, then `PostQuitMessage(1)` (`0x521B39`).
  The SAVE lines every 10 minutes earlier in the log are the player's own saves.
- **Two `Session::Clear` back to back is the Quit signature.** A breakpoint at `0x5809B8` (just after
  the reset hook) shows both returns going into `0x4037E2`:
  - first `0x4037A0` called from the Quit handler (`0x521B37`);
  - then `0x4037A0` again from the state machine's shutdown `0x40A9D0` (`0x40A9DC call [eax+0xC]`).
    This runs after the message loop has ended, before every state object is deleted and the
    process exits.
  - The *Leave* path gives a single Clear. A load gives Clear, a frame, Clear, then a `LOAD:` line.
- So the reporter clicked **Quit**. The game saved, tore the world down twice, and stopped
  responding **on the way out**, not during play. At 0 CPU this was a wait, not a loop.
- The DLL code that runs in that window (reporter's build):
  - the reset hooks: `World::Reset` end H1 rebuilds `g_pc`, `on_world_reset`, `WAR reset`;
  - the redirected `GetTickCount` / `timeGetTime` (`clock.c`, lock-free QPC arithmetic);
  - the DLL's CRT at process detach.
  No frame of the DLL ran between the two Clears (there is no "UI Lua glue registered" line).

## 2. What was run (none of it hung)

| Run | Build | What | Result |
|---|---|---|---|
| quit | reporter (4a14899e) | the reporter's quick save loaded, 30 s, Quit -> Yes | exit in 2 s |
| quit + bp | fixed | same, breakpoint on Clear | exit in 2 s; the call chain above |
| leave | reporter | autosave, Leave -> Yes, 30 s in the start menu, Quit | all fine |
| soak + quit x3 | reporter | the reporter's autosave at 20x plus the fast-forward flag, 3 min, Quit at speed | exit in 2-3 s |
| panelquit x3 | reporter | panel opened on every page, a fleet commissioned and the treasury used from the panel, closed, QuickSave, Quit (as the reporter did) | exit in 2 s |
| soak chain | fixed (merged with master 561a8a9f) | the reporter's autosave, then continued from each chunk's QuickSave: 70 + 85 days at 20x plus the fast-forward flag, 12 days at speed step 2 (5x), 2 days at speed step 1; an autosave every 90 s; Quit -> Yes after each chunk | **169 game days, 16 autosaves, 4 QuickSaves, 4 quits: no hang, each exit in 2 s** |
| soak x3 | reporter | the reporter's autosave at 20x, about 80 days each, then Quit | no hang |

The "clock stuck" stops that the soak probe saw were the game's own **sea-battle popup** (*An English
military convoy is attacking* / Evade / Fight, `_build/shots/t08_pause_1.png`). That popup pauses
the world on purpose while frames keep running. The probe now tells the two apart: a harmless
gamehost call (`0x5CE9A0`) has to return within 15 s, and if it does the probe clicks *Evade*. An
autosave asked for while that popup is open is refused (`0x5CE9A0` is false), which is vanilla.

The hang did not reproduce on this PC. The last DLL action before it in the report is the same as
in every clean run here, so the cause is most likely something outside the DLL's game logic: a
race in the D3D8 / DirectSound / driver teardown at exit (the reporter's machine and drivers differ),
or a lock held by a thread that Windows killed at `ExitProcess`.

## 3. What changed so that the next one can be traced (and one exit-time risk removed)

- **`dll/log.c` writes with `WriteFile` under its own critical section**, not a CRT `FILE*`. At
  `ExitProcess` Windows kills every other thread wherever it is. A CRT stream lock held by such a
  thread would block the CRT's exit-time flush forever: 0 CPU, "not responding". The DLL now has a
  second thread (the watchdog), so the log must not use a CRT stream lock.
- **`dll/watchdog.c`** starts on the first frame. It checks the frame counter once a second.
  After 20 s without a frame (and again at 60 s) it does this:
  - suspends the main thread and copies its context and 16 KB of stack, taking no lock while the
    thread is stopped;
  - resumes it;
  - logs `WATCHDOG: no frame for 20 s ...; main thread eip <module+off>` and the return addresses on
    the stack.

  Loads and long saves can trigger it once, harmlessly. A hang during Quit after the second
  `WAR reset` would now leave the main thread's stack in PR2Nation.log. That is enough to name the
  module it waits in (`tools/hangdump.py` does the same from outside for a game under gamehost).
- Tested with a private probe. A 25 s `Sleep` is called on the main thread through the
  exe's IAT (`0x67F614`). The log then shows `WATCHDOG: no frame for 20 s (frame 43093); main thread
  eip ntdll.dll+0x7858C`, a stack line (ntdll / KERNELBASE / d3d8) and `frames run again after 24 s`.

## 4. Tools

- A private probe: the modes `fleets`, `commission`, `soak`, `quit`, `leave`, `panelquit` and
  `inload`. Join modes with `+`; `--repeat N`; `--quit` / `--quit-fast` end a mode with Quit -> Yes;
  `--bp VA=reads` sets gamehost breakpoints; `--dll` deploys another PR2Nation.dll (for example the
  reporter's build). It takes the shared test-install lock and restores the Save folder.
- `tools/hangdump.py`: suspends each thread of a running `PR2_nation.exe` and prints EIP and the
  return addresses on the stack as module+offset, with each thread's CPU time.
