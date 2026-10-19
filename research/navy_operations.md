# Navy operations for nation-5 fleets: sorties, war missions, raiding, loot, disband

This is static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game
was not run, and no repo file other than this one was changed.

- **Tools:** pefile and capstone. The helpers are copied from `agent_battle/` into the session scratchpad
  `agent_navyops/`: `h.py` (`d`, `c`, `vt`, `s`), `g.py` (grep over the linear sweep) and `chk2.py`
  (hook-site check for branch-ins and data refs).
- **Labels:** **[S]** means verified from the bytes (VA quoted). **[H]** means a hypothesis about a
  name or about runtime behaviour.
- **Starting point:** `dll/navy.c` as it is in the working tree. It has a CNation `g_pc`, the mirror
  `g_nations6`, 5 opt-ins, the flagship table `g_flag6`, the P01 self-peace fix and
  `0x5B4892 cmp bl,4→6` (so powers can target nation 5).
- **Read with:** `military_ai.md`, `military_combat.md` and `economy_data.md`.

## 0. Answer in one paragraph

**Sorties.** With the two sortie opt-ins (`0x5B1FF7`/`0x5B2003` and `0x63B3C8`/`0x63B3DA`), a
nation-5 type-4 fleet behaves like a power's fleet:
- On every 5th decision at home, it sails to a **random enemy town**. The candidates are only the
  towns of powers `j` with `IsAtWar(&g_pc, j)` (= `g_pc.rel[j]` = `player_rel[j]`), and among them it
  prefers the towns with the fewest enemy warships heading there.
- It **anchors there and turns straight back home.** A type-4 arrival only clears `+0x1B0` and decides
  again [S `0x5B4E35`]. There is no blockade or siege of its own.
- The fighting is whatever its scanner meets on the way: pirates, enemy warships (it is always
  "strong"), and enemy AI traders.
- With no war it "sorties" to one of its own towns.
- No further nation-indexed read on that path crashes. Opting in the gate without the picker only
  sends the fleet to town #0.

**Assault (recommended).** The cheapest way to a town assault does not use war missions:
- A DLL hook **S at `0x5B4E35`** (type-4 arrival) sets `+0x48 |= 0x40` and calls
  **`NewTownAttack 0x603030(convoyH)`** when an assault-flagged nation-5 fleet anchors at a suitable
  enemy town.
- The siege sets the convoy to state 9, so the vanilla code that follows skips the "go home" decision.
- The siege resolves to `AttackerWon 0x602500` → war.c hook #7 (extended to nation-5 attackers) →
  annex.

**War missions (type 9)** also work for nation 5 against power P<4. They need:
- the rank gate removed (`0x5B48C4`, or the DLL does what `0x5B4870` does);
- 2 opt-ins (`0x5B531E`, the crash #11 fix for sabotage actions 2..11, and `0x63C463`, the siege
  flag);
- a hook **W at `0x5B4DD3`** that forces action 1 (siege). Otherwise action 1 is one random pick
  among up to 11 rank-dependent actions;
- the DLL clearing the nation's own towns from the per-mission town bitmask `+0x174`. The planner also
  accepts bit-22 "own towns", which includes every nation-5 town.

**Raiding.** `+0x1C` is **not a raid flag**. It is the base sea-object's "linked into the sea map"
byte, set for every convoy at sea [S].
- A nation-5 fleet already raids every enemy (at-war) AI trader that comes within its scan radius
  (dist² < 10000).
- It does not seek traders out. For a targeted raid, the DLL gives the fleet a vanilla **MTask**:
  Circle `0x5AD9F0` or Stay `0x5B0A30` with `+0x1C0 = P`. The fleet then patrols an area and attacks
  every convoy of nation P (traders, transports, treasure fleets, and warships when stronger).

**Loot.**
- Base prices: **`u16 SWP[20]` at `0x702114`**, loaded from `Data/waren.ini [SWP]`, in gold per unit
  (barrel). The values are 80/80/80/80/100/100/100/100/300/300/300/300/150/150/150/150/500/500/500.
- Captured cargo sits in the winner's hold at `CKonvoi+0xBE + 2·good` (u16).
- **Vanilla dumps the whole hold the next time the fleet docks** (harbour sub-state 1, `0x5B582A`).
  A hook **K** there is the exact place to turn the hold into treasury gold.

**Disband and reinforce.**
- Disband with `0x635600(convoyH)` (cdecl), only when `+0x90 != 9`, from the frame hook. `ClearOwner`
  (opted in) takes the fleet off `g_pc+8`.
- Reinforce while docked with Lua `Convoy_AddShips(h,{types})` (max 10 ships) and
  `Convoy_AddSailors(h,n)`.

---

## 1. Sorties (Q1)

### 1.1 The sortie path [S]

| Step | VA | What it does for a nation-5 type-4 fleet |
|---|---|---|
| decision | `0x5B1DF0` | mask `0x63C280` (opted in); …; at home: counter `((+0x7C>>13)+1)&7` (`0x5B1FD0`) |
| gate | `0x5B1FF7 cmp eax,4` / `0x5B2000 mov ecx,[eax*4+0x702B14]` (disp `0x5B2003`) / `0x5B200B call 0x5BBE30` | after opt-in: `ecx = &g_pc` |
| strength | `0x5BBE30(this=&g_pc)` | `c = count(pc+8) + pc+0x168`, `T = count(pc+0x14)`. True iff `c·256 ≥ (2304·T − 0x1300)/10`, `c ≥ T−5` and `c ≠ 0`. `pc+0x14` (town list) stays empty for nation 5, because `AddToNation` is not opted in. With T = 0 the gate is **true whenever the nation has ≥ 1 fleet** |
| target | `0x5B2028 call 0x63B3A0(out, 5)` | see 1.2 → `+0x1B0` |
| sail | `0x5B2063 0x417E40`, `0x5B206A call 0x5B19D0` (StarteFahrtZu, thiscall `ret 4`, arg = townH), `0x5B2073 0x62CA00(0x28)` [H: route/speed setting] | |
| at sea | `0x5B3BD0` (type 4) | mask rebuild about every 256 ticks, hunt `0x5AED30`, scan `0x5B1D10` (radius² `[0x6AC1C4]` = 10000) |
| arrival | `0x5B49C0` → `EnterTown 0x6371D0` (foreign town → state 4, anchored) → table `0x5B50CC[3]` = **`0x5B4E35`** | clears `+0x1B0`. If state 4, it calls `0x5B1DF0` again **at once**. At step 4, home ≠ current, so it **sails home** |

**Result.** A sortie is "go to an enemy town, anchor for one tick, return". It is not a blockade
and not a siege. A type-4 fleet never besieges (`military_combat.md` §4.1). The value of a sortie
is the encounters near enemy ports: enemy traders, enemy warships and pirates.

Two notes:
- **Distraction.** After a battle the route is dropped. The re-decision keeps an enemy destination
  only while the fleet is ≥ 2500 away (`0x5B1F3F cmp eax,0x9C4`). Closer than that, it gives up and
  goes home [S].
- **Sortie frequency.** One sortie per 5 home decisions (counter bits 13..15 of `+0x7C`).

### 1.2 Target picker `0x63B3A0(out, P=5)` after opt-in [S]

| Step | VA | Effect |
|---|---|---|
| guard | `0x63B3C8 cmp eax,4` / `0x63B3D7 mov edi,[eax*4+0x702B14]` (disp `0x63B3DA`) | `edi = &g_pc`. Without the opt-in it jumps to `0x63B7F3` = **first town in the town list** (no crash, but the wrong town) |
| war[0..3] | `0x63B400..0x63B418`: `IsAtWar(&g_pc, j)` | vanilla body `0x5BA0A0`: `(rel[j]&0x7F)==1` → `g_pc.rel[j]` (navy_frame keeps it `= player_rel[j] ? 1 : 0`) |
| war[4] | `0x63B41F` | 0 (pirate towns never) |
| war[5] | `0x63B46F 0x5D2C10(5)` | = (rep level == 0). P04 keeps level 3 for 5 → **0: never its own towns** |
| defenders | `0x63B4C7..0x63B549` | for each `j<4` with `war[j]`: walk `g_nations[j]+8` (fixed `0x702B14`, `edi<4` guard `0x63B4CF`) and count the convoys whose `+0x1B0` is each town |
| candidates | `0x63B5E0..0x63B73E` | town nation `cl ≤ 6`, nation ≥ 4 → display byte `+0x391` must be < 4, `war[nation]` set, index < 0x4C, count = minimum |
| pick | `0x63B792..0x63B7BC` | random among the minima |
| fallback | `0x63B574..0x63B5C0` | no candidate → the **last own town** seen (`town+0x390 == 5`). No own town → `0x63B7F3` (first town) |

### 1.3 Further nation-indexed reads on the sortie path [S]

Every function on the path was scanned for `+0xB8`/`+0x6C`, `0x702B14`, `0x6AC4xx` and `+0x390`
table use:
- `0x5BBE30`, `0x63B3A0`, `0x5B19D0`, `0x62CA00`, `0x5B49C0`;
- `EnterTown 0x6371D0` (only the compare at `0x637323`);
- the state-4 idle `0x5B5B70`;
- `0x5B6E20` (capture), `0x638B50`, `0x636210`;
- the battle code (`military_combat.md` §2).

None crashes or needs another opt-in.

The chronicles that a fleet's battles can create (`CChronicleMilitaryAttackTrader 0x5DD430`,
`CChronicleMilitaryDestroyed 0x5DD8F0`) store `+0xB8` and render it through `0x5D83C0` case 5,
which is guarded (`nation5_index_safety.md`). The text is cosmetic [H: the wording shown for
nation 5].

**Extra opt-ins for sorties: none beyond the two.**

---

## 2. War missions and town assault (Q2)

### 2.1 `AssignWarMission 0x5B4870` [S]

**Convention:** `char __thiscall AssignWarMission(CKonvoi *k, uint8 target, uint8 count)`, `ret 8`,
returns AL = 1 on success. `k` is the pool pointer (`*(0x701EE8)[i]`), with type at `+0xB4`.

| Check | VA | Nation 5 → P<4 |
|---|---|---|
| type == 4 | `0x5B487C` | ok |
| target < 4 | `0x5B4892` | `navy.c` patched it to `cmp bl,6`; P<4 is fine either way |
| target != own | `0x5B489B` | ok (5 ≠ P) |
| **local player rank > 1** | `0x5B48A7..0x5B48C4`: `0x402940` → `0x5C2B10` → `0x5A8DA0`; `3C 01` / **`0F 86 EE 00 00 00`** (`jbe 0x5B49B8`) | needs ≥ 150000 rank points (table `0x6A5020`, stride 8: r1 = 100000, r2 = 150000, r3 = 250000, …) |
| state != 9 | `0x5B48CA` | |

**Effect:**
- `SetType(9, 5)` (`0x5B48E8`, opted in → stays in `g_pc+8`);
- `+0x172 = P`, `+0x170 = count`, `+0x171 = 0`;
- if `!(+0x7C & 0x10000)`: `0x5D89D0(5)` returns name id 50 (the ≥ 4 branch `0x5D8A32`), then
  `0x635CA0` (captain) → `0x5D5CF0(50)` [H: captain renamed to an out-of-range buccaneer name]. **Set
  `+0x7C |= 0x10000` first to skip this**;
- re-home if needed (`0x63CA20`);
- if at sea (`+0x90 == 0`): clear `+0x168`, `0x5AD650`, then the planner `0x5B3880`.

**Bypassing the rank requirement for nation 5.** Choose one:
- **(a) NOP `0x5B48C4`** (6 bytes → `90×6`). This is neutral for vanilla: the only vanilla caller
  `0x5F5360` checks rank > 1 itself (`0x5F53D4`/`0x5F53D9`). But it also lifts the rank limit for
  `navy_daily`'s power-vs-nation missions.
- **(b) The DLL does what `0x5B4870` does, without the rank test** (no patch):
  1. `SetType` `0x637050` (`thiscall ecx = k+0x4C`, args `(9, 5)`, `ret 8`);
  2. write `+0x172`, `+0x170` and `+0x171`;
  3. if `+0x90 == 0`: `+0x168 = (+0x168 & 0x1F0000) | 0xFFFF`; `0x5AD650(k)`; `0x5B3880(k)`. Both are
     thiscall with no args.

### 2.2 What a nation-5 type-9 fleet does [S]

| Phase | VA | Behaviour / hazard |
|---|---|---|
| plan | `0x5B3880` | If the destination is valid and not the current town → go. Else, not at home → go home. Else, at home, pick from the towns with `town+0x390 == +0x172` **or (`town+0x40` bit 22 and pop > 1000)** (`0x5B3A40..0x5B3A62`) **and** bit `idx` in `+0x174..+0x183` (128-bit, `0x5B3A87..0x5B3AA3`). Towns with `+0x91B0` set get double weight. Nothing left → abort `0x5B0730` |
| `+0x174` | reset to all-ones by `0x5B6360` (convoy init, also reached from the Lua-spawn path `0x6339CC`) and by the abort; one bit is cleared per town after an action (`0x5B537A → 0x5ADBC0`) | **Hazard:** nation-5 towns carry bit 22, so they **are candidates** for a nation-5 mission. `0x5B5110` returns early there (`0x5B5175`) without clearing the bit, so the fleet can shuttle between its own town and home. **Fix:** the DLL clears the bits of all nation-5 towns (bit = town handle low word) after assigning and every frame |
| at sea | type 9 has no encounter scan (`0x5AF463` handles this-types 3/4/7 only) | sails straight to the target |
| arrival | `0x5B4D6F`: validity `0x5AD8F0` (type 9, `+0x170 > 0`, **ships > 1**, `IsAtWar(g[5], P)`: NULL → P01 → `player_rel[P]`, correct without an opt-in) → `SelectAction 0x5B07A0` | |
| SelectAction | `0x5B07A0` | destination == current, town nation == `+0x172` (`0x5B085B`), then **`0x63C400(townH, cannons +0x142, sailors +0x86, nation)`**. That function needs `g[5]` (**opt-in `0x63C463`/`0x63C46B`**, else no flag). Allowed list: 1 if flag & r > 1; 2 (r > 5 and player assets); 3 (r > 2); 4 (r > 3); 5 (r > 1); 6, 7, 8, 9, 10, 11 by rank and town flags. **Random pick** (`0x5B09C7..0x5B09DF`) |
| `0x63C400` | sets `+0x48 \|= 0x40` iff `IsAtWar(g[n], town nation)` **and wealth `town+0x58 > 3`** **and** (cannons > 20 × guns `+0x919D` **or** sailors > garrison `+0x38E`) (`0x63C477..0x63C4BB`) | the game's own "can assault" judgement |
| action 1 | `0x5B4DD3 cmp byte [esi+0x171],1` → `0x603030` → `0x5AD650` | siege, see 2.3 |
| actions 2..11 | harbour type-9 branch `0x5B567D` → `0x5B5110`: damage, strike, fire, … (`0x5C4C50`, `0x5C4CF0`, `0x5C5E00`, `0x5C6060`, `0x6253F0`, `0x5F17E0`, `0x624460`, `0x625710`, `0x5C4D60`, `0x6244A0`). Then message 0x2B with the captain byte (`0x5B5278`, needs a captain [H: present for builder fleets]), then **`0x5BA400(g[5], P, now)`** | **crash #11 at `0x5BA40F`** unless `0x5B531E`/`0x5B5326` is opted in. With the opt-in it writes `g_pc+0x158+4P` (inside the 0x170 object) |

So to make a nation-5 war mission end in an assault:
- opt in `0x63C463` (the flag) and `0x5B531E` (sabotage-safe);
- add **hook W `0x5B4DD3`** (`80 BE 71 01 00 00 01`, 7 bytes, no branch-in or data ref; esi = CKonvoi*):
  - if `type == 9 && +0xB8 == 5`: when `+0x48 & 0x40` is set and the current town's nation equals
    `+0x172` → `+0x171 = 1`;
  - otherwise `+0x171 = 0` (no sabotage, if that is preferred);
- the handler runs before the `cmp`, so vanilla then takes the siege branch;
- hook C must accept type 9 (2.4).

### 2.3 How the assault itself runs [S]

**`NewTownAttack 0x603030(convoyH)`** (cdecl, 1 arg) has these preconditions:
- `+0x48 & 0x40`;
- `0x635C40(k+0x4C)` (current CStadt*) ≠ NULL, i.e. the fleet is at or anchored in a town.

For type ≠ 1 it creates a CCoastBattle (0x20 bytes, `0x602F30`) in the store `0x7036C0` and runs
**init `0x602900(convoyH)`**. Init does three things:
- **`0x5AD490` → `0x637450`**: the group's battle handle becomes the siege and **state = 9**
  (`0x640950(9)` writes `group+0x44` = `CKonvoi+0x90`). The fleet is frozen;
- type table `0x602AF0` (types 4 and 9 → `0x6029EC`);
- **land** if sailors `+0x86` > 5 × garrison `+0x38E`. Otherwise `+0x1C` (sea) = cannons `+0x142` >
  20 × guns `+0x919D`. Neither holds → land.

The siege then goes through these states:
1. **State 2.** A docked type 4/9 defender of the town's nation is fought first as an AutoBattle
   (`0x602C4D`/`0x602C53`).
2. **State 6 (land) `0x603200` or state 5 (bombard) `0x603690`.** The fight is an instant formula
   (`military_combat.md` §4.2). A win calls **`AttackerWon 0x602500(townH, convoyH)`**, cdecl. The
   return address is `0x6033FB` for land and `0x6039FE` for sea.
3. **State 7.** The fleet is released.

The only nation read in `0x602400..0x603D00` is the defender compare [S]. The letters are 0x30 (land)
and 0x26 (sea, types other than 9) [H: chronicle wording for nation 5].

### 2.4 Hook C (war.c #7 at `0x602500`) [S for the facts, recommended change]

Today the hook returns unless the town is nation 5, and it then requires a power's type-4 attacker.

Add a branch first. When all of these hold, queue a **nation annex** of the town for `war_frame`:
- the convoy has `+0xB8 == 5` and type 4 or 9;
- the town owner P < 4 and `player_rel[P]`;
- the town is not a viceroy or governor seat (`town+0x44 & 0x2001`, if the core forbids that);
- optionally, the return address is the land win `0x6033FB`.

Vanilla never calls `AddToNation` on this path, so there is nothing to suppress
(`military_combat.md` §4.3). The plunder (goods 8..11, or 16..18+ for type 9) lands in the fleet's
hold. Hook K turns it into gold.

### 2.5 Assault without war missions (recommended): hook S at `0x5B4E35` [S]

- **Site.** `0x5B4E35` is `8B 96 B0 01 00 00` (`mov edx,[esi+0x1B0]`, 6 bytes). It is the type-4
  entry of the arrival table `0x5B50CC[3]` and also follows `0x5B4E33`. `chk2.py` found no branch or
  data reference into `+1..+5`.
- **Registers at the hook.** esi = CKonvoi*. ecx = 0 on the table path (`0x5B4B0D xor ecx,ecx`).
- **Handler.** If all of these hold:
  - the convoy is type 4 with `+0xB8 == 5`, the DLL marked it "assault", and `+0x90 == 4`;
  - the current town T (`0x635C40(esi+0x4C)`) has owner P < 4 with `player_rel[P]`;
  - `!BattleAtTown 0x5FD050(ecx=0x7036C0, TH)`;
  - DLL policy holds. Either sailors > garrison, or call `0x63C400(esi; TH, +0x142, +0x86, 5)`
    (thiscall `ret 0x10`, needs the `0x63C463` opt-in) and test `+0x48 & 0x40`.

  Then it sets `word +0x48 |= 0x40` and calls `0x603030(handle +0xA8)`.
- **Why it works.** The siege sets state 9, and the displaced code then runs `cmp [esi+0x90],4`
  (`0x5B4E4D`). That compare fails (`jne 0x5B4E70`), so vanilla only writes `+0x198 = ecx (0)` and
  returns, with **no "go home" decision**. If the siege was not created, the state is still 4 and the
  vanilla decision runs as usual.
- **Precedent.** Vanilla calls `0x603030` from this same function for pirates (`0x5B4D50`) and for
  type 9 (`0x5B4DF4`), so the re-entrancy is safe.
- **Getting there.** Either sorties (the game picks the enemy town) or the DLL: set `+0x1B0 = TH` and
  call `0x5B19D0(k, TH)` while the fleet is at sea or anchored. Re-issue the order if the fleet
  drops it (§1.1 distraction).

---

## 3. Raiding (Q3)

### 3.1 What `+0x1C` is [S]

`CKonvoi` derives from a sea-map object:
- ctor `0x62C4A0`: vtable `0x6AC1C8`; it zeroes `+0x14`/`+0x18` (prev/next in the x-sorted sea list)
  and `+0x1C`/`+0x1D`;
- `0x62C4D0` and `0x62C510` unlink and clear `+0x1C`;
- `0x62C610`, `0x62C710` and `0x62C840` link and set it;
- `0x62C3A0` (pause) copies `+0x1C` to `+0x1D` and clears it for every linked object.

So **`+0x1C` = "on the sea map (at sea)"**. It is not a hunter or trader flag. The readers agree:
- `0x5AF5FB`: a military convoy attacks a type-2 trader only while it is itself on the map;
- `0x5AD230`: the addend makes the military-vs-military mask `(0x80+1)<<n`, i.e. bits n | n+7, at sea;
- `0x5B6838` (`AttackConvoy` refuses a target that is not on the map);
- `0x5F561B`: the vanilla mission picker takes the strongest fleet with `+0x1C == 0`, i.e. one in
  port.

**Correction for `dll/navy.c` `pick_fleet`.** It reads `K_TRADER_FLAG` as a `uint32` (`+0x1C..+0x1F`).
Vanilla tests the **byte** (`cmp byte [esi+0x1c],0`). A non-zero `+0x1D` (the pause copy) would skip
a fleet wrongly. Read it as `k[0x1C]`.

### 3.2 Which convoys a type-4 fleet engages [S]

The encounter path is: scanner `0x5B1D10` → `ShouldAttack 0x5AF330(this, other)` for every linked
convoy with **dist² < `[0x6AC1C4]` = 10000** (radius 100). The window comes from `[0x6AC1C0]`.

| Other | Handler | Condition |
|---|---|---|
| any with `+0x7C & 0x1000000` (PROTECTED) | `0x5AF343` | never |
| 2 AI trader | `0x5AF5FB` | `this+0x1C` and mask bit `1<<other.+0xB8`, plus the `+0x190` cooldown |
| 3, 7 pirate | `0x5AF566` | always (strength and timers) |
| 4 military | `0x5AF63C` | `this+0x7C & 0x80000` and mask `(0x81)<<n` |
| 1 player | `0x5AF49F` | rep level 0: never for nation 5 |
| 5, 6 | `0x5AF480` | never (without an MTask) |

For nation 5 the mask is built by `0x63C280` (opted in) from `g_pc.rel`. So **raiding of enemy AI
traders is already on** for every nation-5 fleet at war, but only for what passes within radius 100
of its route. The fleet does **not** seek trade convoys.

### 3.3 Directed raids: vanilla MTasks [S]

The MTask fields are:
- `+0x1B8`: task (0 none, 1 attack one, 2 circle, 3 stay);
- `+0x1BC`: target handle;
- `+0x1C0`: target nation byte (6 = player convoys);
- `+0x1C2`/`+0x1C4`: centre;
- `+0x1C6`: radius word;
- `+0x1C8`: end time.

**`ShouldAttack` with a task** (`0x5AF352..0x5AF45A`). While `now > other.+0x190` (or with
FORCE_ATTACK `0x100000`), only targets that match `+0x1BC`, or **`other.+0xB8 == +0x1C0`** (any
convoy type), are attacked:
- for task 3, the target must also be inside the circle;
- the strength check is: attack if `other.+0x78·10 < this.+0x78·9`, else `0x63C180`;
- a non-matching target returns 0;
- the target handle goes to `+0x168`.

**At sea** (`0x5B3C13..0x5B3CA7`) a task bypasses the type brain (decision, sorties, patrol):
- inside the area (`0x5B0C70`): hunt `0x5AED30` and scan `0x5B1D10`;
- outside: `0x5B0AA0` sails back into the area.

**In harbour** (`0x5B53CF..0x5B53FE`) a task skips the harbour cycle (repair, hold dump, re-arm) and
leaves for the area.

**Expiry** is in `0x5ADA80`: task 1 ends when `+0x168` is invalid; tasks 2 and 3 end when
`now > +0x1C8`.

| Task | Internal (thiscall `ecx = CKonvoi*`) | Lua |
|---|---|---|
| attack convoy | `0x5AD990(targetH)` `ret 4` | `Convoy_SetMTaskAttack` `0x424E60` |
| circle | **`0x5AD9F0(const u32 *pos, u16 radius (≤0 → 75), u32 targetH, u8 nation, u32 endTime)`** `ret 0x14`; it fails (task 0) if `0x62DE60(pos, radius)` refuses | `Convoy_SetMTaskCircle` `0x424F80` (6 args, `{X=,Y=}` table) [H: exact arg order] |
| stay | **`0x5B0A30(const u32 *pos, u32 targetH, u8 nation, u32 endTime)`** `ret 0x10`. Sails to pos (`0x5AE1B0`); radius = `+0x1C6` (default 100, set by `0x5B6360`) | `Convoy_SetMTaskStay` `0x4251A0` |
| none | `0x5ADAF0()` | `Convoy_SetMTaskNone` `0x428A10` |

**Inputs.**
- pos = `0x63ADC0(&pos, x, y)` (cdecl, returns `&pos`). A town's x,y are the words at `CStadt+0xE` and
  `+0x12`, the same as a convoy's (`0x5B4A2B`).
- `targetH` = `0x0002FFFF` (invalid; it matches nothing).
- `endTime` = `*(u32*)0x702C14 + days·256`.

**Raid recipe.** `0x5AD9F0(k, &pos(enemy port ± offset), 200..300, 0x0002FFFF, P, now + N·256)`.
The fleet circles the enemy's sea lane and attacks every P convoy it can beat: traders, transports,
treasure fleets and weaker warships. It ignores pirates while the task runs. Keep N small, because
the fleet neither repairs nor re-arms during the task. **Never use nation 5 or 6 in `+0x1C0`.**

### 3.4 A task given in port traps the fleet there (the idle-fleets-and-freeze report, runtime-verified)

The raid recipe above only works for a fleet **at sea**. Until v2026.10.17 the DLL gave the Circle
task to *docked* fleets (`send_raids` picked `+0x90 == 2` only). Such a fleet never left port.

**Why** [S, `tools/check_facts.py` NV-*]:
- State 2 (docked) ticks the harbour timer `+0x198` and then calls the harbour AI `0x5B53C0`
  (`0x5B5D7D`).
- The harbour AI checks the task first (`0x5B53CF call 0x5ADA80` = expiry, then
  `cmp [esi+0x1B8],0`). With a task it **skips the whole harbour cycle**: the type switch with
  repair, re-arm, the type-4 decision and `SailToTown 0x5B19D0` is never reached. It calls
  `0x5B0C70` (inside the circle?) and, outside the circle, `0x5B0AA0`.
- `0x5B0AA0` for task 2 only calls `TaskCircle 0x5AD9F0` again (`0x5B0BBC`). That plots a route
  (`0x62DE60` puts it in `+0x2C`) but does not move the convoy. Only state 0 moves (`0x62D2B0`).
  The town is left only by `SailToPos 0x5AE1B0`, which calls `LeaveTown 0x6374A0` (`0x5AE216`), and
  the DLL reaches that through `SailToTown`.
- The result is that the fleet sits in port, re-planning its circle every tick, until the task ends
  (`now > +0x1C8`, 20 days). On that same day the DLL's 20-day raid timer was due again and gave a
  new task to the still-docked fleet. That is the "raids English shipping around X" line every
  20 days without the fleet ever sailing.

**Seen in the reporter's `Quick Save` (the idle-fleets-and-freeze report)** with the old DLL: all 8 fleets of the nation were
`+0x90 = 2`, `+0x1C = 0`, `+0x1B8 = 2`, harbour timer 0. Six were at Turk Islands, two at Port au
Prince. In 5 game days none of them left (a private probe). Five fleets commissioned
together made no difference: each got its task in port on the next day tick and was trapped like
the others.

**Fix (`dll/navy.c`).**
1. `send_raids` (day tick) checks a docked fleet under the raid order: at least 2 ships, no task
   running, at least `RAID_REFIT_DAYS` (2) in port, and 20 days since its last raid. The fleet gets
   `+0x1B0 = target port`, then `SailToTown`, and is in state 0 at once. It is linked into the sea
   map (`+0x1C`) a moment later.
2. `raid_tick` (frame hook, every 30 frames) gives the Circle task as soon as the fleet is on the
   map. The task ends on the raid's day + 20.
3. A docked fleet of the nation that has a task is trapped (old saves, or a fleet that docks while
   its task runs). `raid_tick` cancels the task with `TaskNone 0x5ADAF0`, so the harbour cycle
   resumes and the next day's check sends the fleet out properly.
4. `port_watch_tick` logs every real departure and arrival: `NAVY: fleet X leaves port at T for D`
   and `NAVY: fleet X in port at T`. "In port" means state 2 (docked) or 3 (waiting in a town).
   `+0x1C` is not used for this, because it flickers while a convoy anchors.

---

## 4. Loot value and the hold (Q4)

### 4.1 Base price table [S]

**`u16 SWP[20]` at `0x702114`** (BSS). It is filled at startup by `0x5CB300`:
`GetPrivateProfileInt("SWP", name, 10, "./Data/waren.ini")`, with the names at `0x6E4190[20]`. After
loading it also builds `u8 order[20]` at `0x702100`, sorted by price.

- **Meaning:** waren.ini says "Standardwarenpreis = mittl. Produktionspreis = 1 auf Preiskurve". The
  unit is **gold per hold unit (barrel)**. Convoy amounts are in the same units the price engine
  takes (`0x5CBE46`/`0x5CBE49`: amount × 19200 = raw town units).
- **Readers:** the price engine `0x5CBDA0` (`0x5CC0CF`: factor × `SWP[g]`), `GetBasePrice 0x5D2BB0`
  (thiscall on a CPlayer: `+0x8C == NULL` → `SWP[g]`, else `0x5C35F0` [H: player price memory],
  `ret 8`), and about 20 more.

| id | good | SWP | id | good | SWP |
|---|---|---|---|---|---|
| 0 | Weizen | 80 | 10 | Seile | 300 |
| 1 | Früchte | 80 | 11 | Rum | 300 |
| 2 | Holz | 80 | 12 | Kaffee | 150 |
| 3 | Lehmziegel | 80 | 13 | Kakao | 150 |
| 4 | Mais | 100 | 14 | Farbstoffe | 150 |
| 5 | Zucker | 100 | 15 | Tabak | 150 |
| 6 | Baumwolle | 100 | 16 | Gewürze | 500 |
| 7 | Hanf | 100 | 17 | Wein | 500 |
| 8 | Fleisch | 300 | 18 | Werkzeug | 500 |
| 9 | Kleidung | 300 | 19 | Siedler | (10, default) |

The game itself values a cargo record this way in `0x603D70` (used for the battle report at
`0x5FC6FA`): `Σ_{i<19} goods[i]·SWP[i] + word[+0x5C]·[0x6A4F4E] (= 800) + dword[+0x30]`. Use
`Σ amount·SWP` (times a tunable factor) for loot.

Current town prices are available through Lua `Town_GetGoodsPrice(town, good)` (`0x42B1D0`, good
< 0x14). It runs `0x5CBDA0(ecx=0x70213C, …)` and returns int64 × 2⁻³² [H: buy or sell side].

### 4.2 Where the loot is [S]

- **Goods.** `0x638670` (add) and `0x638690` (remove; it returns the amount actually moved in AX)
  both take `ecx = CKonvoi+0x4C`, `(good, amount)`, `ret 8`.
  - goods `u16[20]` at **`CKonvoi+0xBE + 2g`**;
  - used `u16 +0xBC`;
  - capacity `u16 +0x80` (Lua `Convoy_GetCapacity` `0x42A8C3`);
  - average purchase price word pair at `+0xE8 + 4g` (cleared at 0).
- **Weapons.** `0x639DF0` (add) and `0x6379E0` (remove), `(kind, n)`, `ret 8`, store `u16[6]` at
  **`CKonvoi+0x138 + 2k`**: k = 0 cutlasses, 1 muskets, 5 cannons (`+0x142`, 3 hold units each).
- **The auto-battle (state 3) moves goods B→A** with `remove → add` (`0x5FB0E1..0x5FB105`). The words
  at hook B (`0x5FB107`, `esp+0x3C+2i`) are the **requested** amounts; the moved amounts were in AX
  and are gone. Ships captured in state 2 (`0x5B6E20`) and state 3 (`0x638B50`) bring their cargo
  into A's group.
- **`AttackerWon` plunder** also goes into A's hold (`0x638670`).

### 4.3 Vanilla empties a military hold at every docking [S]

Harbour AI type 4 (`0x5B578A`), **sub-state 1** (`0x5B582A..0x5B5895`):
1. `for g in 0..19: 0x638690(k+0x4C, g, 10000)`. The whole hold is **deleted**: it is not sold and
   not given to the town;
2. the free hold is refilled with cannons up to `+0x84` (`0x639DF0(5, n)`, limited to free/3);
3. `0x5AD780` follows.

A nation-5 fleet docks only in nation-5 towns (`0x637323`). So:
- **Hook K at `0x5B582A`** (`32 DB 88 5C 24 10`, 6 bytes; no branch-in or data ref; esi = CKonvoi*,
  ebp = 0). If `type == 4 && +0xB8 == 5`: `gold = Σ_{g<19} u16[esi+0xBE+2g] · SWP[g] · k`, credit the
  treasury, log it. Vanilla deletes the goods right after. This counts raids, captured ships' cargo
  and town plunder exactly once, in port.
- To empty a hold from the DLL at another time, call `0x638690(k+0x4C, g, 0x7FFF)` for g = 0..19
  outside battle (`+0x90 != 9`). Do not remove weapon kinds 0, 1 and 5: they are the fleet's arms.
- Alternative, not chosen: hook B plus a snapshot at state-3 entry (`0x5FAC90`) to diff A's hold.

---

## 5. Disband and reinforce (Q5)

### 5.1 `DeleteConvoy 0x635600(u32 convoyH)` (cdecl; the caller pops 4) [S]

1. Resolve the pool slot (invalid → return).
2. Owner CPlayer through `0x635FD0`.
3. Event through `CKonvoi+4` (`0x450090`).
4. **`0x634790`**: delete the ships (`0x63F7D0`), the captain (`0x5D67D0`), leave the map and town
   (`0x62CBC0`, `0x636840`), then **`ClearOwner 0x636670`**. With the opt-in, that removes the convoy
   from `g_pc+8`.
5. Pool free (`0x6312E0`), owner list (`0x5D2C40`), UI notify (`0x51E980`, `0x703BF0`).

**Preconditions:**
- **`+0x90 != 9`** (battle or siege). Lua `Global_DeleteConvoy 0x4266A0` deletes only then
  (`0x426738`). For state 9 it walks the ships instead (`0x63AB50`/`0x63A820`) and zeroes a field
  [H: lets the battle sink them];
- call it from the DLL frame hook, not from inside a convoy tick [H: the world tick iterates
  convoys];
- other convoys validate their stored handles (`0x5C2410` at `0x5B3C64`), so a stale `+0x168` is
  harmless [S].

**Recommended pay-off:** delete only when `+0x90 == 2` (docked at a nation town). Then
`navy_fleet_count()` drops at once.

### 5.2 Reinforcement [S]

| Need | Call | Notes |
|---|---|---|
| more ships | Lua **`Convoy_AddShips(h, {t1, t2, …})`** `0x426A70` | per entry: `0x63FD50(&shipH, townH = 0x417D60(k+0x4C) (current town), ownerH = 0x635FD0, type)` (cdecl, 4 args), then **`0x636210(k+0x4C, shipH)`** (thiscall `ret 4`). Stops at **10 ships** (`+0x95 < 10`). Use it while docked: the ship is built "in" the current town [H: invalid town at sea → throw] |
| one existing ship | Lua `Convoy_AddSingleShip(h, shipH)` `0x428610` | `0x636210`, then the ship's owner is set to the convoy's (`0x60D0B0`), then `0x63F960` |
| new loose ship | Lua `Global_CreateShip(type, playerH, townH)` `0x4264E0` | `0x63FD50` |
| sailors | Lua **`Convoy_AddSailors(h, n)`** `0x4210A0` → `0x6415A0(k+0x4C, n)` `ret 4` | cap: `Convoy_GetMaxSailors` `0x421150` |
| cannons | free: harbour sub-state 1 refills up to `+0x84` | or `0x639DF0(k+0x4C, 5, n)` `ret 8` |

**Ship types for the navy:** flagship `g_flag6[5]` (0x0F). The escorts follow the vanilla table
`0x6AC4AC[r·4+n]`; index 5 gives 0x09/0x0D.

---

## 6. Recommended implementation

### 6.1 Exe/runtime patches (DLL `navy_install`)

| # | Purpose | Site (old bytes) | Change | Needed for |
|---|---|---|---|---|
| O1 | sortie gate | `0x5B1FF7` `83 F8 04` / disp `0x5B2003` `14 2B 70 00` | `opt_in("navy.Sortie", 0x5B1FF7, 0xF8, 0x5B2003)` | sorties |
| O2 | sortie target | `0x63B3C8` `83 F8 04` / disp `0x63B3DA` | `opt_in("navy.SortieTarget", 0x63B3C8, 0xF8, 0x63B3DA)` | sorties (always with O1) |
| O3 | siege judgement | `0x63C463` `83 F8 04` / disp `0x63C46B` | `opt_in("navy.SiegeFlag", 0x63C463, 0xF8, 0x63C46B)` | war missions; lets hook S use `0x63C400` |
| O4 | buccaneer date (crash #11) | `0x5B531E` `83 F8 04` / disp `0x5B5326` | `opt_in("navy.BuccDate", 0x5B531E, 0xF8, 0x5B5326)` | war missions (any action 2..11) |
| R1 | rank gate (optional) | `0x5B48C4` `0F 86 EE 00 00 00` | `90 90 90 90 90 90` | only if the DLL calls `0x5B4870` itself at rank ≤ 1. Also lifts the gate for `navy_daily` |
| S | type-4 arrival assault | `0x5B4E35` `8B 96 B0 01 00 00` (6) | `hook_install` | assault (recommended path) |
| W | force siege action | `0x5B4DD3` `80 BE 71 01 00 00 01` (7) | `hook_install` | war-mission path only |
| K | plunder → gold | `0x5B582A` `32 DB 88 5C 24 10` (6) | `hook_install` | loot |
| C | annex | `0x602500` (existing war.c #7) | add the nation-5-attacker branch (§2.4) | conquest |

All the opt-ins keep index 4 on the NULL path (`g_nations6[4] = NULL`) and leave powers 0..3
unchanged.

### 6.2 DLL calls (exact conventions)

```c
typedef char (__thiscall *Assign_t)(void *k, uint32_t target, uint32_t count);   /* 0x5B4870 ret 8 */
typedef void (__thiscall *SetType_t)(void *grp, uint32_t type, uint32_t nation);  /* 0x637050 ret 8, grp = k+0x4C */
typedef void (__thiscall *Void_t)(void *k);                    /* 0x5AD650, 0x5B3880, 0x63CA20, 0x5ADAF0 */
typedef char (__thiscall *Sail_t)(void *k, uint32_t townH);    /* 0x5B19D0 ret 4 */
typedef void (__cdecl    *Attack_t)(uint32_t convoyH);         /* 0x603030 */
typedef void (__thiscall *SiegeOk_t)(void *k, uint32_t townH, uint32_t cannons, uint32_t sailors, uint32_t nation); /* 0x63C400 ret 0x10 */
typedef void*(__thiscall *CurTown_t)(void *grp);               /* 0x635C40, grp = k+0x4C -> CStadt* */
typedef uint32_t *(__cdecl *MkPos_t)(uint32_t *out, int x, int y);                 /* 0x63ADC0 */
typedef void (__thiscall *Circle_t)(void *k, const uint32_t *pos, uint32_t radius,
                                    uint32_t targetH, uint32_t nation, uint32_t endTime); /* 0x5AD9F0 ret 0x14 */
typedef void (__thiscall *Stay_t)(void *k, const uint32_t *pos, uint32_t targetH,
                                  uint32_t nation, uint32_t endTime);                     /* 0x5B0A30 ret 0x10 */
typedef uint16_t (__thiscall *GoodsRm_t)(void *grp, uint32_t good, uint32_t n);    /* 0x638690 ret 8 */
typedef void (__cdecl    *Delete_t)(uint32_t convoyH);         /* 0x635600 */
#define SWP ((const uint16_t *)0x00702114)                     /* u16[20], gold per unit */
#define NOW (*(const uint32_t *)0x00702C14)                    /* 256 ticks per day */
```

**Fields** (offsets on CKonvoi*):

| Offset | Field |
|---|---|
| `+0xA8` | handle |
| `+0xB4` | type |
| `+0xB8` | nation |
| `+0x90` | state |
| `+0x95` | ships |
| `+0x48` | mask (word) |
| `+0x7C` | flags |
| `+0x86` | sailors |
| `+0x142` | cannons |
| `+0x9C` | current town handle |
| `+0x44` | home |
| `+0x1B0` | destination |
| `+0x170` | mission count |
| `+0x171` | mission action |
| `+0x172` | mission target nation |
| `+0x174..0x183` | mission town bitmask |
| `+0x1B8..0x1C8` | MTask fields |
| `+0xBE + 2g` | goods |

Town (CStadt*):

| Offset | Field |
|---|---|
| `+0x390` | owner |
| `+0x40` | flags (bit 22 own town) |
| `+0x44` | flags (`& 0x2001` = governor or viceroy seat) |
| `+0x58` | wealth |
| `+0x38E` | garrison |
| `+0x919D` | guns |
| `+0xE` / `+0x12` | x / y |

### 6.3 Behaviour to implement

1. **Sorties (no new DLL code).** Install O1 and O2. The fleets now strike at enemy ports on their
   own and raid what they meet.
2. **Assault order ("attack T" / "attack power P").**
   - The DLL keeps a per-fleet `assault_target`: a town or "any town of P".
   - Hook S at arrival: if the conditions in §2.5 hold → `k[0x48] |= 0x40; 0x603030(k_handle)`.
   - For an explicit town, while `+0x90 == 0` or `4` and `+0x1B0 != TH`: set `+0x1B0 = TH` and call
     `0x5B19D0(k, TH)`. Clear the order when the town changes owner or after N days.
   - Hook C (war.c #7): nation-5 attacker of type 4 or 9 → queue the annex.
3. **War missions (optional, for a campaign).**
   1. `k[0x7C] |= 0x10000`;
   2. call `0x5B4870(k, P, 1..3)` (R1 when rank ≤ 1), or do what it does (§2.1(b));
   3. then and every frame, clear the `+0x174` bits of all nation-5 town indices for nation-5 type-9
      fleets;
   4. install O3, O4 and W.

   The mission ends by itself (abort `0x5B0730` → type 4) when the war ends, ships ≤ 1, or no P town
   is left.
4. **Raid order.** `0x63ADC0(&pos, x, y)`, then
   `0x5AD9F0(k, &pos, 250, 0x0002FFFF, P, NOW + days·256)`. Cancel with `0x5ADAF0(k)`.
5. **Plunder.** Hook K credits `Σ goods·SWP` (× tuning) for nation-5 type-4 fleets at docking.
6. **Disband (`navy_disband`).** Pick docked nation-5 fleets (`+0x90 == 2`, type 4) and call
   `0x635600(handle)` from the frame hook. Or run Lua `Global_DeleteConvoy(h)`.
7. **Reinforce.** While docked: `plua_run("Convoy_AddShips(h,{15,9})")` and
   `"Convoy_AddSailors(h,n)"`.

### 6.4 Tests to add (runtime)

- **Sortie:** at war with Spain → within a few days `+0x1B0` is a Spanish town; the fleet anchors
  there (state 4) and returns.
- **Assault:** flag one fleet and send it to a weak Spanish town → state 9 → `AttackerWon` (hook C
  log) → annex queued.
- **Raid:** a Circle task near Spanish lanes → `+0x168` takes Spanish traders → hook K credits gold
  at docking.
- **War mission:** with O3, O4 and W → type 9 → siege; with W off and rank > 3 → a sabotage action
  runs without crashing (O4).
- **Disband in port:** the count drops and save/reload is clean.

## 7. Confidence

- **High [S]:**
  - the sortie path, gate maths and picker;
  - the arrival flow and why hook S skips the "go home" decision (state 9 from `0x637450`/`0x640950`);
  - the `AssignWarMission`, `SelectAction`, `0x63C400` and `0x5B5110` conditions;
  - the `+0x174` semantics and the bit-22 own-town hazard;
  - `+0x1C` = on-map;
  - the MTask conventions;
  - the SWP table and loader, the hold layout and the harbour dump;
  - the `0x635600` and Lua conventions.
- **[H], to check at runtime:**
  - the captain wording for name id 50 (avoided by setting `0x10000`);
  - chronicle and letter wording for nation-5 attackers;
  - the meaning of `0x62CA00(0x28)`;
  - calling `0x5B19D0`/`0x603030` from the frame hook outside the convoy tick;
  - `Convoy_AddShips` at sea;
  - the exact Lua argument order of `Convoy_SetMTaskCircle`/`Stay` (use the internal calls);
  - whether `Town_GetGoodsPrice` is the buy or the sell side.
