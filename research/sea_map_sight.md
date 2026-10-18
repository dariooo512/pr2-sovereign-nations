# Sea map, fog of war, minimap and "jump to convoy": what the national ships need

Date: 2026-10-17 (the national-ships-on-the-sea-map change). Exe =
`%USERPROFILE%\PR2-nation-env\PR2_target.exe` (unpacked 1.1.2.3, ImageBase 0x400000).
**[S]** = VERIFIED-STATIC (bytes/decompile read), **[R]** = RUNTIME (seen in game, `tools/sight_probe.py`),
**[H]** = HYPOTHESIS.

## TL;DR
* "National convoys" were **only a counter** (`NationState.national_convoys`, set by `API_CONVOYS` /
  `Nation_NationalConvoys`, capped by the player's ship count, 3,000 gold upkeep each). No ship was ever
  tied to it. [S: `api.c`, `core.c:1016`]
* The national **fleets** are real nation-5 military convoys (type 4/9) but the sea map never showed them:
  PR2 has a fog of war that only the **local player's** convoys lift. [S]
* Fix (`dll/sight.c`):
  * hook R in the visibility pass reveals around every national fleet at sea, exactly like the pass does
    for the player's convoys (same function, same radius 100);
  * hook M gives national ships their own minimap dot (cyan);
  * *Go to* uses the game's own jump-to-convoy (view controller `CenterOnConvoy`), leaving a town view first;
  * national convoys become **designated convoys of the player** (by handle, saved in a `PNCV` block).

## 1. Map objects and the visibility pass [S]

Every object on the sea map (convoy, town, sea marker) derives from one base class, vtable `0x6AC1C8`,
ctor `0x62C4A0`:

| Off | Meaning |
|---|---|
| +0x00 | vtable; slot +8 = `SetVisible`, +0xC = handle/this, +0x10 = "is a convoy" |
| +0x0E / +0x12 | x / y (int16, map units) |
| +0x14 / +0x18 | next / previous in **one list sorted by x** (unlink `0x62C4D0`) |
| +0x1C | visible now |
| +0x1D | visible in the previous pass |

**Visibility pass `0x62C3A0`** (callers `0x526395`, `0x57F0B0`, `0x402FCD`; `+0x20` re-entry guard):
1. walks the whole list both ways from the anchor: `+0x1D = +0x1C; +0x1C = 0` (`0x62C3C0..0x62C3E5`);
2. local player handle `0x402940` (= `*(u32*)0x701ED0`), player record (table `0x701EC0`, 0x94 bytes, active
   `+0x25`), iterates the player's convoys (list at record+0x2C, iterator `0x640120` / `0x63A3E0`);
3. for each convoy with byte **`+0x3B`** set: `RevealAround(convoy, 100)` **`0x62C760`** (`push 0x64` at
   `0x62C455`).

**`RevealAround 0x62C760`** (thiscall, `ret 4`, word radius): `SetVisible` on itself, then walks the x-list
both ways while `|dx| <= r` and calls `vfunc+8` on every node with `dx²+dy² <= r²`.

**Convoy `SetVisible` `0x5B2CA0`** (convoy vtable `0x6A56E4`, slot 2): `+0x1C = 1`; if `+0x1D == 0` (was
hidden) it emits the signal **`0x701EE4`** with the convoy handle. The view class connects
`0x518B80` to it (`0x51C39F`), which creates the sea-map marker (`CSeekarte::AddShip 0x5A31A0`,
`CSeekarteSchiff "Seekarte_Schiff_%08d"`). `CSeekarte` frame update `0x5A37F0` keeps a marker while the
convoy's `+0x1C` is set and removes it (`0x5A2360`) otherwise. `Convoy_IsVisible` (Lua, `0x425480`) reads
the same byte.

So a convoy that is not the local player's is shown only while one of the player's convoys is within 100
map units. The nation's fleets (nation byte 5, owner not the player) were never shown.

**Hook R** `0x62C3E7` (`8D 44 24 08 50`, `lea eax,[esp+8]; push eax`: after the reset loops, before the
player's convoys; the only jump in is `0x62C3D5 je 0x62C3E7`, to the hook's start): for every convoy of
type 4/9 with nation 5 and `+0x3B` set, `RevealAround(k, 100)`. Cost: one pool scan plus one x-window walk
per fleet, per pass.

Display only: the player still commands nothing but their own convoys; every attack or trade order in the
game is issued by an own convoy [S: the attack paths read the selected own convoy, `0x51DCD0`/`0x51992F`].

## 2. Minimap [S]

`CMinimap` (factory `0x588D10`, draw `0x587100`). Ship dots: vector at `+0xF0`, elements
`{x, y, flags, key}`; add `0x588E60`, set pos `0x586AA0`, kind `0x586C70`, flags `0x586C20`, remove
`0x586D70`. Draw colours: kind 1 blue (own), 2 black/red, 3 white/red (by the option at `+0x1C8`), 4 grey;
flag `0x1000` = pulsing yellow selection, **`0x2000` = cyan dot** (`0x587918`).

The interface keeps two minimaps: `+0xA0` is the sea map's (keys = convoy handles, type 2), `+0xA4` another
one (keys type 3, added in `0x47F180`). The sea map's minimap gets a dot in **`0x4803D0`** (edi = convoy,
kind in eax at `0x480504`): kind 1 if the owner is the local player, otherwise 2/3 from the relation
(`0x5D2C10`), 2 for pirates; the per-frame updater `0x482940` moves it and drops it when the convoy's `+0x1C`
is 0. **Hook M** `0x480504` (`0F BF 57 12 50`, `movsx edx,word [edi+0x12]; push eax`; the two jumps in,
`0x48049B` and `0x4804FD`, land on its start) sets `eax = 1 | 0x2000` for a national fleet or a national
convoy. [R: a first try at `0x47F2F1` (the other minimap) left the fleet's dot white.]

## 3. Jump to convoy [S]

* App singleton `*(u8**)0x6E58E4`; **view controller** `VC = *(app + 0xF0)`; current view `VC+0x6C`
  (Lua `Global_GetView` `0x42DBE0`; `VIEW_NONE 0, SEAMAP 1, TOWN 2, SEABATTLE 3, HARBOURBATTLE 4,
  TOWNBATTLE 5`, registered `0x43D4E4..`); sea map `CSeekarte* = VC+0x4C` (vtable `0x6A4078`);
  selected convoy `VC+0x7C` (`Global_GetSelectedConvoy 0x42DB10`).
* The game's own jump: pressing a convoy group key (1..9) twice, `0x51DCD0`: if `view == 2`
  **`SetView(1)` `0x51CAA0`** (thiscall, `ret 4`; closes all menus via `0x507600`), then
  **`CenterOnConvoy` `0x516E30`** (VC, convoy handle; `ret 4`) → `CSeekarte::CenterOn(x, y)` `0x59DDF0`
  (subtracts half the view `+0x84/+0x88`, clamps, `SetScroll 0x59DCC0` → `+0x7C/+0x80`).
* `CSeekarte::CenterOnConvoy 0x59E0E0` is the same on the map object (used by "follow convoy" with
  CapsLock, `0x59F160`).

## 4. National convoys: decision

The task asks for convoys "bought for the nation" that sail under AI orders. In this build that is not
possible without new engine work: autonomous traders (type 2) are owned by a town's local trader
(`CPlayer`, `Town_GetLocalTrader`) whose nation comes from the owner, and `CPlayer::SetNation(n >= 4)`
breaks the player record (`+0x24 = 0xFF`, research/conquest_transfer.md). The spec's §7.1 MVP is
"national designation on regular convoys", which is what the counter stood for.

So a national convoy is now **one of the player's own convoys, designated by handle**:
* *One more* designates the selected convoy (`Global_GetSelectedConvoy`) or the first free own convoy;
  *One fewer* / *Release* gives it back. The treasury pays its upkeep as before (`national_convoys` is kept
  equal to the number of live designations; a sold or sunk convoy drops out).
* While it serves it is renamed **"National convoy N"** (Lua `Convoy_SetName`; the name is id `+0x194` in
  the name table `0x702CB8`, kind 2 = `wchar[21]` at `+0x5CC`, count `+0x872`); release writes the old id
  back.
* Handles and old name ids are saved in a `PNCV` block after `PFLT`; an older save that only had the
  counter gets that many convoys designated on load.
* They stay the player's convoys: visible, and commanded as before (no new control and none removed).

**Switched off (the removal of national convoys, 18 Oct 2026).** A national convoy gave the player nothing
for its 3,000 a month, so the feature is out of this version, behind the compile-time switch `NATION_CONVOYS`
(`dll/core.h`, default 0). With 0: `natc_designate` refuses ("not part of this version"), `natc_save` writes no
`PNCV` block, `Nation_NationalConvoys` is a no-op returning 0, the upkeep has no convoy term, and
`core_deserialize` zeroes the old `national_convoys` counter. A loaded `PNCV` block is kept aside
(`g_old` in sight.c) and undone at world ready: the convoy's name id goes back to the saved old id and
`flag_convoy_changed` re-flags it (no longer national, so flag.c draws the player's logo); the counter-only
path (designate that many on load) is compiled out. To bring the feature back: build with
`-DNATION_CONVOYS=1` and restore the panel's *National convoys* card in `build_military()` (dll/panel.c):
it was deleted, the last commit that has it is `ebb808f9` (the last released build with the feature is
v2026.10.18-79816ea1); also restore scenarios 11/13/38 and feature-suite UI-07 from that commit.

## 5. Convoy fields used

| Off | Meaning |
|---|---|
| +0x3B | set while the convoy is out on the map (the pass reveals only around these) [S use; R meaning] |
| +0x90 | state (9 battle) |
| +0x95 | ships |
| +0x9C | current town handle (low word = town index) |
| +0xA8 | handle (pool handle = type 2 in bits 16..20) |
| +0xB0 | owner player handle (group +0x4C, +0x64) |
| +0xB4 / +0xB8 | type / nation |
| +0x194 | name id |
| +0x1B0 | destination town handle |

## 6. Runtime results [R] (`tools/sight_probe.py --fleets 9`, save `FNN 46`, 2026-10-18)

| Check | Result |
|---|---|
| SEE-01 fleet at sea is visible (+0x1C) with no own convoy within 200 units | PASS |
| SEE-02 A/B: reveal off: fleet and the Spanish ship beside it hidden (0 of 0); on: both shown (1 of 1), town labels around it too | PASS |
| SEE-03 Go to centres the sea map on the fleet (centre within 1 unit), again after it sailed on | PASS |
| SEE-04 national convoy designated (renamed "National convoy 1"), Go to centres on it | PASS |
| SEE-05 Ctrl+Shift+N path (`Nation_DevCycle`) visits both national ships | PASS |
| SEE-06 Navy tab: eye button on "Fleet 1" / "National convoy 1" cards; eye: panel closes, map centred | PASS |
| SEE-07 QuickSave, kill, reload: 1 national convoy restored (PNCV), Go to works for fleet and convoy | PASS |
| SEE-08 11 national ships (10 fleets at sea + 1 convoy): 746-797 fps with the reveal off vs on, no difference | PASS |
| SEE-09 cyan minimap dot for the national fleet | PASS |

Notes: `CenterOnConvoy` puts the ship in the upper half of the visible sea (vanilla behaviour of the
convoy-key jump). A player convoy designated while already visible keeps its blue dot until it next
reappears (the dot kind is set when the dot is created). The sea-map ship badge uses vanilla's nation-5
icon path (`0x5966C0`: nation 5 → `Run\0.bmp`); sight.c sets no flag image itself.
