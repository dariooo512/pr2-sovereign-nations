# Nation-5 index safety (option C)

Static scan of `reverse-engineering/_re/PR2.exe.unpacked.exe` (pinned build, ImageBase
0x400000). Question: once a town's nation byte (`CStadt+0x390` = `CStadtLager+0x358`) is 5,
does any code use it as an array index without a bound that keeps it in range?
Nothing was run in-game. All VAs below are in this build.

**Short answer:** no code path corrupts global memory with a nation-5 town. But six load
sites use the raw town nation as an index into a 4-row table with no guard. Four of them turn
nation 5 into an **invalid ship type** (≥ 18), and one reads past a 12-byte stack array. The
game also has deliberate nation-5 handling ("-userflag-" flag, reputation 100, map widget
5→4). That supports reading 5 as the player (`SPIELER_NATION`) owner.

## Method

1. Linear disassembly of `.text` with capstone, resynchronised at the 4,511 known function
   starts from `reverse-engineering-v2/decomp/`. This gave 859,326 instructions.
2. Every byte load (`mov`/`movzx`/`movsx` into a register) from `[reg + 0x390]`,
   `[reg + 0x358]` or `[reg + 0x359]` was found. That is **185 sites**: 143 at 0x390, 27 at
   0x358, 15 at 0x359.
3. For each site the loaded register was followed forward for up to 45 instructions. The
   trace followed register copies and byte-to-dword stack round-trips
   (`mov [esp+X], cl; mov edx, [esp+X]; push edx`). It recorded:
   - each use as a memory index;
   - each `cmp` on the value;
   - each call that receives the value as an argument.
4. Each callee that received the value was read by hand to see whether it guards the value.
5. Guards earlier in the function were checked by hand. Three cases were confirmed by showing
   that no direct jump enters the guarded region from outside:
   - `0x5D4B40` region `0x5D4BBE..0x5D4CCF`;
   - `0x5EF7D0` region `0x5EF989..0x5F01C3`;
   - `0x5F4520` region `0x5F455B..0x5F4591`.
6. Table-centric pass: every code reference to the known per-nation tables was checked:
   - `0x6E12EC` flags;
   - `0x6AC4AC`/`0x6AC4B4` military ship types;
   - `0x6A5158`/`0x6A5168`/`0x6A5174` per-nation ship-type rows;
   - `0x6A6EF4`/`0x6A6EFC`;
   - `0x6E41E0` names;
   - `0x6AAFDC` peace pairs;
   - the `CEventNationStatistic` arrays.

Scripts are in the session scratchpad (`agent_tables/scan.py`, `analyze.py`, `classify.py`,
`facts.py`). `facts.py` re-verifies every fact below: **50/50 PASS**.

Limits:
- Only byte loads at these three displacements were scanned. Copies of the nation into other
  objects were followed only where they were found (`+0x24` event objects, convoy `+0xB8`).
- Virtual calls were not resolved. Two sites stay *not traced*.
- Linear sweep can mis-decode data in `.text`. All the sites listed here were re-decoded on
  their own and checked.

## Counts (185 byte-load sites)

| Class | Count | Meaning |
|---|---|---|
| GUARDED | 106 | Bounded by `cmp x,4` before the index: immediate, dominating, or inside the callee (`0x43EF20`, `0x4081B0`, `0x417DC0`, `0x5D2C10`→`0x5D2AC0`, `0x5D2CC0`, `0x5D2D90`, `0x5D45F0`, `0x5D4840`, `0x5D33B0`, `0x637050`, `0x5D83C0` case 5 …) |
| GUARDED-DISPLAY | 14 | Loads of the display nation `+0x359`, only reached after `nation >= 4`. The value is 0..3 for a force-path town |
| NO-INDEX | 40 | Value is only compared, used as a bit mask (`shl 1,cl`), `&3`, serialised, or stored in an event field whose consumers are guarded |
| TEXT-ID | 4 | `sprintf("…_%02d", nation)` string-ID lookups. Nation 5 asks for a missing ID (`…_05`). Cosmetic |
| ADMITS-5 | 11 | Table has ≥ 6 entries, explicit `cmp x,5` handling, `% 6`, or a bound that admits 5 |
| UNGUARDED-BENIGN | 2 | Unguarded read that stays inside `.rdata` or the same object; only a flag or clamp changes |
| **UNGUARDED** | **6** | Unguarded index with a harmful result (below) |
| NOT-TRACED | 2 | `0x519E94`, `0x5C72B2`: the value goes into a virtual call that was not resolved |

## UNGUARDED sites (risk)

Background on the result: ship types are valid in the range 0..17. The type-init loop at
`0x559064` reads `cmp edi, 0x12` / `jl 0x558F70`, so it covers 18 types. Per-type stat
arrays are 20-byte BSS rows, e.g. byte table `0x703C0C`. `0x63F890` stores a new ship's type
at `ship+0x1C` and reads `byte [0x703C0C + type]` (`0x63F93C`). A type ≥ 18 therefore reads
another stat array and leaves a ship with an invalid type. Every later per-type lookup on that
ship (names table `0x69EE80` stride 8, sprites, stats) is out of range. Severity is
**high/unknown**: a crash or garbage ship is likely, and it needs E3.

### U1. Military convoy leader type, `CConvoyCreate::NewKonvoiMilitary(city)` — fn `0x635270`
- `0x6352B7  movzx eax, byte ptr [eax + 0x358]` (town via `0x5C2200`, `add eax,0x38`)
- `0x6352BE  mov cl, byte ptr [eax + 0x6ac4b4]` → `0x63FD50` → `0x63F890` (ship type)
- Table `0x6AC4B4` is `byte[4]` = `0F 0D 0C 0E`, followed by `00 F0`.
  - Nation 4 gives type 0 (valid).
  - **Nation 5 gives type 0xF0 = 240 (invalid).**
- The guarded getter `0x633550` returns 7 for nation ≥ 4. This inlined copy has no such
  check.
- Reached from Lua `Global_CreateMilitaryConvoy`. The binding is `0x426810` and calls this at
  `0x426A1F`. Its nation argument is guarded (`0x426848 cmp al, 4` / `jae 0x426A51`), but the
  city path uses the **town's** nation instead. The function is used by `arcs/lua/data/missions.bin`.

### U2. Military convoy escorts — fn `0x6348E0` (called from `0x635250`, `0x63540C`)
- `0x634902  mov al, byte ptr [eax + 0x358]` (nation of the town handle) → `[esp+0x14]`
- `0x63493B  movzx edi, byte ptr [esp + 0x14]`; `0x634942  mov al, byte ptr [edi + 0x6ac4b4]`.
  For nation 5 this is **0xF0**, the same failure as U1.
- `0x634A4D  movzx eax, byte ptr [edi + eax*4 + 0x6ac4ac]` uses `rand & 1`. Nation 5 reads
  `0x6AC4B1` = 0x09 or `0x6AC4B5` = 0x0D. Both are valid by luck.

### U3. Town periodic ship spawn — fn `0x5C6A40`, called **every tick** of vtable method `0x5EF7D0`
- `0x5C6A86  mov bl, byte ptr [edi + 0x390]`; `0x5C6A9C  mov al, byte ptr [eax + edx*8 + 0x6a5174]`
  (`rand & 7`)
- `0x5C6AB2  call 0x63cfc0` gets or creates a ship of that type in the town pool `edi+0x20`.
- `0x5EF7D0` calls it at `0x5EF931` and `0x5EF944` (×4), **before** its own guard at
  `0x5EF979  movzx eax, byte ptr [ebp + 0x390]` / `cmp eax, 4` / `jae 0x5F01C3`.
- Table `0x6A5174` is `byte[4][8]`. Rows 0..3 = `00 01 02 03 05 07 08 0A` and similar.
  - Row 4 (`0x6A5194`) = `64 64 64 64 4A 32 64 32`. All entries are invalid.
  - **Row 5 (`0x6A519C`) = `32 00 00 00 05 0D 10 15`. Types 50 and 21 are invalid, so 2 of
    the 8 random picks fail.**
- This is the **most likely live hazard**: it runs on its own timer for every town, with no
  script or player action needed.

### U4. Initial ships at town creation — fn `0x5A7F40`
- Only caller: `0x61BAE2` in `0x61BAB0`, which `CStadtCreate` (`0x61C320`) calls at `0x61C71F`.
- `0x5A80B0  mov bl, byte ptr [ebx + 0x390]` → `0x5A80C6  mov dl, byte ptr [eax + ecx*8 + 0x6a5174]`
- `0x5A822C  mov bl, byte ptr [edi + 0x390]` → `0x5A8242  mov al, byte ptr [eax + ecx*8 + 0x6a5174]`
  → `0x5A8252  movzx edx, byte ptr [edx + 0x6a4f50]` (indexed by ship type, stays in `.rdata`)
- This runs only at creation. It matters only if a town is created while already marked 5.
  The force-path stamp `0x61BDE0` is called later, from `0x61C8A8`. Flipping an existing town
  does not reach this code.

### U5. Welcome voice — inside fn `0x578C10` (town-entry/battle dialog)
- `0x57D0B6  mov al, byte ptr [eax + 0x358]`; `0x57D0C0  lea ecx, [esp + eax + 0x20]`;
  `0x57D0C4  lea edx, [ecx + eax*2]` → `sprintf(buf, "music/voice/Willkommen_%s_%02d.mp3", &abbr[n])`
  (`0x57D0CF push 0x6a0034` … `call [0x67f398]` = `A2dLib std_sprintf`)
- `abbr` is a local `char[4][3]` = {"En","Fr","Ho","Sp"}, copied from `.rdata 0x6A0058`
  (`53 70 00 00 48 6F 00 00 46 72 00 00 45 6E 00 00`) at `0x57D015..0x57D06E`.
- Nation 5 points 3 bytes past the end of the 12-byte array, into other stack locals. `%s`
  then reads stack garbage until the first NUL. The result is a wrong or missing mp3 name. A
  long run without a NUL could overflow the format buffer.
- Severity is low to medium. The same function also builds `ID_QST_WELCOME_INTRO_%02d` at
  `0x57CDE3` (TEXT-ID).

### U6. Patch idea (not applied)
For owned towns the non-force setter writes the same value to both bytes:
- `0x5C9E54  mov byte ptr [esi + 0x358], bl`
- `0x5C9E5A  mov byte ptr [esi + 0x359], bl`

So the display byte equals the nation for nations 0..3 and for 0xFF. Changing the
displacement from 0x390 to 0x391 (or 0x358 to 0x359) is therefore behaviour-neutral for
vanilla towns. For a nation-5 town it uses the host power's row instead.

| VA | Bytes now | Change |
|---|---|---|
| `0x5C6A86` | `8A 9F 90 03 00 00` | `+0x391` |
| `0x5A80B0` | `8A 9B 90 03 00 00` | `+0x391` |
| `0x5A822C` | `8A 9F 90 03 00 00` | `+0x391` |
| `0x6352B7` | `0F B6 80 58 03 00 00` | `+0x359` |
| `0x634902` | `8A 80 58 03 00 00` | `+0x359` |
| `0x57D0B6` | `8A 80 58 03 00 00` | `+0x359` |

Each of these is a one-byte patch.

## UNGUARDED-BENIGN

- **B1** — trade function `0x5D5660`: `0x5D57C4  movzx eax, byte ptr [esi + 0x390]` then
  `0x5D57D2  lea ecx, [ebx + eax*4 + 0x54]`.
  - This reads the player-side per-nation dword array at `this+0x54`. Index 5 reads
    `this+0x68`, which is inside the next array at `+0x64`.
  - The value is only used to clamp an amount.
  - The write path `0x5D4840` is guarded: `0x5D485E mov eax, [esp+0x10]` / `cmp al, 4` /
    `jae 0x5D49FE`.
- **B2** — `0x5C57C0`: `0x5C599F  movzx eax, byte ptr [edx + 0x390]`, then a loop of
  `0x5C59B3  cmp byte ptr [edi + eax + 0x6a5174], bl` for i < 8.
  - This is a read-only membership test in `.rdata` (row 5 = `0x6A519C..A3`).
  - Only a found/not-found flag changes.

## ADMITS-5 (deliberate or harmless)

- **Flag image table `0x6E12EC`, 6 entries:**
  - `nation00..03.aim`
  - `[4] nation_piraten.aim`
  - **`[5] "-userflag-"`** (pointer `0x6E1300` → `0x689970`)

  Users:
  - `0x4F6484`/`0x4F649B` (raw town nation, no guard, index 5 → "-userflag-")
  - `0x4FB815`
  - `0x485E84` (`movzx eax,[eax+0x390]; cdq; mov ecx,6; idiv ecx; mov edx,[edx*4+0x6e12ec]`)
  - `0x4A40E1`→`0x4A413C`/`0x4A41BD`
  - `0x4A639F`/`0x4A63B2`
  - `0x4B7C76`/`0x4B7C89` (all `% 6`)
  - convoy `+0xB8`: `0x4FAA8C mov al,[esi+0xb8]; cmp al,4; jb; cmp al,5; je` → table

  **The engine already draws a player flag for owner 5.**
- **Reputation:** `0x5D2AC0` returns `nation >= 4 ? (nation == 5 ? 100 : 0) : rep`. The test
  is `cmp al,5; setne cl; dec ecx; and ecx,0x64`.
  - The same logic is inlined at `0x5D35B7` and at `0x5D3466` (`0x5D33B0`).
  - `0x5D2C10` (rank = rep / 25, capped at 3) and the many callers that pass a town nation
    (13 sites) therefore treat a 5-town as "own nation".
- **Map widget:** `0x58DE60` maps 5 → 4 (`cmp al,5; jne; mov [ecx+0x190],4`). Its consumers
  are bounded at `0x5907BC cmp eax,5; jge` and `0x5907F5 cmp eax,4; jge`. A 5-town is drawn
  with the pirate/neutral icon. Reached from `0x515A14` via `0x59B670`.
- **Flag widget:** `0x5949C0` special-cases `0x5949F5 cmp al,5`; otherwise it guards `< 4`.
  The caller `0x463156 push 5` already uses owner 5.
- **Inline-text icon** `0x4066C0` (`cmp al,0x1a`) with `nation+3`: `0x459B9F`, `0x4D9C56`.
  Index 8 is `INTEXT_HAUS`, so a 5-town shows a house icon instead of a flag (cosmetic).
- **`0x5D8E70`:** bound is `cmp al,4; ja`, and its tables `0x6A6EF4`/`0x6A6EFC` have 5 rows.
  Nation 5 picks a random row 0..3. Called from `0x60DA67`.

## Other structures asked about

- **`CNation::rel[4]`:** only `0x5BA0A0` (IsAtWar) was seen indexing it. It is guarded, and
  `>= 4` means war [N1].
- **`CEventPeace` pair table `0x6AAFDC`** (`00 01 00 02 00 03 01 02 01 03 02 03`, 6 pairs):
  - schedule `0x5F4E80` guards both nations: `0x5F4E89 cmp cl,4; jae` and
    `0x5F4E96 cmp al,4; jae`;
  - `ChangeDate` `0x5F4F90` guards both: `0x5F4F98 cmp bl,4` and `0x5F4FA4 cmp [esp+0x18],4`;
  - `0x5F521A` and `0x5F56F1` walk the table in fixed loops.

  **Safe.** A player nation needs its own relations store anyway.
- **`CEventNationStatistic`:** the writer `0x5F4520` is guarded (`0x5F4550 mov cl,[eax+0x390];
  cmp cl,4; jae 0x5F4591`), so 5-towns are simply not counted. The getters
  `0x5F3F10`/`0x5F3F60`/`0x5F3FB0` take an unguarded nation argument but read inside the
  object. They are only called from the statistics UI `0x4BDD..`, with nations from the
  caller.
- **Convoy nation `+0x24`:** the setter `0x5A9DF0` writes only `< 4`, otherwise 0xFF
  (`0x5A9E28 movzx eax,bl; cmp eax,4; jae 0x5A9E5B` → `mov byte ptr [edi+0x24],0xff`).
  Military convoy `+0xB8` (inner `+0x6C`) is set by `0x637050` only when `< 4`
  (`0x63707A cmp eax,4; …; jae`). Convoys created *for* a 5-town therefore never carry 5.
  Player convoys do, by design (`0x4FAA8C`).
- **Display accessor** `0x40FC70`: `mov al,[ecx+0x358]; cmp al,4; jb; mov al,[ecx+0x359]; ret`.
  Most UI paths use it, which is why GUARDED dominates.
- **Soldier sprites (`0x5311C0`, again at `0x537F2B`):** these are preloads by filename
  (`lcr/musketenschuetze_<nation>.lcr`, `saebeltraeger_*`). They are not a nation-indexed
  pointer table. The runtime lookup was not traced.
- **Text IDs** (TEXT-ID class), all with only `_00.._03` in `arcd/scripts/global.h`:
  - `0x4A3E66` `IDPR_SID_SITZ_VIZEKOENIG_%02d`
  - `0x4A3EFA` `IDPR_SID_GOUVERNEURSTADT_%02d`
  - `0x4A3F8D` `IDPR_SID_KOLONIE_%02d`
  - `0x57CDE3` `ID_QST_WELCOME_INTRO_%02d`

  `ID_NATION_%d` users are guarded (`0x4081B0`, `0x5D868D`). Lookups go through
  `A2dLib g_pStringMgr`; the DLL exports `ReportMissingStrings`, which suggests a missing ID
  is tolerated (HYPOTHESIS).

## Save/load (bonus, relevant to H2)

- Save: `0x5C9883 mov cl,[ebp+0x358]; mov [eax],cl` and `0x5C989B` (display byte). Both
  bytes are written raw.
- Load: `0x5C9AF6 mov al,[edx]; mov [ebp+0x358],al`. There is **no validation**, so a 5
  survives. The display byte is read when the save version is ≥ 0x3F4
  (`0x5C9B02 cmp esi,0x3f4; …; jb 0x5C9B26`); older saves fall back to `nation & 3`.

## Facts ready for the fact checker (all verified PASS)

Format: `(id, va, [instructions])`. Each instruction string is
`f"{mnemonic} {op_str}".strip()`, the same as in `tools/check_facts.py`. So a bare `ret` is `"ret"`
and `cdq` is `"cdq"`.

```python
("X1-milconvoy-leader", 0x6352B7, ["movzx eax, byte ptr [eax + 0x358]", "mov cl, byte ptr [eax + 0x6ac4b4]"]),
("X1-milconvoy-bind",   0x426A1F, ["call 0x635270"]),
("X1-milconvoy-luaguard", 0x426848, ["cmp al, 4", "mov byte ptr [esp + 0x14], al", "jae 0x426a51"]),
("X1-shiptype-getter-guard", 0x633550, ["mov eax, dword ptr [esp + 4]", "cmp eax, 4", "jb 0x63355c", "mov al, 7", "ret"]),
("X2-escort-nation", 0x634902, ["mov al, byte ptr [eax + 0x358]"]),
("X2-escort-type",   0x63493B, ["movzx edi, byte ptr [esp + 0x14]", "xor eax, eax", "mov al, byte ptr [edi + 0x6ac4b4]"]),
("X2-escort-type2b", 0x634A4D, ["movzx eax, byte ptr [edi + eax*4 + 0x6ac4ac]"]),
("X3-township", 0x5C6A86, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                           "movzx edx, bl", "and eax, 7", "mov al, byte ptr [eax + edx*8 + 0x6a5174]"]),
("X3-township-call1", 0x5EF931, ["call 0x5c6a40"]),
("X3-township-call2", 0x5EF944, ["call 0x5c6a40"]),
("X3-later-guard",    0x5EF979, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4", "jae 0x5f01c3"]),
("X3-shipcreate",     0x5C6AB2, ["call 0x63cfc0"]),
("X4-create-ships-a", 0x5A80B0, ["mov bl, byte ptr [ebx + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                                 "movzx ecx, bl", "and eax, 7", "mov dl, byte ptr [eax + ecx*8 + 0x6a5174]"]),
("X4-create-ships-b", 0x5A822C, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                                 "movzx ecx, bl", "and eax, 7", "mov al, byte ptr [eax + ecx*8 + 0x6a5174]"]),
("X4-caller",  0x61BAE2, ["call 0x5a7f40"]),
("X4-caller2", 0x61C71F, ["call 0x61bab0"]),
("X5-welcome-voice",   0x57D0B6, ["mov al, byte ptr [eax + 0x358]", "movzx eax, al", "push edx",
                                  "lea ecx, [esp + eax + 0x20]", "lea edx, [ecx + eax*2]"]),
("X5-welcome-sprintf", 0x57D0CF, ["push 0x6a0034", "push eax", "call dword ptr [0x67f398]"]),
("X6-shiptype-store",  0x63F93C, ["movzx eax, byte ptr [ecx + 0x703c0c]"]),
("X6-shiptype-count",  0x559064, ["cmp edi, 0x12", "jl 0x558f70"]),
("B1-trade-read",        0x5D57C4, ["movzx eax, byte ptr [esi + 0x390]", "push 0x19", "lea edx, [esp + 0x30]",
                                    "push edx", "lea ecx, [ebx + eax*4 + 0x54]"]),
("B1-trade-write-guard", 0x5D485E, ["mov eax, dword ptr [esp + 0x10]", "cmp al, 4", "jae 0x5d49fe"]),
("B2-membership-cmp",    0x5C59B3, ["cmp byte ptr [edi + eax + 0x6a5174], bl"]),
("A1-flag-town-idx",  0x4F649B, ["mov edx, dword ptr [eax*4 + 0x6e12ec]"]),
("A1-flag-mod6",      0x485E84, ["movzx eax, byte ptr [eax + 0x390]", "cdq", "mov ecx, 6", "idiv ecx",
                                 "mov edx, dword ptr [edx*4 + 0x6e12ec]"]),
("A1-convoy-flag-5",  0x4FAA8C, ["mov al, byte ptr [esi + 0xb8]", "cmp al, 4", "jb 0x4fab6d", "cmp al, 5", "je 0x4fab6d"]),
("A2-intext",         0x459B9F, ["mov al, byte ptr [esi + 0x390]", "add al, 3", "cmp al, 0x1a", "jae 0x459bba"]),
("A3-rep-5",          0x5D2AC0, ["mov al, byte ptr [esp + 4]", "cmp al, 4", "jb 0x5d2ad8", "xor ecx, ecx",
                                 "cmp al, 5", "setne cl", "dec ecx", "and ecx, 0x64"]),
("A4-mapwidget-5",    0x58DE60, ["mov al, byte ptr [esp + 4]", "cmp al, 5", "jne 0x58de75", "mov dword ptr [ecx + 0x190], 4"]),
("A5-flagwidget-5",   0x5949EF, ["mov al, byte ptr [esi + 0xb0]", "cmp al, 5"]),
("A5-flagwidget-push5", 0x463156, ["push 5"]),
("A6-range-ja",       0x5D8E8E, ["ja 0x5d8ea4", "mov ebx, dword ptr [esp + 0x1b8]", "movzx eax, al",
                                 "mov cl, byte ptr [eax + 0x6a6ef4]"]),
("G1-peace-changedate", 0x5F4F94, ["mov bl, byte ptr [esp + 0x10]", "cmp bl, 4", "push esi", "mov esi, ecx",
                                   "jae 0x5f502e", "cmp byte ptr [esp + 0x18], 4", "jae 0x5f502e"]),
("G1-peace-schedule",   0x5F4E89, ["cmp cl, 4", "jae 0x5f4f87", "mov al, byte ptr [esp + 0x14]", "cmp al, 4", "jae 0x5f4f87"]),
("G2-stats-writer",     0x5F4550, ["mov cl, byte ptr [eax + 0x390]", "cmp cl, 4", "jae 0x5f4591"]),
("G3-display-accessor", 0x40FC70, ["mov al, byte ptr [ecx + 0x358]", "cmp al, 4", "jb 0x40fc80",
                                   "mov al, byte ptr [ecx + 0x359]", "ret"]),
("G4-convoy-setnation", 0x63707A, ["cmp eax, 4", "mov dword ptr [esi + 0x64], 0xffffffff", "jae 0x637137"]),
("S1-save-nation",  0x5C9883, ["mov cl, byte ptr [ebp + 0x358]", "mov byte ptr [eax], cl"]),
("S1-load-nation",  0x5C9AF6, ["mov al, byte ptr [edx]", "mov byte ptr [ebp + 0x358], al"]),
("S1-load-display", 0x5C9B02, ["cmp esi, 0x3f4", "mov dword ptr [ebx + 4], ecx", "jb 0x5c9b26"]),
```

Data facts (raw bytes; also PASS):

| ID | Address | Bytes | Meaning |
|---|---|---|---|
| D1 | `0x6AC4B4` | `0F 0D 0C 0E 00 F00000` | Index 5 = 0xF0 |
| D2 | `0x6A5174` | `00 01 02 03 05 07 08 0A` | Row 0 |
| D2 | `0x6A5194` | `64 64 64 64 4A 32 64 32 32 00 00 00 05 0D 10 15` | Rows 4 and 5 |
| D3 | `0x6A0058` | `"Sp\0\0Ho\0\0Fr\0\0En\0\0"` | Welcome-voice nation abbreviations |
| — | `0x6E1300` | pointer → `"-userflag-"` | Flag table entry 5 |

## Implications for option C / experiments

- E3 should watch the ship pool of the flipped town (`CStadt+0x20`; ship `+0x1C` = type)
  across several ticks of `0x5EF7D0`. U3 predicts that a ship with type 50 or 21 appears.
  The likely result is a crash or a garbage ship in the shipyard or market. Applying the
  one-byte displacement patches (U6) first should remove this.
- **H1 cross-check:** if vanilla really had live nation-5 colony towns, U3 would already hit
  them. Either those towns don't run `0x5EF7D0` before they are founded, or H1 is wrong.
  Worth confirming in E2.
- Several vanilla code paths already expect owner 5: the "-userflag-" flag, reputation 100,
  the map widget remap, and the flag widget. This supports option C's reading of 5 as
  "player-owned".
