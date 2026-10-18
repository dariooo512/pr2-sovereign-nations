# Military combat resolution: AI sea battles, AI sieges, raiding, and nation-5 military convoys

This is static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game was not run.
- **Tools:** pefile and capstone. I made a linear sweep of `.text` with `skipdata` and built an E8/E9 xref index.
- **Scratch scripts:** in the session scratchpad `agent_battle/`.
  - `h.py`: `d VA N` disassemble, `c VA` callers, `r VA` data refs, `s TEXT` strings, `vt VA N` dword table.
  - `g.py REGEX MNEM`: grep the sweep.
  - `chk.py`: hook-site check (instruction boundaries, branch-in, data refs).
- **Labels:** **[S]** means verified from the bytes (VA quoted). **[H]** means a hypothesis (naming or runtime behaviour).

Read with `conquest_trigger.md`, `conquest_transfer.md`, `hostility_map.md`, `null_nation_census.md` and `dll/war.c`.

## 0. Answer in one paragraph

**Sea battles between non-player convoys** have three phases:
- **Detection.** The convoy update dispatcher `0x5B3BD0` runs target acquisition (`0x5AF330`, plus the patrol scan `0x5B6A50`). Acquisition writes the target handle to `convoy+0x168`. The hunter `0x5AED30` closes in and, at distance ≤ 0x40, calls `NewSeaBattle 0x5FEF80(attacker, defender, ctx)`.
- **Dispatch.** `0x5FEF80` decides player versus AI on the convoy **type** `+0xB4` only. If the attacker is type 1, or the defender is type 1 and not on autotrade, it creates a `CChooseBattle` (question type 0 to the player). In every other case it creates a `CAutoBattle` (`0x5FBAF0`, 0x190 bytes, vtable `0x6AB3E8`). The nation byte `+0xB8` is never consulted [S].
- **Resolution.** `CAutoBattle` resolves the fight off-screen over a few hundred ticks. It runs a per-ship duel model with flee, boarding and damage rolls, driven by ship class strength (type tables), cannons, crew, hull and sails, using the `[AutoBattle]` constants from `Data/BattleConst.ini`.
  - **If the attacker wins:** it captures surrendered or out-classed ships into its own convoy and plunders 19 goods plus cutlasses, muskets and cannons into its hold. Traders lose only ¼ of the computed share.
  - **Afterwards:** sunk ships are deleted, an emptied convoy is deleted through `0x635600`, and Lua `OnSeaBattleEnd`, chronicles, reports and autotrade messages follow.
  - **What the winner gains:** ships plus hold cargo. No gold changes hands and no nation treasury exists [S].

**A type-4, nation-5 mod convoy** follows the same rules:
- It is always auto-resolved against AI convoys.
- It reaches the player's battle UI only if the player's own type-1 convoy is a party.
- Vanilla never targets nation-5 convoys from a nation-5 convoy:
  - its attack mask is forced to 0 for nation ≥4 (`0x63C280`);
  - its "attack the player" branch needs reputation level 0 with nation 5, which is always 3.

  The DLL must keep that guarantee once it gives the convoy a mask. Gates are in §7.

**AI town attacks** (`siege 0x603030` → states 5/6) are **instant formulas**, not battle objects:
- **Land:** sailors `+0x86` against garrison `CStadt+0x38E`. Weapons are ignored.
- **Sea:** cannons `+0x142` against harbour guns `CStadt+0x919D`.
- **Defenders:** a defending military convoy docked in the town is fought first with a `CAutoBattle`.
- **On success** they call `AttackerWon 0x602500`. It only plunders goods 8..11 (or 16..18 plus one) into the attacker's hold. **No AI path ever changes a town's owner** and none calls `AddToNation`, so the mod must transfer the town itself from hook #7 (`0x602500`).

**Corrections to war.c**, all [S]:
- **The attacker type is wrong.** Vanilla AI sieges come from **type 9 (`CONVOY_BUCCANEER` = war-mission fleet)** and type 3 (pirates), never from plain type 4. Hook #7's `type != KT_MILITARY` test therefore rejects every real power assault.
- **Power war fleets never pick a nation-5 town.** Their mission target must have town byte == `+0x172`, and `+0x172` is <4. Pirates do bombard nation-5 towns.

---

## 1. Data used below

### 1.1 Convoy types (`+0xB4`), from the Lua constant registration [S]

The pairs are `pushnumber(v); setglobal(name)` at `0x43C7B7..0x43C8B8`.

| v | name | AI driver in `0x5B3BD0` (table `0x5B3F80`) [S] |
|---|---|---|
| 1 | CONVOY_PLAYER | `0x5AEFA0` (pursue the ordered target) |
| 2 | CONVOY_AI_TRADER | `0x5B3EE0` (trade route, never hunts) |
| 3 | CONVOY_PIRATE | `0x5AED30` hunt, then `0x5B1D10` scan |
| 4 | CONVOY_MILITARY | builds mask `0x63C280`, then `0x5AED30` hunt, then scan `0x5B1D10` or planner `0x5B1DF0` |
| 5 / 6 | CONVOY_TRANSPORT / CONVOY_TREASURE | `0x5B3E5D` (move) |
| 7 | (no name) | like pirate: `0x5AED30`, `0x5B28F0` |
| 8 | CONVOY_MISSION | `0x5AED30` |
| 9 | CONVOY_BUCCANEER | `0x5B3880` war-mission planner (no hunting) |

Notes [S]:
- **Type 4 becomes type 9.** `AssignWarMission 0x5B4870` takes a **type 4** convoy and turns it into **type 9** through `ShipGroup::SetType 0x637050(9, nation)` (`0x5B48E4..0x5B48E8`). It sets `+0x172` = target nation (<4 enforced at `0x5B4892`), `+0x170`, and `+0x171` = 0 (action). It needs the local player's rank > 1 (`0x5B48BD..0x5B48C4`).
- **Mission town picker.** The type-9 picker `0x5B3880` accepts a town only if `town+0x390 == +0x172` (`0x5B3A40..0x5B3A4C`), or if it is a bit-22 "own town" with population > 1000 (`0x5B3A4E..0x5B3A62`). The town index must also be set in the bitmask `+0x174` (`0x5B3A87..0x5B3AA3`).
- **Military list registration.** `0x637050` writes the type to `group+0x68` (= `+0xB4`) and the nation to `group+0x6C` (= `+0xB8`). For types 4..10 it registers the convoy in `g_nations[nation]+8` (the military list). That step is skipped when the nation is ≥4 (`0x63707A..0x637093`), so **a nation-5 military convoy is in no vanilla list**. The mod needs its own registry.

### 1.2 Convoy fields used by combat

Base layout is as in `conquest_trigger.md`. This table lists only the combat fields [S unless marked].

| off | meaning | evidence |
|---|---|---|
| `+0x1C` | byte, "active / at sea" [H]; used as the 0/1 addend in `0x5AD230` and required for most targets | `0x5AF5FB`, `0x5B6838` |
| `+0x48` | **word** attack mask. Bit n = attack convoys whose `+0xB8 == n`. Bit 4 = pirates (0x10). Bit 5 = nation-5 convoys (0x20). Bit 6 = **siege flag** (0x40). Bits 7+n = "stronger than n" (`0x81<<n`) | `0x63C2B4`, `0x63C32E`, `0x63C389`, `0x63C596` |
| `+0x7C` | flags. 0x1000000 PROTECTED: never a target (`0x5AF343`). 0x80000 is required for military-vs-military in `0x5AF330` (`0x5AF63C`); no vanilla writer was found | — |
| `+0x86` / `+0x142` | sailors (word) / cannons = weapon 5 (word); `+0x84` max cannons | `0x6029EC..0x602A6D`, `0x5FAF80` |
| `+0x80` / `+0xBC` | hold capacity / used (free = difference) | `0x6025B8..0x6025C6` |
| `+0x95` | ship count (byte); 0 means the convoy is deleted by `0x635600` (`0x5B3BEC`) | — |
| `+0x168` | **target convoy handle** (hunt / pursuit) | writers `0x5AF449`, `0x5AF548`, `0x5AF5DA`, `0x5B686C`, `0x5B6C19`, `0x5B6DF7` |
| `+0x170..0x172` | war mission: `+0x171` action (1 = siege, 2..11 = sabotage), `+0x172` target nation | `0x5B48F8..0x5B4904` |
| `+0x190` | attack cooldown (world time) | `0x5AF49F`, `0x5AF72F` |
| `+0x1B0` | mission town handle | `0x5B3B69` |

Ship (pool `0x703CD4`, stride 0x28):
- `+0x1C` type [S].
- `0x63E420` = class strength `(T94[t]+100)*T6C[t]*T80[t]*k`, from tables at `0x703C94`, `0x703C6C`, `0x703C80` [S].
- `+0x1D` cannons [H]. `0x63E460` = firepower `+0x1D*k` [S].
- `+0x1F` crew [H]. Lowered by `0x63EDA0`, which also recalculates the convoy (`0x6409F0`) [S].
- `+0x00` hull, `+0x04` sails [H] (damage targets in `0x5FD810`).
- `+0x24` ship state: 9 battle, 0xA boarded/surrendered, 0xB fled (Lua `SHIPSTATE_*`) [S for the values, H for the meaning per site].

---

## 2. Q1: AI sea battles: detection, resolution, outcome

### 2.1 Detection [S]

| step | VA | what |
|---|---|---|
| scan of nearby convoys | `0x5B1D10` (calls `0x5AF330` at `0x5B1D76`/`0x5B1DD9`), `0x5B0AA0` (`0x5B0BEE`) | for moving pirate / military / escort convoys |
| **target acquisition** | **`0x5AF330` `bool CKonvoi::ShouldAttack(CKonvoi* other)`**, thiscall `ret 4` | self type 3/7 → `0x5AF67C`; type 4 → `0x5AF48C`; other types never attack (`0x5AF463..0x5AF47A`). Sets `+0x168` |
| military (4) vs other.type | table `0x5AF81C` | 1 player: `0x5AF49F` needs `GetReputationLevel(self nation)==0` (`0x5AF4DE`), a crew comparison and a geometry check. 2 trader: `0x5AF5FB` needs mask bit `1<<other.nation`. 3/7 pirate: `0x5AF566` (no mask test). 4 military: `0x5AF63C` needs `+0x7C&0x80000` **and** `0x5AD230(other.nation)` = mask & `(0x80+self[+0x1C])<<n`. 5,6,8,9: never |
| pirate (3/7) vs other.type | byte table `0x5AF848`, targets `0x5AF838` | 1 player: `0x5AF7AA`. 2 trader: `0x5AF69A` (mask bit). 4/9 military: `0x5AF709` = **flee** (`0x5AE1B0`, `+0x7C\|=0x8000000`). Others: never |
| patrol scan | `0x5B6A50` (from `0x5F1FB2`) | any convoy with mask bit `1<<target.nation`. For `target.nation==5 && self.type==4` the target's owner must resolve to a CPlayer, and raw rep must be < 2 or a distance condition must hold (`0x5B6B79..0x5B6BE3`, `0x5B6D56..0x5B6DC0`) |
| **engage** | **`0x5AED30`** (hunters: types 3, 4, 7, 8 and the `+0x1B8` task path) | the target must still exist; distance `0x5B6660` > 0x27D9 drops it (`0x5AEDF6`); ≤ 0x40 → `0x5FEF80(self, target, invalid)` (`0x5AEE90`) |
| player engage | `0x5AEFA0` (type 1) | ≤ 0x40 → `0x5FEF80` (`0x5AF187`) |
| other starters | `0x602D1D` (siege defender, §4.3), `0x60843C` (island battle) | — |

### 2.2 `NewSeaBattle 0x5FEF80(A, B, ctxBattle)` (cdecl, 3 handles) [S]

Here A is the attacker and B the defender.
- `0x5FF019 cmp [A+0xB4],1 / je 0x5FF0F4` → **CChooseBattle** (0x24 bytes, ctor `0x5FEED0`, vtable `0x6AB4B0`, store `0x7036C0`). Its tick `0x5FF250` posts **question type 0** (`0x5FF2AC push 0`) to the player.
- `0x5FF028 cmp [B+0xB4],1 / jne auto`. If B is a player convoy, `0x638030(B+0x4C)` (= `group+0x110 → +0x10`, autotrade active [H]) is checked: not on autotrade → CChooseBattle; on autotrade → auto.
- Otherwise → **`NewAutoBattle 0x5FBAF0(out*, A, B, ctx)`** (`0x5FF0E4`).

CChooseBattle answer `vfn6 = 0x5FEB80`:
- arg 0 → real-time `COceanBattle` (`NewShipBattle 0x60A9A0`, `0x5FEE0F`).
- otherwise, `0x5FEE19 cmp [A+0xB4],1`: if A is the player → cancel (`vfn7(3)` + `0x5AD8D0`); else (the player was the defender) → `0x5FBAF0`.

The answer-to-button mapping is [H]. A second creator, `0x60CA30` → `0x5FBAF0`, is reached from the COceanBattle dispatcher `0x60D310` [H: "auto-resolve" from the battle screen].

**No code on this path or in the CAutoBattle code range (`0x5F9C00..0x5FF300`) tests `+0xB8==5`.** The only `+0xB8` reads are `0x5FC0DC` and `0x5FC2EF`, which supply chronicle data [S].

### 2.3 `CAutoBattle`

**Construction and init** [S]:
- `0x5FBAF0` checks both convoys; if neither `+0x3B` is set, it needs a valid ctx and both groups out of battle (`0x5F9CF0`).
- It allocates 0x190 bytes (ctor `0x5FB510`), adds the object to the battle store `0x7036C0` (`0x5FCCA0`) and calls **init `0x5FA810(A, B, ctx)`** (thiscall `ret 0xC`).
- Init fires the mission event to `0x702B0C` (`0x5FAC10`) and puts the battle on the map (`0x62C610`, `0x703AEC`).

Fields [S unless marked]:
- `+0x28` / `+0x2C`: owners of A / B (`0x635FD0`).
- `+0x30`: **A handle**. `+0x34`: **B handle**.
- `+0x38`: town of ctx (`ctx->vfn[0x30]`). `+0x3C`: **ctx battle handle** (the siege).
- `+0x40` / `+0xA8`: side objects (0x68 bytes each, `0x604400`).
- `+0x178`: state. `+0x17C`: tick word.
- `+0x17E`: A battleships. `+0x17F` / `+0x180`: B battleships / B other ships. Battleship = ship record flag 4 = `Ship_IsBattleShip` [H].
- `+0x181`: **alive mask** (bit0 = A still fighting, bit1 = B; ctor value 3).
- Loss counters:
  - `+0x182`: A sunk.
  - `+0x183`: B sunk.
  - `+0x185`: A fled or boarded.
  - `+0x186`: B fled.
  - `+0x18A`: B ships taken by class match in state 3.
  - `+0x18B`: A boarded.
  - `+0x18C`: B ships captured in state 2.

  Semantics [H]; increment sites [S].

**Initial state** (`0x5FAAB3..0x5FAB08`, tables `0x5FAC70`/`0x5FAC78`), by B type:
- B type 1/2 (player / trader) → **3** (direct plunder) unless one of B's ships has record flag 4 → **1** (fight the escorts).
- B types 3..9 → **1** (fight).
- Anything else → 7.

**Tick** `vfn5 = 0x5FC980` (state table `0x5FCA44`). Waits use `SelSteps`=160 from `[BattleData]` → `[0x7036B0]`:

| state | handler | behaviour [S] |
|---|---|---|
| 0 | — | reset the tick word |
| 1 | `0x5F9E10` | **combat round, every tick.** Pairs A and B ships into ≤10 duels (`0x5FD5E0`); extra ships join duels (`0x5FD670`). Each ship then rolls `0x5FD810`. `+0x181` = OR of `1<<side` over ships still fighting (`0x5FDA90`, `0x5FA0B4..0x5FA0F3`). 3 → stay. **1 → state 2 (A won).** 0 or 2 → state 6 (A lost) |
| 2 | `0x5FA160` (after SelSteps) | **A won.** Counts B's ships. State 0xB → fled. State 0xA, or (A type 4 **and** B type 3 and state 9) → **captured into A**: `0x5B6E20(B, ship, A)` moves the ship and its goods and weapons, and trims B's cannons to `+0x84`. Otherwise the ship is counted as sunk. → state 3 (4 if a convoy is gone) |
| 3 | `0x5FAC90` (after SelSteps) | **plunder.** B ships whose class strength `0x63E420` is beaten by an A ship are captured into A (`0x638B50`, `+0x18A++`, `0x5FAF0F..0x5FAF55`). Cutlasses / muskets / cannons in the loot array move B→A (`0x639DF0` add, `0x6379E0` remove; cannons clamped to A's `+0x84`). 19 goods move B→A (`0x638690` remove, `0x638670` add, `0x5FB0E1..0x5FB105`). **B type 2: loot >>2** (`0x5FB0D3`). **B type 1: loot scaled by player rank** (`0x5A8DA0`, `0x64DE90`, `0x41C6B0`). → state 4 |
| 4 / 7 | **`0x5FBF00`** | **cleanup** (§2.4) → state 8, or 5 when the player must answer |
| 5 | `0x5FA430` | wait for `[0x701344]` → 8 |
| 6 | `0x5FB130` (after SelSteps) | **A lost.** Counts A sunk / fled / boarded and B's sunk / fled → state 7 |
| 8 | `0x5FBDF0` + `0x5FCCF0` | leave the map, remove from the store |

**Per-ship roll `0x5FD810(ship, side)`** [S for the structure; the constants come from `[AutoBattle]`, loaded at `0x55883E..0x558986`]:

1. **Flee test:** `AFleeCond`(1.5) `[0x7036D4]` × own side's firepower is compared with the enemy's. Then `rand%1000` is compared with `AFleeProp`(0.5) `[0x7036D0]` × class ratio → `0x63E3F0` (flees).
2. **Boarding test:** crew × `AEntCond`(1.1) `[0x7036D8]` is compared with the enemy crew sum, with `AEntProp` `[0x7036DC]`. On success: crew loss `0x63EDA0`, the boarder is picked by `0x5FD730`, and `0x63E400` sets the ship's state to boarded (0xA).
3. **Otherwise `rand%3` damage**, scaled by the enemy side's total cannons (`duel+0x28/+0x2A`, sums of ship `+0x1D`):
   - one roll hits ship `+0` (`[0x7036E0]`);
   - one hits ship `+4` (`[0x7036E8]`);
   - one hits crew `+0x1F` (`[0x7036E4]`).

   A part reaching 0 removes the ship from the fight.

   The values are AHull/ACrew/ASail=65536 and ATime=32. Which constant maps to which address is [H].

**Not used:** the captain, player skills, sailors' weapons, and the nation [S, absent from `0x5F9C00..0x5FF300`].

### 2.4 Cleanup `0x5FBF00` (states 4 and 7) [S]

1. **For each side:**
   - Ships with hull ≤0 are destroyed (`0x638F90` + `0x63F7D0`, `0x5FC076..0x5FC0B6`).
   - Trader / transport (type 2/5) → town economy update `0x5C9160` (route town and home).
   - A convoy that still has ships is released (`0x5AD5C0` / `0x5AD510`). Types 3, 4 and 7 drop their target (`0x62CAB0`); other types resume their route (`0x62D630`).
   - A convoy with **0 ships** is queued for deletion. If it was **type 9**, `CChronicleBuccaneerDestroyed` (create-data 0x31, `0x5DBA00`) is created with the killer's nation byte (`0x5FC2EF..0x5FC354`). That chronicle treats nation ≥4 as "the player" (`0x5DBB22`) and does not throw [S].
2. Morale / experience `0x63A600(+0x160, …, 0x64)` for each side [H]. State = 8.
3. **Event `CEventSeaBattleEnd`** (`0x44F300`) → `0x702B0C` (Lua `OnSeaBattleEnd`, `MEVENT_SEABATTLE_END`=0x80000) (`0x5FC563`).
4. If B is a player convoy on autotrade: message **0x17** `ID_MSG_PIRATE_ATTACKS_AUTOTRADE` (A type 3) or **0x18** `ID_MSG_MILITARY_ATTACKS_AUTOTRADE` (A type 4) (`0x5FC56E..0x5FC5CB`).
5. If B is type 1: player statistics (`0x60E810` / `0x60E7D0` / `0x60E7F0`) and a battle-report letter (`0x5FC6DF..0x5FC7D7`). If B is not on autotrade: state 5 plus **question 0x22** (`0x5FC7EC..0x5FC813`).
6. **Convoy deletion:** `0x635600(handle)` for the emptied convoys (`0x5FC851`, `0x5FC890`). The handle slot is valid only for a 0-ship convoy; otherwise it is a no-op.
7. **Report to ctx:** `ctx->vfn7(+0x181)` (`0x5FC91D..0x5FC92B`). For a siege that is `0x6024E0`: result 1 → siege state 4 (assault), else 7 (abort).

### 2.5 What a power gains [S]

- **Captured ships** join the winning convoy (states 2 and 3), so the convoy's strength grows.
- **Cargo** of 19 goods (traders yield ¼) and **weapons** (cutlass, musket, cannons) go into the winner's hold.
- **No gold, no reputation and no nation counters** change in the auto-battle.
- **Vanilla has no nation treasury.** Lua has only `Player_GetGold` / `Player_AlterGold`, and the DLL's `treasury` lives in `core.h`.
- Pirates later "deliver" loot only implicitly [H].
- The goods unloader `0x5B40D0` runs **only for type 5 transports**: in-town table `0x5B5B30` → `0x5B58C5` → `0x5B5906`.

---

## 3. Q2: when the player is involved, and keeping nation 5 off itself

### 3.1 Every player / nation test on the battle paths [S]

| VA | test | consequence |
|---|---|---|
| `0x5FF019` | A `+0xB4==1` | CChooseBattle (player question type 0) |
| `0x5FF028..0x5FF03B` | B `+0xB4==1` and not autotrade (`0x638030`) | CChooseBattle; on autotrade → AutoBattle |
| `0x5FEDC8` / `0x5FEE19` | answer 0 → real-time; A type 1 → cancel; else auto | — |
| `0x5FAAB3` | B type 1/2 | plunder-or-escort-fight start state |
| `0x5FA2A0` | A type 4 and B type 3 | pirate ships in state 9 are also captured |
| `0x5FB027` / `0x5FB0CC` | B type 1 / 2 | loot ×rank / loot ÷4 |
| `0x5FC595..0x5FC5B5` | B autotrade and A type 3/4 | messages 0x17 / 0x18 |
| `0x5FC5E3`, `0x5FC6BC`, `0x5FC7E3` | B type 1 (and not autotrade) | statistics, report letter, question 0x22 |
| `0x5FC0C1..0x5FC0EF`, `0x5FC2EF` | type 3 / nation byte | chronicle data only |
| siege `0x6029A1` (byte table `0x602AF0`, targets `0x602AE0`) | attacker type 1 → question; 3 → pirate (sea); 4/9 → AI choice; others → abort | — |
| siege state 4 `0x603518` | type 1 → `CCoastBattle` / `CHarbourBattle` (interactive); else instant AI resolver (state 5/6) | — |
| `0x603093` | type 1 → bit-22 / protection checks | — |
| `0x5AF4AF..0x5AF4E5` | military hunting a type-1 convoy needs `GetReputationLevel(self.nation)==0` | `GetReputation(5)` = 100 → level 3: **a nation-5 convoy never hunts the player** (unless a DLL detour changes n==5) |
| `0x63C28C..0x63C296`, `0x63C3EA` | mask builder: nation ≥4 → mask = 0 | a nation-5 military convoy attacks only pirates (`0x5AF566` ignores the mask) |

**Conclusion [S].** A type-4 or type-9 convoy with `+0xB8==5` fighting any AI convoy always goes through `CAutoBattle`. No battle-UI or player-question code runs unless one party is type 1. The nation byte plays no part in the decision.

### 3.2 Paths by which two nation-5 convoys could still fight, and the gates

| path | vanilla status | gate needed |
|---|---|---|
| mod military → player convoy (`0x5AF4AF`) | blocked (rep level 3) [S] | none, as long as nothing detours `GetReputation(5)` |
| mod military → mod military (mask bit 5, `0x5AD230` / `0x5B6A50`) | blocked while the mask stays 0 [S] | when the DLL builds a mask for P=5, **never set bits 5 or 12**; add the §7 hook E as a safety net |
| player → mod military (UI order `0x576B20` → `CKonvoi::AttackConvoy 0x5B67D0`) | refused only if both convoys have the **same owner** (`0x5B6845..0x5B6863` compares `0x635FD0` owners) [S] | if the mod convoy is not owned by the human player: §7 hook F (`0x5B6841`) |
| `CConvoy` `+0x1B8` task (`Convoy_SetMTaskAttack`) | attacks the `+0x1BC` handle or the `+0x1C0` nation (`0x5AF37D..0x5AF3C5`) | never set `+0x1C0=5` or a nation-5 handle |
| siege defender (`0x602C34..0x602C59`) | the defender must be docked with `+0xB8 == town+0x390`. A nation-5 attacker never besieges its own town (hooks #1/#2 cover the player) | none |

---

## 4. Q3: AI sieges of towns, and a nation-5 convoy winning a power's town

### 4.1 Who besieges [S]

`0x603030 NewTownAttack(convoyH)` has exactly 3 callers:

| caller | who | condition |
|---|---|---|
| `0x5B4B43` | any convoy whose owner is the **human** CPlayer (`[owner]==0`, `0x5B4B17`) | `+0x48&0x40` and the town is not bit 22 (hook #2 at `0x5B4B2D`) |
| `0x5B4D50` | types 3 and 7 (arrival table `0x5B50CC`) | `0x63C4D0`: town `+0x58>3`, cannons > 20×guns `+0x919D`, global cooldown `[0x702044]`, **no docked type-4 convoy** in the town (`0x63C580`). **The town's nation is not checked** |
| `0x5B4DF4` | **type 9** at its mission town | `0x5AD8F0` (mission valid: `IsAtWar(g_nations[+0xB8], +0x172)`), then `0x5B07A0` sets `+0x171=1`. That needs the town byte == `+0x172` (`0x5B0855..0x5B085D`), plus `0x63C400` (the siege flag; **NULL `g_nations[P]` for P≥4 means no flag**) and player rank >1 |

**Type 4 never besieges** unless it is owned by the human player [S: the type-4 arrival handler `0x5B4E35` only re-plans].

### 4.2 Siege object for AI attackers (vtable `0x6AB5B8`, tick `0x603C10`, table `0x603C7C`) [S]

- **init `0x602900`** (type table `0x602AF0`):
  - type 3 → state 2, `+0x1C=1` (sea), `0x5BD7D0`.
  - **types 4/9 → `0x6029EC`.** If sailors `+0x86` > 5×garrison `CStadt+0x38E` → land (`+0x1C=0`). Else `+0x1C` = (cannons `+0x142` > 20×harbour guns `CStadt+0x919D`) [H: cached gun count]. State 2.
- **state 2 `0x602B00`:** a docked (`+0x90==2`) type 4/9 convoy with `+0xB8 == town+0x390` is a **defender**. If one exists, `0x5FEF80(attacker, defender, siege)` starts a `CAutoBattle`, then state 3 waits for `vfn7` (`0x6024E0`: result 1 → 4, else 7). With no defender → state 4.
- **state 4 `0x6034D0`:** for non-players, `state = 6 - (+0x1C != 0)` (`0x603677..0x603682`).
- **state 6 = land `0x603200`:** instant.
  - S = sailors, G = garrison, r = `rand16-0x8000`.
  - `x = r·k[0x6AB628] + G/(S+1)`; then `G_loss = G/x²` and `S_loss = S·x²`.
  - The town loses `G_loss/2` soldiers (`0x5C5B30`) and the convoy loses `S_loss/2` sailors (`0x6415D0`).
  - **won = (S−S_loss) > (G−G_loss)** (`0x603364`).
  - Then `0x624920(lager, 0, won, 0)`, and **`AttackerWon` if won** (`0x6033F6`, return address `0x6033FB`), and letter create-data 0x30 (`0x6034AD`). State 7.
- **state 5 = bombard `0x603690`:** instant.
  - `x = k1 − rnd·k2 + 20·T/(C·(b96+100)·k3)`, where T = harbour guns, C = cannons, b96 = convoy `+0x96` [H: skill or class].
  - `T/x²` guns are destroyed (`0x61D7F0` each).
  - `ships·x²` ships are sunk (keeping at least 1); their crew and cannons are lost. Each hull is reduced by `x²` (capped at `[0x69C0A0]`).
  - **won = (no guns left)** (`0x603953..0x60395B`) → `AttackerWon` (`0x6039F9`, return address `0x6039FE`).
  - Type 9 gets message 0x2B (won) or 0x2C (lost) plus letter 0x30; others get letter 0x26. State 7.
- **state 7 `0x602D60`:** release, then state 8 → removed.

**Weapons (cutlasses / muskets) do not enter the AI formulas.** Only sailors, garrison, cannons, guns and convoy `+0x96` count [S].

### 4.3 `AttackerWon 0x602500(townH, convoyH)` (cdecl, 2 args) [S]

- `0x6237C0(town+0x91C8)` zeroes a two-dword accumulator [H: the town's collected income, lost and credited to nobody].
- The plunder set is goods 8, 9, 0xA, 0xB, or for type 9: 0x10, 0x11, 0x12 plus the least-stocked of 8..0xB (`0x6025D9..0x60262A`).
- Those goods are taken from the town's store (`0x5CAA30` / `0x5CAA60` / `0x5C8AC0`) into the convoy's free hold (`0x638670`), proportionally when the hold is short (`0x602653..0x6026D1`).
- **No owner change:** neither `0x602500`, `0x603200`, `0x603690` nor `0x602D60` calls `AddToNation 0x5C9DA0` or `AnnexTown 0x5BC310` [S; full call lists checked].

### 4.4 Mod: a nation-5 military convoy takes a power's town

- **Starting the attack.** A vanilla nation-5 type-9 fleet never gets `+0x171=1`, because `0x63C400` needs a non-NULL `g_nations[5]`. So the DLL drives the attack itself [H runtime, S preconditions]:
  1. The convoy is anchored at the town (`+0x90==4`, `+0x9C` = town).
  2. Set `+0x48 |= 0x40` immediately before the call; the mask is rebuilt periodically and the rebuild clears bit 6.
  3. Call `0x603030(convoyH)`.

  Types 4/9 take the AI branch (no question, no hooks #1/#3..#6). A docked power fleet is fought first, as an AutoBattle.
- **Taking the town.** This is decided only in **hook #7 at `0x602500`**. If the convoy has `+0xB8==5`, type 4/9, the town owner is <4 and at war, and the town is not a viceroy seat → queue `core_annex` (`Nation_Annex` / `war_resolve_conquest`-style) for `war_frame`. The return address tells land (`0x6033FB`) from bombardment (`0x6039FE`).
- **AddToNation(5) is never at risk.** Vanilla never reaches `AddToNation` on this path, so nothing must be suppressed.

---

## 5. Q4: AI attacking a nation-5 town [S]

- **Power war fleets (type 9)** cannot select a nation-5 town:
  - the picker needs `town+0x390 == +0x172` (`0x5B3A46`);
  - the action check needs the same (`0x5B085B`);
  - `+0x172` is <4 (`0x5B4892`).

  Only bit-22 vanilla own-towns with population >1000 are an exception.
- **Type 4** never besieges.
- **Pirates (3/7)** do bombard nation-5 towns. `0x63C4D0` has no nation test, but a **docked type-4 convoy prevents it** (`0x63C580`). A docked nation-5 type 4/9 convoy also **defends** in siege state 2, because its `+0xB8` (5) equals the town byte (5).
- **Defences that matter:** garrison `+0x38E` (land) and harbour guns `+0x919D` (sea) through the formulas in §4.2, and docked military as the defender.
- **Hook #7 today** returns early unless the town is nation 5. It then requires `type == 4`, which vanilla never delivers. **Change it to accept 4 or 9.** Pirates (type 3) are rejected, which is correct: plunder only.
- **To let powers conquer the mod's towns,** give a power's type-9 fleet **`+0x172 = 5`**. Write it after `AssignWarMission` succeeded with any target <4. All readers of `+0x172` are safe with 5 [S]:

  | reader | why it is safe |
  |---|---|
  | `0x5AD92D` → IsAtWar(P, 5) | P01 gives `player_rel[P]` |
  | `0x5B084B`, `0x5B3A46`, `0x5B5161`, `0x41B350` | compares |
  | `0x5B5336` → `0x5BA400(this=g_nations[P], 5)` | guarded other<4: no write |
  | `0x63C400` (IsAtWar(P, 5) via P01) | sets the siege flag |

  The picker then chooses nation-5 towns, as long as the `+0x174` town bitmask includes them [H: who fills `+0x174` was not traced]. The fleet besieges, and hook #7 transfers the town with `core_lose_town`.

## 6. Q5: raiding [S]

- **Pirates raid** traders (type 2, by mask) and player convoys.
- **Military raids** enemy traders (type 2 whose nation bit is in the mask). Military-vs-military in `0x5AF330` additionally needs `+0x7C&0x80000`.
- **Trader without battleships:** `CAutoBattle` state 3 immediately; captures by class strength plus ¼ cargo. **With escorts:** a fight first.
- **Loot goes into the attacker convoy's hold and nowhere else.** No treasury and no player gold are touched. A player autotrade victim triggers messages 0x17/0x18.
- **A mod "Raid" order** sets the target (`CKonvoi::AttackConvoy 0x5B67D0(self, targetH)`, thiscall `ret 4`, or write `+0x168`). The type-4 driver's `0x5AED30` then engages. Plunder is read at §7 hook B and credited to the treasury. Optionally the DLL removes the goods (sells them) to avoid a hold full of loot.

## 6b. Hazards for nation-5 military convoys (`+0xB8 = 5`) [S]

| site | hazard |
|---|---|
| `0x5B5340` → `0x5BA400` (in `0x5B5110`) | a type-9 nation-5 fleet performing **mission actions 2..11** writes through NULL `g_nations[5]` (`[NULL+0x158+4·target]`), so `+0x172` must be <4 for the write to happen at all. **Keep `+0x171` ∈ {0,1}** for mod fleets, or patch the `0x5B5317` lookup |
| `0x5B40D0` (`0x5B4144` rep movsd from NULL+0x24) | type 5 only; never use type 5 with nation 5 |
| `0x637050`, `0x63C280`, `0x63C400`, `0x5AD8F0`, `0x5B5195` | NULL-safe (guards or P01); results: no list, mask 0, no siege flag, `player_rel` |
| `0x5DBA00` chronicle 0x31 | nation 5 shown as "the player" (cosmetic) |

---

## 7. Recommended hooks

All of these were checked with `chk.py` [S]:
- the byte patterns are exact;
- the ranges end on instruction boundaries;
- the displaced instructions are position-independent;
- no E8/E9/Jcc in the sweep and no dword in the image points inside a range.

Handlers run **before** the displaced instructions (hook.h), so they change registers, not values loaded by those instructions.

| # | purpose | VA | bytes (displaced) | regs at hook | handler |
|---|---|---|---|---|---|
| **A** | (a) **auto-battle outcome** | `0x5FBF00` (CAutoBattle cleanup, states 4/7, sole caller `0x5FC9F3`) | `6A FF 68 5E 39 67 00` (`push -1; push 0x67395E`), 7 | ecx = CAutoBattle* | read `+0x30`/`+0x34` (they are invalidated later in this function), `+0x181` (1 = A won, 2 = B won, 0 = neither; 3 = plunder path with no capture), counters `+0x17E..0x18C`. If either side is nation-5 type 4/9: log and queue the fleet update |
| **B** | (a) **plunder credit** | `0x5FB107` (end of state 3, after all transfers) | `8B 4C 24 2C 5F` (`mov ecx,[esp+0x2C]; pop edi`), 5 | ebx = A*, edi = B*, `[esp+0x2C]` = battle | loot words at `esp+0x3C+2i` (goods i=0..18) and weapons at `esp+0x64/+0x66/+0x6E`. The amounts actually moved are min(loot, B's stock) [H]. If A is nation 5: credit the treasury. Ships captured in state 2 carry their own cargo: count them with `+0x18C` |
| B′ | snapshot (optional) | `0x5FA810` (init) | `6A FF 68 50 38 67 00`, 7 | ecx = battle; stack args A, B, ctx | record handles for A |
| **C** | (b) **nation-5 convoy wins a town** | `0x602500` (existing #7) | `83 EC 10 8B 54 24 18`, 7 | `stack_arg(1)` = townH, `(2)` = convoyH, `(0)` = return address `0x6033FB` land / `0x6039FE` sea | add: convoy `+0xB8==5`, type 4/9, owner <4 and at war, not viceroy → queue an annex. Fix the existing branch: accept type **4 or 9** |
| **D** | (c) **convoy destroyed** | `0x635600` (global DeleteConvoy; 18 callers) | `64 A1 00 00 00 00` (`mov eax,fs:[0]`), 6 | `stack_arg(1)` = convoyH (still valid; resolve with PoolGet `0x701EE8`) | if nation-5 type 4/9 → registry remove. The cause comes from the return address: `0x5FC856`/`0x5FC895` auto-battle, `0x5B3C09` emptied at update, `0x4267F1` Lua, … Merged convoys also pass here [H]. Alternative: poll the handles in `war_frame` |
| **E** | never engage nation-5 vs nation-5 (AI) | `0x5AEDF6` in `0x5AED30` | `3D D9 27 00 00` (`cmp eax,0x27D9`), 5 | esi = hunter, ebx = target, eax = distance | if both `+0xB8==5` → `eax = 0x27DA`. That takes the vanilla "target lost" path (`0x5AEF5E`: `0x62CAB0`, `+0x168` cleared) |
| **F** | player cannot attack the mod's convoys | `0x5B6841` in `AttackConvoy 0x5B67D0` | `8D 4C 24 10 8D 75 4C` (`lea ecx,[esp+0x10]; lea esi,[ebp+0x4C]`), 7 | ebp = attacker, edi = target (edi is popped at `0x5B6882`) | if the attacker is type 1 and the target is `+0xB8==5` type 4/9 → `edi = ebp`. The owner compare then matches and vanilla refuses the order |
| **G** | mask for P = 5 | `0x63C3F0` (common exit of `0x63C280`, reached by the P≥4 path) | `5F 5E 5B 83 C4 08`, 6 | edi = convoy; P = `[esp+0x18]` | if P==5: `word[edi+0x48] \|= mod mask`. Use bits 0..3 (+7..10 when stronger) for powers at war, bit 4 for pirates; **never bit 5/12**; bit 6 only to request a siege |
| H | (optional) let power fleets pick nation-5 towns without `+0x172=5` | `0x5B3A46` | `3A 83 72 01 00 00` (`cmp al,[ebx+0x172]`), 6 | al = town byte, edi = town, ebx = fleet | if al==5 and the fleet's power is at war with the mod → `al = [ebx+0x172]`. Also needs `0x5B085B` (2-byte cmp + rel32: not hookable). **Prefer `+0x172=5`** (§5) |

## 8. Confidence and open points

- **High [S]:** dispatch (§2.2, §3.1), CAutoBattle states and transfers, siege formulas, the AttackerWon contents, the absence of owner changes, the type-9 / war-mission facts, the hook bytes.
- **[H], to check at runtime:**
  - the exact flee / boarding inequalities;
  - which ship fields are hull, sails and crew;
  - the meaning of `0x638030` (autotrade);
  - the effects of `0x624920`;
  - who fills `+0x174`;
  - calling `0x603030` and `0x5B67D0` from `war_frame`;
  - whether the type-4 planner `0x5B1DF0` overrides a DLL-set `+0x168` before `0x5AED30` engages.
- **Convoy ownership.** If the mod convoys are owned by the human CPlayer:
  - hook F is redundant (same owner);
  - `0x5B4B20` would let `+0x48&0x40` trigger AI-style sieges on arrival;
  - `0x5B6B8F` would let powers hunt them as "player" convoys.

  The ownership choice should be made deliberately.
