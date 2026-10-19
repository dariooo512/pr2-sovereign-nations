# Who owns a nation town, as the game shows it (the conquered-town info fix)

Static RE of `PR2_target.exe` (= the pinned `PR2.exe.unpacked.exe`, ImageBase 0x400000) with capstone; in-game check
with a private probe on the reporter's save (<the player's nation>). Facts `TI-*` in
`tools/check_facts.py`. Labels: [S] bytes read, [R] seen in game, [H] hypothesis.

## 0. Answer

*"Your relationship with Holland"* in the town info of Port-au-Prince is the **display byte** of the town
(`CStadt+0x391`, `CStadtLager+0x359`), read through patch **P07**. Every member town's display byte is the nation's
**host power**: `NationState.host_power`, set once at founding to the former power of the capital
(`core_found`: `host_power = town_prior_power(capital)`), and written into every town that joins the nation by
`eng_town_to_nation(town, g_state.host_power)` (`dll/towns.c`, `adapter.c` `FX_TOWN_TO_NATION`). In this save the
capital was a Dutch town, so **all** member towns have display byte 2 = Holland, whoever owned them before
(Port-au-Prince was English). The display byte is meant for art only (house sets, flagpoles, `research/flags.md`
6), but the dialog shows it as the town's owner.

There is no wrap-around or table overrun: the dialog asks "who owns this town" and gets the host power by design of
the display byte. The word *hostile* next to it is `CPlayer::ReputationTier(2)`, and that is **not** the player's
stored reputation with Holland, which is 93 in the save [R]: patch **P04** makes `GetReputation 0x5D2AC0` answer 0
for the human player while the nation is at war with that power (`player_rel`), so after Holland's declaration
(the Holland war fix; the player's screenshot is dated 4 Feb 1606, the save 16 Jan) the line showed the nation's war, not anything
the player did.

## 1. The town info dialog (CTownInfoDialog, Create `0x4A3610`) [S]

| VA | What |
|---|---|
| `0x4A3DD8` | `movzx ebp, byte [town+0x390]` - the section's nation; bit 22 (a vanilla player town) takes the display accessor `0x40FC70` instead. **P07 changes the displacement to `+0x391`**, so every town now takes the display byte. Kept in `ebp` and `[esp+0x10]` |
| `0x4A3E03..0x4A3E44` | heading: `0x4081B0(str, ebp)` = the nation's name (`ID_NATION_%d`), formatted into `IDPR_SID_VERH...` "Your relationship with %1", set into `SID_VerhaeltnisZu` = dialog `+0xC0` (`0x45B070`) |
| `0x4A3E58..0x4A3FD2` | the town type line `SID_StadtTyp` (`+0xC4`): `IDPR_SID_SITZ_VIZEKOENIG_%02d` / `GOUVERNEURSTADT` / `SPIELERSTADT` (bit 22, display) / `KOLONIE_%02d`, the last three with the **raw** byte: `..._05` does not exist, so the line was empty for a member town [R] |
| `0x4A3FEB..0x4A401F` | `CPlayer::ReputationTier 0x5D2C10(player, [esp+0x10])` & 3 - the player's reputation tier with that nation |
| `0x4A4030..0x4A4097` | the four mini flags `SID_Nat_00..03` (`+0x7C..+0x88`, CStatic): anim name `0x6E1A40[nation]` (`Pr2_Flagge_<N>.anim`, 4 entries; index 5 would be a string, which is why P07 exists), lit while `i <= tier` |
| `0x4A4099..0x4A40C5` | the relation word `0x407330(tier)` (`ID_GESINNUNG_x`: hostile ...) into `SID_Verhaeltniss` (`+0xCC`) |
| `0x4A40CB..0x4A41E0` | the two waving header flags `SID_NationsFlagge_l/r`: `0x6E12EC[(bit22 ? 5 : town+0x390) % 6]` - the **raw** byte, so slot 5 = `Run\7.bmp`, the nation's flag [R: the screenshot shows the nation's flag in the header and the Dutch flag below] |

Refresh `0x4A4B00` does not touch the section (no call of `0x4081B0`, `0x5D2C10`, `0x407330`, no use of `+0x7C..+0x88`,
`+0xC0`, `+0xCC`) [S], so the section is written once per opening.

## 2. Fix (dll/towninfo.c)

* Hook `towninfo.Section` at `0x4A40CB` (displaced `mov eax,[esp+0x1C]; mov ecx,[eax+0x40]`, 7 bytes): esi = the
  dialog, `[esp+0x1C]` = the town. For a member town (`core_officials_serve`: a founded nation, `town[t].member` and
  byte 5) it overwrites what vanilla just wrote:
  * `+0xC0` heading "Your nation";
  * `+0xCC` the loyalty word (`core_loyalty_label`, the Towns page's thresholds): unrest for 2 months = *in unrest*,
    unrest coming or loyalty < 20 = *restless (N)*, 20..49 *calm (N)*, 50+ *loyal (N)*; box widened to 160 px;
  * `+0x7C..+0x88` the four mini flags hidden, and a child screen `FNN_TINFO_NATION_800x600.screen`
    (art/make_towninfo.py: the town-list row's flag cell `LOS_Nation` + `LOS_NationFrame`, as `FNI_Flag` /
    `FNI_Frame`) created on the dialog's root (`+0x44`) at the last mini flag's place (188,345), its CDynamicImg
    loaded with the nation's flag (`flag_nation_path()`, `Run\7.bmp`) and fitted (`0x4C1540`);
  * `+0xC4` the town type line "Capital of <nation>" / "Town of <nation>" (`core_town_role`).
* Every other town (the powers', a vanilla bit-22 player town, a member town a power has retaken) runs vanilla
  untouched. Nothing is stored; the decision is made from the live state each time the dialog opens.
* Log: `TOWNINFO <town> (town N): nation section 'Your nation' / '<label>', '<role>'; flag shown (vanilla would show
  the display power D)`.

P07 stays: without it the mini flags would index the anim table with 5. The heading's name and the tier are the
host's only because of P07, and the hook replaces exactly those.

## 3. Other places that show a nation town's owner [S, R in 6]

Census: every byte load of a town's `+0x390/+0x391/+0x358/+0x359` in a function that builds UI (screen names,
`IDPR_`/`IDT_` strings), plus every caller of the nation-name helper `0x4081B0` (6 sites).

| Place | Code | What a member town got | State |
|---|---|---|---|
| Town info dialog, relationship section | `0x4A3DD8` (P07) | the host power (Holland) and the player's reputation with it | **fixed** (2) |
| Town info dialog, town type line | `0x4A3F8D` raw byte -> `IDPR_SID_KOLONIE_05` | empty | **fixed** (2) |
| Town info header flags | `0x4A40E1` raw byte | nation's flag | correct (flags.md 8) |
| Political map, town tooltip | `0x4D9C1B` raw byte -> `0x4081B0(5)`, intext icon `5+3 = INTEXT_HAUS` | **"Invalid"** as the owner's name, a house icon | **fixed**: `0x4081B0` hook (below) |
| Sea battle dialogs (SAD_/SBD_) | `0x4F6645` `0x4081B0(nation)`; flags `0x4F6484` raw -> slot 5 | "Invalid" for a nation-5 side | **fixed** by the same hook; flag correct |
| Nation-name helper `0x4081B0` | `0x4081CC cmp al,4 / jae` -> `L"Invalid"` (`0x680E84`) | - | hook `towninfo.NationName` at `0x40822F` (`call [0x67FA24]`, wstring =): nation 5 and a founded nation -> the nation's name; 0..3 and 4 unchanged |
| Town plate in the town view (STADT_INFO) | `0x4A602B` raw byte -> `0x5D2C10(5)` = tier 3; flags `0x4A639F` `table[5 % 6]` | four nation flags (full) | correct |
| Chronicle town list (STADT_ENTRY) | `0x4B7C76` `table[5 % 6]` | nation's flag | correct (no relation column) |
| Selection panel / town top bar | `0x485E84`, `0x4A639F` | nation's flag | correct (flags.md 8) |
| Officials (treasurer, commander, governor, building master) | NPC nation byte = display (`0x444B71`) | reputation checks with the host | fixed in the own-town officials change (`officials.c`, research/officials.md); their greetings name no nation [R] |
| Autotrade window intext icon | `0x459B9F` `nation+3` | house icon | cosmetic, unchanged |
| Help window / battle message | `0x508AA7`, `0x5035C5` raw byte -> `0x5D2D90` (rep >= 25) | true (100) | correct |
| Welcome voice / question texts | `0x57D0B6` (P03 -> display), `0x57CDE3` `_05` ids | host voice / missing id | unchanged (nation5_index_safety.md U5) |

## 4. Does the same lookup reach reputation or AI logic? (for the Holland war fix)

The display byte is not only read by the dialog. Vanilla treats it as "the owner" wherever code substitutes it for a
nation byte >= 4 [S]:

| Reader | Effect for a member town (display = host = Holland here) |
|---|---|
| Lua `Town_GetNation` `0x421D2E` | returns **2 (Holland)** for every member town [R]; any mission script that asks a member town's owner hears "Holland" |
| NPC nation byte (`0x4445AF`, `0x444B71`, tavern `0x4436C9..`, market `0x433574`, wedding `0x44952B`, commander `0x4179BB..`) | the town's NPCs are "Dutch" (the own-town officials change fixed their reputation checks only) |
| `0x5D5840` -> `AddReputation 0x5D45F0(display, ...)` (TI-addrep-display), from `0x5EF4A5` (a town tick method) and `0x5F983E` (an event) [H: rewards for helping the town] | reputation the player earns in a member town goes to **Holland** (raises it; it never lowers it) |
| Sortie target picker `0x63B3A0` (`0x63B625`, `0x63B644`), opted in for nation 5 by navy.c | a power's (and the nation's) sorties judge a member town by **Holland's** wars: a power at war with Holland may pick it, one at war with the nation but not with Holland may not |
| owner getters `0x5BE010` (objects with a home town at `+0x3C`), `0x60DD30` (ship/town by handle) | answer Holland [S]; callers not traced (virtual) |
| the mod's own monthly relation drift (`core.c`, `- (p == s->host_power ? 20 : 0)`) | the host power's relation score target is 20 lower every month: **Holland** in this save |

The reputation writers that **lower** reputation do not read the display byte: `SubReputation 0x5D4840` is called
from the harbour battle `0x5D4A50` (raw `+0x358`), the trade `0x5D5660` (raw `+0x390`, guarded `< 4`) and the
player's daily update `0x5D4B40` (loops over powers); `AlterReputation 0x5D2FB0` only from Lua. So the wrong
owner in the town info does not itself drive the Dutch reputation down. Nor does the dialog's *hostile*: the mod's
relation drift reads the stored reputation (`eng_player_reputation`, `CPlayer+0x54`, raw), not the P04-patched
`GetReputation`, so there is no loop from "at war" to "reputation 0" to "score down"; in the save the stored Dutch
reputation is 93. What links the Holland war fix and 13 is the host
power: the same `host_power = Holland` is the -20 in the relation drift, the owner of every member town in vanilla
AI/scripts, and the line in the dialog.

## 5. In-game (the reporter's save) [R]

a private probe, 2026-10-18, 11/11 checks pass (`_build/t13_results.md`):

* TI-00: the five member towns Tortuga, Port-au-Prince, Turk Islands (capital), Isabella, Santo Domingo all have
  nation byte 5 and display byte **2 (Holland)**; Lua `Town_GetNation` answers 2 for each. Stored reputation with
  England / France / Holland / Spain: 0 / 95 / 93 / 50.
* TI-01: each member town's dialog: heading *Your nation*, *Capital of* / *Town of <the player's nation>*, the nation's
  flag, *loyal (75)* (Turk Islands), *calm (44/39/39/43)* (the others) = the Towns page's values; no power's name.
* TI-02: Corpus Christi (Spain), New Orleans, Biloxi (viceroy seat), Pensacola (France): vanilla *Your
  relationship with Spain/France*, *neutral* / *friendly*, the vanilla town type line.
* TI-03: `0x4081B0(0..5)` = England, France, Holland, Spain, Invalid, <the player's nation>.
* TI-04 (screenshots): the Chronicle town list shows the nation's flag for Turk Islands; the town plate four nation
  flags; the governor and general of Turk Islands greet and serve the player with no nation named (the town's
  buildings fly the host's flag: art, flags.md 5.4); the political map shows the member towns with the player's
  warehouse icons, and the tooltip of Port-au-Prince / Tortuga reads *"Port-au-Prince (house icon) (<the player's nation>) 2.472"* (`--polmap-only` run; the town buttons are named `PKA_StadtDrawable_<town handle>`, type bits 1).
* Seen in passing (the Holland war fix): in the `--polmap-only` run, shortly after the load (still 16 Jan 1606, normal speed) and with
  nothing done, the ticker said *"Holland has declared war on <the player's nation>!"* and *"A Dutch war fleet has put
  to sea against your nation"*.
* TI-05: after QuickSave and a cold reload the capital's dialog shows the nation section again.

## 6. Tests

* A private probe (lock, backup, the save copied as "FNN T13"):
  TI-00 lookup source, TI-01 every member town's dialog, TI-02 power towns vanilla, TI-03 `0x4081B0(0..5)`, TI-04
  screenshots (political map tooltip, Chronicle town list, town plate, town hall tabs), TI-05 after QuickSave and
  reload, alive.
* Unit tests: `test_town_info_labels` (dll/tests/test_core.c).
