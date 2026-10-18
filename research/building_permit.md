# Building permit (Baugenehmigung / "Licence")

Where vanilla keeps the player's building permit, who grants it, who checks it, and how
PR2Nation gives it to the player in every town of the nation
(the automatic building permit change). PR2.exe 1.1.2.3, unpacked
(`PR2_target.exe`, sha 9c9250bc...). Byte facts: the private fact checker `BP-*`.

## 1. Storage: one licence record per town

| What | Where | Evidence |
|---|---|---|
| Licence record | `Lager+0x9174` = `CStadt+0x91AC` (`Lager = CStadt+0x38`) | STATIC: `0x6211B4 lea ecx,[esi+0x9174]` (grant), `0x410823`/`0x40FCA4` (sale) |
| `+0` i32 progress | `CStadt+0x91AC` | STATIC: grant/sale loops `0x61B6DF`, `0x61B9CF` (clamped to 0 .. required) |
| `+4` u8 **granted** | `CStadt+0x91B0` (`Lager+0x9178`) | STATIC: `0x61B614 mov byte [ebx+4],1` (grant), `0x61B906 mov byte [ecx+4],0` (sale) |

- The record is **on the town**, not on the player or the nation, and is not keyed by the
  town's current nation: a town that changes owner keeps it (`AddToNation 0x5C9DA0` and the
  annexation `0x5BC310` do not touch it, `conquest_transfer.md` §5). VERIFIED-STATIC.
- It belongs to the local (only) human player: every licence function first fetches the
  player handle `0x701ED0` (`0x402940`) from the player pool `0x701EC0` (0x94-byte slots).
- The required progress is `0x61B3D0`: `((rank*2 + 3) << 16) * (difficulty 0x701E68 + 1) >> 16`
  (`0x5A91D0` on the player, HYPOTHESIS: the rank). Progress is the town's reputation-like
  counter.
- The town is saved by vanilla with the record, so a granted byte survives save/load.

## 2. Who grants, who takes away

| Function | What | Callers |
|---|---|---|
| `0x6211A0` `Lager::GrantLicence(price)` | `0x61B570` on the record, then a "new licence" message (`ID_MSG_NEW_LICENCE`, type 0x2E) and chronicle 0x33 (`CChronicleNewLicence`) unless bit 22 of `Lager+8` | `0x4107E6` master builder purchase, `0x428F77` Lua `Player_SetLicence(t, true)`, `0x5A874C` start town at New Game (price 0), `0x61C8B8` town creation |
| `0x61B570` `Licence::Grant(price, nation)` | pays `price` from the player (`0x60E570`), sets `+4 = 1`, then walks all towns: granted towns get progress = required, the others progress += a delta proportional to the price (0 for price 0) | only `0x6211BA` |
| `0x61B770` `Licence::Sell(town, value)` | pays `value` to the player (`0x60E570`), sets `+4 = 0`, the same walk over all towns | `0x40FCAA` (Lua `Player_SetLicence(t, false)` via `0x40FC90`), `0x410823` master builder sale |

Nothing else writes the granted byte: no code stores to `+0x91B0` or `Lager+0x9178`
(displacement scan of `.text`), and the only callers of the sale are the two above
(`BP-sell-callers`). **Vanilla never takes a permit away by itself.** VERIFIED-STATIC.

## 3. Who reads it

| Site | What |
|---|---|
| `0x61B4C0` `Licence::Check` | `+4` set -> 3 (may build); else 2 if progress < required; else whether the player can pay (`0x61B330` price). `0x61B51E` (`BP-check`) |
| `0x410A2B` master builder | permit held -> "sell" page, sale value `0x61B1E0` (>= 2000) stored at dialog `+8` (`0x410A56`) |
| `0x44465F`, `0x4448B9`, `0x44496B` | master builder dialog states (welcome/licence/no licence texts `ID_NPC_BMASTER_*`) |
| `0x4A5119` | town info window (`STADT_INFO_800x600.screen`): if the player has an office in the town (`0x5ABBB0(town, player)` != 0, kept at `[esp+0x18]`, RUNTIME: 0 in Coro without property) **and** the permit, it lists *Your buildings*; otherwise *Your trading record* = the licence progress (`IDT_TOP_BAULIZENZ_FORTSCHRITT`, `0x4A6262`) |
| `0x4233F0` Lua `Player_HasLicence(town)` | returns `Lager+0x9178` (`BP-lua-has`) |
| `0x5B3AE3`, `0x5F6FED`, `0x614057` | other readers (AI/trader/building code); none writes |

There is no count of permits: holding many does not block buying one elsewhere (VERIFIED-STATIC:
no reader loops over the towns' granted bytes except the grant/sale walks). The master builder
also wants reputation level 2 with the town's power (`0x410A6A call 0x5D2C10 / cmp al,2`).

## 4. What PR2Nation does

- **Grant** = write `CStadt+0x91B0 = 1` (`towns.c eng_town_set_permit`), **take back** =
  write 0. The vanilla functions are not used: the grant would post a "new licence" message
  and chronicle entry for every member town on every load, and walk the progress of all
  towns; the sale pays the player. Buildings are never touched (vanilla's own sale leaves
  them standing as well).
- **When** (pure logic in `core.c`, unit tests PRM-01..05 in `tests/test_core.c`):
  - founding (`core_found`): the capital, `FX_PERMIT` after `FX_TOWN_TO_NATION`;
  - joining (`core_annex`, used by conquest, the fleet's war campaign, purchase and
    petition): the town, and the join message says "You may now build there.";
  - every load (`adapter_on_world_ready` -> `core_permit_sync`) and every day
    (`core_daily`): any member town without the permit gets it again (older saves, a
    permit given up at the master builder).
- **Remembering the earlier state:** `TownState.permit_before` records at joining whether
  the player already held the permit: `0xA1` had it, `0xA0` had none, `0` not recorded.
  For towns of an older save the first sync records the state found on load (the older mod
  never granted permits, so that is the state from before joining).
- **Leaving** (`core_lose_town`: secession, an enemy's conquest, release; also the daily
  "town reported under a power" check): `0xA0` and held -> taken back; `0xA1` and not held
  -> given back; the record is cleared.
- **No money tap:** a permit in a nation town is the nation's. The master builder would buy
  it back (`0x61B1E0`, at least 2,000 gold) and the daily sync would grant it again, so the
  hook at `0x410A53` (`mov ecx,[esi+0x14] / mov [ecx+8],eax`, 6 bytes) sets the sale value
  to 0 when the dialog's town (`[[esi+0x14]+4]`) has nation byte 5.

## 5. Save format

`permit_before` sits in what was the padding of `TownState` (offset 10 of 12;
`_Static_assert` in `core.c`), so `sizeof(NationState)`, the version (2) and the checksum
layout are unchanged:

- older saves: the padding was always 0 (every `TownState` is `memset` before use) ->
  "not recorded" -> recorded on the first load;
- saves from this version in an older mod: the byte is ignored; permits already granted
  stay granted (the older mod never takes them back);
- an unexpected value is read as "not recorded" (`core_deserialize`), never rejected.

## 6. Runtime checks (RUNTIME, 2026-10-17, `tools/permit_probe.py`: ALL PASS)

Every check reads the flag twice (Nation_GetTown and vanilla `Player_HasLicence`) and calls
the game's own build check `0x61B4C0` (ecx = `Lager+0x9174`; 3 = may build) through gamehost.

| Check | Result |
|---|---|
| `FNN 02`: Margarita's permit removed, nation founded there | permit 1, recorded "had none", build check 3, founding message "You may build there without a permit."; no other town changed |
| QuickSave + reload | still 1 / "had none" |
| Margarita released to Spain | permit 0, build check 0, player buildings 1 -> 1; no other town changed |
| `FNN 22`: Coro annexed by conquest | permit 1, build check 3, message "Coro (formerly Spain) has joined ... by conquest. You may now build there."; foreign towns without permit: build check 2 |
| Coro's permit removed (as when sold), 2 days run | granted again |
| Caracas (permit set beforehand) annexed, then both released | Caracas recorded "had", keeps the permit; Coro back to 0, build check 2 |
| `FNN 46` (made before this feature) loaded | "building permit granted in 5 member town(s)"; all members build check 3; Margarita (vanilla start-town permit) recorded "had" |
| a town of `FNN 46` released | permit 0 |

Town info screenshots: `_build/shots/permit_found_capital.png` (*Your buildings*),
`permit_found_released.png` (*Your trading record 166%*); `docs/permit_town_info.jpg`.
Not run in game: the master builder's sale page for a nation town (the hook at `0x410A53`
installs, `HOOK MasterBuilder permit value ... ok`; the zero value itself is untested).
