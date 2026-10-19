# The human player handle during a New Game: 0x0009FFFF means "no player"

A clean build of the mod crashed on every New Game on a tester's laptop (`0xc0000005` at
`PR2Nation.dll+0x22063`, in `replog_daily()`, about 2 s after "new game ready"). A probe build
logged the human player handle `*(u32*)0x701ED0` at "new game ready" and on the next 40 day ticks:
`0x0009FFFF` every time, on both machines. The DLL's `human()` only tested the handle for 0, so it
returned `PLR_BASE + 0xFFFF * 0x94`, about 9.7 MB past the CPlayer pool, and `replog_daily()` read
the reputation at `+0x54` there. Where that memory is unmapped the game crashes; on this PC it was
mapped and the read returned stable garbage.

The first fix (pr2-sovereign-nations f6770da, pr2-modkit 54e50ed) adds
`(HUMAN_H & 0xFFFF) == 0xFFFF` to the "no human player" test. This note checks that against the
engine.

Labels: **SOLID** = read from the code (capstone on `reverse-engineering/_re/PR2.exe.unpacked.exe`,
sha256 `9c9250bc...`; every address below is a fact in `tools/check_facts.py`, ids `PH-*`) or
measured in the game. **GUESS** = inferred, not checked directly.

## 1. What 0x701ED0 holds, and who writes it

**SOLID.** A player handle is `index (bits 0..15) | type (bits 16..20, 9 = player) | generation
(bits 21..31)`.

- `0x41C510` is the empty player handle constructor: `mov dword [eax], 0x9FFFF`. Type 9, index
  0xFFFF. (`PH-null-handle`)
- The static initializer at `0x67B8F0` runs it on `0x701ED0` (`mov ecx, 0x701ED0; call 0x41C510`).
  The human handle is `0x0009FFFF` from start-up. (`PH-static-init`)
- `0x4028F0` is the typed copy: it starts from `0x9FFFF` and keeps the source only if its type
  bits are 9. `0x402940` copies `0x701ED0` this way; it is Lua `Global_GetPlayer`'s getter.
  (`PH-copy-typed`, `PH-local-getter`)
- `0x701ED0` occurs 7 times in `.text` (`PH-handle-refs`). Only three places write it:

| Where | What it writes | When |
|---|---|---|
| `0x5A86FB` in `CAction::DoCreatePlayer` `0x5A8530` (named by its error string at `0x6A4E88`) | the new CPlayer's handle (`CPlayer+0x20`) | the player is created (§3) |
| `0x5A9DDA` in the CPlayer load `0x5A9B60` | the loaded player's handle, if it is a human (`[CPlayer] == 0`) with an index other than 0xFFFF | a save is loaded |
| `0x5A9FDF` in the CPlayer teardown `0x5A9F30` | `(old & 0x1F0000) | 0xFFFF`: type kept, index 0xFFFF | the human player is destroyed, or the handle no longer resolves to a live player |

So the handle is never 0 while the game runs. Its "no player" value is index 0xFFFF:
`0x0009FFFF` at start-up and after a teardown, which is exactly the value the probe saw.

## 2. Index 0xFFFF is never a valid player

**SOLID.**

- The engine's own handle lookup `0x5C29E0` (thiscall, `ecx = &handle`) takes a handle only if
  (`PH-validate`):
  1. the index is below the pool capacity: `cmp ax, word [0x701EC8]; jae fail`;
  2. the generation matches the slot's tag: `(h >> 21) ^ word [[0x701EC4] + 4*idx + 2]`, low 11
     bits zero;
  3. the record is alive: `byte [record + 0x25] != 0`.

  Otherwise it throws (`_CxxThrowException` with "CHaendlerHandle::operator->() - object pointer
  is 0 ...", `0x6A6958`).
- The pool (`0x701EBC`: records `+4` = `0x701EC0`, slot table `+8` = `0x701EC4`, capacity `+0xC`
  = `0x701EC8`) grows to at most 0xFFFE slots (`0x5A7C43`: `mov esi, 0xFFFE` ... `mov word
  [ebp+0xC], 0xFFFE`, `PH-pool-cap`). So test 1 always rejects index 0xFFFF.
- The engine itself tests the human handle this way. `0x57F3A0` (§3) does `call 0x402940; and ecx,
  0xFFFF; cmp ecx, 0xFFFF; sete al` and creates the player when it is true
  (`PH-create-if-none`). The CPlayer load does the same before it stores a handle (`PH-load-restore`).

## 3. When the real player appears in a New Game

**SOLID (static).** `0x522800` builds the New Game loading sequence. It registers its steps with
`0x4F4990(id, functor, weight)` into a deque, and the weights add up to the progress bar's length.
In order:

| # | Step id | Functor | Weight | What it does |
|---|---|---|---|---|
| 1 | `0x65` | `0x580C20` | 11 | the world generator. Its last state returns 11 at `0x580E5E`, which is PR2Nation's "new game ready" hook (`GH_NEWGAME_DONE`). (`PH-steps-gen*`, `PH-gen-done`) |
| 2 | `0x64` | `0x57F310` | 25 | **the pre-simulation.** Each call runs the world 32 times (`0x57F050`, `PH-presim-run`) and reports progress until `world time [0x702C14] - start [0x701E80] >= [0x6E3354]` (`PH-presim-step`). `[0x6E3354]` = 23040 ticks = **90 game days** (`PH-presim-len`). `0x57F620` is the matching predicate "still pre-simulating" (`PH-presim-pred`). |
| 3 | `0x66` | `0x51FE00` | 5 | `0x57F3A0`: if the human index is 0xFFFF, create the player with `DoCreatePlayer` `0x5A8530`, which writes `0x701ED0` at `0x5A86FB` (`PH-step-player`, `PH-create-*`). `0x57F3A0`'s only caller is this step, and `DoCreatePlayer`'s only caller is `0x57F3A0` (`PH-ifnone-callers`, `PH-create-callers`). |
| 4 | `0x67` | `0x520520` | 15 | the next step (not examined) |

**GUESS (static), SOLID (runtime, below):** the deque runs its steps in the order they were
registered. The code shows `push_back` order and a front pointer at `+0x94`. I did not trace the
per-frame runner that advances it.

**SOLID (runtime).** On both machines the handle is `0x0009FFFF` at "new game ready" and on the
first 40 day ticks (the tester's probe). The fixed build logs the moment the player exists
(`replog.c`, `PLAYER ...`). The feature suite's New Game on this PC logged:

```
22:38:48 new game ready
22:39:35 PLAYER the human player exists (handle 0029003C) after 90 day ticks without one
```

There were exactly 90 day ticks without a player, the same as the 23040-tick constant. The new
player's handle is `0x0029003C`: index 60, type 9, generation 1. The line comes at the first day
tick of the real game, after the player exists. GUESS: the 90 ticks ran in the 26 s before the game screen opened (the panel's top-bar button
was ready at 22:39:14; the tester's probe logged 40 ticks in about 12 s).

So, in a New Game:
- the world is generated;
- 90 days are simulated with no player (handle `0x0009FFFF`, while the DLL's daily hook already
  runs);
- only then is the player created.

The player is valid from the first day tick after the pre-simulation. A loaded game has its player
as soon as the load is done (§1).

## 4. Is `(HUMAN_H & 0xFFFF) == 0xFFFF` right and complete?

- **Right: SOLID.** Index 0xFFFF is the engine's own "no player" (§1, §2), and the engine itself
  tests the handle the same way (`0x57F3BD`). The old `!HUMAN_H` test could never fire while a game
  runs, because the handle is never 0 (§1).
- **Complete for 0x701ED0 in practice: SOLID by the writers.** Three code paths write the handle.
  Each one leaves either index 0xFFFF or the handle of a live player, and the teardown resets the
  handle when its player dies.
  - The fixed DLL now makes all three of the engine's tests, so it never depends on that:
    `eng_human_player()` (`dll/player.c`), with the pure parts in `core_player_index` /
    `core_player_tag_ok` (`dll/core.c`, unit tests `test_player_handle`).
- **What the first fix left out (it touched only the pointer lookups):**
  - `eng_player_fleet()` (`player.c`) counted every valid ship whose owner field equals `HUMAN_H`.
    It still compared against `0x0009FFFF` during the pre-simulation, and an unowned ship or
    convoy could carry that same empty player handle. (GUESS that one does; the empty handle is
    the natural default.) Now it compares against `eng_human_handle()`, which is 0 while there is
    no player.
  - `sight.c` `is_players()` compared convoy owners with the raw handle in the same way. It now
    uses `eng_human_handle()` too.
  - `officials.c` wrote the raw handle into the dialog and indexed the pool by hand. It now uses
    `eng_human_player()` / `eng_human_handle()`.
  - `tools/conquest_test.py` `player_convoys()` indexed the pool with the raw handle. It now
    returns nothing for index 0xFFFF.
- One helper replaces the three copies of `human()` (`player.c`, `replog.c`, `officials.c`), so
  they cannot drift apart again. No other DLL code indexes the CPlayer pool (`grep` for
  `0x701EC0`, `0x701ED0`, `HUMAN_H`, `0x94u *`).

## 5. Old logs on this PC

Each run overwrites the test install's `PR2Nation.log`, and no copies are archived. The only old
log is the tester's probe run of 19 Oct 21:49. It has no `REP` lines at all, before or after
"new game ready".
- That fits the bug: `replog_daily()` prints a line only when a whole-number reputation changes,
  and the memory 9.7 MB past the pool held the same garbage on every tick.
- So on this PC the bad reads were silent. They left no nonsense `REP` lines to find.
