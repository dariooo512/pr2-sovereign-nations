# Triggering a real player town conquest from an automated test

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game was not launched.
Tools: pefile + capstone (robust linear sweep of `.text`, E8/E9 xref index). Lua binding names were mapped to
impls by scanning the registration function `0x438D90` (317 `Name_X` bindings).

Labels: **[S]** = VERIFIED-STATIC (bytes/instructions quoted); **[H]** = HYPOTHESIS (needs a runtime check).

## TL;DR

- **Use the vanilla land assault (`CCoastBattle`), not the sea assault (`CHarbourBattle`).**
  - The land battle is an automatic simulation. Its only interactive parts are questions in the question
    store, and the harness can answer those with `call`.
  - The sea assault is a real-time sea battle against the fort. Avoid it.
- **Entry point:** `0x603030 NewTownAttack(convoyHandle)` (cdecl). Convoy arrival calls it when the convoy has
  the "Attack towns" flag (`convoy+0x48 |= 0x40`).
- **Answering questions:** OnJa `0x57DF00` / OnNein `0x577780` / third button `0x577A50`. Each is thiscall on
  the question store `*(DWORD*)0x6E7368` and answers the **front** question.
- **No Lua function starts a town attack or conquers a town for the player.** `Town_SetNation` cannot target nation 5.
- **Which mod hooks fire.** A nation conquest fires hook **#3 CoastOffer** (`0x6011BE`), then `war_frame` logs "ready".
  **#4 CoastExecute and #6 HarbourExecute are not on the normal path**: #3 clears vanilla's annex bit, so vanilla
  never reaches its annex state. §5 gives a synthetic way to drive #4.

## 1. Q1: what starts a player attack, and is there an auto-resolve?

### 1.1 Entry chain [S]

| Step | Address | Evidence |
|---|---|---|
| UI button `IAM_Btn_AttackTowns` binds handler `0x472C90` (thiscall panel, bool). For player convoys it sets or clears **`convoy+0x48` bit 0x40** | `0x472F02 mov eax,0x472c90` next to string `0x68D150`; `0x472CE9 cmp [ecx+0xb4],1`; `0x472CFA or byte [ecx+0x48],0x40` |
| Convoy arrival: if the flag is set and the town is not bit 22, it calls `0x603030(convoyH)` | `0x5B4B20 mov al,[esi+0x48] / shr al,6 / test al,1`; `0x5B4B43 call 0x603030` (mod hook #2 at `0x5B4B2D`) |
| `0x603030` (cdecl, 1 arg = convoy handle; war.c calls it "NewCoastBattle") **creates the siege object, not the battle** | see below |

`0x603030` checks, in order:
1. The convoy exists (`0x603072`, pool `0x701EE8`) and has flag `+0x48 & 0x40` (`0x60307D`).
2. A town is found via `0x635C40(convoy+0x4C)`, which reads the town handle at `convoy+0x9C`. `Convoy_GetTown` uses the same call (`0x423BB5`).
3. For player convoys (`+0xB4==1`): town `CStadt+0x40` bit 22 must be clear (mod hook #1 at `0x60309F`), and the
   town must not be protected (`0x624430`: `CStadt+0x50` < `[0x702C14]` world time). A protected town gets question `0x27` and **no battle** (`0x6030CE`).

If the checks pass, it allocates 0x20 bytes, constructs the object (`0x602F30`, vtable `0x6AB5B8`), adds it to the
battle store (`0x5FCCA0` on `0x7036C0`) and initialises it with `0x602900(convoyH)`.

**Siege object** [S]: `+0x0C` convoy handle, `+0x10` town handle, `+0x14` state, `+0x18` question id,
`+0x1C` choice (0 = land, 1 = sea). Tick `0x603C10`, table `0x603C7C`. Player convoys start in state 1 (`0x6029BF`).

| State | Handler | What it does [S] |
|---|---|---|
| 1 | `0x603150` | Posts question **type 2** (land/sea/cancel); flag 1 if `convoy+0x86>0 && +0x138+0x13A>0` (`0x6031AC..0x6031F0`) |
| answer | vfn6 `0x602E20` | `arg==1` → land (`+0x1C=0`), state 2; `arg==2` → sea (`+0x1C=1`), state 2; else state 7 (abort) (`0x602EEF..0x602F1D`) |
| 2 | `0x602B00` | Looks for a defending military convoy in the town (`+0xB4` 4 or 9, `+0x90==2`, `+0xB8 == town+0x390`, `0x602C34..0x602C59`). **If found, starts a real-time sea battle** (`0x5FEF80`, state 3). Otherwise state 4 |
| 4 | `0x6034D0` | Land (player, `+0x1C==0`, sailors>0): (1) `0x5AD5C0(convoy, townH)`; (2) `0x635870(convoy+0x4C)` forces a docked (state 2) player convoy to state 4 = anchored outside (`0x635870..0x63587E`); (3) message 0x31; (4) **`0x601720(&out, convoyH)` creates a `CCoastBattle`** (`0x603637`). Sea: `0x605640(convoyH)` creates a `CHarbourBattle` (0x24C bytes, `0x60359B`). Then state 8 → deleted |

Answers to question type 2 [S]: OnJa calls `vfn6(1)` = **land** (`0x57DFB8 push 1 / call [edx+0x18]`); OnNein calls
`vfn6(0)` = abort (`0x577860`); the third button `0x577A50` calls `vfn6(2)` = sea (`0x577B9B`).

### 1.2 The land battle `CCoastBattle` [S]

**Constructor and creator.** Constructor `0x600C20` (0x88 bytes, vtable `0x6AB578`). Creator `0x601720`
(cdecl, hidden return pointer: `THandle* f(THandle* out, DWORD convoyH)`; writes `0xDFFFF` on failure).

**Precondition `0x5FF3E0(convoyH)`** (`0x5FF425..0x5FF4BB`). All must hold:
- `0x635C40` returns the town, and the town has no running battle (`0x5FD050` on `0x7036C0`);
- `convoy+0xA4` handle is invalid (`&0xFFFF==0xFFFF`) and **`convoy+0x90 == 4`**;
- **`convoy+0x86` (sailors) > 0** and **`convoy+0x138 + convoy+0x13A` > 0** (cutlasses + muskets);
- town `CStadt+0x40` bits 19 and 20 are clear.

**Init `0x5FF9B0(convoyH)`.** Re-checks the precondition and sets the attacker convoy (`+0x14`) and town (`+0x18`).
Sets **`+0x5A = rand()%100 < 50`** (`0x5FFB2D..0x5FFB44`) and `+0x84` = battle length (≥1000, `0x5FFB83..0x5FFB8C`).

**Fields:** `+0x1C` defender army; `+0x28` sim/display object (created in state 2); `+0x2C` open question id
(-1 = none); `+0x3C` troops landed; `+0x4C` tick counter; `+0x54` **state**; `+0x58` outcome bits;
`+0x59` vanilla annexer; `+0x5A` duel flag.

**States** (tick `0x6021C0`, table `0x60231C`; vfn6 = `0x5FF310`, case map `0x5FF3C8`):

| State | Handler | Behaviour |
|---|---|---|
| 0 | `0x600DF0` | setup → 1 (or 0xE on failure) |
| 1 | `0x600FC0` | posts question **type 9** (troop count). vfn6(n): `+0x3C = min(n, +0x44)` → state 2 (`0x5FF32B..0x5FF351`) |
| 2 | `0x601FE0` | builds the armies and `+0x28` → 3 |
| 3 | inline `0x6021FB` | one combat round (`0x6006F0`) every 20 ticks. `+0x4C >= +0x84` → `0x600670` → 4; a side gone → 5 |
| 4 | `0x601000` | more rounds for 0xA0 ticks → 5 |
| 5 | `0x5FFC00` | outcome (below) |
| 6 → 7 | | duel offer (question 8), then the **fencing mini-game** (`0x601950` → `0x60E050`) |
| 8 | `0x6010A0` | **player won**: vanilla annexer argmin, then **mod hook #3 at `0x6011BE`** → state 9, or question 5/0xB/4 |
| 9 | `0x601230` | raid: plunder plus question 6 (or a variable type) → vfn6 → 0xD |
| 10 | `0x6013D0` | **annex**; mod hook #4 at `0x601481` |
| 0xD | `0x601600` | question 0x1B → vfn6 → 0xE |
| 0xE | `0x601A60` | builds the town-battle-end event (`0x450630`), dispatches it to mission filter `0x702B0C` (`0x601D06`) = Lua `OnTownBattleEnd`, then state 0xF |
| ≥0xF | default | removed from the store (`0x60230F call 0x5FCCF0`). Only now does war.c's `battle_alive()` turn false |

**State-5 outcome** (`0x5FFDF9..0x5FFE4E`):
1. Defenders gone (`0x575F50(+0x1C)` false) → `+0x58=1`.
2. Otherwise, `(+0x28)->+0x10 != 0` → `+0x58=0x80` → state 0xC (lost, message 0x35). [H] This field means "attackers beaten".
3. Otherwise `+0x58 = 0/1`. Then if `+0x5A` is set, `+0x58 |= 2` → state 6 (duel); else state 8.

So **the player wins unless the attackers are beaten. Clear `+0x5A` to skip the fencing mini-game.**

**Auto-resolve:** none for the player. The AI's resolvers (siege states 5/6, `0x603690`/`0x603200`) end in
`0x602500 AttackerWon(townH, convoyH)` (mod hook #7, plunder only). The land battle itself needs no tactical input.

### 1.3 The sea battle `CHarbourBattle` (not recommended) [S]

Created by `0x605640(convoyH)`; state at `+0x240`. At the end of the real-time battle, vfn7 `0x606370(bool lost)`
with `arg 0` in state 6 sets state 7 and calls gate `0x605A50` (hook #5) (`0x606384..0x606398`). [H] Unsafe to call by hand.

## 2. Q2: Lua API

**No Lua function attacks a town or conquers one for the player.** [S]
- `Town_SetNation` `0x429200` calls `AddToNation(n,0)`. It refuses seats and player towns and cannot produce nation 5.
- `Convoy_SetMTaskAttack` `0x424E60` takes two convoy handles (type 2) and sets an attack-convoy task via `0x5AD990`. Not a town attack.

Useful helpers (impl VAs from the registration scan) [S]:

| Name | Impl | Notes |
|---|---|---|
| `Convoy_AddSailors(c,n)` | `0x4210A0` | `(c+0x4C)+0x3A += n`, clamped to `convoy+0x88` (max crew) (`0x6415A5..0x6415B6`) |
| `Convoy_GetSailors` / `Convoy_GetMaxSailors` | `0x421280` / `0x421150` | |
| `Convoy_AlterWeapAmmoAmount(c,type,n)` | `0x426C80` | `type<6`, `n>0` only. `0x6390A0` updates `convoy+0x138+2*type`; capped by hold space (`0x638050`) |
| `Convoy_MoveToTown(c,t)` | `0x421440` | refuses convoy types 2 and 5 only, so player convoys are allowed |
| `Convoy_GetTown(c)` / `Convoy_GetState(c)` | `0x423B40` / `0x427A10` | GetState returns `convoy+0x90` (`0x427A83`) |
| `Convoy_SetFlag` / `Convoy_ClearFlag` | `0x425680` / `0x42A620` | change `convoy+0x7C`, **not** the attack bit `+0x48` |
| `Convoy_GetWeapAmmoAmount` | `0x425390` | |

Also present: `Global_GetPlayer 0x41CDA0`, `Global_GetSelectedConvoy 0x42DB10`, `Player_GetConvoyList 0x42D240`,
`Global_SetGameSpeed 0x41F4F0`, `Global_CreateShip 0x4264E0` (3 args), `Convoy_AddSingleShip 0x428610` (2),
`Convoy_AddShips 0x426A70` (2), `Convoy_SetArms 0x42A050` (5 args; reads `+0x86`/`+0x142` [H: per-sailor arming]),
`Global_CreateMilitaryConvoy 0x426810`, `Global_SetMilConvoys 0x42E670`, `Global_SetRelations 0x41D850`,
`Player_HasAnnexMission 0x41DBD0`, `Player_SetAnnexCounter 0x41DC90`.

**Weapon constants** [S] (`0x43D935..0x43D9E0`, `pushnumber(v); setglobal(name)`): `ENTERMESSER`=0 (cutlasses, `+0x138`),
`MUSKETEN`=1 (`+0x13A`), `MASSIVKUGELN`=2, `STREUKUGELN`=3, `KETTENKUGELN`=4, `KANONEN`=5.
`CONVOY_FLAG_NO_FENCING`=0x200000 is a `+0x7C` flag tested in sea-battle code (`0x5FE108`); it does not affect the land duel.

**Mod Lua** (`dll/api.c`): `Nation_DeclareWar(p)`, `Nation_PendingConquest()` (→ `town, former` or -1),
`Nation_ResolveConquest(1|0)`, `Nation_Annex(idx, reason)`, `Nation_GetTown(idx)`, `Nation_TownHandle(idx)`.

## 3. Q3: preconditions and granting troops

**Mod side.** `conquest_applies()` (war.c) needs:
- the nation is founded, and owner byte `CStadt+0x390 < 4`;
- **`rel[owner].status == TREATY_WAR` in the DLL state**. Use `Nation_DeclareWar(owner)`, which also sets
  `0x9F7000[owner]=1`. A raw memory write to player_rel is not enough;
- the town is not a viceroy seat (`CStadt+0x44 & 0x2000`) and not already a member.

**Vanilla side** (§1) [S]:
- a player convoy (`+0xB4==1`) at the town (`Convoy_GetTown(c) == T`) with the attack flag (`+0x48|=0x40`);
- the town is not protected (`CStadt+0x50 < [0x702C14]`), not bit 22, and has bits 19 and 20 clear;
- sailors > 0 and cutlasses + muskets > 0;
- no battle already at the town, and `convoy+0xA4` invalid;
- no defending military convoy docked in the town (otherwise a real-time sea battle comes first).

Vanilla does **not** require war with the owner (attacking only costs reputation [H]).
**Convoy layout** [S] (`CKonvoi` base = `u32(u32(0x701EE8) + 4*(h&0xFFFF))`):
- `+0x48` flags (0x40 = attack towns); `+0x4C` ship-group sub-object; `+0x7C` Lua flags;
- `+0x86` u16 sailors; `+0x88` u16 max sailors; `+0x9C` town handle; `+0xB4` type; `+0xB8` nation;
  `+0x138+2*t` weapon/ammo words;
- `+0x90` state: 2 = in harbour, 4 = anchored outside. Set by `0x640950`. `EnterTown 0x6371D0` picks 2 or 4
  via `0x5D2D90`: a player with reputation ≥ 25.0 with the owner gets 2.

The player's convoys: `CPlayer = u32(0x701EC0) + (u32(0x701ED0)&0xFFFF)*0x94`, list at `+0x2C`, node `+8` = handle (economy_data.md).

**Granting troops.** Prefer Lua: `Convoy_AddSailors(c, Convoy_GetMaxSailors(c))`, then
`Convoy_AlterWeapAmmoAmount(c, 0, N)` and `(c, 1, N)`.
- Crew is capped by ship capacity, so for a bigger force add warships first. [H] Vanilla scripts use
  `Global_CreateShip(type, ?, ?)` + `Convoy_AddSingleShip(c, ship)` that way (pr2_arcs.cpr: `Global_CreateShip … ShipType … TOWN`).
- Writing the words directly is possible but skips the `0x640DF0` recompute [H].

## 4. Q4: recommended recipe (land assault, route A = vanilla)

Notation [S, from OnJa `0x57DF3F..0x57DF44`]: `store = u32(0x6E7368)`; `front = u32(u32(store+4))`, with type
byte `front+8`, id `front+0xC`, battle handle `front+0x10`. Battle pointer = `u32(u32(0x7036C0)+4*(h&0xFFFF))`.

1. **Setup.** Load the feature save (nation founded at Margarita). Run `Nation_DeclareWar(3)` (Spain) via the console.
   Pick a small Spanish town T: not a viceroy seat (`CStadt+0x44 & 0x2000 == 0`), `+0x40` bits 19/20/22 clear,
   `CStadt+0x50 < [0x702C14]`, no military convoy docked.
2. **Grant troops (Lua).** `c = <player convoy handle>`; `Convoy_AddSailors(c, 999)`;
   `Convoy_AlterWeapAmmoAmount(c, ENTERMESSER, 200)`; `Convoy_AlterWeapAmmoAmount(c, MUSKETEN, 200)`.
   Check `Convoy_GetSailors(c) > 0` and `Convoy_GetWeapAmmoAmount(c, 0/1) > 0`.
3. **Sail.** `Convoy_MoveToTown(c, Nation_TownHandle(T))`, plus `Global_SetGameSpeed`. Poll `Convoy_GetTown(c) == handle(T)`. Then either:
   - set the flag **before** sailing, so arrival itself calls `0x603030` (the exact vanilla UI path); or
   - after arrival, `write <convoy+0x48> (byte|0x40)`, then `call 0x603030 0 <c>`.
4. **Siege question.** When front type == 2 and `front+0x10` is the new siege: `call 0x57DF00 <store>` (OnJa = land).
   If `bp 0x602D1D` hits, a defending fleet started a real-time sea battle: abort and choose another town.
5. **Land battle.** Get the pointer with `bp 0x6017F6=edi` (edi = CCoastBattle*), or from the next question.
   **Write `battle+0x5A = 00`** (no duel). When front type == 9 with `+0x10` == the battle handle:
   `call 0x5FF310 <battle> 0x7FFF` (vfn6; lands `min(n, +0x44)` men), then `call 0x57DDD0 <store>` to close it.
   This is exactly what OnJa does (vfn6 + `0x57DDD0`, `0x57E066..0x57E06B`).
6. **Optional speed-up.** Once `+0x54 == 3`, write `+0x84 = u32(+0x4C)`: the sim ends next tick through vanilla's
   `0x600670`. State 4 still runs 0xA0 ticks of rounds. Do **not** jump straight to state 5 (`+0x28` is needed and
   `0x600670` closes the display [H]).
7. **Win.** State 8 runs mod hook #3. Expect:
   - `WAR conquest recorded: town T (...) from power 3 (Spain), coast battle … handle …`
   - `WAR coast: vanilla annexer … cancelled (+58h xx->xx); vanilla continues (raid / no transfer)`
8. **Raid and end.** While front `+0x10` == the battle handle, repeat `call 0x57DF00 <store>`: first the raid
   question (state 9 → 0xD), then type 0x1B (0xD → 0xE). The battle broadcasts `OnTownBattleEnd` and is removed
   in state 0xF. The DLL logs `WAR conquest of town T (...) ready: battle ended, awaiting Annex/Withdraw`, and
   `Nation_PendingConquest()` returns `T, 3`.
9. **Decide.** Either:
   - **(a) API:** `Nation_ResolveConquest(1)` → `WAR conquest of town T (...) from Spain: ANNEX -> ok`. Then, if the
     mod popup (type 0x15) is at the front, close it with `call 0x57DDD0 <store>`.
   - **(b) UI:** `fnn_on_battle` opened `FNN_P_CONQUEST` (popup type 0x15). `call 0x57DF00 <store>` = button 0 =
     **Annex** (`0x57E165 push ebx(0)` → `0x44E890` popup-close event); `call 0x577780 <store>` = button 1 =
     **Withdraw** (`0x577937 push 1`).
10. **Check.** `CStadt+0x390 == 5`; `Nation_GetTown(T) == 1`; Spain's `Nation_GetNumTowns` dropped by 1; the
    `WAR` log lines above; no `SECOND … UNHANDLED`. On withdraw: owner still 3, no `FX_TOWN_TO_NATION`.

**Negative test (hooks #1/#2).** Repeat steps 3–4 against a nation-5 town. Expect `WAR refuse: player attack on
own-nation town …` (hook #1 via `0x603030`) or `… arrival attack …` (hook #2), the ticker message, and no new store object.

**Route B (fallback; skips the siege and its defender sea battle).** With c at T:
1. `call 0x5AD5C0 <convoy*> <townH>`;
2. `call 0x635870 <convoy*+0x4C>` (makes state 4);
3. `call 0x601720 0 s:x <c>` (the `s:` argument just supplies 12 bytes of scratch for the hidden `out`
   pointer; `0xDFFFF` written there means failure). Then continue at step 5. [H] This is the same sequence
   siege state 4 runs (`0x6035EE..0x603637`), minus message 0x31.

## 5. Driving #4 CoastExecute / #6 HarbourExecute

**#4 is defensive.** It fires only in state 10, which needs `+0x58&4` to survive state 8. #3 clears that bit
whenever a nation conquest applies, and #4 needs a conquest pending for the town.

Synthetic test, after step 7 (state 9, raid question open):
1. `call 0x57DDD0 <store>` to drop the raid question. A stale question would make OnJa throw (battle lookup NULL →
   `0x57E0FB _CxxThrowException`).
2. Write `battle+0x2C = FFFFFFFF`, `+0x59 = 03`, `+0x54 = 0A`.
3. Next tick `0x6013D0` passes `0x6013DD` (`+0x2C==-1`) and reaches `0x601481`. Hook #4 logs `WAR coast execute: …
   -> withdraw path` and forces `0xFF` → `jae 0x60155D` → state 0xE → normal end. The conquest stays pending.
4. [H] The two `vfn[0x30]` calls and `0x5D4AC0` that `0x6013D0` makes before `0x601481` look read-only.

**#6** needs a real-time `CHarbourBattle` **and** a vanilla annexation order against the owner (`CNation[p]+0x154`
type 0x17, made only by `0x5BA260` from the viceroy dialog). Not practical to automate.

## 6. Side findings

- **The Lua UI does not use the war.c resolver** (`include.ini` lines 447–455, VERIFIED source):
  - Annex calls `Nation_Annex(idx, 0)`, not `Nation_ResolveConquest`. The pending entry is later dropped with
    `WAR conquest of town … dropped: … owner now 5`.
  - Withdraw calls nothing, so the entry stays pending and `Nation_PendingConquest` keeps returning it until the owner changes.
  - Consider calling `Nation_ResolveConquest(btn==0 and 1 or 0)` in `FNN_P_CONQUEST`.
- war.c names `0x603030` "NewCoastBattle", but it creates the **siege** object (vtable `0x6AB5B8`); the coast battle comes later via `0x601720`.
- The question store is a singleton (`0x42D020` → `&0x6E7368`, `0x42D076`). The answer functions act on the front
  node only, so always check `front+8` (type) and `front+0x10` (battle handle) first.

## Confidence

- **Static chain:** high. Every address and offset above was read from the bytes.
- **The recipe working first time:** medium. Open runtime points: (1) calling `0x603030`/`0x5FF310` from the
  harness hook (InputProcessor, UI thread) rather than the game tick; (2) the strength needed to avoid the
  `+0x58=0x80` loss; (3) the troop clamp `+0x44`; (4) defender fleets that trigger the sea battle in route A.

## Automated test

`tools/conquest_test.py` runs §4 as **CON-01** and the negative test as **CON-02**. It has not been run yet.
- **CON-02** runs first, at Margarita. Once the nation is founded, Margarita is nation 5 and the start convoy is there.
  The test sets `+0x48|=0x40`, runs `call 0x603030 0 <c>`, and expects the hook #1 `WAR refuse` line and no type-2 question.
- **CON-01** gives the convoy troops, sails with the attack flag set, and declares war only on arrival. Declaring war
  earlier would let Spanish fleets intercept the convoy at sea. The test then answers the questions, which needs
  `bp 0x6017F6=edi` for the battle and `bp 0x602D1D` to detect the sea battle. It resolves with
  `Nation_ResolveConquest(1, T)` and checks the result.

Every wait has a timeout. When a step stalls, the FAIL line names it, and `CONQUEST_RESULTS.md` keeps the full step log.
Run: `python tools/conquest_test.py` (options: `--build`, `--town IDX`, `--route B`, `--resolve ui`, `--no-speedup`).
