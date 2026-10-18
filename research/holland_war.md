# Holland's war "for no reason" (the Holland war fix)

A player's report (the Holland war fix, build v2026.10.18-79816ea1): load the reporter's save, run at 100x, and within
seconds to two minutes Holland declares war on *<the player's nation>*. The player suspected the national fleets.
This note says what really happened, proven in the game, what changed, and what the freeze after the
save in the same log was.

Runtime facts come from a private probe on a copy of the reporter's save in the test install; static facts from `PR2_target.exe` (capstone).

## 1. The cause, from the game

The new log lines (section 3) on the first load of the save:

```
REL Holland: Peace, score -38 (drifts towards 0: reputation 90: +20, former sovereign of the capital -20),
    recognized 0, exhaustion 0, last treaty change day 585820 (today 586202), strategy Opportunistic, reputation 90
REL England: War, score -90 (drifts towards -40: reputation 30: -10, War -30), ...
REP Holland 90.29 -> 91.48: gains +1.39 (3), losses -0.00 (0), set/mod 0, daily update and rest -0.21
AI Holland (Opportunistic, day 586205): score -38 <= -20, strength ratio 76 < 150, 385 days since the last
    treaty change, 0 other wars, exhaustion 0, reputation 92: war chance 19, roll 6 -> WAR
REL Holland score -38 -> -48 (-10: it declared war on the nation)
MSG Holland has declared war on <the player's nation>!
```

- **Not the fleets, not the reputation.** The player's reputation with Holland was 90 and *rising*
  (trade). In the whole run no `REP ... SubReputation` line appeared: nothing the fleets, or anyone,
  did cost reputation with Holland. No sea battle had a national fleet on either side before the war
  (`BATTLE` lines: none). The fleets' raids all targeted England, the power at war.
- **Holland is the former sovereign of the capital.** The capital is Turk Islands, a Dutch governor
  seat. At founding (day 585820) the core set Holland's relation to -60 ("The Dutch crown condemns the
  secession"), and the monthly drift adds a permanent -20 for the former sovereign (`host_power`).
  So the relation recovers by +2 a month towards 0 and stood at -38 after 12.7 months.
- **The nation's war with England makes Holland an opportunist.** With the nation at war with another
  power and weaker (ratio 76 < 100), `core_ai_strategy` returns Opportunistic, whose war threshold is a
  relation of -20 (Commercial: -60). -38 is below it, the 180-day cooldown after the last treaty change
  was long over, so the next AI evaluation (every 7 days, three days after the load) rolled for war:
  chance 19, roll 6.
- **Why always the same, 35-40 s after a load.** The roll is deterministic (`roll100(day, power, 2)`),
  so every load of the same save reached the same evaluation day with the same result.
- **What the player saw.** Only the founding message, a year earlier, and then the declaration. The
  relation score was on the Diplomacy page, but nothing said that Holland was about to strike, or why.
  That was the bug: a war out of nowhere.

Suspect 2 of the task (the war with England spilling over): yes, but through the AI strategy, not through
an alliance or "their enemy is our enemy" (`core_declare_war` was not involved; Holland and England were
not at war with each other). Suspect 3 (something on load): no; the drift and the evaluation ran once per
game day as designed, the reputation was read correctly.

## 2. Can the fleets attack a power at peace? Yes, two ways (neither caused Holland's war)

A raid gives the fleet the vanilla MTask Circle (`0x5AD9F0`, `+0x1B8 = 2`) with a target nation
(`+0x1C0`). `ShouldAttack 0x5AF330` with a task attacks every convoy whose nation byte equals `+0x1C0`,
**whatever the diplomacy** (navy_operations.md 3.3). The task runs 20 days. So a raid begun in a war went
on after a ceasefire or peace: in the player's game England offered a ceasefire at every load while eight
fleets raided English shipping. Accepting it would have left them attacking English ships at peace.
The attack mask the fleets use without a task (`0x63C280` on `g_pc.rel` = `player_rel`) is built from
the nation's wars only, but only now and then (about every 256 ticks), and a game event can OR a power's
bit into it in between (`0x5F1BC0`, called by the patrol event type 0, vtable `0x6AAE70`, before the patrol
scan `0x5B6A50`).

And in practice: with the battle log in place, two of four runs of the player's save showed a national fleet
**starting** a battle (`NewSeaBattle` from the hunter `0x5AED30`, return `0x5AEE95`) against a power it was
at peace with:

```
BATTLE national warship 07E80041 (6 ships) attacks Spain trader 00A8008F (2 ships) near Isabella (day 586216; the nation is AT PEACE with Spain)
BATTLE national warship 07E80041 (2 ships) attacks France warship 006800CA (5 ships) near Isabella (day 586219, fleet task 2 against England; the nation is AT PEACE with France)
BATTLE national warship 07E80041 (5 ships) attacks player player convoy 07280012 (2 ships) near Grenada (day 586213; ... fleet mask 0091)
```

The last one is the player's own convoy, with a correct mask (0x91: English traders and warships,
pirates); the target came from the patrol scan, which for player ships (`+0xB8 == 5`) also accepts a
distance condition (military_combat.md table, `0x5B6B79..0x5B6BE3`). None of these cost reputation (no
`SubReputation`), and Spain and France are not Holland, so they did not cause the war; but they are the
"fleet attacking ships of a power you are at peace with" that the task forbids. The battles are not
deterministic (one run in two).

Battles the other way round (a power's trader or warship as the hunter, a national fleet as the target,
"Spain trader ... attacks national warship") are the power's decision and stay.

Reputation: a sea battle between AI convoys (CAutoBattle) touches no reputation (military_combat.md
2.4). The vanilla reputation losers are the player's own actions, all through `SubReputation 0x5D4840`:

| Return address | Caller | What the player did |
|---|---|---|
| `0x5D52BE` | `0x5D5170` (wrappers `0x5D5940/90/E0`, from the player's sea battle `0x609540`, `0x609D40`, `0x60A480`, `0x60A680`) | attacked a convoy of that power |
| `0x5D4AAA` | `0x5D4A50` (from the siege `0x5FFC00` and the harbour attack `0x6052E0`, on the attacker's owner) | attacked a town: -25 with its power (and with all others unless `0x5D2F70`) |
| `0x5D5808` | `0x5D5660` (trade, `0x5AB67A`.., `0x63836C`) | a trade in the power's town |

Gains go through `AddReputation 0x5D45F0` (trade, deliveries `0x5D5840`, the coast/harbour handlers
`0x5D4AC0`); `SetReputation 0x5D3B50` and the raw `0x5D2FB0` are used by dialogs and Lua only. The daily
update `0x5D4B40` drifts the reputation towards 50 (decay of at most a few tenths a day above it).

## 3. What changed

**Log (`dll/replog.c`, core trace).** PR2Nation.log now has:
- `REL <power>: ...` at every load / new game: status, score, the drift target with its terms, recognition,
  exhaustion, last treaty change, strategy, reputation.
- `REL <power> score a -> b (+d: cause)` for every change of a relation score in `core.c` (all
  `add_score` sites and the founding / declaration resets; the monthly drift lists its terms).
- `AI <power> (...)` for every war decision of a power at peace: the numbers, then WARNING, "warned n
  evaluation(s) ago, no war yet", or the roll and WAR / no war; and "the war warning lapses".
- `REP <power> -x by SubReputation (was y; cause) at <call site> <- <callers>` for every reputation loss
  of the player, `REP <power> +d by the nation (cause)` for the mod's own changes (`FX_REPUTATION` now
  carries its cause), and once a day per power whose whole-number reputation changed: the sum of gains
  and losses and the rest (the daily update).
- `BATTLE <side> attacks <side> near <town> (day, fleet task, the nation's diplomacy with the other
  side; caller, the fleet's mask, flags and state)` for every sea battle with a national fleet on either
  side (hook at `NewSeaBattle 0x5FEF80`), and `BATTLE refused: ...` (below).

**No war out of nowhere (`core.c`, `Relation.threat`).** When a power's war conditions first hold, it does
not roll: it warns, with the causes, in two messages:

```
Holland may declare war on <the player's nation>: relations are unfriendly (-38), and it sees the nation tied up in its war with England.
Improve relations within a month to keep the peace. Holland's view drifts towards 0 (reputation 90: +20, former sovereign of the capital -20).
```

The Diplomacy page shows "threat!" in the power's row and the reason in the footer (the drift target with
its terms is always there now). A war is possible only after the warning has stood `THREAT_EVALS` (4)
evaluations, about a month, with the conditions still true. When the relation rises 5 above the threshold
(for example after a ceasefire with England, which makes Holland Commercial again: threshold -60), the
warning lapses ("Tension with Holland eases"), and a later war needs a new warning. `threat` lives in what
was struct padding (byte 7 of `Relation`), values `0xB1..0xB4`; anything else, as in older saves, means no
warning, so the save layout and version are unchanged.

**Raids stop at peace (`navy.c`).** Every half second the fleet tick cancels (`TaskNone 0x5ADAF0`) a Circle
or Stay task whose target nation is not at war with the nation, and does not start a raid that sailed out
before a peace. The player hears it once: "Your fleets break off their raids on English shipping: the
nation is not at war with England."

**A fleet never starts a battle with a power at peace or with the player (`replog.c`, `navy.c`).**
`NewSeaBattle` (hooked at its entry, cdecl) refuses a battle whose attacker is a national fleet and whose
target is a convoy of a power the nation is not at war with, or a convoy of nation 5 (the player's own):
no battle starts, and the fleet's hunter target (`+0x168`) is cleared, so it sails on ("BATTLE refused:
... may not attack ..."). The hunter ignores `NewSeaBattle`'s result (`0x5AEE95 mov al,1`), so skipping it
is safe. In addition the fleet tick clears the mask bits (`j` and `j+7`) of every power the nation is not
at war with, which the patrol event may have set.

**Reputation losses are announced.** A `SubReputation` of at least one point with a power the nation is at
peace with posts "Your reputation with Holland falls by 25 after an attack on one of its towns; Holland's
relations with <the player's nation> follow it." (once per power and day). With the raid fix the fleets cause
none; these are the player's own actions.

## 4. The freeze after the save in the same log

```
18:48:17 SAVE: nation '<the player's nation>' written (1064 bytes)
18:48:21 WAR reset: pending conquests cleared
18:48:41 WATCHDOG: no frame for 20 s (frame 18759); main thread eip ntdll.dll+0x76B9C
18:48:41 WATCHDOG:  stack KERNELBASE.dll+0x144158 KERNELBASE.dll+0x1440C2 nvwgf2um.dll+0x7C978A ... D3D11.DLL+0x55189
18:49:21 WATCHDOG: no frame for 60 s (frame 18759); the same stack
```

- One `WAR reset` four seconds after the save is one `Session::Clear`: the world torn down after a save,
  as the *Leave to the start menu* dialog does (it saves when it opens, then Yes clears the world once;
  quit_hang.md 1). A load would show Clear, a frame, Clear and `LOAD:`; Quit shows two Clears.
- The main thread then never ran another frame. It waited inside NVIDIA's user-mode Direct3D 11 driver
  (`nvwgf2um.dll`) under `D3D11.DLL`, which on the player's PC is dgVoodoo2 translating the game's Direct3D 8.
  No frame of the game, Walhalla or PR2Nation.dll is among the 28 return addresses: the wait is inside the
  graphics driver stack while the world's resources are released, not in the mod's code.
- This is the same kind of freeze as the idle-fleets-and-freeze report (a world teardown right after a save, then a wait with no
  CPU). the idle-fleets-and-freeze report had no watchdog yet; quit_hang.md concluded "most likely a race in the D3D8 / driver
  teardown at exit". This log now names the module: the NVIDIA D3D11 driver under dgVoodoo2.
- Not reproducible here (no dgVoodoo2, another GPU). In the test install the same save was QuickSaved at
  100x and at normal speed, and the leave dialog's autosave plus *Leave -> Yes* was done at both speeds,
  followed by loading the save again: results in section 5.
- What the player can do: dgVoodoo2 is only meant for PCs whose Direct3D 8 hangs at start (Intel D3D9on12);
  on an NVIDIA PC run without it (uninstall the option in the setup), or update the NVIDIA driver.

## 5. Results

a private probe on a copy of the reporter's save (final build, 2026-10-19):

```
PASS  T12-load    each power's relation, drift target with its terms, strategy, reputation logged
PASS  T12-diplo   Nation_GetRelation(2) = [0, -36, 0, 100, 1]: Holland at peace, warning given (screenshot)
PASS  T12-run     days 586203 -> 586353 (150 days at 100x): no declaration; Holland warned on day 586205
PASS  T12-peace   30 fleet battles, 0 started against a power at peace or a player convoy; 55 such attacks refused
PASS  T12-log     18 REL lines, 100 REP lines (no SubReputation: the player lost no reputation)
PASS  T12-save100 QuickSave at 100x, the world clock runs on, watchdog quiet
PASS  T12-save1   QuickSave at normal speed, the same
PASS  T12-leave100 leave autosave + Leave -> Yes at 100x, start menu runs frames, the save loads and runs
PASS  T12-leave1  the same at normal speed
PASS  alive       no unhandled exception
```

Holland's course in that run: warning on day 586205 ("... tied up in its war with England"), warned 1 and 2
evaluations ago on days 586212 and 586219, then on day 586226 Holland went to war with Spain, turned
Defensive and the warning lapsed ("Holland no longer threatens war on <the player's nation>: it is at war with
Spain now"). It stayed Defensive for the rest of the five months. Before the fix the same save declared war
on day 586205 at every load, at any speed (the roll is deterministic).

The refused attacks were 77 tries at one player convoy near Martinique and the rest at Spanish (and two
French, one Dutch) ships, mostly near the member towns Santo Domingo, Isabella and Tortuga while Holland,
the towns' host power, was at war with Spain. That fits the finding of the conquered-town info fix that vanilla code which reads
a town's display byte treats every member town as Dutch (section 6); which path picked the targets was not
traced (the fleets' masks were clean, 0x0091, at the time).

Unit tests WAR-01..05 and the 20-year fuzz invariant "every AI war comes at least 28 days after its warning"
are in `dll/tests/test_core.c`; scenarios 54 (*Spain threatens war*) and 55 (*Navy - raids stop at peace*)
and the check "the fleet's assault costs no reputation" in scenario 46 are in `tools/scenarios.py`.

## 6. Town info "Your relationship with Holland" (the conquered-town info fix)

In the same save all five member towns (Tortuga, Port-au-Prince, Turk Islands, Isabella, Santo Domingo)
have the town nation byte `+0x390 = 5` and the display byte `+0x391 = 2` (read in the game). The display
byte is the nation's host power, `NationState.host_power`, set at founding to the capital's former
sovereign (Holland, for Turk Islands) and written for every town that joins
(`eng_town_to_nation(t, g_state.host_power)`). Vanilla code that needs a power for a town reads the display
byte for nations >= 4 (`0x40FC70`), so a nation town is "Dutch" to such code whoever owned it before. Holland
in the Town info is therefore not an index wrapping from slot 5 but the host power.

The same `host_power` is in the Holland war fix's cause, but as a relation term (-60 at founding, -20 in the monthly
drift target), not through a wrong lookup: no vanilla code that lowers the reputation reads the display
byte, and none ran in the probe (no `SubReputation`). Holland's war decision is the mod's own AI (`core.c`).

the conquered-town info fix (merged) found the readers of the display byte; for the Holland war fix they mean:
- `0x5D5840` AddReputation(display): deliveries to member towns raise the reputation with Holland. It only
  raises it, so it cannot have driven Holland to war.
- The sortie target picker `0x63B3A0` (opted in for nation 5) reads the display byte of a member town
  (`0x63B625`, `0x63B644`) and takes it as a candidate when `war[display]` is set. `war[]` is the nation's own
  wars (`g_pc.rel` = `player_rel`), so this only matters while the nation is at war with its host power:
  then a fleet may "sortie" to one of the nation's own towns (anchor, come back). A sortie is not a siege
  (navy_operations.md 1.1) and no town is attacked; it does not concern a power at peace. Not changed here.
- An immediate declaration on load (the conquered-town info fix saw "Holland has declared war" on the save's own date, 16 Jan
  1606, at normal speed): that is the same day-586205 evaluation; with the fix that evaluation gives the
  warning instead, and an older save (threat byte 0) always starts without a warning.
