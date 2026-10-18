# Economy data map: what the nation-economy DLL can read and write

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000;
the target base in the private feasibility study §1). The method was capstone over the real
bytes: a full `.text` sweep (859k instructions) with xrefs, plus a decode of the
Lua registration block 0x438400–0x43E800. The game was **not** launched.

Labels: **[S]** = VERIFIED-STATIC (the instruction text was read at that VA).
**[H]** = HYPOTHESIS (meaning inferred from usage).

Spec items: §5 treasury and taxes, §8 loyalty, §9 upkeep. Save hooks are **not**
covered here; see `player_cnation_design.md` §6 (0x5D11A6 / 0x5D23C3).

---

## 0. Summary

| Need (spec) | Source in the real game | Level |
|---|---|---|
| Town population | `u16 CStadt+0x38A` | S |
| Garrison | `u16 CStadt+0x38E` (soldiers; Lua "workers" = pop − this) | S (layout) / H (name) |
| Prosperity | `u8 CStadt+0x58` wealth level 0..7, derived from ALQ and population | S |
| Satisfaction / "loyalty" | **ALQ** `i16 CStadt+0x54` = current living quality (Lebensqualität), 8.8 fixed, about 0..115. **ELQ** `i16 CStadt+0x56` = target LQ. ALQ moves toward ELQ by 1.0 per update | S |
| Essential-goods supply | starvation bit `CStadt+0x40` bit 4; food-shortage counter `u8 CStadt+0x59`; scarce good id `u8 CStadt+0x5A`; stock `i32 CStadt+0x60[20]`; supply thresholds `i32 CStadt+0x1A0[20][4]` | S / H |
| Harbour cannons | count of built type-0xD0 buildings in `CStadt+0x9184` (Lua caps the count at 10) | S |
| Player gold | `i32 CPlayer+0x3C`; change it **only** via `0x60E570` | S |
| Fleet | `CPlayer+0x2C` convoy list → `CKonvoi+0x95` ships, `+0x84` cannons; ship table `0x703CD4` (battleship bit) | S |
| Player-controlled town | `CStadt+0x40` bit 22 (0x400000) "Your Own Town" (+ nation 5) | S |
| Vanilla taxes | **None.** No tax, tribute or toll mechanic exists | S (absence) |
| Unrest effects | Strike `0x624460` (halts production, ends by itself); ALQ `0x624790`; luxury-shortage bit 23 | S |
| Date / monthly tick | `0x702C14` time (256 ticks per day); cached `day 0x702C1C`, `month 0x702C1D`, `year 0x702C1A`, set at day rollover in `0x5D2790` | S |
| Message to the player | `CMessageSystem::PostMessage 0x5B82A0` (fixed IDs) or `AddText 0x5B7FF0` (free text) | S |

---

## 1. Object tables and handles [S]

Every object is reached through a **handle**:

- bits 0–15: slot index
- bits 16–20: type (1 = town, 3 = ship, 8 = captain, 9 = player)
- bits 21–31: 11-bit serial

Each pool keeps four globals: `base`, `links` (dword per slot: `u16 next`,
`u16 serial`), `u16 cap`, and `head`. The resolver checks
`idx < cap && ((h>>21) ^ links[idx].serial) & 0x7FF == 0`.

| Pool | base | links | cap (u16) | head | Element | Resolver (thiscall `ecx=&handle`; throws on a bad handle) |
|---|---|---|---|---|---|---|
| Towns `CStadt` | `0x702068` (ptr→`CStadt*[]`) | `0x70206C` | `0x702070` | `0x702074` | pointer | `0x5C2200` (`0x5C22B0` = Fetch variant) |
| Players `CPlayer` | `0x701EC0` (ptr→array) | `0x701EC4` | `0x701EC8` | `0x701ECC` | **inline, stride 0x94**; `+0x25` alive | `0x5C29E0` |
| Convoys `CKonvoi` | `0x701EE8` (ptr→`CKonvoi*[]`) | `0x701EEC` | `0x701EF0` | `0x701EF4` | pointer | `0x5C2360` |
| Ships | `0x703CD4` (ptr→array) | `0x703CD8` | `0x703CDC` | `0x703CE0` | **inline, stride 0x28**; `+0x20` bit 0 valid | `0x5C2520` |

**Town walk**, as used by Lua `Global_GetFirstTown` 0x421FD0 and
`GetNextTown` 0x422030 [S]:

```
4220B2 mov ecx,[0x70206c] ; 4220B8 mov ax,[ecx+eax*4]   ; next = links[idx].lo
4220C4 mov eax,[0x702068] ; 4220C9 mov eax,[eax+edx*4]  ; CStadt*
```

The idiom is: `idx = head; while (idx < cap && (t = towns[idx])) { …; idx = links[idx].next; }`.
`0x428B3F..0x428C71` (`Global_GetSupplyDegree`) walks the towns the same way.

**Town handle from an object**: `CStadtLager` (at `CStadt+0x38`) has vtable
slot 0 = `GetHandle(out*)` (`0x5D28E0`-style `call [edx]`, e.g. 0x624470).

---

## 2. Towns

`CStadt* t`; the economy sub-object is `CStadtLager* L = t+0x38`. Lua getters
resolve the handle with `0x5C2200`, then `add eax,0x38` and read `L+off`.

### 2.1 Fields

| CStadt off | L off | Type | Meaning | Evidence |
|---|---|---|---|---|
| +0x40 | +0x08 | u32 flags | bit 1 gold find; **bit 3 plague**; **bit 4 starvation**; bit 9 / 13 / 7 = ELQ modifiers; **bit 22 player town**; **bit 23 luxury shortage**; bit 24 (cleared by town event 7); **bit 25 strike** | [S] `Town_IsStarvation` 0x42B853 `mov eax,[eax+8]; shr eax,4; and 1`. `Town_IsPlayerTown` 0x427453 `shr eax,0x16`. `Town_IsStrike` 0x42BA16 `and eax,0x2000000`. `Town_SetLuxuryShortage` 0x4229A3 `or ecx,0x800000`. Citizen-comment UI 0x5152AA `shr edx,3` → `ID_STADT_BUERGER_SEUCHE`, 0x51534C `shr ecx,4` → `…_HUNGERSNOT`, 0x5153DD → `…_GOLDFUND` |
| +0x44 | +0x0C | u32 flags | bit 0 governor/viceroy seat (`Town_IsGovernorTown` 0x423113 `mov eax,[eax+0xc]; and eax,1`); bit 1 treasure fleet in town (UI 0x51546D); bit 15 hostile (`hostility_map.md`) | S |
| +0x54 | +0x1C | i16 | **ALQ**, 8.8 fixed point. Lua returns `ALQ * 0.00390625` | [S] 0x427315 `movsx eax,word [eax+0x1c]`; 0x427324 `fmul [0x682e80]` (= 1/256) |
| +0x56 | +0x1E | i16 | **ELQ** (target LQ), 8.8 | [S] 0x428125 `movsx eax,word [eax+0x1e]` |
| +0x58 | +0x20 | u8 | **Wealth level 0..7** (`Town_GetWealth`) | [S] 0x429383 `movzx eax,byte [eax+0x20]` |
| +0x59 | +0x21 | u8 | Food-shortage counter, 0..25 | [S] 0x6250B6 `inc byte [eax+0x21]`; 0x62531B `mov byte [esi+0x21],0x19` |
| +0x5A | +0x22 | u8 | Scarce good id (≥ 20 means none) | [S] UI 0x51578E `cmp byte [ebp+0x5a],0x14` → `ID_STADT_BUERGER_WAREKNAPP` + good name, else `…_ALLESVORHANDEN` |
| +0x60 | +0x28 | i32[20] | **Stock** per good, raw units. Raw / `[0x6E4364]` (= 19200) = barrels (Lua `GetGoodsAmount`) | [S] `0x5CACA0`: `mov eax,[ecx+eax*4]`; `0x5CAA30`: `idiv [0x6E4364]` |
| +0xB0 | +0x78 | i32[20] | Daily industrial demand per good (store+0x50) | [S] `0x5CAB90` `mov eax,[ecx+eax*4+0x50]`. Meaning [H] |
| +0x1A0 | +0x168 | i32[20][4] | **Supply thresholds ("x-marks")** per good, ascending, raw units. `Global_GetSupplyDegree` maps stock to a level 0..4 | [S] `Town_GetXAmount` 0x422409 `lea eax,[edx+eax+0x168]` (edx = good*16), `[eax+xmark*4]`; 0x428BF5 `lea ecx,[ebp+0x1a]; shl ecx,4` |
| +0x38A | +0x352 | u16 | **Population (total)** | [S] `Town_GetPopulation` 0x421DD3 `movzx eax,word [eax+0x352]` |
| +0x38C | +0x354 | u16 | Can-produce bitmask (bit = good) | [S] `Town_CanProduce` 0x429442 |
| +0x38E | +0x356 | u16 | **Soldiers (garrison)** | [S] `Town_GetWorkers` 0x4273AE: `pop − [+0x38E]`. Max garrison `0x5C4A90` = `((pop−sold)/30)*10 − sold − [+0x91C8]/1000`. `0x5C8870` decrements +0x356 and +0x352 together [H: soldiers] |
| +0x390 / +0x391 | +0x358 / +0x359 | u8 | Nation / display nation | see the private feasibility study |
| +0x9184 | — | ptr | Building array, stride 0x14 (cap u16 `+0x918C`, head u16 `+0x9190`, next = `0x416CC0` thiscall `ecx=t+0x38`, arg entry). Entry `+0x10 & 0xF8 == 0xD0` and `+0x11` bit 7 → **harbour cannon** | [S] `Town_GetHarbourCannons` 0x4270B0..0x4270C7 (stops at 10) |
| +0x91C8 | — | object | Soldier-order / palace sub-object (`+0` = ordered soldiers ×1000) | [S] 0x5C4AC0; meaning [H] |

**Goods ids** [S] (Lua constants at 0x43D67D..): 0 WEIZEN, 1 FRUCHT, 2 HOLZ,
3 LEHMZIEGEL, 4 MAIS, 5 ZUCKER, 6 BAUMWOLLE, 7 HANF, 8 FLEISCH, 9 KLEIDUNG,
10 SEILE, 11 RUM, 12 KAFFEE, 13 KAKAO, 14 FARBEN, 15 TABAK, 16 GEWUERZE,
17 WEIN, 18 WERKZEUG, 19 SIEDLER (settlers). Per-capita consumption is in
`arcs/Data/waren.ini` `[Warenbedarf]`.

### 2.2 How vanilla computes LQ (input for the loyalty model) [S]

`CStadtLager::UpdateLQ` is `0x624FA0` (thiscall, ret 4).

- **ELQ** sums 5 goods groups (goods 0–18). Each good contributes up to 6.0 if
  its stock covers `(industrial demand + citizen consumption 0x5C89E0) × [0x6E413C]`
  (pro rata below that). Each group is capped at 18 (`0x625105 mov eax,0x12`).
- Towns with fewer than 800 civilians get up to +20 (`0x625159 cmp edx,0x320`).
- Flag modifiers: bit 13 +5, bit 7 −40, bit 3 (plague) caps ELQ at 60.
- The result is `ELQ → +0x1E` (0x625204).
- **ALQ** then steps ±1.0 toward ELQ (`0x625213 add eax,0x100` /
  `0x62522A add eax,-0x100`), clamped at 0.
- ALQ is capped by population: <2000 → 70, <4000 → 80, <6000 → 90
  (0x62523A..0x62527F).
- `0x6242E0` (ret 4, arg pop) then sets the wealth level: ALQ ≤20 → 0,
  ≤40 → 1, ≤60 → 2/3, ≤70 → 4; above that 5/6/7 by pop ≥2000/4000/6000
  and ALQ >80/90.
- **Starvation**: a missing staple (goods **0, 1, 4, 8** = wheat, fruit,
  maize, meat; `0x6250A3..0x6250B6`) increments `+0x21`.
  - Counter ≤ 2: clears bit 4.
  - Counter > 19 and not yet starving: `0x624E10(1)` sets starvation and posts
    message **0x1D `ID_MSG_STARVATION`** (`0x6253DF push 0x1d; call 0x5B82A0`).
- So **"supply of essential goods" = the native staple set {0,1,4,8}, plus
  bit 4, plus `+0x21`.**

### 2.3 Engine calls (all thiscall `ecx = L = t+0x38` unless stated)

| VA | Signature | Effect | Level |
|---|---|---|---|
| `0x624460` | `void SetStrike(int durationTicks)` ret 4 | If bit 25 is clear: schedules town event type 5 at now+duration+1 via `0x5F17E0(handle, dur, 5)` and sets bit 25. Event type 5 clears the bit (`0x5F1782 and [esi+8],0xFDFFFFFF`). Strike makes the production step skip the town (`0x629E46 test [edx+0x40],0x2000000; jne`) | S; "production halt" [H] |
| (inline) | EndStrike | `L+8 &= ~0x2000000`. This is all Lua `Town_EndStrike` does (0x42B993) | S |
| (inline) | Set/End luxury shortage | `L+8 |= / &= ~0x800000` (0x4229A3 / 0x422A23). Read once at 0x5EFF26 [H: suppresses a supply spawn] | S |
| `0x624790` | `void AlterALQ(int16 delta_8_8)` ret 4 | `ALQ += delta`, clamped ≥0, then recomputes wealth (`0x6242E0`). Vanilla drifts ALQ back toward ELQ by 1.0 per update, so **re-apply penalties every tick** | S |
| `0x624390` | `void LQBonus(u8 kind)` | `+10 / +6 / +3` ALQ by kind 2/1/0; stores the date at `L+4` | S; "celebration" [H] |
| `0x5C89E0` | `int DailyConsumption(u8 good)` ret 4 | `pop × perCapita[0x702090+good*4] >> 16`, plus flag modifiers | S |
| `0x5CAA30` | `short GetAmount(u8 good)` ret 4, **ecx = t+0x60** | Stock / 19200 | S |
| `0x5C8870` | `void RemoveSoldiers(u16 n)` ret 4 | Subtracts n from soldiers and from population | S (code) / H (name) |
| `0x5F17E0` | `cdecl ScheduleTownEvent(townHandle, delayTicks, type)` | Town event; type switch at 0x5F17B8 (5 = end strike, 7 = clear bit 24) | S |

Lua alternatives, if the DLL drives a Lua state: `Town_SetStrike(t,dur)` 0x42B870,
`Town_AlterALQ(t,f)` 0x429110, `Town_RemoveCitizens` 0x42B600. Lua numbers
are int32 in this build (`lua_tonumber` result used as an int); there is a
separate `lua_tofloat`.

---

## 3. Player

### 3.1 Getting the human player [S]

`0x402940(out*)` copies `*(DWORD*)0x701ED0` into out, type-checked to 9
(`0x402945 push 0x701ed0`). **The human player handle = `*(DWORD*)0x701ED0`.**
This is the Lua `Global_GetPlayer` impl 0x41CDA0.

`CPlayer* = (BYTE*)*(DWORD*)0x701EC0 + (h & 0xFFFF)*0x94`, valid if
`byte +0x25 != 0` (`0x5C2A35..0x5C2A43`). Or call
`0x5C29E0` (thiscall `ecx=&handle`).

### 3.2 CPlayer fields

| Off | Type | Meaning | Evidence |
|---|---|---|---|
| +0x00 | u16 | 0 = human [H] | `hostility_map.md` |
| +0x0C | i32 | Company wealth (`Player_GetWealth`) | [S] 0x41D834 `mov ecx,[eax+0xc]` |
| +0x14 | u8[4] | Letter-of-marque bits | `hostility_map.md` |
| +0x25 | u8 | Alive / valid | S |
| +0x2C | ptr | **Convoy list** sentinel (STL list; node `{next, prev, u32 convoyHandle}`) | [S] `Player_GetConvoyList` 0x42D273 `mov eax,[eax+0x2c]; mov esi,[eax]`; loop until `esi == [player+0x2c]`; handle at `[node+8]` (0x42D29E) |
| +0x34 | i32 | Rank points (`0x5A8DA0` → rank via table 0x6A5020) | S |
| +0x3C | i32 | **Gold** | [S] `Player_GetGold` 0x42272C `mov edx,[eax+0x3c]` |
| +0x40 | u8 | Gold-counter enabled. **If 0, AlterGold is a no-op** | [S] 0x60E570 `mov al,[ecx+4]; test al,al; je ret` |
| +0x54 | i32[4] | Reputation 16.16 | `hostility_map.md` |

### 3.3 Changing gold

**`0x60E570`** `void __thiscall Counter_AddSaturating(Counter* ecx = player+0x3C, int amount, int ledgerCat)`, ret 8 [S].

- Clamps gold to ±2,000,000,000 (`0x60E59F mov esi,0x77359400`).
- Adds `amount` to the balance-sheet ledger
  `int ledger[13][11]` at `0x703758[(cat*11 + [0x703A10])*4]` (11-day ring;
  `0x60E730` rolls it daily).
- Lua `Player_AlterGold` 0x41D000 does this:

  ```
  push 9; … lua_tonumber; push eax; … call 0x5C29E0; add ecx,0x3c; call 0x60E570
  ```

  So **category 9 = scripts**.
- Other categories seen [S]: 2 = crew wages, 3 = captain salaries, 4 = ship
  upkeep (all from the daily player update 0x5D4F3E..0x5D4F64); 5/6/7 = trade;
  0xA; 0xC = dialogs and rewards.
- Use a free category for "taxes" only if the Bilanz UI tolerates it [H].
  Category 9 is safe.
- `0x60E5E0` (same signature) defers the add to the day roll (`0x703750`).
- **Never write `+0x3C` directly**: the ledger and the clamp would be skipped.
- Recompute wealth after large changes: Lua `Player_UpdateWealth` 0x41F160
  calls `0x5AA330(ecx=player, gold)` [H on the signature].

### 3.4 Fleet (founding eligibility)

- **Convoy fields** (CKonvoi*, via `0x5C2360`) [S]:
  - `+0x84` u16 total cannons (`Convoy_GetMaxCannons` 0x4260E3 `[eax+0x38]` after `add eax,0x4c`)
  - `+0x95` u8 ship count (0x423B23)
  - `+0xB0` owner player handle (`0x635FD0` reads `[esi+0x64]` with esi = conv+0x4C)
  - `+0xB4` type: 1 PLAYER, 2 AI_TRADER, 3 PIRATE, 4 MILITARY, 5 TRANSPORT, 6 TREASURE, 8 MISSION, 9 BUCCANEER (Lua constants at 0x43C82C)
  - `+0xB8` nation (5 = player)
- **Ship fields** (array `*0x703CD4`, stride 0x28) [S]:
  - `+0x14` owner handle (`0x60D0B0`)
  - `+0x18` convoy handle (`0x63E840`)
  - `+0x1C` type (0 PINASSE … 7 KORVETTE, 8 FREGATTE, 9 MILITAERKORVETTE, 0xA MILITAERFREGATTE, 0xB GALEONE, 0xE KRIEGSGALEONE, 0xF LINIENSCHIFF, 0x11 KANONENSCHIFF)
  - `+0x20` bit 0 valid, **bit 2 = battleship** (`Ship_IsBattleShip` 0x42579E `movzx eax,byte [eax+0x20]; shr eax,2; and 1`)
  - Max cannons = `u8 [0x703CBC + type]`. This table is in BSS and filled at runtime.
- **Recipe**:
  - ships = Σ `conv+0x95` over the player's convoy list;
  - armed warships = ship-table entries with valid, owner == human handle,
    battleship bit set (or `maxCannons(type) > 0`).
  - Adapt the spec's §3.1 gate to these numbers.
- **Vanilla daily fleet costs** already exist [S] (0x5D4EF0..0x5D4F64), per
  player convoy:
  - ship upkeep `u16 conv+0x8C` → cat 4;
  - `5 × u16 conv+0x86` (sailors [H]) unless `conv+0x90 == 3` → cat 2;
  - captain `0x5D5B70` → cat 3.

  Spec §9 upkeep should be **added on top** (or scale these), not duplicated.

### 3.5 "Player-controlled" town [S]

Use **bit 22 (`0x400000`) at `CStadt+0x40`**: vanilla's "Your Own Town"
(viceroy offer `0x61BDE0` → `0x624D30` sets `0x600000`), optionally together
with nation byte 5. Governor seat (`+0x44` bit 0) marks admin towns, not
player ones. Player buildings per town can be counted through the building
list (`Player_GetNumBuildings` 0x423480 / `Town_GetProductionCount` 0x423130),
but no single "owner" field was pinned [H].

---

## 4. Vanilla taxes and unrest [S]

- **No tax mechanic.**
  - No string matches `steuer` / `abgab` / `tribut` / `zoll` / `tax` in the
    exe (only `STEUERMANN` = helmsman, `Pr2_Icon_Steuerrad`) or in
    `missions.bin`.
  - No message id for it (table 0x6E4440, ids 0..0x46).
  - The governor "economy share" `0x5C8650` distributes goods, not gold.
  - Gold flows only through `0x60E570`.
  - **The DLL must invent `TownTaxableBase`.** Suggested inputs, all from
    real data: population or civilians (`+0x38A − +0x38E`), wealth level
    `+0x58`, ALQ.
- **Loyalty analogue = ALQ.** The UI already ties it to citizen mood, and
  message `0x40 ID_MSG_TOWN_LOW_LQ` exists.
- **Unrest effects available**:
  - Strike `0x624460`: timed; halts production [H].
  - Luxury-shortage bit 23.
  - ALQ penalty `0x624790`.
  - Soldier loss `0x5C8870`.
  - Lua `Town_RemoveCitizens` 0x42B600 (emigration).
- **Garrison effect on loyalty**: read `+0x38E` against the cap from
  `0x5C4A90` (civilians/3).

---

## 5. Date and monthly tick [S]

- `u32 g_time` at **`0x702C14`** (= World `0x702140` + 0xAD4). The low byte
  is the tick of the day (256 ticks per day); `t>>8` = day number. Lua
  `Global_GetWorldTime` 0x41CE50 returns it raw.
- `World::Tick` **`0x5D2790`** (thiscall `ecx=0x702140`, called by `0x57F0BA`)
  does `inc [edi+0xad4]`. When the low byte wraps to 0 (`0x5D27A6`):
  - runs the daily player update `0x5D4B40(dayOfWeek)` for each player;
  - then `0x5CDDC0(time, &day, &month, &year)` into
    **`u8 day 0x702C1C` (1..31), `u8 month 0x702C1D` (1..12), `u16 year 0x702C1A`**;
  - then `u16 dayOfYear 0x702C18` (0x5D2877).
- `0x5CDDC0` is `ret 0x10` and ignores ecx, so it can be called as
  `__stdcall(u32 t, u8* d, u8* m, u16* y)`: 365-day years, month table 0x6A4F00.
- **Monthly tick**: hook the day-boundary block (e.g. after `0x5D2855`) and
  fire when `month` changes. Alternatively poll `0x702C1D` from any per-frame
  hook. `0x57F0BA` is a clean 5-byte `call` site.

## 6. Messages to the player [S]

- `CMessageSystem* ms = **(CMessageSystem***)0x42F850()`. `0x42F850` is a lazy
  singleton (ctor `0x5B7FC0`, size 0x310) that returns `&ptr`.
- **`0x5B82A0` PostMessage(id, a, b, c)**, thiscall, ret 0x10. The id indexes
  the string table `0x6E4440`. Examples:
  - `(0x1D, townHandle, -1, -1)` starvation (0x6253DA..);
  - `(0xD/0xE, -1, nation, -1)` hostility.
  - There are no tax or strike ids; 0x40 `ID_MSG_TOWN_LOW_LQ` and 0x39
    `ID_MSG_TOWN_STARVATION` fit unrest.
- **`0x5B7FF0` AddText(const std::wstring* text, bool)**, thiscall, ret 8. It
  copies the string (STLport copy-ctor `[0x67FA10]`). This is what Lua
  `Global_AddMessage` 0x4306A0 uses after localising (`0x437E40`→`0x436980`).
  - For DLL free text: build the wstring with the STLport import `[0x67FA18]`
    (`basic_string<ushort>(const ushort*, const alloc&)`), call AddText, then
    destroy it with `[0x67FA04]`.
- Both are skipped unless `(*0x42D990())->flags & 0x10` (message option [H]).
- Letters and popups: Lua `Global_CreateLetter` 0x42FF80 / `Global_CreatePopup`
  0x42DAE0 / `Global_CreateLog` 0x42FAC0 (impls not traced [H]).

---

## 7. C header

```c
/* economy_pr2.h -- PR2.exe.unpacked.exe (sha 9c9250bc…). Verified static, see economy_data.md */
#include <stdint.h>
typedef uint32_t H;                                  /* handle: idx16|type5|serial11 */
#define G(t,a)   (*(t*)(a))
/* pools */
#define TOWN_PTRS   G(uint8_t**, 0x702068)           /* CStadt*[]            */
#define TOWN_LINKS  G(uint32_t*, 0x70206C)           /* lo16 = next          */
#define TOWN_CAP    G(uint16_t,  0x702070)
#define TOWN_HEAD   G(uint32_t,  0x702074)
#define PLR_BASE    G(uint8_t*,  0x701EC0)           /* inline, stride 0x94  */
#define PLR_STRIDE  0x94
#define HUMAN_H     G(H,         0x701ED0)
#define CONV_PTRS   G(uint8_t**, 0x701EE8)
#define SHIP_BASE   G(uint8_t*,  0x703CD4)           /* inline, stride 0x28  */
#define SHIP_CAP    G(uint16_t,  0x703CDC)
#define SHIP_MAXCAN ((uint8_t*)0x703CBC)             /* [type], runtime table */
/* world time */
#define W_TIME      G(uint32_t, 0x702C14)            /* 256 ticks/day         */
#define W_DOY       G(uint16_t, 0x702C18)
#define W_YEAR      G(uint16_t, 0x702C1A)
#define W_DAY       G(uint8_t,  0x702C1C)            /* 1..31                 */
#define W_MONTH     G(uint8_t,  0x702C1D)            /* 1..12                 */
/* CStadt offsets (L = t+0x38) */
enum { T_LAGER=0x38, T_FLAGS=0x40, T_FLAGS2=0x44, T_ALQ=0x54, T_ELQ=0x56,
       T_WEALTH=0x58, T_FOODMISS=0x59, T_SCARCE=0x5A, T_STOCK=0x60,
       T_XMARK=0x1A0, T_POP=0x38A, T_CANPROD=0x38C, T_SOLDIERS=0x38E,
       T_NATION=0x390, T_DISPNAT=0x391, T_BLD_ARR=0x9184, T_BLD_CAP=0x918C,
       T_BLD_HEAD=0x9190 };
enum { TF_GOLD=1u<<1, TF_PLAGUE=1u<<3, TF_STARVE=1u<<4, TF_PLAYERTOWN=1u<<22,
       TF_LUXSHORT=1u<<23, TF_STRIKE=1u<<25, TF2_GOVSEAT=1u<<0 };
#define RAW_PER_BARREL G(int32_t, 0x6E4364)          /* 19200 */
/* CPlayer offsets */
enum { P_WEALTH=0x0C, P_ALIVE=0x25, P_CONVLIST=0x2C, P_RANKPTS=0x34,
       P_GOLD=0x3C, P_GOLD_EN=0x40, P_REP=0x54 };
/* CKonvoi offsets */
enum { K_CANNONS=0x84, K_NSHIPS=0x95, K_OWNER=0xB0, K_TYPE=0xB4, K_NATION=0xB8 };
/* ship (stride 0x28) */
enum { S_OWNER=0x14, S_CONVOY=0x18, S_TYPE=0x1C, S_FLAGS=0x20 }; /* flags: 1 valid, 4 battleship */
/* engine functions (thiscall emulated as fastcall with dummy edx) */
typedef void (__fastcall *AddGold_t)(void* ctr /*player+0x3C*/, void*, int amount, int cat);
#define PR2_AddGold        ((AddGold_t)0x60E570)     /* ret 8; cat 9 = scripts */
typedef void (__fastcall *I1_t)(void* L, void*, int);
#define PR2_SetStrike      ((I1_t)0x624460)          /* L=t+0x38, dur in ticks */
#define PR2_AlterALQ       ((I1_t)0x624790)          /* arg = int16 delta*256  */
#define PR2_RemoveSoldiers ((I1_t)0x5C8870)
typedef int (__fastcall *I1r_t)(void* L, void*, int);
#define PR2_DailyConsumption ((I1r_t)0x5C89E0)       /* (u8 good)              */
typedef void* (__fastcall *Res_t)(H* h, void*);
#define PR2_TownFromH      ((Res_t)0x5C2200)         /* throws if invalid      */
#define PR2_PlayerFromH    ((Res_t)0x5C29E0)
#define PR2_ConvoyFromH    ((Res_t)0x5C2360)
typedef void (__stdcall *Date_t)(uint32_t t, uint8_t* d, uint8_t* m, uint16_t* y);
#define PR2_DecomposeDate  ((Date_t)0x5CDDC0)
typedef void** (__cdecl *MsgSys_t)(void);
#define PR2_MsgSys         ((MsgSys_t)0x42F850)
typedef void (__fastcall *Post_t)(void* ms, void*, int id, int a, int b, int c);
#define PR2_PostMessage    ((Post_t)0x5B82A0)        /* ret 0x10 */
typedef void (__fastcall *AddText_t)(void* ms, void*, const void* wstr, int flag);
#define PR2_AddText        ((AddText_t)0x5B7FF0)     /* ret 8; STLport wstring* */
/* hooks: World::Tick 0x5D2790 (called @0x57F0BA); day rollover @0x5D27AC */
```

Helpers: `inline int civilians(uint8_t* t){ return G(uint16_t,t+T_POP) - G(uint16_t,t+T_SOLDIERS); }`.
To post an unrest message: `PR2_PostMessage(*PR2_MsgSys(), 0, 0x40, townH, -1, -1)`.
The argument shape is the one starvation uses [H for 0x40 specifically].

## 8. Open points [H]

- The meaning of `+0xB0[20]` (industrial demand) and of `conv+0x86` (sailors) is inferred.
- Whether ledger categories ≥ 0xD crash the Bilanz page is untested. Use 9.
- Lua `Town_GetProductionCount` returns business counts per good, built from
  the building list. The per-building owner field is not pinned.
- Run every engine call on the main thread inside the sim tick.
