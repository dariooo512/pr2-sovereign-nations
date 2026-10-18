# Military AI for the player nation (nation 5): can vanilla drive nation-5 military convoys?

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000). The game was not
launched and no repo file other than this one was changed. Tools: pefile + capstone. The function
boundaries come from the Reko `byfn` list. Where Reko merged functions, the real start was found by
scanning back to the `CC` padding. Scratch scripts are in the session scratchpad `agent_mil/`:
- `pe.py`: disasm, callers, sweep;
- `closure.py`: call-graph closure of the military code, depth 4, 548 functions;
- `sites.py`: every `+0xB8` read in that closure.

Labels:
- **[S]**: VERIFIED-STATIC. The bytes or instructions at the VA were read.
- **[H]**: HYPOTHESIS. Purpose or runtime value inferred, not observed.

## 0. Answer in one paragraph

A power's military convoys come from two places:
- a per-nation timer event checks every 0x3C00 ticks whether the power has fewer military convoys
  than its target, which is its town count, plus 3 while it is at war;
- build-up bursts at new game, war start and annexation.

All of this runs only for nations 0..3, and the convoys live in the list `CNation+8`.

The convoy brain is a state machine on `+0x90`. When idle it calls the decision function
`0x5B1DF0`, which:
- rebuilds the attack mask `+0x48` from `IsAtWar(own, j)`;
- picks a patrol town by cost;
- every 5th time, if the fleet is big enough, picks an enemy town to sail at.

At sea a scanner attacks:
- pirates, always;
- enemy warships, only when strong;
- enemy-nation AI traders, under a flag;
- the player's convoys, when reputation is hostile.

It never attacks transports or treasure fleets. Sieges and town raids happen only on vanilla
"war missions" (type 9), and only `0x5F5360` hands those out, for the 4×4 power pairs.

A convoy with `+0xB8 = 5` is mostly fine: P01 already makes `IsAtWar(NULL, …)` mean "the player
nation". But there are **three hard blockers and three soft ones**:
- Blocker: `SetType` silently turns a nation-5 military convoy into **nation 4 (pirate)**.
- Blocker: the home-town picker `0x63C780` **crashes for any nation ≥ 4**. It dereferences address 8.
  This resolves the census's "unresolved" site `0x63C7AB`.
- Blocker: the flagship type table `0x6AC4B4` gives **type 0xF0** for index 5 at four sites. One of
  them is a re-arm step in governor towns such as Margarita, indexed by the convoy's own nation.
- Soft: the mask builder returns mask 0, so the convoy hunts nothing.
- Soft: the war-mission action writes through a NULL `CNation` (crash `0x5BA40F`).
- Soft: nothing replenishes the fleet.

**Verdict: feasible.** The cheapest correct variant is **A1-lite**:
- a static player `CNation` built with the vanilla ctor;
- the `nations6` mirror from `player_cnation_design.md`;
- **5 required 5-byte opt-ins**;
- one relocated 6-byte ship-type table;
- a DLL that spawns ships through `Global_CreateMilitaryConvoy` and replenishes the fleet.

A pure "display-byte" trick (A2) cannot work for the convoy-indexed sites, because a convoy has no
display byte. The home picker needs a real `CNation+8` list either way.

## 1. Lifecycle of a power's military convoys

### 1.1 Types, lists and fields [S]

Convoy types `+0xB4` come from the Lua constants registered at `0x43C7B0..0x43C8B9`
(`push n; push "CONVOY_x"`):

| Type | Lua name | Meaning |
|---|---|---|
| 1 | `CONVOY_PLAYER` | Player convoy |
| 2 | `CONVOY_AI_TRADER` | AI trader |
| 3 | `CONVOY_PIRATE` | Pirate |
| **4** | **`CONVOY_MILITARY`** | Patrol fleet |
| 5 | `CONVOY_TRANSPORT` | |
| 6 | `CONVOY_TREASURE` | |
| 8 | `CONVOY_MISSION` | |
| **9** | **`CONVOY_BUCCANEER`** | The military convoy while on a war mission |

**Inner `SetType(type, nation)` `0x637050`** (thiscall on `convoy+0x4C`, `ret 8`):
- it first calls `ClearOwner 0x636670`;
- it then switches on `type-4` through the table at `0x637180`.

| Type | Entry | Effect |
|---|---|---|
| **4, 9** | `0x637070` | guard `0x63707A cmp eax,4` / `0x63708A mov edi,[eax*4+0x702b14]` / `test edi,edi` → `+0x6C = n` and **insert into `CNation[n]+8`** (`0x6370AA lea ecx,[edi+8]; call 0x636dd0`) |
| 5 | | list `+0xC` |
| 6 | | list `+0x10` |
| 8, 10 | | store n raw |
| **4/9 with n ≥ 4** | `0x637137` | **`mov byte [esi+0x6c],4`**: the convoy becomes nation 4 |

**`CNation` lists** [S]:
- `+8` = military, types 4 and 9 (read by `0x5BBB00`, which counts them);
- `+0xC` = transports;
- `+0x10` = treasure fleets;
- `+0x14` = towns.

The list helpers are thiscall on `&list_head_field` with `ret 4`:
- `0x636DD0` = insert-unique (handle), at `0x636DE0..0x636E0C`;
- `0x636630` = remove (handle). It returns AL=0 if the handle is absent, so it is safe.

**`ClearOwner 0x636670`**, types 4/9: guard `0x636720 cmp eax,4`, load `0x636725`, then remove from
`+8`.

**Convoy field map** (on top of `conquest_trigger.md`) [S unless marked]:

| Off | Meaning | Evidence |
|---|---|---|
| `+0x44` | home town handle | `0x417E00` `add ecx,0x44`; set by `0x63CA20` |
| `+0x48` | word attack mask | see §2.3 |
| `+0x7C` | flags | Lua flags: `0x10` LEAVE_MAP, `0x20` PIRATE, `0x40` INACTIVE, `0x100000` FORCE_ATTACK, `0x200000` NO_FENCING, `0x400000` DELAYED_DESTRUCTION, `0x800000` SMUGGLE, `0x1000000` PROTECTED (values pushed next to the names). Internal flags: bits 13..15 = patrol counter (`0x5B1FD0`); `0x80000` "has docked" (`0x6372D3`, `0x637335`) [H on name]; `0x2000000` escort mode; `0x10000` "preferred for war mission" (`0x5F5604`) [H] |
| `+0x90` | state | §2.1 |
| `+0x95` | ship count | `0x635920` [H on exact name] |
| `+0x9C` | current town | `0x417D60` (inner `+0x50`) |
| `+0x142` | strength word | |
| `+0x168` | **pursuit target convoy handle** | set by the scanners, read by `0x5AED30` |
| `+0x170` | mission count | |
| `+0x171` | mission action | |
| `+0x172` | mission target nation | |
| `+0x198` | timer | |
| `+0x19C` | harbour sub-state | |
| `+0x1B0` | **destination town** | `0x417E40` |
| `+0x1B8` | engagement state | |

### 1.2 Who creates them [S]

| Path | Code | Behaviour |
|---|---|---|
| Build-up `CNation::0x5BBB20(bool annexFlag)` | callers: `0x5BBEE0` (new game, from `0x5BBEB0` ← `0x580DD5`), `0x5F52B5`/`0x5F52D1`/`0x5F57BA`/`0x5F57D6` (peace/war events, both sides), `0x5BC5D3` (annexation, `push 1`) | `desired = 0x5BBAB0()`; if `desired > count(+8) + pending(+0x168)` then `+0x168 = desired − count`. With a local player, this is capped at `word[0x703A30]/10 + 1`. With `annexFlag` it is capped by the annex counter `+0x16C` (≤1→0, 2→1, 3→3, >3→6) and by `word[0x703A30]/5 + 1` (`0x5BBBCD..0x5BBC37`). It then schedules the build event: `0x5F1B30(n,0)` |
| Desired count `0x5BBAB0` | | **number of towns in `+0x14`, plus 3 if at war with any power** (`0x5BBACC jne 0x5bbae9` → `lea eax,[edx+3]`) |
| Build event, type 0xE (vtable `0x6AAE5C`, `+8` = nation) | created by `0x5F1B30` (`0x5F1B38 cmp eax,4` guard) | Execute `0x5F1A20` (`0x5F1A24 cmp eax,4`) → `CNation::BuildOne 0x5BA440` every 0x100 ticks while `+0x168 > 0` |
| `BuildOne 0x5BA440` | | `home = 0x63C780(nation)`; `pos = 0x63ADC0(town x,y)`; `0x6350D0(nation, homeH, pos)`; `+0x168--` |
| Replenish event, type 5 (vtable `0x6AAF00`, 0x1C bytes, `+0x19` = nation) | created by `0x5F3630(n)` (`0x5F3641 cmp bl,4`) at new game (`0x5BBED4`); first check at `now + 0x5A00 + n²` | Execute `0x5F3D20` (`0x5F3D30 cmp eax,4`) runs three timers. The third is `0x5F3C30`: if `desired > count + pending`, build one at once (`0x5F3CDD call 0x6350d0`). It returns 0x3C00 as the next delay |
| Builder `0x6350D0(nation, homeTownH, pos)` (cdecl) | | **rejects n ≥ 4** (`0x6350DC cmp esi,4` / `0x6350E6` / `test eax,eax`). Then: new convoy (`0x633580`); flagship type `0x63511A mov al,[esi+0x6ac4b4]`; ship `0x63FD50`; `Init 0x633AF0(…, type 4, nation)`; `0x6346F0(pos)`; escorts `0x6348E0(homeH, nation)` |
| `CConvoyCreate::NewKonvoiMilitary(townH)` `0x635270` (cdecl) | only caller: Lua `0x426A1F` | nation = the **town's** byte: leader type `0x6352B7 movzx eax,[eax+0x358]` / `0x6352BE mov cl,[eax+0x6ac4b4]`. It docks the convoy in that town: `0x633940(ship,4)` → `0x633A4B mov dl,[ebp+0x390]` → `SetType(4, townNation)`, then EnterTown. Then `0x6346F0(-1)` → `0x63C780`, then escorts `0x6348E0(townH, 0xFF)` |
| Lua `Global_CreateMilitaryConvoy(n, pos \| townH)` `0x426810` | | `0x426848 cmp al,4; jae → return -1`. With a table `{x,y}` it uses home picker + `0x6350D0`. With a number that is **a valid town** (`0x426977 call 0x633480`), it calls **`0x635270(townH)`**, and the n argument is **ignored**. An invalid handle goes through home picker + `0x6350D0` |
| Lua `Global_SetMilConvoys(n, count)` `0x42E670` | | `0x42E6C0 cmp bl,4; jb` (else throw). The count is clamped to 0..80 (`0x42E72F`). It builds `count − have` via `0x63C780` + `0x6350D0`, or deletes surplus |

The CNation "daily tick" `0x5BA5A0` has **no military code**. Its calls are town and statistics
helpers only: `0x5CACA0`, `0x5CAC10`, `0x5C8AA0` [S].

**Fleet size per convoy**: `0x633F50(…, nation)` derives the wanted ship counts from the **local
player's rank** `0x5A8DA0` (clamped to 2..5, then `(r+1)/2`; nations 0 and 3 are capped at 2:
`0x633FD8..0x633FE7`). The escort builder `0x6348E0` and the re-arm step `0x634160` both use it.

**`word[0x703A30]`** is a per-game statistics counter. It is zeroed with the block at `0x60E54D`
and increased by `0x60E850` from `0x60BDC0`, inside the sea-battle result code `0x60BAD0`. [H: the
player's naval victories.] Military build-up therefore scales with the number of towns, with war,
with the player's statistics, and (on annexation) with the annex counter.

### 1.3 Home, destruction, replenishment [S]

**Home town `+0x44`** is set by `0x63CA20`. That function calls the home picker `0x63C780(nation)`
when the current home is invalid or no longer owned by the convoy's nation (`0x63CA8C cmp
[eax+0x390], cl`). It is called:
- at the end of every build (`0x63477D`);
- from `0x5B1FAD`;
- from `0x5B497B`.

**Home picker `0x63C780(out, P)`**:
- `0x63C7A0 cmp eax,4`, `0x63C7A8 mov ebx,[eax*4+0x702b14]`, else `xor ebx,ebx`;
- it walks the towns with `+0x390 == P` and keeps the one with the fewest of P's convoys heading
  there. Those are counted by walking **`ebx+8`** (`0x63C8D2 add ebx,8 / push ebx / call 0x640120`);
- town index limit 0x4C (`0x63C83E`);
- if there is no own town, it falls back to the target picker `0x63B3A0(out, P)` (`0x63C9DF`).

**Destruction**: a lost sea battle removes the convoy, and `ClearOwner` takes it off `CNation+8`.
The battle end `0x609D10` calls `0x5BA4C0(nation)`, which re-arms the nation's type-5 event
(`0x5BA4E7 cmp [eax+0x19],bl` → `0x5F3390`). The replenish event then refills up to `desired`.

**Persistence**:
- the convoy's type and nation are restored **raw** by `0x635AC0` (`0x635AE7 mov [edi+0x68],edx`,
  `0x635B00 mov [edi+0x6c],cl`), with no `SetType`;
- the per-nation lists are part of the `CNation` blob.

## 2. The military state machine

### 2.1 Tick dispatch [S]

`Convoy::Tick 0x5B5CF0` is called from the world tick at `0x5D2922`. It switches on `+0x90`
through the table at `0x5B5E70`:

| State | Handler | Meaning |
|---|---|---|
| 0 | `0x5B5D44` | at sea. `0x62D2B0` moves a step. On arrival → `0x5B49C0`, otherwise → **at-sea AI `0x5B3BD0`** |
| 2 | `0x5B5D72` | docked. Timer `+0x198`, then **harbour AI `0x5B53C0`** |
| 3 | `0x5B5D98` | wait (`0x635F30`), then message 0xC [H] |
| 4 | `0x5B5E18` → `0x5B5B70` | **anchored outside, idle**. Switches on type (table `0x5B5CC8`): type 4 → **`0x5B1DF0` decide**; type 9 → timer, then `0x5B53C0` |
| 5 | | `0x63A5A0` |
| 7 | | timer, then `0x5AF1D0` |
| 8 | | `0x635F30` |
| 9..12 | | nothing [H: in battle or frozen. `0x5B48CA` and `0x5F1E36` both refuse state 9] |

`EnterTown 0x6371D0`, for non-player types (table `0x637374`):
- if the town's nation equals the convoy nation (`0x637323 cmp cl,[esi+0x6c]`), it docks (state 2)
  and sets `+0x7C |= 0x80000`;
- otherwise it anchors (state 4).

A nation-5 convoy therefore docks in nation-5 towns and anchors at power towns.

### 2.2 Decision function `0x5B1DF0` (type 4) [S]

1. **Mask**: `0x63C280(this, strong ? +0xB8 : 0xFF)`. "Strong" is `0x635920`: type 4, more than 2
   ships, crew and morale ratios.
2. `+0x7C & 0x10` (LEAVE_MAP): sail to the map edge (`0x5AE1B0`). `+0x7C & 0x2000000`: escort
   target `0x63C5B0` → `+0x1B0`.
3. If the destination is valid and not the current town:
   - destination owned by its own nation → go;
   - else if the distance is ≥ 2500 → go;
   - otherwise clear the destination.
4. If the home `+0x44` differs from the current town, it re-homes when the home's owner changed
   (`0x5B1F9D cmp al,[esi+0xb8]` → `0x63CA20`) and sails home (`0x5B19D0`).
5. **At home**: counter = `((+0x7C >> 13) + 1) & 7` (`0x5B1FD0`).
   - **Counter < 5 → patrol**: `0x63B840(out, homeTownH)` → `+0x1B0`.
   - **Counter ≥ 5 → sortie**, but only if `nation < 4 && g_nations[n] && 0x5BBE30()`
     (block `0x5B1FF7`). `0x5BBE30` returns non-zero when `count+pending` is large enough for the
     town count (`0x5BBE47..0x5BBEA2`). The target is `0x63B3A0(out, nation)` → `+0x1B0`, then
     `0x62CA00(0x28)`.
   - Otherwise the counter is reset and the convoy patrols.

**Patrol picker `0x63B840(out, homeH)`**:
- source = **home town's** `+0x390` (`0x63B8C7`/`0x63B8CE`/`0x63B8D3` ternary);
- own-nation towns cost `distance/5`;
- for other towns: `IsAtWar(src, townNation)` (`0x63BA43`) → hostile `+0xC000000`, else
  `+0x8000000`;
- towns already targeted by the military of all four nations add `+0x96` or `+0x7D` (LOOP4
  `0x63BB92`).

**Target picker `0x63B3A0(out, P)`** (see `hostility_map.md` #15):
- `war[0..3]`, `war[4]=0`, `war[5] = (GetRepLevel(P)==0)`;
- among enemy towns it picks a random one with the fewest attackers already assigned. That count
  comes from a base walk over the enemies' lists `+8`;
- with no candidate it returns the last own town seen;
- for P ≥ 4 or a NULL nation it returns the **first town in the town list** (`0x63B7F3`).

A type-4 sortie has no siege of its own. The arrival code for type 4 (`0x5B4E35`, table `0x5B50CC`)
only clears `+0x1B0` and decides again. [H: a sortie is a presence or blockade that fights whatever
the scanner finds.]

### 2.3 Attack mask builder `0x63C280(this, P)` [S]

Block guard: `0x63C28C cmp esi,4` / `0x63C29C mov eax,[esi*4+0x702b14]` / `test eax,eax`. When
the guard fails: **`0x63C3EA mov word [edi+0x48],0`**.

1. `mask = 0x10` (pirates).
2. If there is a local player and `GetReputationLevel(P) == 0`, or level 1 and `rand%5 == 1`, then
   `mask = 0x20`. Note `mov`, not `or`: the pirate bit is dropped (`0x63C32E`).
3. For j = 0..3 with `IsAtWar(g[P], j)` (`0x63C345`):
   - inner ternary `0x63C34E cmp esi,4` / `0x63C353`;
   - compare `count(+8)*10` against `towns(+0x14 via 0x5BB3F0)*12`;
   - if more: `mask |= 0x81<<j`; else `mask |= 1<<j`.
4. If overall `count*10 > towns*12`: `mask |= (mask&0xF)<<7`.

Bits in the mask: 0..3 = power j; 4 = pirates; 5 = nation-5 or player ships; 6 (`0x40`) = attack
towns (set by `0x63C400` for missions); 7..10 = "strong vs power j".

### 2.4 At-sea AI, encounters and raiding [S]

`0x5B3BD0`, type 4 (`0x5B3DD5`):
- about every 256 ticks it rebuilds the mask (`0x5B3E07`/`0x5B3E13`);
- pursues `+0x168` through `0x5AED30`. At distance ≤ 0x40 that starts a battle
  (`0x5FEF80`, AI vs AI auto);
- when it has a route, it scans neighbours: `0x5B1D10` → `0x5AF330(this, other)` for every convoy
  inside radius `[0x6AC1C4]`;
- with no route it decides again (`0x5B1DF0`).

**`0x5AF330` for this = type 4** (switch on the other's type, table `0x5AF81C`):

| Other type | Handler | Condition to attack |
|---|---|---|
| 1 player | `0x5AF49F` | `GetReputationLevel(this nation)==0` for the local player (`0x5AF4DE`), plus a crew advantage |
| 2 AI trader | `0x5AF5FB` | **`this+0x1C != 0`** and mask bit `1<<trader.+0xB8` (`0x5AF606..0x5AF619`). **This is the raiding path.** [H: `+0x1C` is a per-object "hunter" flag] |
| 3, 7 pirate | `0x5AF566` | **always**, subject to strength and protection timers |
| 4 military | `0x5AF63C` | `this.+0x7C & 0x80000` and `0x5AD230(n, this+0x1C)`, i.e. mask bit `(0x80+flag)<<n`: bit n+7 (strong), plus bit n when the flag is set |
| 5, 6 | `0x5AF480` | **never** |
| 8, 9 | | not handled (the scan table covers types 1..7; type 8 is also skipped by the event scanner `0x5B6A50` unless `+0x7C&0x20`) |

A type-9 convoy (on a mission) does not scan for encounters: `0x5AF463` handles only this-types
3, 4 and 7.

A second scanner, `0x5B6A50` (only caller: the convoy event Execute `0x5F1DB0`, vtable `0x6AAE70`;
[H] Lua or mission driven), tests `1<<target.+0xB8` (`0x5B6AC2`). It has an explicit branch for
`target.+0xB8 == 5 && this.type == 4` (`0x5B6B79`) that uses the player's reputation and rank.

So, yes: the military **does raid trade convoys** (AI traders of an enemy nation, under the `+0x1C`
flag). It always hunts pirates, fights enemy warships only when strong, and ignores transports and
treasure fleets.

### 2.5 War missions (type 9): assign, validate, act [S]

**`AssignWarMission 0x5B4870(target, count)`** (thiscall, `ret 8`):
- requires `type == 4` (`0x5B487C`);
- **`target < 4`** (`0x5B4892 cmp bl,4`);
- `target != own` (`0x5B489B`);
- **local player rank > 1** (`0x5B48BD call 0x5a8da0` / `cmp al,1`);
- `state != 9`.

It then calls `SetType(9, own)` (`0x5B48E8`) and sets `+0x172 = target`, `+0x170 = count`,
`+0x171 = 0`. Without flag `0x10000` it posts a message (`0x5D89D0` on `0x702CB8`). It re-homes if
needed and, if at sea, calls `0x5B3880` (sail to the target nation).

**The only vanilla caller is the war-start handler `0x5F5360(a,b)`** (from `CEventPeace::Execute`):
- `IsAtWar(g[a], b)`;
- a local player with rank > 1;
- at least 0x3800 ticks since the last mission;
- it weights the sides by the player's assets in their towns (`0x5ABBB0`) times reputation;
- it picks the strongest idle convoy of `g[a]` or `g[b]` (list `+8`, `0x5F557F mov edi,[eax+8]`;
  a convoy with flag `0x10000` is taken first);
- then `0x5B4870(target, rand%(rank/2)+1)`.

**Validity `0x5AD8F0`**: type 9, `+0x170 > 0`, ships > 1, `IsAtWar(g[own], +0x172)`
(`0x5AD91D`/`0x5AD922` ternary, `0x5AD937`). If it fails, the mission is aborted by **`0x5B0730`**
(→ `SetType(4, own)`, mission fields cleared).

**Arrival, type 9** (`0x5B4D6F`):
- validate, else abort;
- **`SelectAction 0x5B07A0`**: needs a local player (else throw `0x5B0A09`). It calls
  **`0x63C400`** (siege flag `0x40` when at war with the town owner, `town+0x58 > 3` and
  size/strength hold; ternary `0x63C463`/`0x63C468` then `test ecx,ecx`). It builds the list of
  allowed actions 1..11 from rank and town flags and picks one at random;
- **action 1 → AI siege `0x603030`** (`0x5B4DF4`). The siege resolves to `AttackerWon 0x602500`,
  which plunders only and is war.c hook #7;
- actions 2..11 run in harbour: `0x5B53C0` → **`0x5B5110`**. That function checks
  `town+0x390 == +0x172 && IsAtWar(g[own], +0x172)` (`0x5B5182`/`0x5B5195`), switches on `+0x171`
  (table `0x5B5398`; town-damage helpers `0x5C4C50`, `0x5C4CF0`, `0x5C5E00`, `0x5C6060`,
  `0x6253F0`, …) and finally writes **`CNation::SetLastBuccActionDate 0x5BA400(g[own], target,
  now)`** (`0x5B531E`/`0x5B5323` ternary, `0x5B5340`).

### 2.6 Harbour AI for type 4 (`0x5B53C0` → `0x5B578A`; sub-state `+0x19C`) [S]

| Sub-state | Action |
|---|---|
| 0 | repair, `0x5ADF90` |
| 1 | buy ammunition (`0x638690` ×20) and crew (`0x639DF0(5,n)`), `0x5AD780` |
| 2 | in an **administrative town** (`+0x44 & 0x2001`: governor or viceroy seat, e.g. Margarita): **re-arm `0x634160`** (needs town nation == convoy nation, `0x634239`). Otherwise `0x633FF0` (returns 1 for nation ≥ 4, `0x63407A`), else set flag `0x2000000` |
| ≥3 | leave, `0x5B1DF0` |

**`0x634160` reads the ship-type tables by the convoy's nation**:
- flagship `0x6344A1 movzx eax,[edi+0xb8]` / `0x6344AA mov cl,[eax+0x6ac4b4]`;
- escorts `0x6343F5` / `0x634411 movzx eax,[edx+eax*4+0x6ac4ac]`.

## 3. Every nation read in the military paths, for `+0xB8 = 5`

Tables [S]:
- `0x6AC4AC` = `08 07 08 08 | 0A 09 07 0B` (escort `[r*4+n]`);
- `0x6AC4B4` = `0F 0D 0C 0E`, then `00 F0`. Index 5 = **0xF0**, an invalid ship type: types are
  0..17 (`0x559064`).

"Today" means vanilla plus P01..P07. In P01, `IsAtWar(NULL, j<4)` = `player_rel[j]`,
`(NULL, 4)` = war, `(NULL, 5)` = peace.

| # | Site | Function / what | Index source | n = 5 today | Class | With A1 (`nations6[5] = &pc`) |
|---|---|---|---|---|---|---|
| 1 | `0x63707A`/`0x63708A` | `SetType` 4/9: list insert | arg (convoy) | `+0x6C := 4` (`0x637137`): the convoy **becomes a pirate-nation warship**. Every power's mask has bit 4, so all would hunt it, and its own mask is 0 | **wrong, severe** | opt in: keeps 5, inserted in `pc+8` |
| 2 | `0x636720`/`0x636725` | `ClearOwner` 4/9: list remove | `+0x6C` | skipped | fine | opt in, **mandatory with #1**: `SetType` re-adds on every 4↔9 change and destroy must remove |
| 3 | `0x63C7A0`/`0x63C7A8` | home picker `0x63C780` | arg (`+0xB8`) | `ebx=0` → `0x640120(8)` → `0x64012C mov ecx,[ecx]` reads address 8: **AV** (also for n=4). Reached from every build (`0x6346F0`→`0x634757`/`0x63CA20`), `0x5B1FAD`, `0x5B497B`, Lua | **crash** | opt in (ternary): walks `pc+8` and picks a nation-5 town |
| 4 | `0x63C28C`/`0x63C29C` | mask builder block | arg | mask = 0: hunts nothing, not even pirates | skipped | opt in: `0x10` + war bits from `pc.rel[]` |
| 5 | `0x63C34E`/`0x63C353` | mask inner ternary | arg | unreachable today. **Crash** (`0x5BBB00(NULL)`) if #4 is opted in and #5 is not | — | opt in **with #4** |
| 6 | `0x5B1FF7`/`0x5B2000` | sortie gate (`0x5BBE30`) | `+0xB8` | skipped → patrols only | skipped | optional opt-in (sorties) |
| 7 | `0x63B3C8`/`0x63B3D7` | target picker | arg | returns the first town in the list | wrong but harmless | optional opt-in (with #6) |
| 8 | `0x63B8CE`/`0x63B8D3` | patrol picker source | **home town** `+0x390` | NULL → P01 → `player_rel`; own towns cost /5 | fine | optional |
| 9 | `0x5AD91D`/`0x5AD922` | mission validity | `+0xB8` | NULL → P01 → correct | fine | optional |
| 10 | `0x5B5182`/`0x5B5187` | mission at town | `+0xB8` | same as #9 | fine | optional |
| 11 | `0x5B531E`/`0x5B5323` → `0x5BA400` | buccaneer action date | `+0xB8` | `0x5BA40F mov [ecx+eax*4+0x158],edx` with ecx=0: **write AV**, type 9 only | **crash** | opt in (ternary) if war missions are used |
| 12 | `0x63C463`/`0x63C468` | siege flag `0x63C400` | arg (`+0xB8`) | NULL test → flag cleared, no siege | skipped | optional opt-in (sieges) |
| 13 | `0x6350DC`/`0x6350E6` + `0x63511A` | builder `0x6350D0` | arg | rejected, returns 0 | skipped | opt in only after relocating `0x6AC4B4` (§4.1) |
| 14 | `0x6352B7`→`0x6352BE` | leader type (U1) | **town** `+0x358` | type 0xF0 | **crash or garbage** [H] | table fix |
| 15 | `0x634902`→`0x634942` | escort flagship (U2) | town `+0x358` (else arg) | type 0xF0 | **crash or garbage** [H] | table fix |
| 16 | `0x634A4D` | escort type | same | `0x6AC4B1`=09 / `0x6AC4B5`=0D, valid by luck | fine | — |
| 17 | `0x6344A1`→`0x6344AA` | re-arm flagship in admin town | **convoy** `+0xB8` | type 0xF0, whenever docked in a nation-5 governor or viceroy town with ≤5 ships | **crash or garbage** [H] | table fix |
| 18 | `0x6343F5`→`0x634411` | re-arm escorts | convoy | 09/0D, valid by luck | fine | — |
| 19 | `0x63407A` | `0x633FF0` fleet check | convoy | `cmp …,4; jae` → returns 1 | fine | — |
| 20 | `0x5B4892` | `AssignWarMission` | target | own = 5 is allowed. It then calls `SetType(9,5)`, which runs into #1 | wrong (via #1) | fine with #1 |
| 21 | `0x5F5360` | war-start mission picker | pair a/b < 4 | never picks a nation-5 convoy | skipped | DLL must call `0x5B4870` itself |
| 22 | `0x5BBB20`/`0x5F3641`/`0x5F3D30`/`0x5F1A24`/`0x5F1B38` | build and replenish events | n | guarded, never run for 5 | skipped | DLL replenishes (or optional opt-ins) |
| 23 | `0x5AF4AF`→`0x5AF4DE` | this=5 vs a player convoy | `GetRepLevel(5)` | P04 passes ≥4 to vanilla = 100 → level 3: **never attacks the player's own convoys** | fine | same |
| 24 | `0x5AF606`, `0x5AF650`→`0x5AD230`, `0x5AF69A`, `0x5B6AC2`, `0x5B6C9F` | mask tests on a target's `+0xB8` | target | `1<<5` and `(0x80+f)<<5` stay inside the word | fine | — |
| 25 | `0x5B6B79`/`0x5B6D56` | scanner "target is nation 5" branch | target | nation-5 warships are treated like player ships | fine (by design) | — |
| 26 | `0x637323` | `EnterTown` dock or anchor | `+0x6C` | docks at its own towns | fine | — |
| 27 | `0x5D736C` | captain name | ≥4 → town nation → `0x5D8E70`, which admits 5 (`nation5_index_safety` A6) | | fine | — |
| 28 | `0x63DED3` | ship sprite variant | 5 → variant 0 | | cosmetic | — |
| 29 | `0x4FAA8C`, `0x50C798`, `0x485C4C` | UI flag | 5 → `"-userflag-"`: shows the nation's flag | | fine | — |
| 30 | `0x5FC0DC` | battle setup | ≥4 → 0 | | fine [H] | — |
| 31 | `0x609D10`→`0x5BA4C0(5)` | re-arm replenish after a battle | no type-5 event for 5 → no-op | | fine | — |
| 32 | `0x41BE4F`→`0x41BE75` | governor dialog `IsAtWar(gov, 5)` | | P01 | fine | — |

**Not reachable for military convoys** [S, by callers]:
- `0x5B411B` (`0x5B40D0`, only caller `0x5B5906` = type-5 harbour branch);
- `0x5B501B` (type 5);
- `0x5B77DE` (AI trader route, `GetRelation(…, ≥4)` = 0xFF);
- `0x63BF9C` (treasure).

A sweep of every `+0xB8` read in `.text` that feeds a table, `g_nations`, `GetNation` or a
reputation call found no further site: 17 hits, all listed above or not military.

## 4. Feasibility

### 4.1 A1: vanilla code plus a real `CNation` for index 5 (recommended, as "A1-lite")

**Object.** A static 0x170-byte `pc`, built with `ctor 0x5BBC70(&pc, 5)` (thiscall, `ret 4`).
`nations6[0..3]` mirrors `0x702B14`, `[4] = 0`, `[5] = &pc`. Keep it exact with the writer hooks
H1 (`0x5D12EB`), H2 (`0x5D14F5`) and H3 (`0x5D23C3`) from `player_cnation_design.md` §6.

A per-frame DLL refresh is **not** enough. An opted-in site serves powers 0..3 too, so a stale
mirror right after `World::Load` would hand out freed pointers.

Keep `pc.rel[0..3] = player_rel[0..3]`. Either alias them (design §5) or have the DLL copy them on
every war or peace change.

Also make the P01 `jae war` retarget from design §5 (`IsAtWar(pc, 5)` would otherwise be "war").
No military site found here passes other=5 with a non-NULL self, but the retarget belongs with any
use of `pc`.

**Opt-ins.** Each is `cmp r,4` → `cmp r,6` plus disp32 `0x702B14` → `nations6`, same length:

| Need | Site (guard / load disp32) | Why |
|---|---|---|
| **required** | `0x63707A` (imm at `0x63707C`) / `0x63708D` | keep nation 5, register in `pc+8` |
| **required** | `0x636720` (`0x636722`) / `0x636728` | symmetric removal |
| **required** | `0x63C7A0` (`0x63C7A2`) / `0x63C7AB` | home picker: crash otherwise |
| **required** | `0x63C28C` (`0x63C28E`) / `0x63C29F` | mask (hunt pirates and enemies) |
| **required** | `0x63C34E` (`0x63C350`) / `0x63C356` | mask inner: crash if only the block is enabled |
| sorties | `0x5B1FF7` / `0x5B2003`; `0x63B3C8` / `0x63B3DA` | attack trips to enemy towns. `0x5BBE30(pc)` is true once `pc+8` is non-empty and `pc+0x14` is empty |
| war missions | `0x5B531E` / `0x5B5326`; `0x63C463` / `0x63C46B` | action date (crash #11), siege flag. Plus a DLL call to `0x5B4870(target, n)`: vanilla never assigns one. It also needs player rank > 1 |
| optional | `0x5AD91D`/`0x5AD925`, `0x5B5182`/`0x5B518A`, `0x63B8CE`/`0x63B8D6` | already correct through P01 |
| vanilla replenish (optional) | guards `0x5F3641`, `0x5F3D30` (loads `0x5F3D35`, `0x5F3D56`), `0x5F3C3B`/`0x5F3C42`, `0x5F1A24`/`0x5F1A2A`, `0x5F1B38`/`0x5F1B3D`, builder `0x6350DC`/`0x6350E9` | and the DLL would have to create the type-5 event (`0x5F3630(5)`). Simpler: the DLL replenishes |

**Tables.**
- Relocate the flagship `byte[4]` `0x6AC4B4` to a new `mil_flag6[6] = 0F 0D 0C 0E 00 xx`
  (xx = the nation's flagship type). This fixes #13/#14/#15/#17 in one go, at the disp32s
  `0x6352C0`, `0x634944`, `0x63511C`, `0x6344AC` and (optionally, guarded) `0x63356F`.
- The escort table `0x6AC4AC` has stride 4 (`[r*4+n]`), so it cannot get a sixth column in place.
  Index 5 is valid by luck (0x09/0x0D), so leave it.
- No other per-nation table is indexed by a convoy's nation in these paths.
- `rel[4]` and `+0x158[4]` are indexed by the **other** (target) nation, which is < 4.

**Persistence.** The convoys keep 5 through save and load (`0x635B00`). The `pc+8` list needs one
of these:
- the `pc` blob (design H4/H3). Note the DLL already uses the magic `'PNAT'` for its own blob
  (`dll/persist.c`), so pick a different tag or nest it;
- **or, cheaper:** after load, the DLL rebuilds the list. Walk the convoy pool `0x701EE8` for
  `+0xB4 ∈ {4,9}` and `+0xB8 == 5`, then call `0x636DD0(&pc+8, h)`.

**Estimated cost.** 3 lifecycle hooks, 5 required opt-ins (25 bytes), one table relocation
(4–5 disp32s), the P01 one-byte retarget, and DLL code for spawn, replenish, rel-sync and
list-rebuild. Sorties add 2 opt-ins; war missions add 2 opt-ins plus a DLL mission caller.

### 4.2 A2: cheaper tricks

- **A2-proxy (`+0xB8` = the host power d).** Zero patches, but the fleet *is* power d's:
  - it sits in `g[d]+8`;
  - its mask and targets follow d's wars;
  - it is attacked by d's enemies;
  - it inflates d's count, so d builds fewer of its own.
  
  Friend and foe would be wrong for the nation. Usable only as a visual test.
- **A2-display (P03-style display-byte substitution).** It helps only the **town**-indexed reads:
  U1 `0x6352BA` and U2 `0x634904` (`0x58`→`0x59`, one byte each). It cannot fix the
  convoy-indexed sites #1, #3, #4 and #17, because a convoy has no display byte.
- **A2-nolist (nation 5 without a `CNation`).** It needs:
  - a stub in `SetType` that keeps 5 and skips the list;
  - a mask stub on `0x63C280`'s ≥4 path: `mask = 0x10 | Σ player_rel[j] ? 0x81<<j : 0`;
  - the table fix;
  - and a home picker for P=5, which needs a list at `[x+8]`, i.e. a `CNation`-shaped object.
  
  At that point it is A1-lite with hand-written stubs instead of 5-byte opt-ins. **Not cheaper.**

### 4.3 Friend and foe toward nation-5 and type-1 targets [S unless marked]

**A nation-5 military convoy:**
- **never attacks the player's own convoys** (type 1, `+0xB8 = 5`):
  - the encounter path needs `GetRepLevel(5)==0` (#23), and P04 keeps P≥4 at 100;
  - mask bit 5 is never set for P=5, since `GetRepLevel(5)` = 3 at `0x63C302`, so `0x5B6A50` does
    not target them either;
- does not attack other nation-5 warships (bit 5/12 not set);
- attacks pirates (bit 4);
- attacks powers at war with the nation (`IsAtWar(pc, j)` = `pc.rel[j]` = `player_rel[j]`):
  enemy warships (bit j+7, "strong", which is always true while `pc+0x14` is empty and the fleet is
  non-empty) and, under `+0x1C`, enemy AI traders;
- never besieges its own towns: `war[5] = 0` and own towns are only the fallback.

**The powers:**
- they target `+0xB8 == 5` ships through mask bit 5. That bit is set only when the human player's
  reputation with them is hostile. P04 forces that while `player_rel[P] == 1`;
- so **the nation's warships inherit the player's reputation hostility**: a power that hates the
  player at peace also attacks nation-5 warships [H: acceptable, matches the "nation = player"
  model];
- power-vs-nation-5-warship engagements in `0x5AF63C` need `this.+0x1C` (bit n only with the
  flag), so they are rarer than power vs player;
- the event scanner `0x5B6A50` handles them like player ships (rep < 2, `0x5B6BD2`).

**Still to do outside this scope:**
- the player may try to attack the nation's own warships through the UI [H]. Consider a war.c-style
  refusal;
- a power's siege of nation-5 towns still needs `war[display]` (`hostility_map.md` §4).

## 5. Recommended spike: one nation-5 military convoy that patrols

**Goal.** Spawn one fleet at a nation-5 town and have vanilla dock, re-arm, patrol and fight
pirates with it, with no crash. No sorties and no missions.

### Exe patches

1. **`nations6` + `pc`** in `.nation`: `pc` 0x170 bytes (align 4), `nations6` 0x18 bytes. Mirror
   hooks H1 `0x5D12EB`, H2 `0x5D14F5`, H3 `0x5D23C3`. H1 destructs and constructs `pc` with
   `0x5BBDB0`/`0x5BBC70(5)` and clears the mirror; H2/H3 copy `[0x702B14+4i]`, i=0..3. The bytes
   are in the design doc. They can be DLL `hook_install` hooks instead of exe stubs.
2. **5 opt-ins**: `0x63707C` `04`→`06` + `0x63708D`; `0x636722` + `0x636728`; `0x63C7A2` +
   `0x63C7AB`; `0x63C28E` + `0x63C29F`; `0x63C350` + `0x63C356`. Each disp becomes `nations6`.
   Check the old bytes as listed in §4.1 (`83 F8 04` / `83 FE 04` and `… 14 2B 70 00`).
3. **`mil_flag6`** = `0F 0D 0C 0E 00 0F`. Repoint the disp32 at `0x6352C0`, `0x634944`,
   `0x63511C` and `0x6344AC` (old bytes `B4 C4 6A 00`).
4. **P01**: the `jae war` → `notpower` retarget (design §5).

### DLL

1. At game start or load (after H3), sync `pc.rel[j] = player_rel[j]`. Keep it in sync whenever
   `Nation_DeclareWar` or peace changes it. Rebuild `pc+8` from the convoy pool (§4.1).
2. **Spawn**: run Lua `Global_CreateMilitaryConvoy(d, Nation_TownHandle(T))` through the existing
   Lua bridge, with T = a nation-5 town and d = any 0..3 (it passes `0x426848` and is ignored).
   That reaches `0x635270(townH)`:
   - nation 5 from the town;
   - flagship from `mil_flag6[5]`;
   - docked (state 2);
   - `pc+8` registration;
   - home picked among the nation-5 towns.
   
   Prefer the Lua path over calling `0x635270` directly: on failure it throws C++ exceptions
   (`0x64DC32`, "bad city handle" or "failed to create leader ship"), and the script dispatcher is
   the natural catcher [H].
3. **Check after spawning**:
   - convoy `+0xB4 == 4`, `+0xB8 == 5`;
   - `0x5BBB00(&pc) == 1`;
   - `+0x44` = a nation-5 town;
   - `+0x90 == 2`.
   
   Over a few game days, expect `+0x19C` to step 0→1→2→3, `+0x48 & 0x10` set, `+0x1B0` changing
   between nation-5 towns, and `+0x90` cycling 2→0→4/2.
4. **Replenish (later)**: when a fleet is lost (`0x5BBB00(&pc)` drops), spawn again. Cap it at
   `nation towns (+3 at war)` to match vanilla `0x5BBAB0`.

### Spike tests

- Spawn at an ordinary nation-5 town **and** at Margarita (governor: exercises `0x634160`).
- Declare war on one power: its warships near the fleet should be engaged, and the player's own
  convoys never.
- Save and reload: the convoy keeps 5 and the list is rebuilt.

### Not in the spike

Sorties (`0x5B1FF7` + `0x63B3C8`), war missions and sieges (`0x5B531E` + `0x63C463` + a DLL caller
of `0x5B4870`), vanilla replenishment events, conquest attribution of AI-won sieges (war.c hook #7
returns early for nation-5 attackers today), and the UI refusal of player attacks on the nation's
warships.

## Confidence

- **The site census and classifications: high.** Every VA was disassembled; the closure scan
  covered the tick, scanner and builder graphs to depth 4.
- **Exact ship-type validity: medium [H].** `0xF0` is outside 0..17, but the exact failure (crash
  or garbage) was not observed.
- **The `+0x1C` meaning: [H].**
- **That nothing in the battle code reads the attacker's nation beyond `0x5FC0DC`: medium**
  (range scan `0x5FC000..0x60A000`).
