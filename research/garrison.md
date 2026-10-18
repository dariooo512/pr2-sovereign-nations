# Garrisons and town defence for nation-5 towns

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game was not run.
Tools: pefile + capstone over the cached linear sweep of `.text`. Scratch scripts are in the session scratchpad
`agent_garrison/` (`g.py`, `nat.py` nation-byte call-tree scan, `facts.py`). `facts.py` re-disassembles every
instruction fact this note relies on: **59/59 PASS**.

Labels: **[S]** = VERIFIED-STATIC (instruction text read at that VA). **[H]** = HYPOTHESIS (meaning inferred).

Notation: `t` = `CStadt*`, `L` = `t+0x38` (CStadtLager). Lager offset = CStadt offset − 0x38. `B` = the town
budget object at **`t+0x91C8`** (5 dwords, not a single "order" field). `S` = soldiers `u16 t+0x38E`.

## 0. Answer in one paragraph

Garrisons and cannon towers in PR2 are **not** paid by the owning power. Every town has a 5-dword budget object
at `t+0x91C8`. The daily town tick `0x5C6D70` fills it for free from the town's own size and spends it on
soldiers (1000 gold each, word `0x6E4F78`) and cannon towers (building type 0x1A `KANONENTURM`, 50000 gold each,
word `0x6E4F7C`, at most 10 per town). Recruits arrive every other day: `n = min(budget/1000, isqrt(budget)/10,
free housing)`. A soldier needs a free house place, and population grows by n. Accrual stops once soldiers reach
**20 % of the target population**. Above that level, soldiers are slowly dismissed whenever the budget is empty.

This tick is called from the per-town timer `0x5EF7D0` at `0x5EF848`, **before** the `nation >= 4` guard at
`0x5EF979`. The skipped block is the governor-seat transport-convoy generator, which has nothing to do with
defence. The whole recruit/tower call tree has **no nation-byte read**. So **nation-5 towns already grow a
garrison and cannon towers exactly like the powers' towns**, provided they do not have flag bit 22 (vanilla
"Your Own Town"). Bit-22 towns take the player-funded path instead.

A change of owner (player land conquest, annexation, `AddToNation`) does not touch `S` or `B`. Only the battle
does: after a player land battle the town loses **one third** of the defenders killed. After an AI auto-assault
it loses half of the computed loss.

For the DLL, the clean levers are:
- add gold to the soldier budget with vanilla `0x5C4B50` (thiscall `t`, `int* amount`, ret 4; capped at
  civilians/3);
- add gold to the tower budget with `0x623CB0` (thiscall `t+0x91C8`, `(L, amount)`, ret 8);
- disband with `0x5C5B30` (thiscall `t`, `n`, ret 4).

In each case the DLL books the cost against its own treasury. No P03-style displacement patch is needed for
growth. The two defence sites that read the raw nation byte (`0x63C47B` AI attack decision, `0x602C53`
defender-fleet match) should **not** be switched to the display byte (§5).

## 1. How a town recruits soldiers (Q1)

### 1.1 Call chain [S]

| VA | What | Evidence |
|---|---|---|
| `0x5EF7D0` | Per-town timer event (vtable ref `0x6AADD4`). Returns `0x100` = rescheduled every **1 day** | `0x5F01C3 mov eax,0x100` |
| `0x5EF848` | `call 0x5C6D70` (CStadt daily tick), **unconditional**, before the guard | `0x5EF846 mov ecx,ebp / call 0x5c6d70` |
| `0x5EF979` | Guard `movzx eax,[ebp+0x390] / cmp eax,4 / jae 0x5F01C3` for the AI-owner block | facts G-tick-guard |
| `0x5C6DF7` | `local10 = S`. Then, for every house of the town (pool `0x701ED4`): `local10 += 4*[h+0x112]`, `t+0x168 += [h+0x130]*k`, `t+0x16A += [h+0x130]*k − [h+0x132]` (`k = [0x6AC15C]`). So `local10 = T` = **target population** (soldiers + 4 × households [H]), `t+0x168` = housing capacity, `t+0x16A` = free housing [H names, S arithmetic] | `0x5C6E1A..0x5C6E65` |
| `0x5C6ECD` | Skip all recruiting while a battle runs at the town: `0x5FD050` (thiscall `ecx=0x7036C0`, arg town handle, ret 4, bool) | facts G-battle-skip |
| `0x5C6EDB` | `t+0x40` **bit 22** (player town) → `0x623840(B, &T, L)` only (player-funded) | facts G-bit22 / G-player-recruit |
| `0x5C6EF9` | else (every other town, **any nation byte**) → `0x623BD0(B, &T, L, wealth u8 t+0x58)` | facts G-ai-recruit |
| `0x5C6F83..` | if `T != pop`: `0x5C50C0(t, T)` re-houses the town to the target, then `pop = t+0x168 − t+0x16A` (`0x5C88C0`) | facts P-pop |

### 1.2 The budget object `B = t+0x91C8` [S layout, H names]

| Off | CStadt off | Meaning | Writers / readers |
|---|---|---|---|
| +0x00 | `0x91C8` | **soldier budget** (gold) | accrue `0x6237E0`, spend `0x623840`, player order `0x5C4B50`, refund `0x5C5CAF` |
| +0x04 | `0x91CC` | donated treasure pot (decays −100/day, capped by rank `0x623B60`) | `0x623CE0`, `0x623C00` |
| +0x08 | `0x91D0` | accrued treasure pot (+T/2 per day, cap T×50 − pot4; skipped when wealth == 3) | `0x623C25..0x623C38` |
| +0x0C | `0x91D4` | **cannon-tower budget** (gold) | accrue `0x623C5D`, `0x623CB0`, spend/wipe `0x6239D0` |
| +0x10 | `0x91D8` | time of the last tower build (`[0x702C14]`) | `0x623C9D` |

- `+4` and `+8` together are the **raid plunder** (`0x6237C0` returns `+4 + +8` and zeroes both; it is called
  from coast-battle state 8 at `0x60128C`, AttackerWon `0x6025B3` and the harbour battle `0x605BB6`).
- Save `0x623A50` (from the CStadt save `0x5C6504`); load `0x623AD0` (from `0x5C66F1`). **DLL writes persist.**
- `S` itself is saved and loaded by the Lager (`0x5C98E5` / `0x5C9B87`), and so is the musketeer ratio `L+0x35A`.

### 1.3 Rates and caps (AI path `0x623BD0`, ret 0xC) [S]

**1. Accrual, daily: `0x6237E0(B; T, S)`, ret 8.**
- It accrues only if `T/5 > S` (`0x6237E5..0x6237F7`).
- `r = min(0x10000, T*90 / max(10, S) − 300)`.
- `B+0 += (T + 5000) * r / 5000`.
- Example: T=3000, S=100 gives r=2400 and +3840 gold/day. At S=500: +384/day. At S=600 = T/5: none.

**2. Recruit / dismiss: `0x623840(B; int* T, L)`, ret 8.** It runs only on odd day-of-year
(`0x623841 test byte [0x702C18],1`).

- **Hire** when `B+0 >= 1000`:
  - `n = min(B/1000, isqrt(B)/10 (0x41C6F0), freeHousing u16 L+0x132)`;
  - in bit-22 towns, `T + n` is also capped at 500, at 2000 (bit 17), or at 65000 (bits 17 + 11) (`0x623911..0x623959`);
  - then `B −= n*1000; *T += n; L+0x356 += n` (`0x623964..0x623979`).
- **Dismiss** when `B < 1000` and `T < 5*S`:
  - remove `min(1 + S/200, S − civilians/4)` via `RemoveSoldiers 0x5C8870(L, n)` (soldiers −n, population −n);
  - then `*T −= n` (`0x623862..0x6238C2`).
- The result is a **soft equilibrium garrison of about 20 % of the population** (`S ≈ T/5 ≈ civilians/4`).
  Free housing limits the rate.

**3. Cannon towers (same function):**
- If towers `L+0x9164 (t+0x919C) < 10` and `< T/1000 + 2`, then `B+0xC += T/2 + 500` per day.
- When `B+0xC > 50000` and more than 7 days (`0x700` ticks) have passed since `B+0x10`, it calls `0x6239D0`.
- `0x6239D0` builds `0x61F3B0(L, noOwner, 0x1A, 1)` and, if the count went up, `B+0xC −= 50000`.
- **If the build fails, `B+0xC` is set to 0** (`0x623A37`).

Hard cap: 10 towers (`0x61FCD9 cmp [esi+0x9164],0xa / jae fail`).

**4. Town creation `0x61BAB0`:** `0x623990` sets `S = min(capacity − pop, pop/4)` (`L+0x130`, `L+0x352`).

### 1.4 Do nation-5 towns gain soldiers today?

- **Yes [S static; runtime unconfirmed].** `nat.py` scanned the call trees of `0x623BD0`, `0x623840` and
  `0x6239D0` to depth 3 for byte loads at `+0x358/+0x359/+0x390/+0x391`. It found none (the only hit,
  `0x628CC6 lea eax,[edi+0x390]`, is arithmetic).
- The mod's founding and annex paths (`eng_town_to_nation` → `AddToNation` force path) do **not** set bit 22, so
  these towns take the AI path with free accrual.
- A vanilla Spielerstadt (bit 22) that joins the nation recruits only from what is ordered into `B+0`.
  It never accrues anything for free.

### 1.5 Owner changes [S]

- None of the writers of `S` (complete list in §4.1) and none of the users of `t+0x91C8` lie in
  `AddToNation 0x5C9DA0`, the annex transfer `0x5BC310`, coast-battle states 8, 9 or 10, or `eng_town_to_nation`.
  A town keeps its garrison and its budgets when it changes owner, and recruitment carries on for the new owner.
- **Player land battle** (CCoastBattle state 5, `0x5FFD6B..0x5FFDD6`):
  - `loss = (S − survivorsSabre − survivorsMusket) / 3`, read from the defender army `battle+0x24` via `0x572B60`;
  - `0x5C5B30(t, loss)`.
  - So **the town keeps two thirds of the killed defenders**. A conquered town comes to the player's nation with
    at least 2/3 of its old garrison.
- **AI auto-assault** (siege resolver `0x603200`):
  - `r = (rand − 0.5)*k + S/(sailors + 1)`;
  - defender loss = `S / r²`, of which half is applied (`0x603333 → 0x5C5B30`);
  - the attacker loses `sailors * r²`, half applied (`0x6415D0`);
  - the attacker wins if more sailors than soldiers remain → `AttackerWon 0x602500`: plunder only.
- **Emigration** `0x5C5B60` (Lua `Town_RemoveCitizens 0x42B6CB`, plus `0x61D6BA`, `0x625B10`) takes soldiers last
  and **refunds** `n*1000` into `B+0` (`0x5C5C9D..0x5C5CAF`), so they are recruited again.

## 2. Harbour defence (Q2)

**Storage.** The building store is at `L+0x9148` (`t+0x9180`): array `t+0x9184` (stride 0x14), cap `t+0x918C`,
head `t+0x9190`, plus per-class counters. `0x622370` (remove) shows them:

| t off | L off | Meaning |
|---|---|---|
| `0x919C` u8 | `0x9164` | cannon towers (type 0x1A) |
| `0x919D` u8 | `0x9165` | **finished** towers (entry `+0x11` bit 7) |
| `0x9192` u16 | `0x915A` | tower-slot bitmask (`1 << (entry+0x11 & 0x3F)`) |

Lua `Town_GetHarbourCannons 0x427010` counts finished type-0xD0 entries (0x1A<<3), capped at 10.

**No walls.** There is no wall or fort building type. Lua types 0x10..0x1F include `KANONENTURM` = 0x1A.
The land battle's "fortified" flag is `t+0x40` bit 18 or `t+0x44 & 0x2001` (governor or viceroy seat):
- `0x602121..0x602135` [S];
- bit 18 is set once the population exceeds 6000 (`0x5C8C0A`) and never cleared [S];
- it selects 200 instead of 100 from word table `0x6E2D1C`, which goes to `0x575EE0`. That function writes the
  value to word `+8` of every entry of the battlefield list `+0xE29C` [S]. Meaning: defender cover/HP [H].

**How towers are built.**
- AI path: automatically, §1.3.
- Player: via the General NPC dialog (type-3 NPC, vtable `0x682440`, strings `ID_NPC_GENERAL_ADD_CANNONS` /
  `_ADD_SOLDIERS`) → `CPlayer::InvestInTown 0x5D52F0` kind 0, or by building them in the player's own town
  (build menu cap `0x614150 cmp [ebp+0x919C],0xa`).

**Where towers are used [S]:**

| VA | Use |
|---|---|
| `0x604F40` (CHarbourBattle setup, from `0x605767`) | Walks the building list. Every 0xD0 entry becomes a shore battery via `0x5FE290` (finished ones only: `0x614B70` must return 0 [H]) |
| `0x602A31..0x602A72` (siege init `0x602900`, AI attacker) | **Land** if `sailors > 5*S`, else **sea** if `convoy cannons +0x142 > 20*finishedTowers` |
| `0x63C400` (AI military target test, from `0x5B0896`) | Sets the attack flag `convoy+0x48 |= 0x40` only if `IsAtWar(convoyNation, t+0x390)`, wealth > 3, and (`cannons > 20*finishedTowers` or `men > S`) |
| `0x63C4D0` (from `0x5B4D2E`) | Same tower test, plus a global cooldown `0x702044` |
| `0x603690` (AI sea auto-resolve) | Strength from `t+0x919D` against convoy cannons. Destroys up to `finishedTowers` random towers via `0x61D7F0` → `0x622370` |

## 3. Land battle defenders (Q3) [S]

**State 0 init `0x5FF9B0`.**
- Attacker: sailors `+0x48`, cutlasses `+0x40`, muskets `+0x44`.
- `0x5C8940(L, cut, musk)` sets the town's musketeer ratio `L+0x35A`: 0x80 / 0 / 0x40 or a proportional value,
  plus `rand & 0x7F` (default 0x7F at init and on load).
- **Defenders:**
  - `+0x30 = sabres = S − musketeers` (`0x5C8910`);
  - `+0x34 = musketeers = S*(510 + ratio)/1275` (`0x5C88E0`), i.e. 40–60 % musketeers.
- The **whole garrison defends.** There is no per-soldier unit multiplier.

**State 2 `0x601FE0`.**
- Attacker landing: the landed men are removed from the convoy (`0x6415D0`, weapons `0x6379E0`).
- `0x6248C0(L)` sets `L+8 |= 0x100000` (town under attack).
- It builds the map `+0x1C` (0xE2A8 bytes, from the town layout `t+0x3A0`), the attacker army `+0x20` and the
  defender army `+0x24` (0x830 bytes each). Then `0x572BB0(map, att, def, attCounts, defCounts{+0x30,+0x34},
  fortified)`.
- Figure size (`0x572A30`): `q = clamp(maxSide/90, 3, 10)` figures for the larger side. Men per figure =
  `maxSide/q`, and each side's count is divided by that (constants `0x6E2D10..18` = 3, 10, 90).
- Battle length `+0x84 = max(1000, attackers, defenders)`.

**State 5 writeback.** See §1.5 (one third of the losses). The attacker's survivors go back to the convoy.

**AI attackers** never build a CCoastBattle; they use `0x603200` (§1.5). The battle-scene code
(`0x576090`, `0x572320`, `0x5723C0`, `0x601D30`, `0x6008D0`, `0x6006F0`, `0x600670`) reads no nation byte
(depth-3 scan).

## 4. Adding soldiers and towers from the DLL (Q4)

### 4.1 Complete list of writers of `S` (`t+0x38E` / `L+0x356`) [S]

| VA | Fn | Write |
|---|---|---|
| `0x5C8884`, `0x5C8891` | `0x5C8870` RemoveSoldiers (thiscall L, n, ret 4) | `S −= n` (floor 0), `pop −= n` |
| `0x623979` | `0x623840` recruit | `S += n` |
| `0x6239B8` | `0x623990` creation init | `S = min(free, pop/4)` |
| `0x5C9B87`, `0x5C9BB2` | Lager load | |
| `0x5C9F2A` | Lager init | |

**No Lua binding writes `S`.**
- `Town_AlterSailors 0x42AB50` is the tavern sailor pool.
- `Town_RemoveCitizens` only removes people.
- The only Lua reader is `Town_GetWorkers` (= pop − S).

### 4.2 Engine calls (all `__thiscall`; in the mod's style `__attribute__((thiscall))`)

| VA | Signature | Notes | Level |
|---|---|---|---|
| `0x5C4B50` | `void AddSoldierBudget(CStadt* t, int* amount)` ret 4 | If `*amount > 0`: `h = 0x5C4AF0(t)`. If `h > *amount`, `B+0 += *amount`. Otherwise `B+0 += h; *amount = h`. **`*amount` on return = gold actually booked** | S |
| `0x5C4AF0` | `int SoldierBudgetHeadroom(CStadt* t)` ret | `max(0, ((civ/30)*10 − S)*1000 − B+0)`, i.e. the order cap is civilians/3 | S |
| `0x5C4A90` | `int MaxOrderableSoldiers(CStadt* t)` ret | `(civ/30)*10 − S − B+0/1000` (palace-UI number `IDPR_PAL_MAX_SOLDIERS`) | S |
| `0x623CB0` | `void AddTowerBudget(void* B /*t+0x91C8*/, void* L, int amount)` ret 8 | `amount > 0`: `B+0xC += amount`, then `while (0x6239D0(L)) ;`. Builds one tower per 50000 | S |
| `0x6239D0` | `bool TryBuildTower(void* B, void* L)` ret 4 | needs `B+0xC >= 50000`; on failure **zeroes `B+0xC`** | S |
| `0x5C5B30` | `void KillSoldiers(CStadt* t, int n)` ret 4 | `RemoveSoldiers(L, n)`, then re-house (`0x5C50C0(t, pop)`) | S |
| `0x5C8870` | `void RemoveSoldiers(L, int n)` ret 4 | no re-house | S |
| `0x5D52F0` | `void CPlayer::InvestInTown(CPlayer*, u32 townH, int amount, u8 kind)` ret 0xC | vanilla donation, **paid from player gold** (ledger cat 0xC). kind 0 = towers, 1 = soldiers, 2 = treasure pot. Needs a human player, gold ≥ amount and `player+0x8C`. Reputation `0x5D45F0` is guarded `nation < 4` (`0x5D4614`): none for a nation-5 town | S |
| `0x5FD050` | `bool BattleAt(ecx=0x7036C0, u32 townH)` ret 4 | vanilla skips recruiting while true | S |

### 4.3 Direct write (fallback)

`*(u16*)(t+0x38E) += n` with `n <= *(u16*)(t+0x16A)` (free housing). Do **not** write population `t+0x38A`:
the next daily tick computes `T = S + 4Σhouseholds` and re-houses through `0x5C50C0`, and `0x5C88C0` overwrites
pop anyway.
- Side effect: soldiers above `T/5` are dismissed again (`1 + S/200` per 2 days) once `B+0 < 1000`.
- So keep a direct boost within about 20 % of the population, or keep the soldier budget topped up.

## 5. Nation-byte reads in defence code (Q5)

| VA | Read | Behaviour for nation 5 | Display-byte (+0x391) patch? |
|---|---|---|---|
| recruit / towers `0x623BD0` tree | none | identical to the powers | not needed |
| `0x63C47B` (AI attack decision) | raw `t+0x390` → `IsAtWar 0x5BA0A0` | with **P01**, power vs 5 = `player_rel` → the player nation's enemies attack its towns (correct) | **No.** +0x391 would make the host power's enemies attack instead and ignore the player's wars. Risk high |
| `0x602C53` (siege state 2, defending military convoy) | raw `t+0x390` vs `convoy+0xB8` | no convoy has `+0xB8 == 5` (setter `0x637050` refuses ≥ 4), so a nation-5 town never gets a defending fleet and attackers go straight to the land/sea assault | **No** as a plain patch: +0x391 would let the host power's docked warships defend a player town, even at war with the player. A national navy needs its own design (convoy nation 5 reaches the null-CNation military AI paths, `null_nation_census.md` §2). Risk high |
| `0x5D53D8` (InvestInTown) | raw → `0x5D45F0` (guarded) | no reputation for donating to the own nation | No (intended) |
| `0x5D4A63` (`0x5D4A50`, attack penalty) | `L+0x358` → guarded `0x5D4840` | none for 5 | No |
| `0x60DA67` (fencing) | raw → `0x5D8E70` (`ja` bound, admits 5) | random row | No |

**Conclusion:** no one-byte fix is required for garrison or tower growth. The P03/P05/P07 sites are not on the
defence path.

## 6. Recommended implementation

1. **Keep vanilla growth.** Nation-5 towns already accrue, recruit and build towers on their own (§1.4). Add a
   runtime check to the feature suite: log `S`, `B+0`, `B+0xC` and `t+0x919C` for a nation-5 town across about
   10 game days. Expect `S` to grow every other day until about pop/5, and towers up to `min(10, pop/1000 + 2)`.
2. **Make the treasury pay.** In the monthly accounts (`core.c` upkeep), charge per town
   `S × soldier_wage + towers × tower_upkeep`. `TownSnap` gets `cannons = t[0x919D]`.
   When the treasury is insolvent:
   - stop growth by zeroing `*(i32*)(t+0x91C8)` and `*(i32*)(t+0x91D4)`;
   - optionally disband with `KillSoldiers(t, n)`.
3. **"Grows with the nation".** Each month, per member town, compute a target garrison D from nation strength,
   war state and town size. Then:
   ```c
   typedef void (__attribute__((thiscall)) *AddSB_t)(void *t, int *amount);
   #define PR2_AddSoldierBudget ((AddSB_t)0x005C4B50)                    /* ret 4 */
   typedef void (__attribute__((thiscall)) *AddTB_t)(void *B, void *L, int amount);
   #define PR2_AddTowerBudget   ((AddTB_t)0x00623CB0)                    /* ret 8, ecx = t+0x91C8 */
   typedef void (__attribute__((thiscall)) *Kill_t)(void *t, int n);
   #define PR2_KillSoldiers     ((Kill_t)0x005C5B30)                     /* ret 4 */
   ```
   - **soldiers:**
     ```c
     int a = min(D - S, budgetCap) * 1000;
     PR2_AddSoldierBudget(t, &a);
     treasury -= a;
     ```
     `a` comes back clipped to the headroom. Vanilla turns the gold into men at up to
     `isqrt(B)/10` every 2 days, limited by free housing.
   - **towers:** if `t[0x919C] < 10` and the treasury holds ≥ 50000:
     ```c
     uint8_t c0 = t[0x919C];
     PR2_AddTowerBudget(t + 0x91C8, t + 0x38, 50000);
     if (t[0x919C] == c0) refund 50000;  /* B+0xC was wiped */
     ```
     Alternatively write `*(i32*)(t+0x91D4) += x` and let the daily tick build the tower (7-day spacing, cap
     `min(10, T/1000 + 2)`); that path never loses money.
   - Above about 20 % of the population, vanilla dismisses soldiers whenever `B+0 < 1000`. Either cap D at pop/5
     or keep a small standing budget (≥ 1000) in `B+0` for those towns each month.
4. **Calling rules.**
   - Main thread only, inside the sim tick (`GH_DAILY` / the monthly hook).
   - Skip a town while `0x5FD050(0x7036C0, townH)` returns true (battle running).
   - Re-resolve `t` from the handle every time.
5. **Do not** patch `0x63C47B` or `0x602C53` to the display byte (§5). Defence against attacks then comes from
   `S` (land; AI picks land when `sailors > 5S`) and the towers (sea; AI attacks only if `cannons > 20 ×
   finishedTowers` or `men > S`). Both are raised by step 3, so the deterrence scales with what the nation buys.
6. **Conquest.** No action is needed: the captured town keeps at least 2/3 of its garrison and its budgets
   (§1.5). Optionally zero the old owner's accrued `B+0` / `B+0xC` in `eng_town_to_nation` if the treasury is
   meant to pay for every recruit.

## 7. Open points [H]

- Runtime confirmation of §1.4 (no in-game check yet).
- Names: `t+0x168` capacity / `t+0x16A` free housing and `[house+0x112]` = households are inferred from the
  arithmetic. The 100/200 "fortified" value semantics are inferred too.
- Whether `0x61F3B0(…, 0x1A, 1)` builds a tower already finished (bit 7 of `+0x11`) or under construction.
- Meaning of the bit-22 town caps (500 / 2000 / 65000, flags bits 17 and 11); probably the land-gift stages.
