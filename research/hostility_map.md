# Hostility map: powers vs. player (nation 5)

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000).
Method: capstone linear sweep of `.text` (859k instructions), E8/E9 xref scan,
immediate/pointer xrefs, and manual disassembly of every site listed here.
The game was not launched.

Labels: **[S]** = VERIFIED-STATIC (the bytes/instructions were read at the
given VA). **[H]** = HYPOTHESIS (an inference about purpose or runtime values).

---

## 0. The one-paragraph answer

The game has **two separate hostility systems**:

1. **Power vs. power** = the `CNation` relation byte `rel[other]` (offset +0..+3),
   read by `CNation::IsAtWar` 0x5BA0A0 (18 callers). For `other >= 4` (pirates 4,
   player 5) IsAtWar **always returns TRUE**.
2. **Power vs. player** = the **player's reputation** with each power. It is a
   16.16 fixed-point int at `CPlayer+0x54+4*P`, clamped to 0..100. **"Hostile to
   the player" means reputation level 0, i.e. rep < 25.** Nothing stores a separate
   "hostile" flag (apart from cached UI bits). Three getters read it:
   `GetReputation` 0x5D2AC0, `GetReputationLevel` 0x5D2C10 (= min(rep/25, 3),
   55 call sites), and `IsRepAtLeast25` 0x5D2D90 (13 call sites).
   The `ID_MSG_NATION_HOSTILE_START/END` messages, the 03/04 "Spieler (nicht)
   feindlich" videos, letter-of-marque expiry and the per-town hostile flag 0x8000
   are side effects of crossing that threshold.

Military AI already models "nation 5 = the player". Each military convoy has an
attack mask at `+0x48`, with bit *n* meaning "attack ships whose `+0xB8` nation is
*n*". Bit 4 (pirates) is always set. Bit 5 (player) is set from
`GetReputationLevel(P)==0`. The siege target picker gives nation-5 towns
`war[5] = (GetReputationLevel(P)==0)`. So **the player-hostility table can be
driven from two detours: GetReputation (0x5D2AC0) and IsRepAtLeast25 (0x5D2D90).
A third detour on IsAtWar's ≥4 branch (0x5BA0BA) covers the few paths that ask
"is P at war with nation 5" directly.**

---

## 1. All direct callers of `CNation::IsAtWar` (0x5BA0A0)

[S] Bytes:
```
5BA0A0 8A442404   mov al,[esp+4]
5BA0A4 3C04       cmp al,4
5BA0A6 7312       jae 5BA0BA
5BA0A8 0FB6C0     movzx eax,al
5BA0AB 8A0408     mov al,[eax+ecx]        ; rel[other]  (deref of `this`)
5BA0AE 247F       and al,7Fh
5BA0B0 FEC8 / F6D8 / 1BC0 / 40   ; eax = (rel==1)
5BA0B7 C20400     ret 4
5BA0BA B001       mov al,1                ; other>=4 → TRUE, `this` NOT touched
5BA0BC C20400     ret 4
5BA0BF CC         int3
```
[S] 18 E8 calls, 0 E9 jumps, 0 pointer references (it is not virtual).
[S] `GetNation(idx)` 0x417DC0 (ecx=0x702140): `[0x702140+0x9D4+idx*4]` is the
same array as `g_nations` (0x702B14). It **returns NULL for idx>=4**. Every
caller uses the same guard pattern (`cmp x,4; jae → ecx=0`), so a ≥4 *self*
becomes `ecx=NULL`. That is harmless only while `other>=4`.

| # | Call VA | Containing fn | Decides | `this` (self) | `other` | Can pass 4/5? |
|---|---|---|---|---|---|---|
| 1 | 0x41BE75 | 0x41B5E0 `CGovernor::ProcessAnswer` (vtbl 0x682C50 slot 21; string "DLG_STATE_LOM_OFFER in CGovernor::ProcessAnswer") | Governor dialog branch (only if player rank `0x5A8DA0 > 4`): if the governor's nation is at war with the dialog convoy's nation, the convoy gets a flag (`[conv+0x7C] \|= 0x20000`) and the dialog advances; else dialog state 0xC [H: governor-offered military task] | `GetNation([[npc+0x10]+0x12])` (governor nation; NULL if ≥4) | `convoy[+0xB8]` of the convoy whose handle is at `dlg+0x30` (lookup via 0x701EE8/0x41F620) | **YES, 4 or 5** if that convoy is pirate- or player-owned [H] |
| 2 | 0x41D479 | 0x41D3F0 Lua `Global_IsWar` | Script query | `g_nations[a]` | b | No: both are validated `<4`, else "LUAGlobal_IsWar - invalid nation number(s)" [S] |
| 3 | 0x448161 | 0x447ED0 `CViceroyNPC::ProcessAnswer` (vtbl 0x688A58 slot 21) | Viceroy dialog: loop over nations at war with the viceroy's nation, then `0x5D2F70` per nation [H: letter-of-marque offer list] | viceroy nation (`0x43EDF0`) | loop byte 0..3 | No |
| 4 | 0x4482FA | 0x447ED0 | Viceroy dialog: chosen nation must be an enemy, else dialog state 0xC | viceroy nation | dialog byte `[[npc+0x14]+0x19]` | [H] 0..3 (dialog-selected nation) |
| 5 | 0x44863F | 0x447ED0 | Viceroy dialog: "is the viceroy at war with anyone" (loop, early exit) | viceroy nation via GetNation | loop 0..3 | No |
| 6 | 0x448811 | 0x447ED0 | Viceroy dialog: builds the list of enemy nations (`0x42EA50` push) | viceroy nation | loop 0..3 | No |
| 7 | 0x4B1A51 | 0x4B16B0 nations/relations UI page (vtbl 0x691198; strings `CHN_NationsCapIcn_%02d`, `IDPR_SCHLACHT_DLG_KAPERBRIEF`) | UI: list the nations this power is at war with | page's CNation (ebp) | loop 0..3 (skips self) | No |
| 8 | 0x5AD937 | 0x5AD8F0 (called by convoy update 0x5B4D71) | **Military convoy: is the current attack mission still valid?** (`state[+0xB4]==9`, `[+0x170]>0`, `[+0x95]>1`, owner at war with target). If not, `0x5B0730` aborts the mission | `g_nations[conv+0xB8]` (NULL if ≥4) | `conv[+0x172]` (mission target nation) | Vanilla: no. `+0x172` is written only by `AssignWarMission` 0x5B4870, which rejects ≥4 (`cmp bl,4; jae` @0x5B4892) [S] |
| 9 | 0x5B5195 | fn @0x5B5110 (SEH prologue; called from 0x5B56E3) | **Military convoy arriving at a town**: if `town+0x390 == conv+0x172` and the owner is at war with it → `switch(conv+0x171)` (mission action: attack/blockade) [H on action names] | `g_nations[conv+0xB8]` | `conv+0x172` | Vanilla: no (same as #8) |
| 10, 11 | 0x5D10A4, 0x5D10C2 | 0x5D0FA0 `World::SetRelation(a,b,state)` | After a relation change: if a (or b) is now at war with nobody → `[nation+0x16C]=0` | `g_nations[a]`, `g_nations[b]` | loop 0..3 | No (a,b validated <4) |
| 12 | 0x5D3419 | 0x5D33B0 player creation / initial reputation (callers 0x5A8488, 0x5A8740) | Initial rep with each power: home nation → table `0x6A5194[diff]`, at war with home → `0x6A519A[diff]`, otherwise `0x6A5197[diff]` (bytes: home 100/100/100, other 100/74/50, enemy 100/50/50) | `g_nations[homeArg]`; **NULL if home ≥4** | loop 0..3 | other <4. **If home nation ≥4, IsAtWar(NULL,0..3) crashes at 0x5BA0AB** [S], and 0x5D34F4 writes rep[home] out of bounds |
| 13 | 0x5D4578 | 0x5D44C0 letter-of-marque expiry (`CPlayer+0x14+i` bitmask) | If issuer i is no longer at war with j, or rep(i) < 25 (0x5D4503 `cmp eax,0x19`), clear the LoM bit and post `ID_MSG_LOM_EXPIRED` (0x33) | `g_nations[i]` | j = 0..3 | No |
| 14 | 0x5F5395 | 0x5F5360 war-start handler (called from `CEventPeace::Execute` 0x5F577B) | On a new war a↔b: choose a side (weighted by the player's rep with each) and give its biggest idle military convoy a war mission via `0x5B4870` | `g_nations[a]` | b | No |
| 15 | 0x63B407 | 0x63B3A0 (cdecl, `out*`, nation P; callers 0x5B2028, 0x63C9DF) | **Military target-town picker**: `war[0..3]=IsAtWar(P,j)`, `war[4]=0`, `war[5]=(GetRepLevel(P)==0)` (0x63B46F). A nation-5 town needs `war[5]` **and** `war[display nation +0x359]` [S] | `g_nations[P]` | loop 0..3 | No (5 is handled through the rep path) |
| 16 | 0x63BA43 | 0x63B840 (caller 0x5B20A4) | Route/threat cost per town: own town → dist/5; hostile → `+0xC000000`; other → `+0x8000000` [H: patrol/route weighting] | `g_nations[sourceTown+0x390]` (**NULL if the source town is ≥4**) | `town+0x390` of every town | **YES: 4, 5, 0xFF** (all → TRUE). NULL self plus other<4 would crash |
| 17 | 0x63C345 | 0x63C280 military convoy attack-mask builder (callers 0x5B1E18, 0x5B3E07/13, 0x5B60CA, 0x633B4C) | Mask bit j (or `0x81<<j` if stronger) for each power at war | `g_nations[P]` | loop 0..3 | No |
| 18 | 0x63C48A | 0x63C400 (caller 0x5B0896) | **Sets `mask |= 0x40` (siege/attack-town flag)** if P is at war with the town's owner, the town has `+0x58>3`, and size conditions hold | `g_nations[P]` (NULL-checked) | `town+0x390` | **YES: a nation-5 or nation-4 town always counts as "at war"** |

### Inlined copies of IsAtWar (bypass the function) [S]
Pattern `mov r8,[idx+nation]; and r8,7Fh; dec; neg; sbb; inc`:
- 0x5BA1CB in 0x5BA130 (CNation slot exchange at +0x144, caller 0x447AC5): loop 0..3
- 0x5BA2C9 in 0x5BA260 (viceroy, caller 0x44832F): arg checked `<4` first
- 0x5BBABD in 0x5BBAB0 (`IsAtWarWithAnyone`; callers 0x5BBB39, 0x5BBBB1, 0x5F3C60): loop 0..3
- 0x5BC005 in 0x5BBF50 `CNation::SelectNationForAnnexation`: loop 0..3

`GetRelation` 0x5BA080 (`rel&7Fh`, 0xFF for ≥4) has 7 callers: 0x41C11C,
0x5B77EF, 0x5D0FDE, 0x5DDDA1, 0x5F5296, 0x5F5727, 0x5F579B. All of them use
power pairs. **None of the inlined copies or GetRelation callers involves
index 5.** The only writer of relation bytes is `SetRelation` (0x5D0FF3 /
0x5D0FFD, symmetric) [S].

---

## 2. Hostility checks that bypass IsAtWar: the per-power "hostile to player" state

### 2.1 Storage [S]
- The player array is at `0x701EC0`, stride 0x94 (handle table 0x701EC4, count
  0x701EC8). The local player handle comes from `0x402940`, resolved via
  `0x5C2B10`/`0x5C29E0` or `0x701EBC→0x402C60`. `+0x25` is the "alive/valid" byte.
  `word +0x00 == 0` is the human player [H]: non-zero makes IsRepAtLeast25 return
  TRUE and makes the rank read as 9.
- **`int32 rep[4]` at `CPlayer+0x54`**: 16.16 fixed point. `ClampRep` 0x5D2EB0
  clamps it to [0, 0x640000] (0..100).
- `CPlayer+0x14..0x17`: letter-of-marque bitmask per issuing power.
- `CPlayer+0x38` bit 0x40: "first hostility already shown". It is set together
  with event 0x3B(nation) at 0x5D4797 / 0x5D48E0 [H: this plays
  `videos/03_Spieler_feindlich.wmv`; video table 0x6E15F0 / 0x6E15F8].
- Cached per-town flag: **`CStadtLager(+0x38)` flags dword `+0xC`, bit 0x8000**.
  It is set (`0x624C20`) or cleared (`0x624C60`) on every town whose `+0x390 == P`
  when hostility starts or ends (0x5D47D8 / 0x5D4718 / 0x5D4928 / 0x5D49AC /
  0x5D3C2C / 0x5D3CDC). Both setter and clearer notify 0x703ADC. No direct reader
  of the bit was found [H: map/UI display only; see
  `imagesSD\Pr2_Seekarte_feindlich.aim`, table 0x6E368C].

### 2.2 Getters
| VA | Name (ours) | Semantics [S] | Callers |
|---|---|---|---|
| **0x5D2AC0** | `CPlayer::GetReputation(n)` | n<4 → `(int8)(rep[n]>>16)`. **n==5 → 100. n==4 (or other ≥4) → 0** | 9 direct, plus via 0x5D2C10 |
| **0x5D2C10** | `CPlayer::GetReputationLevel(n)` | `min(GetReputation(n)/25, 3)`. **Level 0 = HOSTILE** | 55 |
| **0x5D2D90** | `CPlayer::IsRepAtLeast25(n)` | `word[this]!=0 → 1`; `n>=4 → 1`; else `rep[n] >= 0x190000`. Reads rep **inline**, not via 0x5D2AC0 | 13 |
| 0x5D3B50 | `SetReputation(n,v)` | Inline level calc. Sets/clears town flag 0x8000 | — |
| 0x5D45F0 | `AddReputation(n,amt)` | Level before/after. 0→>0 posts `ID_MSG_NATION_HOSTILE_END` (msg 0xE, 0x5D46F3) and clears 0x8000 on P's towns | 7 |
| 0x5D4840 | `SubReputation(n,amt)` | >0→0 posts `ID_MSG_NATION_HOSTILE_START` (msg 0xD, 0x5D48D0), sets `+0x38\|=0x40`, event 0x3B, and sets 0x8000 on P's towns | 3 |
| 0x5D2FB0 | raw `AlterReputation(n, delta<<16)` (caller 0x41D0DA, Lua area) | No messages or flags | 1 |
| 0x5D4B40 | daily reputation update (caller 0x5D27E5) | Inline level calc at 0x5D4E05 | — |

Message ids are indices into the string table at 0x6E4440 [S]: 0xD
`ID_MSG_NATION_HOSTILE_START`, 0xE `..._END`, 0x11 `ID_MSG_WAR_BEGIN`, 0x12
`ID_MSG_WAR_END`, 0x33 `ID_MSG_LOM_EXPIRED`. They are posted by
`0x5B82A0(id,-1,nation,-1)` with ecx=`*0x42F850()`.
Lua exposes `Player_GetReputation` / `Player_AlterReputation` (strings
0x6869D4 / 0x686A0C) [S]. **A script can already make a power hostile by
pushing rep below 25** [H: the AlterReputation path may be the raw 0x5D2FB0
with no messages].

### 2.3 Consumers of "power P hostile to the player" (level==0 / rep<25)
[S] unless noted. The argument is the **town's `+0x390`** or a **convoy's `+0xB8`**.

- **Military, attack player ships**: 0x63C302 in mask builder 0x63C280. Level 0,
  or level 1 with `rand%5==1`, gives `mask=0x20` (bit 5 = player). The bit is
  tested as `1 << target[+0xB8]` at 0x5AF606, 0x5AF69A, 0x5B6AC2, 0x5B6C9F
  (and `0x5AD230` uses `(0x80+x)<<n`). [S] 0x5B6B79 / 0x5B6D56 contain
  `cmp byte [conv+0xB8],5`, an explicit player-convoy branch: for patrol state 4
  it also needs raw rep(P) < 2, or else a distance condition.
  → **Player convoys carry `+0xB8 == 5`** [S that the game tests for it; H that
  every player convoy has it].
- **Military, besiege player towns**: 0x63B46F `war[5] = (level==0)` in the target
  picker 0x63B3A0 (see #15). Also IsAtWar(P, 5) at 0x63C48A (#18), which is
  *always* TRUE in vanilla.
- **Trade window**: 0x463779 level==0 → `IDPR_WFT_MSG_NO_BUY/NO_SELL`. 0x508AD2
  (`TMPL_HandelsScreen`) uses `IsRepAtLeast25`.
- **Harbor / convoy at town**: 0x636167 (fn 0x6360C0) and 0x636558 (fn 0x6364A0):
  level>0 is required [H: entering or docking].
- **Autotrade / prices**: IsRepAtLeast25 at 0x5AB51A, 0x5AB773, 0x5AB943, 0x5AC994,
  0x6372C1, 0x6381E9, 0x638939, 0x6397B9, 0x639A9F. Raw rep>25 at 0x611354.
- **Sea-map town icon**: 0x4DAEDF level==0 picks the hostile drawable [H].
- **Town citizen mood strings**: 0x515528 (`ID_STADT_BUERGER_ANSEHEN_0..3`), 0x5159E5.
- **Governor / Viceroy dialogs**: 0x419AA0, 0x41ACAE (table 0x6E0B90 is indexed by
  level, and level 0 = `ID_NPC_GOV_DIALOG_END_HOSTILE`), 0x41B91C..0x41BB89,
  0x445401 (level 0 → `ID_NPC_VICEROY_WELCOME_HOSTILE` via 0x6E0E2C), 0x44803D/75, ...
- **AI trader** (`CKonvoi::AI_SellAll` fn 0x5AF330): 0x5AF4DE.
- **Letters of marque expire** at rep<25: 0x5D4503.

Inconsistency [S]: for pirates (4), `GetReputation` gives 0 (hostile) but
`IsRepAtLeast25` gives TRUE. For the player (5), both say friendly.

### 2.4 Other explicit 4/5 nation tests found [S]
`cmp byte [x+0xB8],4` at 0x425C7C, 0x4C5BAF, 0x5A2F76, 0x5B6546, 0x63407A.
`[esi+0xB8]==5` at 0x485C4C (UI). `al<4 / al==5` at 0x4FAA9A (UI).
`[x+0x358]<4` at 0x5C9DB1 (AddToNation).

---

## 3. How power-vs-power relations change and propagate

- **CEventPeace** (vtbl 0x6AAFE8: 0x5F5040, 0x5F4E70, 0x5F5060, 0x5F50F0,
  **Execute 0x5F56E0**). It is created by 0x5F51C0 (caller 0x580E27, new game)
  as a 0x2C-byte object: `+8..+0x1C dword date[6]`, `+0x20` scheduler handle,
  `+0x24`, `+0x28`. [H] The global pointer is 0x70364C (cleared by the dtor at
  0x5F5810). [S]
- **Pair table at 0x6AAFDC** (6×2 bytes): (0,1) (0,2) (0,3) (1,2) (1,3) (2,3) [S].
  It is hard-wired to 6 pairs: the loops at 0x5F4EE3, 0x5F4FEF and 0x5F56F9 all
  count to 6.
- **New game** (0x5F51C0): for each pair, `relation = rand & 1` (war or neutral,
  random) via SetRelation, and `date = now + (rand%11+2)*0x1900`. If war,
  `0x5BBB20(0)` runs on both nations [S] [H: military build-up].
- **Execute** (0x5F56E0): for each pair whose date has passed, it does
  `SetRelation(a,b, 1 - GetRelation(a,b))` (toggles war/neutral), sets
  `date = now + (rand%11+2)*0x1900`, calls the war-start handler 0x5F5360(a,b)
  (#14), and if war, `0x5BBB20(0)` on both. It returns the time to the next
  date [S].
- **Lua `Global_SetRelations`** (0x41D850) → `CEventPeace::Schedule`
  **0x5F4E80(a,b,state,date)** [S]: it rejects a≥4, b≥4 and a==b, finds the
  pair, calls `SetRelation` **immediately**, and stores `date[pair]` (the
  earliest next automatic change). `Global_GetRelationChangeDate` →
  `ChangeDate` 0x5F4F90 returns `date[pair]` ("invalid nation pair" if not
  found) [S].
- **`World::SetRelation(a,b,state)` 0x5D0FA0** (ecx=0x702140, ret 0xC) [S]:
  it rejects a==b and ≥4, then writes `g_nations[b]->rel[a] = g_nations[a]->rel[b] = state`.
  If the value changed it posts `ID_MSG_WAR_BEGIN` (state==1) or `ID_MSG_WAR_END`,
  and on non-war runs the local player's LoM expiry 0x5D44C0. It then zeroes
  `[nation+0x16C]` for a side left with no wars.
- **Convoy retargeting is lazy** [S/H]: nothing walks the convoys in SetRelation.
  Masks are rebuilt by 0x63C280 when convoy logic calls it. Running missions are
  re-validated by 0x5AD8F0 (#8) and aborted via 0x5B0730 once the target is no
  longer an enemy. New war missions come only from 0x5F5360 → 0x5B4870.
- Player hostility has no event or date. It is pure reputation, changed by
  gameplay (0x5D45F0 / 0x5D4840) and Lua (`Player_AlterReputation`).

---

## 4. Recommended minimal detours (table-driven "P hostile to player nation 5")

Table proposal (new section): `byte HOST5[4]`, one per power. Values:
0 = vanilla (follow reputation), 1 = force hostile, 2 = force non-hostile.
All sites below were checked: **no branch in `.text` targets the interior of
any patched range** [S].

### D1 (required) `GetReputation` entry, 0x5D2AC0, 6 bytes
```
5D2AC0 8A442404   mov al,[esp+4]
5D2AC4 3C04       cmp al,4            ; overwrite D2AC0..D2AC5 with JMP stub + NOP
5D2AC6 7210       jb 5D2AD8           ; keep (stub jumps back to 5D2AC8 for >=4)
```
Stub: `mov al,[esp+4]; cmp al,4; jae 5D2AC8` (vanilla ≥4 path, al intact).
Then `movzx edx,al; mov eax,[ecx+edx*4+54h]; sar eax,16; movsx eax,al` (same
result as the original 0x5D2AD8..0x5D2AEC). Then optionally gate
`cmp word [ecx],0; jne done` (human only [H]). Then apply `HOST5[edx]`:
1 → `xor eax,eax`; 2 → `eax=max(eax,50)`; then `ret 4`.
Use 50, not 25: level 1 still has a 1/5 chance of setting the hunt bit
(0x63C310..0x63C32E), and 0x5B6BD2 attacks at rep<2.
**This covers all 55 `GetReputationLevel` sites** (0x5D2C15 calls 0x5D2AC0):
attack mask bit 0x20, `war[5]` for nation-5 towns, trade, harbor, dialogs, map
icon, LoM expiry, AI. It also covers the 9 raw-rep sites.

### D2 (required) `IsRepAtLeast25` entry, 0x5D2D90, 6 bytes
```
5D2D90 66833900   cmp word [ecx],0
5D2D94 751A       jne 5D2DB0         ; overwrite both (JMP + NOP)
5D2D96 8A442404   mov al,[esp+4]
```
Stub: replicate the function (≤20 bytes) with `HOST5`: 1 → return 0, 2 → return 1.
This covers the 13 trade/autotrade sites, which read rep inline and miss D1.

### D3 (recommended) `IsAtWar` ≥4 branch, 0x5BA0BA, exactly 5 bytes
```
5BA0BA B001       mov al,1
5BA0BC C20400     ret 4              ; 5BA0BF = CC → JMP rel32 fits exactly
```
Stub (it never returns into the original):
```
cmp byte [esp+4],5 ; jne war
test ecx,ecx       ; jz war          ; self may be NULL (GetNation/guard for >=4)
movzx eax,byte [ecx+18h]             ; CNation::index — ctor 0x5BBD39 `mov [esi+18h],al` [S]
cmp eax,4 ; jae war
movzx eax,byte [HOST5_bool+eax]      ; 1 = hostile
ret 4
war: mov eax,1 ; ret 4
```
This makes #18 (siege flag 0x40 against a nation-5 town), #16 (route cost of
nation-5 towns) and #1 (governor dialog with a player convoy) follow the
table. Pirates (4) stay at war. Derive `HOST5_bool` from D1's effective result
(vanilla mode = `GetReputationLevel(P)==0`), or keep a plain 0/1 table.
Alternative entry point: 0x5BA0A0 (6 bytes `8A442404 3C04`), if
power-vs-power must also be table-driven.

### Optional finer-grained call-site patches (military only)
- 0x63C301 `53` + `E8 0969F9FF` (push ebx; call 0x5D2C10), 6 bytes: replace the
  "hunt player" level read only.
- 0x63B46B `8B550C 52` + call at 0x63B46F: replace `war[5]` only. Note that
  nation-5 towns *also* need `war[display nation +0x359]`
  (0x63B63A..0x63B653). For a sovereign player nation, NOP that second test or
  set display=5-safe.

### Side effects to handle in the mod (not covered by D1–D3)
- Table flips post no HOSTILE_START/END message, play no video, and do not
  update town flag 0x8000. To mimic them: call `0x624C20/0x624C60(0x8000)` with
  `ecx=town+0x38` for towns with `+0x390==P`, and post
  `0x5B82A0(0xD/0xE,-1,P,-1)` [H on calling details].
- **Crash hazards when the player's own "nation" is 5** [S]:
  - 0x5D33B0 with home ≥4: NULL IsAtWar at 0x5BA0AB, and an out-of-bounds rep
    write at 0x5D34F4.
  - 0x63B840 when its source town is ≥4: NULL self while other<4.
  - 0x5AD8F0 / 0x5B5110 if a convoy with `+0xB8≥4` ever gets a war mission
    (0x5B4870 blocks this in vanilla).
  - D3's NULL check makes ≥4 queries safe, but **not** NULL-self + other<4.
    Those need guards at the callers, or a stub at 0x5BA0A0 that returns 0
    when ecx==NULL.
