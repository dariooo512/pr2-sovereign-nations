# Vanilla nation-5 path: "Your Own Town" (Spielerstadt)

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000).
The game was not launched. Tools: pefile + capstone, with a full linear disassembly
of `.text` and a call/immediate xref index. Scratch scripts are in the session
scratchpad (`agent_force/`).

Labels:
- **VERIFIED-STATIC**: I read the bytes and quote the instruction.
- **HYPOTHESIS**: an inference that still needs a runtime check.

## TL;DR

1. **H1 is refuted in its original form, but the core idea holds.** The 16 `Nation=Spezial`
   sites are **not** created at game start. They are the candidate sites for the
   **player's own town**, which a **viceroy** (Vizekoenig NPC) offers as a gift of land.
   The town is created only when the player accepts that offer. Creating it sets
   nation byte = **5** (`SPIELER_NATION`), display nation = the viceroy's power, and the
   town flags `|= 0x600000`.
2. Vanilla has exactly one producer of nation 5: player-town founding.
   `0x61BDE0` <- `0x61C7A0` <- `0x447520` (viceroy NPC vtable slot 14) <- *(the UI-side caller
   was not found statically; see section 1.5)*.
3. Most "player town" behaviour keys off **flag bit 22 (`0x400000`) at `CStadt+0x40`**, not off
   nation==5. Lua `Town_IsPlayerTown` reads that bit. Nation 5 itself is handled mostly by
   the generic `>=4 -> display nation` substitution. There is **one** explicit `==5` test,
   which gives max reputation-equivalent.
4. **Test trigger, no patching:** call Lua `Player_SetAnnexCounter(<nation>, >=2)`. Vanilla
   `scenario005.lua` does this. Then talk to that nation's viceroy, who offers a site; the
   player picks one and `0x447520` fires. The candidate sites are already assigned at
   New Game by `0x5BBEB0`.

---

## 1. The call chain (Q1)

### 1.1 `0x61BDE0`: CStadt "create player town at site"  (VERIFIED-STATIC)
`thiscall(CStadt* this, WORD siteId, BYTE nation)`, `ret 8`. This is the same build
sequence as the normal create (`0x61C320`), with three differences:

| VA | Instruction | Meaning |
|---|---|---|
| 0x61BE75..7D | `push 1 / push ebx / mov ecx,esi / call 0x61cce0` | Lager init from template `siteId` with **flag=1**. The normal create passes `push 0` at 0x61C382. With flag=1, `0x61CCE0` also allocates a 0x7104-byte extension object and stores it at Lager+0x9184 (`0x61CD25 push 0x7104`, `0x61CD57 mov [esi+0x9184],eax`). |
| 0x61BE82..8A | `mov ecx,[ebp+0xc] / push 1 / push ecx / mov ecx,esi / call 0x5c9da0` | `AddToNation(nation, force=1)` |
| 0x61BE8F..91 | `mov ecx,esi / call 0x624d30` | `0x624D33 mov eax,[ecx+8] / 0x624D36 or eax,0x600000 / mov [ecx+8],eax`. This sets town flag bits 21 and 22 (`CStadt+0x40`) and then notifies the town list at `0x703ae0` (`0x459e90`). |

Force path of `AddToNation` (VERIFIED-STATIC, `0x5C9DB1..0x5C9DE5`):
`cmp byte [esi+0x358],4 ; jb skip ; ... ; mov [esi+0x359],al(nation%4) ; mov byte [esi+0x358],5`.
It does **not** insert the town into any `CNation` town list (there is no call on this path).
So a nation-5 town is counted by no power.

The Lager starts with nation 0xFF. `0x5C9EA0` (Lager init) sets `+0x358 = +0x359 = al`
(`0x5C9EF7/0x5C9EFD`), so the force path applies. (That al = 0xFF is a HYPOTHESIS; it is
implied by the force path firing.)

### 1.2 `0x61C7A0`: "CStadtCreate (player town)"  (VERIFIED-STATIC)
`cdecl Handle* f(Handle* out, WORD siteId, BYTE nation)`; the only caller is `0x44755A`.
- `0x61C7A8 cmp eax,4 / jae`: the nation must be 0..3 (`ebx = g_nations[nation]`).
- `0x61C7C1 call 0x402940`: gets the player handle and validates it in the 0x701ec0
  table (stride 0x94, byte +0x25 != 0).
- `0x61C830..0x61C849`: the loop `cmp [ebx+edx+0x144], bp` checks that `siteId` is one of
  the nation's 4 candidate site bytes at **`CNation+0x144`**. If not, it exits.
- `0x61C854 call 0x61bf90`: allocates a new slot in the town array `0x702068`.
  `0x61C86E push "CStadtCreate: out of memory"`.
- `0x61C8A8 call 0x61bde0` (this=new town, siteId, nation)
- `0x61C8AF call 0x5ba810`: `CNation::PurgeFoundedSites`. It sets every entry of
  `+0x144[0..3]` whose site is now founded (`0x703bb4[site] != 0`) to 0xFF.
- `0x61C91A push 0x2f / call 0x5b82a0`: posts event 0x2f for the new town handle.
  HYPOTHESIS: this is the news, chronicle and video hook: `ID_MSG_NEW_TOWN`,
  `CChronicleNewTown` (`0x5DF6A7` strings), `videos/13_Spielerstadt.wmv` (table `0x6E1640`).

### 1.3 `0x447520`: viceroy NPC, vtable slot 14 "found town at choice"  (VERIFIED-STATIC)
`thiscall(NPC*, int choice)`, `ret 4`. There is no direct caller. The only reference is
the vtable entry **`0x688A90` = 0x00447520** in the vtable at `0x688A58`; the ctor `0x447689`
does `mov [esi],0x688a58`.
- `0x447523 call 0x43ee40 / cmp eax,6 / jne`: the NPC dialog state must be **6**.
- `0x44752D cmp ecx,4 / jge`: choice must be 0..3.
- `0x447536..43`: `site = byte(choice)` of the packed dword `data+0x28`; store it in `data+0x2c`.
- `0x447546 call 0x43edf0` (the NPC's nation) -> `0x44755A call 0x61c7a0(&data->hTown, site, nation)`
- `0x44757A push 2 ... 0x447586 call 0x5c3720`: **consumes 2 from the player's per-nation
  "annex counter"** at `player+0x8c -> +0x19C[nation]`.
- `0x44758B push 8 / call 0x43ee50`: dialog state becomes 8.

### 1.4 The class is the Viceroy NPC (NPC type 2)  (VERIFIED-STATIC)
- Static registration at `0x6766B0`: `call 0x411200 / push 0x447b90 / push 0x447c30 / push 2 / call 0x5daa50`.
  This registers factory type **2** with create `0x447C30` and load `0x447B90` in the NPC
  manager `0x411200`.
- `0x447C30` creates the NPC for a **town** handle (`[ebp]==2`, `[ebp+4]` = town). It sets
  the NPC nation from the town (`0x447D3E`: `>=4 -> +0x391`).
- Slot 3 `0x444D20` (to 0x447385) is the dialog builder. Its switch over state at
  `0x444E3F jmp [eax*4+0x447388]` emits the `ID_NPC_VICEROY_*` strings (pointer table
  `0x6E0E20..0x6E0E6C`):

| State | Handler | Text |
|---|---|---|
| 5 | 0x445949 | `ID_NPC_VICEROY_LOM_OFFER` (letter of marque) |
| **6** | 0x445A76 | **`ID_NPC_VICEROY_TOWN_OFFER`**. Opens dialog type 0xA (`0x445AE1 push 0xa / call 0x415bc0`) with the packed site list (`0x445AED mov edx,[ecx+0x28] / call 0x415e80`). |
| **8** | 0x445B55 | **`ID_NPC_VICEROY_TOWN_SELECTED`**, with the new town's name (`data+0` handle). |
| 9 | 0x445CDA | `ID_NPC_VICEROY_NEW_LAND_ALL` (if `data+0x14==4`) else `..._NEW_LAND_PART` (`data+0x14*25`). These are later land gifts for an existing player town. |

- Slot 21 `0x447ED0` is the answer state machine (`jmp [eax*4+0x448958]`). In state 5,
  when no letter-of-marque target exists, `0x4481B3 push 6 / call 0x43ee50` sets state 6.
  State 6 handler `0x4481C1`:
  `0x4481D7 call 0x5c36e0` (annex counter[nation]) `/ cmp ax,1 / jbe -> state 9`. It also
  requires `data+0x10 == 0` (no existing player town) and `!(player[+0x38] & 0x10)`.
  Then `mov byte [eax+0x18],1` marks the offer as shown.
- Slot 19 `0x4477C0` (dialog enter/refresh) packs the 4 bytes of `CNation+0x144..0x147`
  into `data+0x28` (`0x447A70..0x447AB3`). If all four are 0xFF, it calls
  `0x5BA130` (re-balance: take a site from another power that has more than one) up to twice.

### 1.5 The caller of slot 14 is still unresolved  (VERIFIED-STATIC negative result)
The search found no code that invokes vtable+0x38 on this object:
- Direct calls and jumps to 0x447520: none.
- `call/jmp [reg+0x38]`: 86 byte hits, all reviewed by context. None is in the NPC
  region 0x43E000..0x44E000, and none has the viceroy as receiver.
- MSVC vcall thunk `8B 01 FF 60 38`: none.
- disp32 forms (`FF 9x/Ax 38 00 00 00`): none.
- `mov r,[r+0x38]; call r`: none.

So the dialog-type-0xA site-picker UI reaches slot 14 by a path not found statically.
Candidates are a sigc++ slot (libsigc-1.0.dll) or a call from a DLL.

**HYPOTHESIS:** the "pick a site" screen calls `npc->vfn[14](index)`. To settle it, break on
`0x447520` at runtime and read the return address.

### 1.6 Game start does NOT create Spezial towns  (VERIFIED-STATIC)
`0x61C980` (called from game setup `0x580D12`) loops `si = 0..0x3B`:
`0x61CBEA call 0x61c320`, then `0x61CC04 cmp si,0x3c / jb`. It also writes
`mov word [0x702076],0x3c`. That covers 60 towns only.

`0x61C320` reads the template nation (`0x61C399 call 0x623df0`) and throws
`"CStadtCreate: Invalid Nation"` (`0x61C76C`) when it is `>=4`. `staedte.ini` has 76
sections; the last 16 are the `Spezial` ones (Gruppe 0..3, four per group).

This matches the runtime observation that the force path is not hit at game start.

### 1.7 Where the 4 candidate sites per power come from  (VERIFIED-STATIC + HYPOTHESIS)
`0x5BBEB0` runs in the same setup routine (`0x580DD5`). For `ebx = 0..3` it calls
`0x5BA510(&groupKey=ebx+1, rand)` on the site registry `0x703BC0` and stores the result
in `mov [esi+ebx+0x144],al` (`0x5BBF09`). It also bumps a per-site use counter (capped at 0xFA).

HYPOTHESIS: each power gets one random site from each `Gruppe` (stored as Gruppe+1).
Several powers can hold the same site. `0x5BA810` purges a site once it is founded.

## 2. Which in-game event makes a nation-5 town (Q2)

**Player-founded town ("Your Own Town", manual §6.7).** The manual says: *"If you are on good
terms with a viceroy and have captured many towns for him, he will present you with a
parcel of land. You can choose the location yourself from a couple of alternatives…
You are the only person who can construct buildings in the town."*

In code:

1. The player's per-nation annex counter (`player+0x8c -> +0x19C[n]`) is **>= 2**. It is
   incremented by `0x5C3700`, which is called from the annexation code `0x5BC8F3` (towns
   captured for that power) and from Lua `Player_SetAnnexCounter` (`0x41DD36`).
2. The player visits that power's **viceroy**. The dialog goes through state 5
   (letter-of-marque offer) to state 6 (`TOWN_OFFER`), and a site-picker opens with up to
   4 sites from `CNation+0x144`.
3. Choosing a site runs `0x447520 -> 0x61C7A0 -> 0x61BDE0`. The town gets nation 5,
   display = viceroy power, flags `0x600000`, and an extension object at Lager+0x9184.
   The counter drops by 2 and the dialog shows `TOWN_SELECTED`.

AI powers never found towns. `0x61C7A0` requires the player handle and has only the
viceroy caller (VERIFIED-STATIC). The `ID_NPC_VICEROY_NEW_LAND_*` texts are later
expansions of the same player town, not new towns.

## 3. Code that treats nation 5 / player towns specially (Q3)

Scan basis: every read of `[reg+0x390]` (CStadt) or `[reg+0x358]` (Lager) in `.text`, about
260 sites, sorted automatically by what follows the read. A second scan covers every read
of flag bit 21/22 at `CStadt+0x40` (= Lager+8).

### 3.1 Explicit `== 5`: one site  (VERIFIED-STATIC)
- **`0x5D3530`** (callers `0x5C4DF0`, `0x5D36C0`):
  `0x5D35B7 mov al,[ecx+0x390] / cmp al,4 / jb normal / xor ecx,ecx / cmp al,5 / setne cl / dec ecx / and ecx,0x64`.
  - For nation 0..3 it uses the player's reputation with that power (`[ebx+n*4+0x54]>>8`).
  - **Nation 5 gives 100 (maximum).** Nation 4 or 0xFF gives 0.
  - The result is turned into a tier `/25`, capped at 3, then `quota = (tier+1)*N/4`, and
    compared with `0x5C3590`.
  - HYPOTHESIS: this is the per-town quota of player buildings or settlers that depends on
    reputation (`0x5C4DF0` is used by `Town_AlterSailors` and by the HDC settler UI near
    `0x47002A`). In your own town the quota is full.

### 3.2 The generic `>=4 -> display nation` substitution: 33 sites  (VERIFIED-STATIC)
Each of these reads `+0x391` / `+0x359` when the byte is `>=4`, so a nation-5 town behaves like
its display power. Examples:
- `Town_GetNation` `0x421D2E: mov cl,[eax+0x390] / cmp cl,4 / jae -> mov al,[eax+0x391]`
- Viceroy NPC create (`0x447D3E`, `0x447DB3`)
- NPC classes (`0x410E2F`, `0x413BCF`, `0x414A7F`, `0x4153F1`, `0x415AFF`, `0x4179AF`, `0x417A70` x4, `0x418441`, `0x433568`, `0x44154C`, `0x4436BD`, `0x444490` x3, `0x444B71`, `0x44951F`)
- UI (`0x4D9CF3`, `0x52D424`), nation and town logic (`0x5BE072`, `0x5C72FA`, `0x5D5897`, `0x60DDE4`, `0x63B618`, `0x63B63A`), and the getter `0x40FC70`.

### 3.3 `>=4` branches that treat 5 as "no power", like pirates  (VERIFIED-STATIC sites; purpose HYPOTHESIS)
| Site | Behaviour |
|---|---|
| `0x410C40`, `0x415916`, `0x4445AF` | NPC `SetNation(town nation)` runs only if `<4`; otherwise it falls back to `+0x391` a few bytes later. |
| `0x4DA25C` | UI colour by owner. A nation-5 town gets no national colour. |
| `0x5CD982` | Per-nation town statistics. Skipped. |
| `0x5D4BB0` | Per-nation count of towns (<0xFA). Skipped. |
| `0x5F4550` | Per-nation counters at `+0x816` (event bookkeeping). Skipped. |
| 12 bounded `g_nations[n]` reads | `0x5B013F 0x5B41B0 0x5B41DA 0x5B42EB 0x5B438D 0x5B5169 0x5B77C3 0x5C86A5 0x5C9DE8 0x5E75C7 0x5EF979 0x63B8C7`: the CNation pointer is null for 5, so the logic is skipped. This includes the annexation and war code in 0x5B0000..0x5B8000. |

Also, `AddToNation(force=1)` does not add the town to any CNation list, so `Nation_GetNumTowns`
and strength do not count it (VERIFIED-STATIC from the force-path bytes).

### 3.4 Unguarded per-nation tables indexed by the raw byte: crash or garbage risk  (VERIFIED-STATIC)
The ship-type table `0x6A5174` is 4 rows x 8 bytes (`00 01 02 03 05 07 08 0A`, ...). It is
indexed with the **raw** `+0x390` and no guard at:
- `0x5A80C6 mov dl,[eax+ecx*8+0x6a5174]` (fn ~0x5A7F40)
- `0x5A8242` (fn ~0x5A80E8)
- `0x5C59B3 cmp [edi+eax+0x6a5174],bl` (fn 0x5C57C0)

For nation 5 these read `0x6A519C` = `32 00 00 00 05 0D 10 15`, which belongs to the next
table. HYPOTHESIS: these are town-shipyard or ship-type choices. Vanilla probably keeps a
player town off these paths through the 0x400000 flag; check this before flagging ordinary
towns as 5.

Bitmask uses `1<<nation` (`0x428BA0`, `0x42B410`, `0x5D4AD5`, `0x5A825E`) give bit 5 for
player towns. The masks are caller-supplied: Lua `Town_*`/`Global_*` "nation set" arguments.

47 sites pass the raw byte to a callee (for example the title string
`IDPR_SID_SITZ_VIZEKOENIG_%02d` at `0x4A3E66`, which would format `_05`). 37 sites compare it
for equality with another nation value; nation 5 never equals a power 0..3. I have not
audited these individually.

### 3.5 The real "player town" switch: flag bit 22 (0x400000) at CStadt+0x40  (VERIFIED-STATIC)
- **Lua `Town_IsPlayerTown` = `0x4273E0`.** The binding is registered at
  `0x43AFBC push 0x4273e0 ... 0x43AFD8 push "Town_IsPlayerTown"`. The handler does
  `0x427450 add eax,0x38 / mov eax,[eax+8] / shr eax,0x16 / and eax,1`.
  So it tests **bit 22, not nation==5**.
- Town status title `0x4A3F44`: `mov ecx,[ebx+0x40] / shr ecx,0x16 / test cl,1 / je -> "IDPR_SID_KOLONIE_%02d"`,
  else `push "IDPR_SID_SPIELERSTADT_%02d"` (with the display nation).
- `0x61BC77` (`0x61BC40`, called from `0x61BF28` in the player create) uses bit 22 to choose a
  value of 0 or 5 for slot 0x13 of the town's 20 production/limit entries.
- About 70 other bit-22 readers. Representative ones:
  - `0x429288` (inside Lua `Town_SetNation` 0x429200: **a player town cannot be re-nationed**, `jne` past `AddToNation`)
  - AI/annexation `0x5B23A1`, `0x5B259D`, `0x5B353C`, `0x5B3A4E`, `0x5B4B2A` (skip or special-case player towns)
  - Building and permission UI `0x505280`, `0x505617`, `0x505B73`, `0x505F58`, `0x5060EF`, `0x613F90` x6
  - Trade/AI `0x5AA52B`, `0x5ABB2D`, `0x5C61BA`, `0x5C6EDB`, `0x5C8107`, `0x5D1522`, `0x5EF0B1`, `0x5EFA5D`, `0x5F6ADB`, `0x60309C`, `0x60D1A0`
  - Lager internals `0x61DD0C`, `0x61E4C3`, `0x620459`, `0x620532`, `0x6205E0`, `0x620AE4`, `0x6211BF`, `0x62390A`, `0x6292CC`, `0x62A7CF`
  - Map `0x63D3F3`, `0x63D6ED`
  - Per-site purpose not decoded (HYPOTHESIS).
- Bit 21 (`0x200000`), set together with bit 22: readers include `0x42A033` (a Lua getter),
  `0x482C40`, `0x493D36`, `0x4B54CA`, `0x4B78BB`, `0x4DA24E`, `0x4DAE40`, `0x51596D`, `0x5F924F`,
  `0x60FDA9`, `0x624C35/0x624C72/0x624CAC/0x624D98/0x624DDF`. Purpose HYPOTHESIS: "extended
  or growing town" state.

**Implication for option C:** stamping a town to nation 5 alone gives the display-power
behaviour, which is mostly safe. It does **not** give player-town semantics; those come
from bit 22. Setting bit 22 on a normal town without the Lager+0x9184 extension object is
risky, because `0x61D1A0` reads `[+0x9184]` with a null check, and the other readers are
unaudited.

### 3.6 Save/load  (VERIFIED-STATIC)
`0x5C9A60` (Lager load) reads `+0x358` from the stream at `0x5C9AF8`. Then
`0x5C9B02 cmp esi,0x3f4 / jb`. For save version `>=0x3F4` it reads `+0x359` explicitly; for
older saves it derives `+0x359 = +0x358 % 4`, which gives 1 for nation 5. So nation 5 and its
display byte persist in current saves. (H2, nation byte survives save/load: static reading said
"likely". Confirmed RUNTIME 2026-10-11 (SAV-01, the private feasibility study E3).)

## 4. Can the vanilla path be triggered on purpose? (Q4)

**Yes, via Lua and the normal game UI, with no patching** (VERIFIED-STATIC prerequisites;
runtime flow is HYPOTHESIS):

1. `Player_SetAnnexCounter(nation, n)` (`0x41DC90`; it rejects `nation>=4` with
   "LUAPlayer_SetAnnexCounter - bad nation id") adds n to `+0x19C[nation]` through
   `0x5C3700`. Use n >= 2.
2. Make sure the reputation with that power is high enough for the viceroy to talk:
   `Player_AlterReputation`. The welcome state shows `ID_NPC_VICEROY_BAD_REP` otherwise.
3. Go to that power's viceroy seat (Biloxi, GrandBahama, Guadeloupe or PortRoyale) and talk
   to the viceroy. Decline or pass the letter-of-marque offer; it then shows `TOWN_OFFER`
   and the site picker. Pick a site.
4. Observe at `0x447520`, `0x61C8A8`, `0x61BE8A`. After the call, check `CStadt+0x390 == 5`,
   `+0x391 == power`, and `+0x40 & 0x600000`.

**Vanilla precedent:** the compiled `scenario005.lua` in `arcs/lua/data/missions.bin`
references `Player_AlterReputation`, `SPANIEN`, `Player_SetAnnexCounter`, and then loops
`Global_GetFirstTown/Town_IsPlayerTown -> PlayerTown` with goals such as `KIRCHE` and
`Town_GetPopulation`. In other words, the designers' "own town" scenario unlocks the offer
exactly this way (HYPOTHESIS on argument values, which were not decoded).

There is no Lua binding that creates a town (the full list of 203 registered bindings was
checked), and no debug function. Direct alternative for a debugger test: set
`g_nations[n]+0x144[0]` to a Spezial template index, set the viceroy NPC state to 6, then call
`0x447520(choice=0)` with ECX = the viceroy NPC. That is more fragile than the Lua route.

## 5. Open items
- The caller of the viceroy's slot 14 (`0x447520`), section 1.5. Break there at runtime to get the return address.
- The exact semantics of bit 21 and of the Lager+0x9184 extension object (stage byte read by `0x61D1A0`; stage 3 is used at `0x447AEA`).
- An audit of the 37 equality and 47 pass-through readers of the raw nation byte, for nation-5 safety.
- The unguarded `0x6A5174` indexing (section 3.4). Check whether vanilla player towns ever reach it.
