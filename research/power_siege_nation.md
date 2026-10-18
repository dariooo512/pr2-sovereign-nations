# Powers besieging nation-5 towns: war missions with target 5

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game was not run.
- **Tools:** pefile and capstone, with a linear `.text` sweep and an E8/E9 xref scan.
- **Scratch scripts** (session scratchpad `agent_siege5/`):
  - `h.py`: `d VA N` disassemble, `c VA` callers, `g REGEX` sweep grep, `vt` dword table;
  - `cl.py`: recursive-descent call-closure scanner that flags `+0x390/+0x358/+0x359/+0xB8`, `g_nations`, IsAtWar and reputation reads;
  - `chk.py`: hook-site check (inward branches and dword refs).
- **Labels:** **[S]** means verified from the bytes (VA quoted). **[H]** means a hypothesis.

Read with `military_combat.md` §4–§5, `military_ai.md` §2.5, `hostility_map.md`, `dll/war.c` and `dll/navy.c`.

## 0. Answer in one paragraph

A power's war fleet already does everything we want against a nation-5 town; the only thing missing is the mission target. A war mission is a type-4 convoy turned into **type 9** by `AssignWarMission 0x5B4870`.
- **Mission fields.** The function writes `+0x172` = target nation, `+0x170` = a "count" byte and `+0x171` = 0 (action). The **`+0x174` 128-bit town mask is never filled by anyone**: init (`0x5B6411`) and abort (`0x5B0768`) set it to all ones, and only a finished sabotage action clears one town's bit (`0x5B537A → 0x5ADBC0`). Every nation-5 town is therefore already a candidate.
- **What the fleet does.** It sails home and docks. After about three harbour sub-steps the picker `0x5B3880` chooses a random town with `town+0x390 == +0x172` whose mask bit is set. The fleet sails there and **anchors** (state 4).
- **Choosing the action.** On arrival it re-validates (`IsAtWar(g[own], +0x172)`, ships > 1). `SelectAction 0x5B07A0` then picks at random among the actions the player's rank allows:
  - **action 1 = siege** (`NewTownAttack 0x603030`). It is offered when `0x63C400` sets mask bit 0x40: at war, wealth `+0x58 > 3`, and cannons > 20×towers **or** sailors > soldiers;
  - otherwise one of the sabotage actions 2..11 (`0x5B5110`).
- **Resolving the siege.** The siege fights a docked defender first, then resolves instantly as a land assault (`0x603200`) or a bombardment (`0x603690`). A win calls `AttackerWon 0x602500`, the existing war.c hook #7.

**I traced every read of `+0x172` and `+0x174`, and every nation-indexed read on this path, with target = 5.** All of them are compares, IsAtWar calls answered by P01 (`IsAtWar(power, 5) = player_rel[power]`), or the guarded `0x5BA400`. The `g_nations` reads on the path are all indexed by the **attacking power's** byte (<4); none is indexed by the town byte or by `+0x172`. **Nothing crashes and nothing misbehaves** [S].

**Recommendation: option (a).**
1. Patch the one immediate at **`0x5B4894` (`80 FB 04` → `80 FB 06`)**.
2. Have the DLL call `AssignWarMission(convoy, 5, count)` (thiscall, `ret 8`, AL = 1 on success) on a power's strongest idle type-4 fleet when that power is at war with the nation.
3. Fix war.c hook #7 to accept **type 9** (today it requires type 4, so it rejects every real power assault).
4. For the first test only, restrict the `+0x174` mask to Margarita, and optionally hook `0x5B09D8` to force action 1.

---

## 1. The war-mission data (Q1)

### 1.1 Field table [S]

Every access to `+0x170..+0x184` in `.text` was found by grep (`+ 0x17x]`, `add/lea reg,0x17x`) and checked in context. Accesses from non-convoy classes are omitted.

| field | meaning | writers | readers |
|---|---|---|---|
| `+0x170` byte | mission "count" (only tested `> 0`) | `0x5B48FE` AssignWarMission (= arg 2); `0x5B63AA` init (dword 0); `0x5B12DF` load (dword `0x170..0x173`, raw) | `0x5AD8FD` validity (`> 0`); save `0x5B0F3B` (dword). **Never decremented anywhere** [S, full grep] |
| `+0x171` byte | action: 1 = siege, 2..11 = sabotage | `0x5B4904` = 0 (assign); `0x5B07B8` = 0 (SelectAction entry); **`0x5B09DF`** = the random choice | `0x5B4DD3` (`== 1` → siege); `0x5B51A2` switch 2..11 (table `0x5B5398`); `0x5B52B4` and `0x5B5309` (arguments to the town lager and to `0x624EA0`) |
| `+0x172` byte | **target nation** | **only `0x5B48F8`** (AssignWarMission) | `0x41B350` (governor dialog: compare with the governor's nation); `0x5AD92D` (validity IsAtWar); `0x5B084B` (SelectAction compare); `0x5B3A46` (picker compare); `0x5B5161` (+ IsAtWar `0x5B5195`); `0x5B5336` → `0x5BA400` |
| `+0x173` | high byte of the saved dword | — | — |
| `+0x174..+0x183` | **128-bit "towns still to hit" mask**, indexed by town handle & 0xFFFF (< 0x80) | ctor `0x5B0E09` = 0; **init `0x5B6411` = all ones**; **abort `0x5B0768` = all ones**; load `0x5B198A` (16 bytes; older saves go through a 64-bit loop at `0x5B16B6`); **`0x5B537A` → `0x5ADBC0` clears the bit of the town after a sabotage action** | picker `0x5B3A96` (bit must be set); save `0x5B117D` (16 bytes) |
| `+0x184` | last mission town handle | `0x5B5354` (after an action); abort `0x5B0779` resets it | save `0x5B1163` |
| `+0x1B0` | destination town handle | picker `0x5B3B78`; cleared by `0x5AD650` | `0x417E40` getter, SelectAction `0x5B07CD` |
| `+0x198` / `+0x19C` | timer / harbour sub-state | arrival `0x5B4AAB` (`+0x19C = 0`), `0x5B4DE8`, `0x5B4E16` | harbour AI |
| `+0x7C & 0x10000` | "veteran": set by abort (`0x5B074A`) | — | war-start prefers it (`0x5F5604`); AssignWarMission skips its news when it is set (`0x5B48ED`) |
| `CEventPeace+0x24` / `+0x28` | time / handle of the last mission (global) | `0x5F569B` / `0x5F5693` | cooldown `0x5F53E1` (`now > +0x24 + 0x3800`) |

So **`+0x174` needs no filling**: a fresh or aborted mission allows every town. A mission ends when:
- validity fails (peace, or ships ≤ 1) on arrival (`0x5B4D71` → abort `0x5B0730`) or at the action step (`0x5B5195`);
- the picker finds no candidate with its bit set (`0x5B3B92..0x5B3B9B` → abort);
- the convoy dies.

### 1.2 `AssignWarMission 0x5B4870` [S]

Calling convention: **`char __thiscall AssignWarMission(CKonvoi *this, uint8 target, uint8 count)`, `ret 8`, AL = 1 on success.** The arguments are read as bytes from dword stack slots (`0x5B488E mov bl,[esp+0x10]`, `0x5B48F4 mov dl,[esp+0x18]`).

Preconditions, in order. A failed precondition returns AL = 0 and changes nothing.
1. `+0xB4 == 4` (`0x5B487C`).
2. **`target < 4`** (`0x5B4892 cmp bl,4 / jae`).
3. `target != +0xB8` (`0x5B489B`).
4. **Local player rank > 1** (`0x5B48AC` 0x402940 → `0x5C2B10` → `0x5A8DA0`, `cmp al,1 / jbe`).
5. `+0x90 != 9` (`0x5B48CA`).

Body:
1. `SetType(9, own)` via `0x637050` on `this+0x4C` (`0x5B48E8`).
2. Write `+0x172 = target`, `+0x170 = count`, `+0x171 = 0`.
3. If `+0x7C & 0x10000` is clear: a captain-name/news call `0x5D89D0(own)` on `0x702CB8` → `0x5D5CF0`. It is indexed by **own** nation (<4).
4. Re-home if the home `+0x44` is invalid (`0x63CA20`).
5. **If state `+0x90 == 0` (at sea):** `+0x168 = invalid`, `0x5AD650` (clear destination), then **`0x5B3880`** (picker).

**Inside the function, `bl` (the target) is used only at `0x5B489B` (compare with own) and `0x5B48F8` (store).** No table is indexed by the target. Allowing 5 here is therefore safe.

Only caller: `0x5F5670` (war-start handler).

### 1.3 Step by step: what a type-9 fleet does [S unless marked]

1. **Picker `0x5B3880`** (thiscall, plain `ret`; callers `0x5B3DC9` at sea, `0x5B49AB` assign, `0x5B4DBB` arrival, `0x5B5692` harbour sub-state ≥ 3):
   - if `+0x1B0` is valid and is not the current town → sail there (`0x5B19D0`);
   - **else if current town ≠ home → sail home** (`0x5B3958..0x5B39DB`);
   - else (at home) build a list of towns with (`town+0x390 == +0x172`, **or** town flag bit 22 with population `+0x38A > 1000`) **and** index < 0x80 **and** mask bit set. A town with `+0x91B0 != 0` is added twice. It then takes a random entry (`0x42D1D0`) → `+0x1B0`, and sails (`0x5B19D0`);
   - an empty list → `0x5AD650` + **abort `0x5B0730`**.
2. **Arrival `0x5B49C0`:**
   - `EnterTown 0x6371D0`. Type 9 goes through table `0x637374` → `0x63731D`: town byte (5) ≠ convoy byte → **anchor, state 4** (`0x637340`). The reputation call `0x5D2D90` is reached only by types 1/2;
   - type dispatch (table `0x5B50CC`), type 9 → `0x5B4D6F`.
3. **Type-9 arrival `0x5B4D6F`:**
   - validity `0x5AD8F0`, else abort;
   - if still type 9: **`SelectAction 0x5B07A0`**;
   - if that fails and we are not at home → picker (usually: sail home);
   - **`+0x171 == 1` → `+0x198 = 0`, `NewTownAttack 0x603030(handle)`, `0x5AD650`** (`0x5B4DD3..0x5B4DFE`);
   - otherwise `+0x198 = 0x40` (wait, anchored).
4. **SelectAction `0x5B07A0`** (thiscall, plain `ret`, AL):
   - needs current town == `+0x1B0` and a valid local player (otherwise it **throws**, `0x5B0A09`);
   - needs `town+0x390 == +0x172` (`0x5B0855..0x5B085B`);
   - calls **`0x63C400(townH, cannons +0x142, sailors +0x86, own)`**, thiscall `ret 0x10`. It sets mask bit 0x40 when `IsAtWar(g[own], town byte)` **and** `town+0x58 > 3` (wealth level) **and** (cannons > 20 × towers `+0x919D` **or** sailors > soldiers `+0x38E`) (`0x63C463..0x63C4BB`);
   - candidate list on the stack at `[esp+0x20]` (count in `bl`):
     - **1** if the siege bit is set and rank > 1;
     - 2 if the player has assets there, rank > 5 and `0x5AAB30 > 50`;
     - 3 if rank > 2; 4 if rank > 3; 5 if rank > 1;
     - 6..11 by rank and town flags;
   - `+0x171 = list[rand % n]` (`0x5B09D8..0x5B09DF`). Actions 4/5/8 also call `0x635960`.
5. **Sabotage (actions 2..11):** the harbour AI for type 9 (`0x5B567D`, sub-state `+0x19C`):
   - away from home, sub-state 1 → `0x5B5110`. It re-checks owner == `+0x172` and IsAtWar, then runs the action helper:

     | action | helper |
     |---|---|
     | 2 | `0x5C4C50` |
     | 3 | `0x5C4CF0` |
     | 4 | `0x5C5E00` |
     | 5 | `0x5C6060` |
     | 6 | `0x6253F0` |
     | 7 | `0x624440` + event `0x5F17E0` |
     | 8 | `0x624460` |
     | 9 | `0x625710` |
     | 10 | `0x5C4D60` |
     | 11 | `0x6244A0` |

     The action names are [H]: town damage or sabotage;
   - it then posts message **0x2B `ID_MSG_BUCC_ATTACK_TOWN_OK`**, a letter, `0x624EA0(action)` and `SetLastBuccActionDate 0x5BA400`, sets `+0x184`, and **clears the town's mask bit**;
   - then sub-state 3 → picker → home → the next town.
6. **Siege:**
   - `0x603030` (cdecl, convoy handle) needs mask bit 0x40 and a current town. A non-player attacker gets the siege object (0x20 bytes, `0x602F30`, vtable `0x6AB5B8`) in the battle store `0x7036C0` and `init 0x602900`;
   - types 4/9 go to `0x6029EC`, which chooses the mode:
     - **land** if sailors > 5 × soldiers;
     - else **sea** if cannons > 20 × towers;
     - else land (`0x602A31..0x602A6F`);
   - state 2 `0x602B00`: a docked type 4/9 with `+0xB8 == town+0x390` (nation-5 navy: 5 == 5) **defends** through a CAutoBattle;
   - state 6 land `0x603200` or state 5 bombard `0x603690` (instant formulas, `military_combat.md` §4.2) → **`AttackerWon 0x602500`** on a win. The return address is `0x6033FB` for land and `0x6039FE` for sea;
   - state 7 `0x602D60` releases the convoy. The mission town's bit is *not* cleared on the siege path, so a failed siege can be repeated later.

"Blockade" is not a separate state. It is the anchored presence (state 4) while the fleet waits and prepares [S for the states, H for the gameplay reading].

---

## 2. How to give a power fleet target 5 (Q2)

| option | how | verdict |
|---|---|---|
| **(a)** | Patch `0x5B4894` `04` → `06`; DLL calls `AssignWarMission(k, 5, n)` | **Recommended.** One byte. Inside the function the target only goes to a compare and a store (§1.2). The only vanilla caller (`0x5F5360`) passes pairs < 4, so vanilla is unchanged. If the fleet is at sea, the picker runs at once with `+0x172 = 5` |
| (b) | No patch. Assign with some power t ≠ own, then write `+0x172 = 5`; if `+0x90 == 0`, call `0x5AD650` + `0x5B3880` again | Works [S], but it is brittle: you must undo a picker run that used t, and a crash or exception between the two steps leaves a real t-mission |
| (c) | Replicate the body (SetType `0x637050`(9, own) on `+0x4C`, write the fields, picker) | Unnecessary; it duplicates the vanilla preconditions |

**`+0x174` needs no write in production** (all ones after init or abort). For the test, the DLL writes the four dwords so that only Margarita's bit is set.

### 2.1 Every read of `+0x172` / `+0x174` with target = 5 [S]

| VA | function | what 5 does |
|---|---|---|
| `0x5AD92D` → `0x5BA0A0` | validity `0x5AD8F0` | `this = g[own]` (real, <4); P01 power-vs-player branch → `player_rel[own]`. **Correct** |
| `0x5B084B` | SelectAction | compare with the town byte. Nation-5 towns pass. **Correct** |
| `0x5B3A46` | picker | compare. Nation-5 towns become candidates. **Correct** |
| `0x5B3A96` | picker | mask bit test. Default all ones. **Correct** |
| `0x5B5161` + `0x5B5195` | `0x5B5110` | compare, then `IsAtWar(g[own], 5)` → P01 → `player_rel`. **Correct** |
| `0x5B5336` → `0x5BA400` | `0x5B5110` | `SetLastBuccActionDate(this = g[own], 5, now)`: guard `0x5BA404 cmp al,4 / jae` → **no write** (no crash; the per-target date is simply not kept) |
| `0x41B350` | governor dialog | compare with the governor's nation (`0x43EDF0`). Harmless |
| `0x63C48A` (town byte, not `+0x172`) | siege flag `0x63C400` | `IsAtWar(g[own], 5)` → P01 → `player_rel`. **Correct** |
| save `0x5B0F3B` / `0x5B117D`, load `0x5B12DF` / `0x5B198A` | convoy save / load | raw copy. A target-5 mission **survives save and load** |

Non-opted-in `g_nations` sites on this path (`0x5AD922`, `0x5B5187`, `0x5B5323`, `0x63C468`, SetType/ClearOwner) are indexed by the **convoy's** nation (the power, <4) → real CNation [S].

### 2.2 DLL prototypes [S]

```c
typedef char (__attribute__((thiscall)) *AssignWar_t)(void *k, uint32_t target, uint32_t count);
#define AssignWarMission ((AssignWar_t)0x005B4870)          /* ret 8, AL=1 ok */
typedef void (__attribute__((thiscall)) *KFn_t)(void *k);
#define WarMissionPlan   ((KFn_t)0x005B3880)                /* picker / sail; plain ret */
#define ClearDestination ((KFn_t)0x005AD650)                /* +0x1B0 = invalid; plain ret */
#define AbortWarMission  ((KFn_t)0x005B0730)                /* type 9 -> 4, mask all ones, +0x7C|=0x10000 */
/* PoolGet 0x41F620 (thiscall pool, handle; ret 4), convoy pool 0x701EE8 (as in war.c) */
```

Call them only from the main thread (`war_frame`), never from inside a hook. `AssignWarMission` edits `CNation+8` through SetType.

---

## 3. The siege path against a nation-5 town (Q3) [S]

I ran a closure scan (depth 3) over `0x603030`, the siege tick `0x603C10`, init `0x602900`, states `0x602B00` / `0x6034D0` / `0x603200` / `0x603690` / `0x602D60`, `0x602500` and `0x6024E0`. It also covered the type-9 path: `0x5B07A0`, `0x5B3880`, `0x5AD8F0`, `0x5B0730`, `0x5B4870`, `0x5B5110`, the ten action helpers, `0x5B19D0`, the type-9 harbour branch and `0x6371D0`.

| site | read | with town byte 5 |
|---|---|---|
| `0x602C4D..0x602C53` | defender: docked convoy `+0xB8 == town+0x390` | nation-5 navy docked in the town defends. Correct |
| `0x63C47B` / `0x63C48A` | IsAtWar(attacker, town byte) | P01 → `player_rel`. Correct |
| `0x6372B0` / `0x6372C1` | IsRepAtLeast25(town byte) | types 1/2 only (not type 9). `≥4` → 1 anyway |
| `0x63731D` | dock or anchor | 5 ≠ power → anchor. Correct |
| `0x5B0855`, `0x5B3A40`, `0x5B5169` | compare with `+0x172` | correct |
| `0x603200`, `0x603690`, `0x602500`, `0x624920`, `0x5C5B30`, `0x61D7F0`, `0x624EA0` | — | **no nation-indexed read** |
| messages `0x2B` / `0x2C` (`0x603AF6`, `0x603B29`, `0x5B52A2`) | argument = `[0x635CA0()+0x22]` (the attacker's captain record [H]) | not the town owner |
| letter create-data 0x30 → `CChronicleBuccaneerAttackTown` (create `0x5DB69E`, vtable `0x6A7DB8`, text `0x5DAAD0`) | town handle → name `0x5D8DE0`; `+0x28` / `+0x29` from the attacker's `0x635CA0` record | no town-owner index |
| `0x5BA400` | per-target date | guarded (§2.1) |

**Verdict: no crash and no wrong behaviour for owner byte 5** on the arrival, action, siege or AttackerWon path [S].

Remaining [H]: message 0x2B/0x2C and chronicle text rendering. They take the town by handle; nation names for 5 already go through `0x5D8E70`, which admits 5 (`nation5_index_safety.md`).

**war.c hook #7 must change** [S]: `h_ai_attack_won` rejects `type != KT_MILITARY`, but the attacker here is **type 9**. Accept 4 or 9:

```c
if ((type != KT_MILITARY && type != 9) || p >= N_POWERS) ...
```

Land (`0x6033FB`) transfers. Bombardment (`0x6039FE`) does not, because of `WAR_AI_BOMBARD_CONQUERS`. Note the bombard rule: with sailors ≤ 5 × soldiers and cannons > 20 × towers (always true with 0 towers), the siege is a **bombardment**, which in the mod plunders but never transfers.

Gameplay notes [S]:
- the nation's navy (type 4) never intercepts a type-9 fleet at sea (`0x5AF330` table `0x5AF81C`: other type 9 → never). It only defends when docked in the target town;
- type 9 does not hunt.

---

## 4. Eligible fleets and how many vanilla sends (Q4) [S]

`0x5F5360(a, b)` (thiscall on CEventPeace, `ret 8`) is called from `CEventPeace::Execute 0x5F577B` after every relation toggle of a power pair.
1. It requires `IsAtWar(g[a], b)` (`0x5F5395`), a local player (`0x5C2AA0`), rank > 1 (`0x5F53D4`), and **`now > CEventPeace+0x24 + 0x3800`** (one mission per 56 days, global, `0x5F53E1..0x5F53F1`).
2. Side choice: for every town owned by a or b it sums `0x5ABBB0(town, player)` `+0x12C + +0x130` [H: the player's buildings or stock there]. It weights each side by `GetReputation`; **the attacking nation is a when rep(b)·Σb > rep(a)·Σa, else b**. The target is the other side (`0x5F563F..0x5F564E`).
3. **Fleet choice from the attacker's `CNation+8`** (head `[n+8]`, node `{next, prev, handle}`, `0x5F5583..0x5F562D`):
   - **if any convoy in the list is already type 9 → no mission** (`0x5F55F7`);
   - the first convoy with `+0x7C & 0x10000` (veteran) is taken at once;
   - otherwise the convoy with the **largest cannons `+0x142` and `+0x1C == 0`** [H: `+0x1C` = "busy / hunting"].
4. `count = rand % (rank/2) + 1`, then `AssignWarMission(target, count)`. The time and handle are stored in `+0x24` / `+0x28`.
5. Separately, `0x5BBB20(0)` runs for both sides on war (`0x5F57BA`) — a fleet build-up to `towns + 3`. But `0x5BBAB0` counts only wars between powers, so **a power at war only with the nation builds nothing extra**.

So vanilla sends **at most one fleet per war-start event, only if that power has no mission running, and at most one per 56 days overall**. `AssignWarMission` itself rejects non-type-4 fleets and fleets in state 9; the mission also needs ships `+0x95 > 1` to pass validity.

What the DLL should copy:
- same fleet choice (veteran first, else max `+0x142` with `+0x1C == 0`, type 4, `+0x90 != 9`, `+0x95 >= 2`);
- **one target-5 mission per power at a time** (no type 9 in its list);
- a mission at war start, then again at most every **0x3800 ticks** while the war lasts;
- `count = rand % (rank/2) + 1`, or simply 1 (only `> 0` matters).

---

## 5. Recommended implementation (Q5)

### 5.1 Patches

| # | VA | old | new | purpose |
|---|---|---|---|---|
| P-A | `0x5B4892` | `80 FB 04` (`cmp bl,4`) | `80 FB 06` | AssignWarMission accepts target 5. DLL `patch_bytes`, same style as the navy opt-ins. Inward refs: none [S] |
| H-7 fix | war.c `h_ai_attack_won` | `type != KT_MILITARY` | accept 4 **or 9** | the real attacker is type 9 |
| H-S (optional) | **`0x5B09D8`**, 7 bytes `8A 54 14 20 80 FA 04` (`mov dl,[esp+edx+0x20]; cmp dl,4`) | hook | — | force or weight the siege. Handler: `k = r->esi`; if `k[0x172] == 5 && *(uint8*)(r->esp + 0x20) == 1` (action 1 is offered) → `r->edx = 0`. The displaced `mov` then loads action 1. Instruction boundaries, no inward branches and no dword refs all checked [S]. Use it always for the test; in production either drop it (vanilla odds) or apply it with a probability |

### 5.2 DLL `siege.c` (main thread, from `war_frame` or the daily hook)

```text
for p in 0..3 with player_rel[p]==1 and the nation owns >=1 town:
    if p's CNation+8 list has a type-9 convoy: continue      # vanilla one-mission rule
    if now < last[p] + 0x3800 and not war_just_started[p]: continue
    k = pick(p)   # type 4, +0x90!=9, +0x95>=2; veteran (+0x7C&0x10000) first, else max +0x142 with +0x1C==0
    ok = AssignWarMission(k, 5, rand%max(1,rank/2)+1)      # AL; 0 => rank<=1 or a precondition failed
    log(handle, ok, +0xB4, +0xB8, +0x172, +0x170, +0x90)
    last[p] = now
on peace with p (optional, vanilla aborts on arrival anyway):
    for type-9 k in p's list with k[0x172]==5: AbortWarMission(k)
```

### 5.3 First test (Spain = 3, Margarita a nation town)

1. **Preconditions:**
   - player rank ≥ 2;
   - Margarita index (handle & 0xFFFF) < 0x80, wealth `+0x58 >= 4`;
   - for a **transferring land assault**: the fleet's sailors `+0x86` > 5 × Margarita soldiers `+0x38E`. For the test, lower the soldiers or pick a crew-heavy fleet. Otherwise you get a bombardment (no transfer);
   - no nation-5 navy docked at Margarita, unless you also want to test the defender battle.
2. Declare war on Spain (`player_rel[3] = 1`) and run the debug call `Nation_ForceSiege(3, Margarita)`:
   1. pick a Spanish fleet, preferably docked at its home;
   2. `AssignWarMission(k, 5, 1)` → expect AL = 1;
   3. write `k+0x174..0x183` = only Margarita's bit;
   4. `ClearDestination(k)`; `WarMissionPlan(k)`. Vanilla calls the picker from the docked harbour state too (`0x5B5692`) [H: safe while docked].
3. **Read back:** `+0xB4 == 9`, `+0xB8 == 3`, `+0x172 == 5`, `+0x170 >= 1`, `+0x171 == 0`, and `k` still in `g[3]+8`.
4. **Observe** (poll every frame and log changes):
   - `+0x1B0` = Margarita handle; if the fleet was away it first goes home;
   - `+0x90` 0 → 4 at Margarita;
   - `+0x171 == 1` (with H-S);
   - a siege object with vtable `0x6AB5B8` in store `0x7036C0`;
   - message 0x2B/0x2C;
   - war.log `WAR AI land assault won at nation town … convoy type 9 nation 3` → `queued` → `transferred`.
5. **Diagnostics:**

   | symptom | cause |
   |---|---|
   | type back to 4 and `+0x7C & 0x10000` set | abort: validity (`player_rel[3] == 0` or ships ≤ 1), or the picker found no town (mask or index) |
   | `+0x171` in 2..11 | siege flag not set (wealth ≤ 3, or neither cannons > 20 × towers nor sailors > soldiers), and H-S is not installed |
   | return address `0x6039FE` | bombardment: plunder only |
   | AL = 0 | rank ≤ 1, convoy not type 4, `+0x90 == 9`, or P-A missing |

## 6. Confidence

- **[S]:** all VAs, the field writers and readers, the calling conventions, the safety of target 5, the save/load of the mission fields, the vanilla fleet choice and cadence, and the hook-site bytes.
- **[H]:**
  - the names and gameplay effect of actions 2..11;
  - the meaning of `+0x1C`, `0x5ABBB0` and `+0x91B0`;
  - the exact text of messages 0x2B/0x2C;
  - that calling `0x5B3880` directly from a docked state is benign (vanilla does it from harbour sub-state 3);
  - travel time: home → target takes days.
