# Conquest and sovereignty transfer: power town <-> player nation (5)

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000).
The game was not launched. Tools: pefile + capstone (linear `.text` disassembly and
E8/E9 xref index). Scratch scripts are in the session scratchpad `agent_conquest/`
(`h.py`: `d VA N` disassemble, `c VA` callers, `r VA` data refs, `s TEXT` strings).

Labels:
- **VERIFIED-STATIC**: I read the bytes and quote the instruction.
- **HYPOTHESIS**: an inference that still needs a runtime check.

Spec reference: §4 (sovereignty transfer), TER-02 (private property survives).

## TL;DR

1. **Vanilla has one real sovereignty transfer**: `CNation(new)::AnnexTown(townHandle)`
   at `0x5BC310`. It is reached only from the player's town battles (land side
   `CCoastBattle`, sea side `CHarbourBattle`) after the player picks **Annex**, and
   only if some power holds an **annexation order** (a viceroy mission the player
   accepted) against the town's owner. The new owner is the power that holds the order,
   not the player's letter-of-marque issuer.
2. **The AI never changes a town's owner.** `AddToNation` has exactly 4 callers
   (Lua, annexation, and the two town-create paths). Annexation orders are created
   only by the viceroy dialog. An order can never target nation 5.
3. **Power -> nation 5 recipe:** vanilla has no function that does this for an owned
   town. A DLL does what `AddToNation` does internally: detach the town from the old
   power's list (`0x636630`), set the bytes (`+0x358=0xFF`, then
   `AddToNation(D,1)`), and notify (`0x624F50`). Do **not** set `0x600000`.
   Viceroy seats must be refused, or their seat moved first. **Nation 5 -> power:**
   vanilla `AddToNation(n,0)` handles it correctly.
4. **Finding: the M0 harness flip leaves the list stale.** `cmd.py setnation` writes the
   raw bytes only, so the town stays in the old power's `CNation+0x14` list. That list
   **is saved** (`0x5BB639`/`0x5BB82F`), and `Nation_GetNumTowns`, the admin-seat
   count and the viceroy-move candidate list all read it. M1 must use the recipe in §1.
5. **P05 fix 3 is defensive only.** `0x5BC310` cannot run with old owner 5, because
   an order's target is always <4. If it ever did, it would also throw: it builds a
   `CChronicleAnnexation` with old=5, and that function rejects nations ≥4
   (`0x5DA79E`).
6. **Property:** buildings are owned by a CPlayer handle (type 9). The building licence
   is a flag stored on the town. Neither transfer path touches buildings, so transfers
   keep them (TER-02).

---

## 0. Data model used below (VERIFIED-STATIC)

| Item | Where | Evidence |
|---|---|---|
| Nation / display bytes | `Lager+0x358` / `+0x359` (`Lager = CStadt+0x38`) | the private feasibility study T1/T3 |
| Seat flags | `Lager+0xC` = `CStadt+0x44`: bit 0 = admin seat (governor), `0x2000` = viceroy, `0x8000` = hostile-to-player marker. Set with `0x624C20(mask)` / clear with `0x624C60(mask)`, thiscall on the Lager, `ret 4`; both notify `0x703ADC` | `0x624C30 or eax,edx / mov [ecx+0xc],eax`; `0x624C6D and eax,edx / mov [ecx+0xc],eax`; `mov ecx,0x703adc / call 0x624810` |
| Player-town bits | `Lager+8` bits 21/22, set only by `0x624D30` (`or eax,0x600000`, notifies `0x703AE0`), sole caller `0x61BE91` | `0x624D36` |
| Power's town list | `CNation+0x14` → sentinel of a circular list; node `{next,prev,handle@+8}` | `0x636632..0x636640 cmp [eax+8],edx` |
| List remove | `0x636630` `bool __thiscall(list* /*&CNation+0x14*/, DWORD handle)`, `ret 4` | `0x63664F..0x636667` unlink + free, `mov al,1` |
| List add-unique | `0x5C97D0` same convention; only caller AddToNation | `0x5C97EF xor al,al` if present |
| Town handle | Lager vfn[0](`DWORD* out`): `mov edx,[esi] / push ecx / mov eax,esp / push eax / mov ecx,esi / call [edx]` | `0x5C9E27..0x5C9E33` |
| List is saved | `CNation::Save 0x5BB630`: `0x5BB639 lea esi,[ebp+0x14] / call 0x5A9580` (from World::Save `0x5D119B`); `Load`: `0x5BB82F lea esi,[ebx+0x14] / call 0x5BB520` | |
| List readers | `0x5BB3F0` count (`mov edx,[ecx+0x14]`) = Lua `Nation_GetNumTowns` (`0x41DAEC`) and attack-mask strength (`0x63C370`); `0x5BB0F0` admin-seat count; `0x5BC4B5` viceroy-move candidates; `0x5BB23B`/`0x5BB365` annex preconditions | |
| Per-nation statistics | `0x5BA5A0` zeroes `+0x1C/+0x20/+0x24../+0x74../+0xC4..`, then walks **all** towns filtering on `town+0x390 == this+0x18` (`0x5BA610`). Called each tick from `0x5D2886` (World). **Self-heals from the byte; no list involved.** | |
| CEventNationStatistic | `0x5F4550 mov cl,[eax+0x390] / cmp cl,4` skips ≥4; history samples only | |
| Town's local AI trader | `0x5C8FE0(lager, DWORD* out)` = Lua `Town_GetLocalTrader` (`0x42A74A`) returns a type-9 player handle. `CPlayer::SetNation(n)` = `0x5A9DF0` (thiscall, `ret 4`): detaches from `CNation[old]+4`, attaches to `[n]+4`; **for n≥4 it writes `+0x24 = 0xFF`** (`0x5A9E5B`) | |
| Lost-town counter | `word CNation+0x16C`: `++` only at `0x5BC59D`, zeroed by SetRelation `0x5D10ED/0x5D1105`, read by `0x5BBB20` (`0x5BBBCD`): with flag=1, 2/3/>3 lost towns raise the warship target `+0x168` to 1/3/6, then `0x5F1B30(nation,0)` | |

## 1. Q1: converting an owned town (0..3) to the player nation, and back

### 1.1 What vanilla's own paths do (VERIFIED-STATIC)

`AddToNation(n, force)` `0x5C9DA0` (thiscall on the Lager, `ret 8`):
- **force≠0** (`0x5C9DAF je` not taken): acts **only** if `+0x358 >= 4` (`0x5C9DB1 cmp byte [esi+0x358],4 / jb ret`).
  It then writes `+0x359 = n%4` and `+0x358 = 5` (`0x5C9DD1/0x5C9DD7`).
  It touches no list, no flags and makes no notify call. For an owned town (0..3) it is a **no-op**.
- **force=0**:
  - Same nation: return (`0x5C9DF4`).
  - `edi = g_nations[cur]` or NULL; `ebp = g_nations[n]`. If n≥4 → `0x5C9E69 test edi,edi / jne ret`:
    an owned town silently ignores the call, and an unowned one throws
    "AddToNation - invalid nation id" (`0x5C9E71`).
  - Otherwise: `+0x358=0xFF` (`0x5C9E1E`). If `edi` (old power): `List_Remove(&old+0x14, h)` (`0x5C9E38`).
    Then `List_Add(&new+0x14, h)` (`0x5C9E4E`) and both bytes = n (`0x5C9E54/0x5C9E5A`).

The "Your Own Town" path `0x61BDE0`:
- creates a **new** town with Lager flag=1, which allocates the `0x7104`-byte extension at `Lager+0x9184` (`0x61CD25`);
- `AddToNation(n,1)` on the fresh 0xFF town;
- then `0x624D30` sets `0x600000`.

That path cannot be reused for an existing town: it creates the town.

Both vanilla re-nation sites call `0x624F50` afterwards (Lua `0x4292E4`, annex `0x5BC5BC`). `0x624F50` (thiscall
Lager, no args) gets the handle and notifies `0x703ADC` through `0x459E90`.

Lua `Town_SetNation` refuses admin seats and player towns:
- `0x42926E mov ecx,[eax+0x44] / test ecx,1 / jne "invalid city type"`;
- `0x429288 shr eax,0x16 / test al,1 / jne`.

### 1.2 Recipe A: power town T (old owner O ∈ 0..3) → nation 5, display D (DLL, main thread)

Steps 1–4 are VERIFIED-STATIC equivalents of vanilla internals. Steps 5–7 are HYPOTHESIS policy.

0. **Refuse** if:
   - `O >= 4`;
   - `Lager+8 & 0x400000` (already a player town);
   - `CStadt+0x44 & 0x2000` (viceroy seat). See §2, or do the seat move first.
   - a battle on T is open (HYPOTHESIS: check the battle store `0x7036C0`).
1. `DWORD h; lager->vfn[0](&h);` gives the town handle (type 1).
2. `((bool(__thiscall*)(void*,DWORD))0x636630)(&g_nations[O]->field_0x14, h);`
   This is the detach that AddToNation does at `0x5C9E35..38`. Note `ecx` is the **address**
   `CNation+0x14`, not its contents.
3. `*(BYTE*)(lager+0x358) = 0xFF;` then `((void(__thiscall*)(void*,BYTE,BYTE))0x5C9DA0)(lager, D, 1);`
   This gives `+0x359=D`, `+0x358=5`. Writing both bytes directly is equivalent.
4. `((void(__thiscall*)(void*))0x624F50)(lager);` (UI/town-list notify).
5. Hostility marker: `0x624C60(lager, 0x8000)`. Bit `0x8000` marks "owner P is hostile to the
   player" (hostility_map §2.1) and has no meaning for nation 5.
6. Local trader: leave it on a power. If D≠O, call `0x5A9DF0(trader, D)`. **Never pass 5**: that
   writes `+0x24=0xFF`, which then leaks into convoy `+0xB8` (HYPOTHESIS: hostile-to-all convoys).
7. **Only for a conquest during war** (not a peaceful declaration), mirror the loser
   bookkeeping: `++*(WORD*)(O+0x16C); 0x5BBB20(O, 1)` (thiscall, `ret 4`), as at `0x5BC59D/0x5BC5D3`.

Do **not**:
- call `0x624D30`, because bit 22 assumes the `Lager+0x9184` extension (vanilla_nation5_path §3.5), and E3
  showed it does not help;
- create `CChronicleAnnexation` (create-data `0x19`, `0x5B9F00`), because it rejects nations ≥4:
  `0x5DA799 mov cl,[ebp+8] / cmp cl,4 / jae 0x5DA951` and `0x5DA7A6 cmp byte [ebp+9],al / jae`;
- call `0x5BC310`, which needs a `CNation*` and an annexation order.

A message is optional: `(*0x42F850())->0x5B82A0(0x19 ID_MSG_TOWN_ANNEX, h, -1, -1)` carries only the
town handle (`0x5BC821..0x5BC831`). HYPOTHESIS: its text shows the display power.

Nation statistics, the statistic event, the economy share (P05) and the admin population
(`CNation+0x20`) all key on the byte and recompute themselves (§0).

### 1.3 Recipe B: nation-5 town → power n (VERIFIED-STATIC that vanilla handles it)

`AddToNation(lager, n, 0)` with `cur = 5`:
- `0x5C9DF6 movzx eax,al(5) / cmp eax,4 / jae → edi=0`;
- `ebp = g_nations[n]` (non-NULL);
- `0x5C9E1E +0x358=0xFF / je 0x5C9E3D`, so the detach is skipped;
- vfn0 + `0x5C97D0` add T to `n+0x14`;
- both bytes = n.

This is correct for `n<4`. Caveats:
- `n>=4` throws (edi=0 → `0x5C9E71`), and `n==5` returns early.
- It does not clear `0x600000`. Fine if Recipe A never set it. Vanilla "Your Own Towns" are not transferable through Lua (`0x429288`).

Then:
- call `0x624F50(lager)`;
- move the trader back with `0x5A9DF0(trader, n)` if it was moved;
- if the player's reputation level with n is 0, set `0x624C20(lager,0x8000)` to mimic `0x5D47D8` (HYPOTHESIS).

## 2. Q2: governor and viceroy seats

**Admin seat, bit 0 (`mask 1`; viceroy towns carry `0x2001`).**
- In vanilla annexation the bit **stays with the town**. Only the NPCs are rebuilt:
  - `0x5BC72D test al,1`, then the governor NPC (`0x5C7450`, NPC type 1);
  - its look bytes are read (`0x43EDD0/0x43EDE0`), then `vfn[0x30]` = NPC::Remove (`0x43FA98` unlinks from town list `+0x91E4`, `0x43F6E0` frees);
  - a new governor is created (create-data type 1, `0x5B9F70` → NPC manager `0x411200` → `0x42EA90`).
- With P05 a nation-5 seat is crash-free (RUNTIME TER-01, Margarita).
- **Recommendation (HYPOTHESIS):** keep bit 0 for M1, with D = O. The governor NPC's nation is the
  display byte (`0x447D3E` style), so it stays coherent.
- Clearing bit 0 would orphan the NPCs: the getters `0x5C7450`/`0x5C7540` gate on bit 0
  (`0x5C7480 test byte [ebp+0x44],1`). If you clear it, first `vfn[0x30]` the type-1 and type-9 NPCs, and
  store the old mask so the reverse can restore it with `0x624C20` and recreate the NPCs (`0x5B9F70` / `0x5B9F90`).

**Viceroy seat (`0x2000`).** Vanilla moves the seat (`0x5BC49E..0x5BC6FA`):
1. It collects O's other bit-0 towns from `O+0x14` (excluding T).
2. **If there are none, it refuses the whole annexation**: `0x5BC57D cmp [ebp],ebp / je 0x5BCB6F` (returns 0).
3. It picks a random candidate (`0x42D1D0`).
4. On that candidate:
   - `|=0x2000` (`0x5BC655`);
   - dismiss its governor (`vfn[0x30]`, `0x5BC648`);
   - move the viceroy NPC (type 2, `0x5C7630`) there with `vfn[0x2C]` = NPC::MoveToTown (`0x5BC66D`; `0x43F9BD` unlinks from the old town);
   - dismiss its type-0xF NPC (`0x5BC6B7..0x5BC6C3`).
5. On T: clear `0x2000` (`0x5BC6CD`) and create a new governor (`0x5BC6E4..0x5BC6FA`). T keeps bit 0.
6. Post create-data `0x2E` (`0x5B9F50` → `0x5A84B0`).

Effects of leaving `0x2000` on a nation-5 town (HYPOTHESIS):
- O has no viceroy in its own list, so the Lua title is `IDPR_SID_SITZ_VIZEKOENIG_%02d` with the raw byte (`0x4A3E66`, formats `_05`);
- viceroy-town annex preconditions read O's list (`0x5BB233`);
- the "Your Own Town" offer, letters of marque and annex orders all come from that viceroy NPC.

**Recipe:** refuse independence or conquest of the 4 viceroy towns, or replicate steps 1–6 before Recipe A.
**Annexation timers:** O's own order (`O+0x154`) is unaffected.

## 3. Q3: player-led conquest in vanilla

**Who becomes owner.** It is not the letter-of-marque issuer. It is the power holding an **annexation order** against the
town's owner:
- `CNation+0x154` holds a type-0x17 timer event, with `+8` = issuer and `+9` = target (`0x5BB205 call [edx+4] / cmp al,0x17`, `0x5BB21A cmp [edi+9],al`).
- Orders are created only by `StartAnnexationTimer 0x5BA260`:
  - `0x5BA2BA cmp bl,4 / jae throw`;
  - an inline IsAtWar requirement;
  - the order also prolongs the war via `0x5F4E80`.
- Its **only caller is `0x44832F`**, in the viceroy's `ProcessAnswer 0x447ED0`.
- The matching letter is `CLetterAnnexationOrder` (create-data `0x2F`, `0x5E4AFE`).

**Flow (CCoastBattle, land side; vtable 0x6AB578, state at `+0x54`)**:
1. State 8 handler `0x6010A0`:
   - `0x60114C mov byte [esi+0x59],0xFF`;
   - loop `0x601157..0x6011B2`: `[esi+0x59] = argmin_n CNation[n]::0x5BB2B0(town)`;
   - `0x6011B4 cmp byte [esi+0x59],4 / jae / or byte [esi+0x58],4`.
   If `+0x58<4` (no annex possible) → `0x6011C5` state 9 (raid, **no question**).
   Otherwise it opens the question at `0x601217`: type 5 (defeated, flags 2 = DECIDE), 0xB (fencing won) or 4 (surrender).
2. Question mechanism (reusable for yes/no):
   - `CQuestionStore* qs = *0x42D020(); id = qs->0x57E7D0(BYTE type, DWORD battleHandle, DWORD flags, DWORD extra)` (`ret 0x10`, node `+8` type, `+0x10` handle, `+0x14` flags). The battle stores id in `+0x2C`.
   - Answers: **OnJa `0x57DF00`** (table `0x57E4AC`/`0x57E48C`: types 4,5,6,7,0xB,0x19,0x1B → `battle->vfn[6](0)`, `0x57E102 push ebx(0) / call [edx+0x18]`).
   - **OnNein `0x577780`** (table `0x577A24`/`0x577A10`: same types → `vfn[6](1)`, `0x577900 push 1`).
   - Type-5 DECIDE buttons: `ID_BTN_RAID` (`0x579F3C`), then `ID_BTN_ANNEX` (`0x579FA4`).
3. `vfn[6] = 0x5FF310`: in state 8, `state = 9 + (arg!=0)` (`0x5FF373..0x5FF388`).
   - Arg 0 → state 9 `0x601230` (raid).
   - **Arg 1 → state 10 `0x6022BF` → `0x6013D0` (annex).**
   The button-to-Ja/Nein order is a HYPOTHESIS; the state mapping is VERIFIED.
4. `0x6013D0`:
   - `0x601481 movzx eax,byte [esi+0x59] / cmp eax,4 / jae 0x60155D` (→ state 0xE, **no transfer**);
   - `0x6014EB call 0x5BC310` (`ecx=g_nations[+0x59]`, arg = town handle `+0x18`);
   - then question 7 (ANNEX_00/01/02 by seat kind ebx = 0/1(gov)/2(viceroy), `0x60154C`).

**CHarbourBattle (sea side; vtable 0x6AB648, state at `+0x240`)**:
- Gate `0x605A50`: loop `0x605AD4..0x605B08` of `0x5BB190` over n=0..3, else state 8.
- Question at `0x605B63` (type 5 with flags 3, or type 0xB).
- `vfn[6] = 0x604930`: `0x604960..0x604978` gives `8+(arg!=0)`. State 9 → `0x605C80`:
  argmin `0x605D4F..0x605D9A` into `[esp+0x17]`, then `0x605DA1 cmp edi,4 / jae 0x605DE2`, then `0x605DD7 call 0x5BC310` → `+0x248`.

**What `0x5BC310` does in addition to `AddToNation(new,0)`:**
- the seat moves (§2);
- old `+0x16C++` and `0x5BBB20(1)`;
- `0x624F50`;
- `CChronicleAnnexation` (old, new);
- message 0x19;
- new owner `+0x13C` `&~2|4`;
- the local trader goes to the new owner (`0x5BC84F`, `0x5BC8C4`);
- player annex counter +1 (`0x5BC8F3 → 0x5C3700(new,1)`), which feeds the "Your Own Town" offer;
- the matching type-0x2F letter is fulfilled (`0x5BC979..0x5BC9AC`);
- the new owner's order timer is cancelled (`0x5BCA03`, `+0x154 = invalid`).

**Hook points for "Annex to player nation / Withdraw" (design, HYPOTHESIS):**
- **Offer:**
  - coast: detour `0x6011BE` (`mov al,[esi+0x58]` 3 bytes + `cmp al,4` 2 bytes = exactly 5, both PIC; both paths, `0x601148 je` and `0x6011B8 jae`, land on its start). If `+0x58<4` and the player nation is at war with the owner (`player_rel[O]`), set `+0x59=5` and `+0x58|=4`. Do not detour `0x6011B4`: it is followed by a rel8 `jae`.
  - harbour: detour around `0x605B0A`/`0x605B1B`.
- **Decide/execute:**
  - coast `0x601481`: 7 bytes, `movzx eax,byte [esi+0x59]` (4) + `cmp eax,4` (3), both PIC. If `==5`, run Recipe A on handle `[esi+0x18]` and jump to `0x6014F4` (post-annex UI and question 7). Otherwise run the original.
  - harbour `0x605D9C` (`movzx edi,byte [esp+0x17]; cmp edi,4`): same.
  - Vanilla's own `+0x59>=4` exit (`0x60155D`, state 0xE) is already a clean **withdraw** that keeps the owner. **Raid** also keeps the owner.
- **Must-have guard:** the player's own nation-5 towns are attackable today. `NewCoastBattle 0x603030` refuses only
  bit-22 towns (`0x60309C mov ecx,[eax+0x40] / shr ecx,0x16 / test cl,1 / jne`), and so does the player-convoy
  path (`0x5B4B2A..0x5B4B33`). Add `town+0x390==5` there.

## 4. Q4: AI capturing a player-nation town

- **Vanilla AI never transfers towns.**
  - Only 4 callers of `0x5C9DA0`: `0x4292D1` Lua, `0x5BC5B5` annex, `0x61BE8A`/`0x61C3C6` create.
  - `0x5BC310` is reached only from `0x6014EB`/`0x605DD7`, after a human answer and an order.
- AI military **does** start coast battles:
  - mission action 1 (`0x5B4DD3 cmp byte [esi+0x171],1` → `0x5B4DF4 call 0x603030`);
  - siege flag 0x40 (`0x5B4D33..0x5B4D50`).
  - For non-docked attackers, `0x603030` skips the bit-22 and protection checks (`0x603093 cmp [esi+0xB4],1 / jne create`).
- The only exit that changes the owner still needs `0x5BB190`/`0x5BB2B0` to find an order whose target equals the town's byte. **An order's target is always <4** (`0x5BA2BA`), so a nation-5 town is never annexed and nothing dangles.
- **P05 fix 3 is therefore unreachable.** If it were reached with old=5, the chronicle create at `0x5BC7FE` would carry `+8=5` and throw at `0x5DA7A0` (HYPOTHESIS: the factory `0x5A84B0 → 0x42ECB0` runs synchronously).
- With P01, `0x63C48A` IsAtWar(P, 5) follows `player_rel`. But the target picker `0x63B3A0` also requires war with the **display** power (`0x63B63A..0x63B653`), so a power at war only with the player nation will not pick the town there.
- An "AI conquers player town" feature is **new code**. Use Recipe B (`AddToNation(P,0)` + `0x624F50` + trader) from a hook on the AI-won battle end. HYPOTHESIS: the end-state handlers `0x601570`/`0x6015B0`/`0x601600`.

## 5. Q5: private property (TER-02)

- Buildings are created with an owner **player handle**: Lua `Global_CreateBuilding` checks/forces type 9
  (`0x429090 cmp ecx,0x90000`, `0x4290B7 or edx,0x90000`) and passes it to `CStadtLager::CreateBuilding 0x61F3B0`.
- The building licence is stored on the town (`Lager+0x9174`, granted flag `+4`: `0x61B614 mov byte [ebx+4],1`; check `0x61B51E`). It is not keyed by the current nation.
- Neither `AddToNation` (full body above) nor `0x5BC310` (full body read, `0x5BC310..0x5BCB94`) touches buildings, offices or warehouses. They touch only lists, bytes, flags, NPCs, the trader, letters, chronicles and counters.
- Nation-dependent rules apply to new building only: the quota `0x5D3530` gives nation 5 a full 100.
- **Transfers preserve player property** (VERIFIED-STATIC by absence; RUNTIME TER-02 still to do).
