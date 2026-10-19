# Town officials in the nation's own towns (the own-town officials change)

Static RE of `PR2_target.exe` (1.1.2.3, ImageBase 0x400000) with capstone; runtime check in the test
install (scenario 52). Labels: [S] verified bytes, [R] observed in game, [H] hypothesis.

## Bug

In a member town the treasurer (*Schatzmeister*) and the commander (*Kommandant*, the General NPC) answered
"reputation with <power> too low" (`ID_NPC_TREASURER_BAD_REP` 6593, `ID_NPC_GENERAL_BAD_REP` 6488).

## Root cause

**Officials are NPC objects with their own nation byte.** NPC layout [S]: `+0` vtable, `+0x10` base data
(`+4` player handle, `+0xC` dialog state, `+0x12` nation, `+0x13` portrait id, `+0x14` town handle; getters
`0x43EC30` player, `0x43EC60` town, `0x43EDF0` nation, `0x43EE40` state, setter `0x43EE50`), `+0x14` class data.

**The nation byte is the town's display power.** The treasurer, commander and building master are single NPCs
kept by the world object `0x702140` (`+0xAE4` treasurer, `+0xAF8` commander, `+0xAE8` building master). The
town menu fetches them per town with `CStadt::GetTreasurer 0x5C4BB0` / `GetGeneral 0x5C4BD0` /
`GetBuildMaster 0x5C4B90` (callers `0x5108C3`, `0x5109DF`, `0x511F56`), which call vtable slot 11 (SetTown,
treasurer `0x444490`). SetTown and the factory create (`0x444A60`) set the nation with the generic
substitution `town+0x390 < 4 ? +0x390 : +0x391` (`0x4445AF..0x4445D6`, `0x444B71..0x444B86`) [S]. A member town
has byte 5 and display = the host power, so the officials ask for the host / former power.

**The check.** `CPlayer::ReputationTier 0x5D2C10` (thiscall player, nation; `rep/25` capped at 3) on top of
`CPlayer::Reputation 0x5D2AC0`. `0x5D2AC0` already returns **100 for nation 5** (`0x5D2AC4 cmp al,4 / ... cmp
al,5 / setne / dec / and 0x64`) [S], so every check that passes the raw town byte (shipyard `0x5C5750`,
`0x5C58F1`; town logic `0x61DD59`, `0x61DDF7`, `0x61DF80`, `0x61E086`; map/UI `0x4A603C`, `0x515528`,
`0x636167`, `0x636558`, `0x63D458`, `0x63D756`, `0x437863`) already treats a member town as full reputation.
Only the NPCs pass their own (display) nation.

Official call sites of `0x5D2C10` (NPC register at the call, class vtable) [S]:

| Return address | NPC | Class (vtable) | What |
|---|---|---|---|
| `0x410A6F` `0x410ABC` `0x410ADF` `0x410B74` | esi | building master, type 5 (`0x681AA8`) | enter `0x410970`: tier < 2 -> states 1/2 (`ID_NPC_BMASTER_NO_WELCOME_*`) |
| `0x41677E` | esi | commander, type 3 (`0x682440`) | slot 5 portrait/mood |
| `0x417469` | esi | commander | enter `0x4173A0`: tier < 2 -> state 1 = `GENERAL_BAD_REP` |
| `0x418C76` `0x419AA5` `0x41AC8F` `0x41ACB3` | edi | governor, type 1 (`0x682C50`) | builder `0x418B10`: welcome text by tier, `GOV_BAD_REP_HOSTILE`, dialog end |
| `0x41B921` `0x41B95A` `0x41BB56` `0x41BB8E` | esi | governor | answer `0x41B5E0`: mission / fee by tier |
| `0x44462C` | esi | treasurer, type 4 (`0x687860`) | slot 5 portrait/mood |
| `0x444871` | esi | treasurer | enter `0x4447C0`: tier < 2 -> state 1 = `TREASURER_BAD_REP` |

Not changed: the viceroy (`0x688A58`; viceroy seats never join the nation, `core_annex`), the governor's
daughter/wife (`0x689440`, personal, not an official), Lua `Player_GetReputation*` bindings `0x41D5CB` /
`0x41D63B` (only scenario scripts use them), power AI and diplomacy callers. Church, tavern and market NPCs
have no reputation check through `0x5D2C10`/`0x5D2AC0`. The building master's licence cap by rank
(`0x410B1A`, table `0x6A5026`) is not nation-specific and stays.

## Fix (dll/officials.c)

`hook_install_ret` at `0x5D2C10` (displaced `8B 44 24 04 50`). The handler reads the return address; for the
16 sites above it takes the NPC from esi/edi, checks its vtable, resolves its town handle (`+0x10 -> +0x14`),
and when `core_officials_serve()` says the town is a member with byte 5 it returns tier 3 (`ret 4`) without
running the function. Any other caller or town runs the original. Nothing is stored, so it holds after a
save and reload, and a town retaken by a power (byte 0..3) is vanilla at once.

## Test

`Nation_DevOfficial(town, kind)` (test install) runs the real path: the world getter (SetTown + nation) and the
NPC's slot 19 enter function, then returns the dialog state. Scenario 52 (`tools/scenarios.py --run --only 52`)
checks capital, a conquered, a bought and a petitioned town at reputation 0 with Spain, a Spanish town, and the
same after QuickSave + cold reload. Result [R] 2026-10-17: 33/33. Margarita, Coro, Caracas (bought) and Puerto
Cabello (petition) at reputation 0 with Spain: treasurer states 5/2 (offer / low value), commander 4, building
master 3/4 (never 1/2), while the vanilla tier with the NPC's nation (Spain) is 0; Maracaibo (Spanish) refuses
with state 1 for all three; identical after the reload. Fact checks OF-* in `tools/check_facts.py`.
