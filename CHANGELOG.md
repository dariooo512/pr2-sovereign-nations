# Changelog — Port Royale 2: Sovereign Nations

Versions are named by date and build: `vYYYY.MM.DD-<build>`. The package's `VERSION.txt` says which one you have.

## Unreleased
**No war out of nowhere (the Holland war fix)**
- Fixed: a power at peace could declare war on the nation without any sign beforehand. In ferra's game Holland did so within a minute of every load: as the former sovereign of the capital (Turk Islands) its relation had started at -60 and was still -38 a year later, and while the nation fought England Holland's strategy turned *opportunistic*, which goes to war from -20. The fleets and the reputation (90 with Holland) had nothing to do with it.
- Now a power that considers war warns first, with the reason: "Holland may declare war on <the player's nation>: relations are unfriendly (-38), and it sees the nation tied up in its war with England." and what its relations drift towards. It may declare war only after the warning has stood about a month (four AI evaluations) with nothing changed; if relations improve (for example a ceasefire with England) the warning lapses: "Tension with Holland eases" (or "Holland no longer threatens war ...: it is at war with France now"), and a later war needs a new warning. The warning is kept in saves (in a spare byte, the save format is unchanged).
- The *Diplomacy* tab shows **threat!** in the power's row, and below it the target its relation drifts towards with every part (reputation, recognition, treaty, tariff, common enemies, former sovereign).
- Fixed: a fleet raiding a power's shipping went on attacking its ships after a ceasefire or peace, until its 20-day raid ended (the game's raid task attacks every ship of that nation, whatever the diplomacy). Raids on a power you are not at war with are now called off at once, and a raid that sailed out before the peace does not start: "Your fleets break off their raids on English shipping: the nation is not at war with England."
- Fixed: a fleet could also start a fight with a ship of a power you are at peace with, or with one of your own convoys, when the game's patrol logic picked it as a target (seen with Spanish and French ships and a convoy of yours in ferra's save). A fleet now never attacks either; it lets the ship go and sails on. Ships of a power that attack a fleet are still fought off.
- When your reputation with a power at peace with the nation falls (you attacked its convoys or towns), a message says so, as its relations with the nation follow your reputation.
- PR2Nation.log records every change of a power's relation (`REL ... score a -> b (cause)`, the monthly drift with its parts) and of your reputation (`REP`, with the game action and its call site), every war decision of a power (`AI ...` with the numbers), each power's relation, target and strategy on load, and every sea battle of a national fleet (`BATTLE`).
- The freeze after saving in the same report: the log shows the world torn down after the save (the *Leave* dialog) and the game then waiting inside the NVIDIA Direct3D 11 driver under dgVoodoo2, not in the mod (research/holland_war.md §4). Saving, leaving to the start menu and loading again work at normal and 100x speed in the test install.
- `Nation_GetRelation` returns a fifth value: the AI evaluations since the power's war warning (0 = none).

**Town info of your nation's towns**
- Fixed: the game's town info window of a town of your nation showed *"Your relationship with Holland"* (or another power) with that power's flags and your reputation with it, even for a town that power never owned. The power was the nation's "host" power (the former owner of your capital), which the game keeps in every nation town only to pick the look of its buildings. Now the section reads **Your nation**, with the nation's flag and the town's loyalty as on the Towns tab: *loyal (72)*, *calm (35)*, *restless (18)* or *in unrest*. The line under the town's name says *Capital of …* / *Town of …* your nation (it was empty). Towns of the powers show their relationship line exactly as before.
- Fixed: the political map's tooltip of a nation town (and the sea battle dialogs) named the town's owner *"Invalid"*; they now name your nation.
- research/town_info_owner.md explains where the wrong power came from and which other parts of the game read that host power.
**Nation panel: every page in the look of the game's own windows**
- The pages are no longer stacks of text cards. Each one is a copy of the vanilla window that does the same job, with the nation's data: the Treasury is the Log's *Balance* page, the Towns tab the Chronicle's *Town list*, Diplomacy the Chronicle's *Nations* relations, the Overview the *Successes* page with the *Nations* page's size-and-strength table (the nation next to the four powers), Government the new-game value selector, and the Navy tab the *Convoy list*. The founding page stays as it was.
- The Treasury keeps real accounts now: every change to the treasury is booked to one of 13 categories (taxes, import tariffs, privateering, plunder, donations; administration, fleet upkeep, tower upkeep, new fleets, soldiers, cannon towers, towns bought, withdrawals), shown for last month and as a forecast for this month. *Taxes and finances* holds the tax and tariff arrows and donations and withdrawals of any amount from 1,000 to 1,000,000. Saves keep the accounts (nation data version 3); older saves load with empty accounts.
- Towns, Diplomacy and the Navy tab are tables: click a row to select a town, a power or a fleet; what you can do with it appears below. *Town info* opens the game's own town window for a member town.
- Numbers use the game's own thousands separator.
- Each page was designed from the game's own window layouts: all 254 of its UI screens were catalogued and every vanilla window was photographed (both kept private) to pick the right look for each page.

**Overview page and messages**
- Fixed: the nation's flag was missing from the Overview (the Name row and the nation's column in *Size and strength*) every time the page was opened after the first time in a game session. Reloading did not bring it back, only restarting the game did. A town joining had nothing to do with it. The page is built again each time its tab is shown, and the mod still thought the new page had the flag. The same fault left the flag empty under the Towns page list when a nation town was selected again later. The cause is described in research/overview_flag.md.
- The *Wars* row of *Size and strength* is lined up. In every cell the flags and "you" sit on one line, centred under the column's flag and level with the "Wars" label. Three or four entries take two centred lines. Before, the flags hung low against the table's border, and a cell with "you" sat higher than the others.
- Messages call the nation by its name instead of its capital's: "The citizens of Eleuthera ask to join <the player's nation>", "A fleet of <the player's nation> brings home plunder ...", "The naval command of <the player's nation> fits out a new fleet ...", and the same for new fleets, paid-off and deserting fleets, towns bought and towns stormed by the navy. The founding message says "Its flag now flies over Turk Islands".
- "An English war fleet has put to sea ..." (it said "A English"). "a" or "an" is now chosen by the next word everywhere a name is filled in: forms of government, naval ranks and treaties ("Propose an Alliance").
- The small marks just outside the panel's right and bottom edges in some places are the sea map's town labels behind the panel (a town's flag and the frame of its icons), not part of the panel. No panel control is left behind from another page.

**The mod's main image**
- The *Sovereign Nations* artwork (an AI-generated image provided by ferra for the mod) is now the mod's image: the banner at the top of the README, the player guide and the release's new *HOW TO INSTALL.html*, and the header of the setup window. The master is kept unchanged in `art/`; the copies (`docs/banner.jpg`, `docs/social_preview.png` for GitHub, `installer/header.png`) are only resized, cropped or compressed, by `art/make_banner.py`.
- The player guide's *Install* section now describes the setup program instead of the old developer installer.

**For builders**
- The paths the tools need outside the mod (the extracted game archives, the DRM-free base exe, the pristine game copy, the test install and its lock, the Save folder, MinGW) are settings with the old defaults, read from environment variables (`tools/sn_paths.py`).
- `tools/build_data.py` builds the data files that are made from the game's own files (the panel screens, the top bar, `include.ini`, the flag logos) from your own copy of the game.
- The mod's sources are prepared as their own public repository, *pr2-sovereign-nations*: the DLL, patches, loader, setup, generators, test tools, docs and research notes, with no game file and nothing made from one.

## v2026.10.18
**National convoys removed**
- National convoys are taken out of this version. A national convoy was one of your own convoys, renamed "National convoy N", flying the nation's flag and costing the treasury 3,000 a month, but it gave you nothing for it: it did not sail by itself, earn anything, count towards the naval rank or fight any differently. The nation's real ships are its fleets. The feature may come back later with a real purpose.
- The Navy and defence tab no longer has the National convoys card (*One more* / *One fewer*, the convoy cards with *Go to* and *Release*). Fleets and town defence work as before.
- Monthly upkeep is now towns, fleets and towers only (one town and no fleets or towers: exactly 2,000 a month); the monthly accounts message no longer counts convoys.
- Your convoys always fly your own flag. Only fleets are national ships: the cyan minimap dot and Ctrl+Shift+N are for fleets only.
- Saves with national convoys (made with v2026.10.18-79816ea1 or earlier) load normally: each such convoy gets its old name and your flag back, in port and at sea, nothing is charged for it at the month end, and the next save no longer stores it. The Lua call `Nation_NationalConvoys` still exists but does nothing and returns 0.

**Navy**
- Fixed: fleets under *Raid enemy trade* stayed in port for good. The raid order reached a fleet while it lay in harbour, and the game's harbour routine then held it there until the order ran out, 20 days later, when the order was given again. Now a raiding fleet first refits in port for two days, then puts to sea and starts its raid out on the water. This holds for five fleets commissioned at once too. Fleets that are stuck like this in an older save are released when the save is loaded.
- A fleet down to a single ship stays home instead of going raiding.
- The log (PR2Nation.log) now records when a fleet actually leaves port and when it is back ("NAVY: fleet ... leaves port at TurkIslands for Grenada", "... in port at Tortuga"), not only when it is given an order.
- Diagnostics: if the game stops running frames for 20 seconds, the log records where it is waiting (a watchdog), so a freeze can be traced. The log is now written without the C runtime's file locks.

## v2026.10.17
**Founding**
- Founding is one card on the nation panel: form of state, name and flag together, then *Found the nation*.
- Type your own name for the nation (up to 28 letters), or keep the suggestion, which follows the form of state.
- All eight forms of state can be chosen: Republic, Kingdom, Free Republic, Commonwealth, Principality, Confederation, Grand Duchy, Empire.
- The flag is picked with the game's own new-game logo selector, showing the flag itself; the arrows step through all 100 flags.
- The old chain of dialog menus is gone: everything is in the panel. Only the conquest decision (*Annex* / *Withdraw*) and its result still appear as a small popup.

**Flags**
- Your own flag and the nation's flag are kept apart. Your convoys and ships fly the flag (logo) you chose at the start of the game everywhere: in port, at sea, on sails and mast flags, on the sea map and in the info bar and player panel. The nation's fleets and national convoys fly the nation's flag everywhere, and the nation's towns show it (header bar, town and battle dialogs, sea-map town marker, trade window). A ship keeps its flag when it enters or leaves port and after a save and reload. Before, founding replaced your logo with the nation's flag, so the two got mixed up.
- Saves from before this change: your own logo comes back when the game still has it (the mod kept a copy before it first replaced it); otherwise the logo stays as it is in the save.
- A flag changed later with the Lua call `Nation_SetFlag` shows at once on the towns and on new ships; ships already lying in a port you are looking at take it when you next enter that town or load.

**Nation panel**
- The nation menu is now one in-game window like the game's Log / Missions window, with six tabs: Overview, Treasury, Towns, Diplomacy, Government, Navy and defence. The map keeps running behind it.
- A **nation button** in the top bar (the flag icon right of the convoy list) opens and closes it. Before founding it opens the founding page. Ctrl+N still works.
- Cards with real text buttons; withdrawals and declarations of war ask for confirmation; the result of each action is shown on the first card.

**Towns and growth**
- Building permit in your own towns: you hold the building permit in every town of your nation, the capital from the founding on and every other town from the moment it joins (conquest, a fleet's war campaign, purchase, petition). The join message says so ("Coro has joined ... You may now build there."). Towns gained in older saves get it when the save is loaded. A town that leaves the nation goes back to the permit you had there before it joined; your buildings stay. A permit in a nation town cannot be sold to the master builder for money. Other powers' towns still need a permit as in the original game.
- Per-town tax: raise or lower a single town's tax on the Towns tab.
- Buy a town: towns where you own property can be bought from their power for a price based on population and wealth.
- Petitions: prosperous towns where you own property may ask to join a stable nation; accept or decline on the Towns tab.
- Fixed: in your own towns the treasurer and the commander refused you because your reputation with the town's former power was too low. In the nation's towns the treasurer, the commander, the governor and the building master now serve you as their sovereign (full access, as with the highest reputation), however the old power thinks of you. This holds for the capital and for conquered, bought and petitioning towns, and after loading a save. Other powers' towns check your reputation as before.

**Diplomacy**
- Offers from the powers (trade agreement, ceasefire) appear on their card with *Accept offer* / *Decline*.
- The Diplomacy tab proposes the next treaty step (trade agreement, non-aggression pact, alliance).

**Sea map: see and follow the nation's ships**
- The nation's fleets now show on the sea map and the minimap wherever they sail, under the nation's flag. Before, the fog of war hid them unless one of your own convoys was close.
- They light up the sea around them like your own convoys do (same sight radius): pirates, merchants and enemy fleets near a national fleet become visible. Showing only: you still command only your own convoys.
- National ships have their own minimap dot (cyan), so they are not mistaken for your personal convoys (blue).
- *Go to* (the eye at the top left of each fleet card and national-convoy card, Navy tab) centres the sea map on that ship, from a town view too. Ctrl+Shift+N jumps to the next national ship.
- Fleet cards show where the fleet is and where it is heading.
- National convoys are now real convoys: *One more* designates the convoy you have selected (or your first free one). It sails as "National convoy N", has its own card (where it is, where it is heading, *Release*, *Go to*), and keeps being yours to command. The treasury pays its upkeep as before. Saves with only a number of national convoys get that many designated when loaded.

**Navy**
- Each fleet can get its own order: guard one of your towns, raid enemy trade, or a war campaign against a chosen enemy town (Navy tab, *Next order* / *Next target*).
- A fleet on a war campaign attacks at most once a week. After an attack it sails home to refit, and it goes back only when it is strong enough for the garrison. Before this, it was sent straight back into the siege and lost.
- A fleet fitted out to replace a lost one takes over the lost fleet's order.
- Fixed: paying off a fleet now really removes it.
- Fixed: the game crashed after your fleet won a siege, and could crash after an enemy took one of your towns.
- A falling naval rank no longer takes fleets or orders away; it only blocks new ones.
- Verified in game: an enemy war fleet can take one of your towns back.

## v2026.10.16
**National navy**
- Your nation has its own fleets, sailed by the game's own military AI: they patrol, hunt pirates and fight your enemies' warships. Battles between AI fleets are fought out automatically.
- Naval rank (Fledgling state, Regional power, Naval power, Great power) sets how many fleets you can keep (1, 3, 6, 10) and which orders you can give.
- Orders: Patrol, Raid enemy trade (plunder goes to the treasury), War campaign (fleets besiege enemy towns; a won land assault annexes the town).
- Fleets cost 120,000 to fit out and 6,000 a month; the naval command replaces lost fleets; unpaid crews desert.
- Garrisons and defence: recruit soldiers (20,000) and build cannon towers (50,000) from the treasury.
- The powers now send war fleets against your towns when they are at war with you.
- Saves from earlier versions still load (the navy starts empty).

## v2026.10.15
- Portable package for another PC: unzip, install the test saves, play — no installation needed.
- Fixed: the nation's flag was not shown on a PC that had never run the game before.

## v2026.10.13
- Fixed: the game froze with a black screen once Windows had been running for more than 24.86 days (a bug of the original game; the mod gives the game its own clock).
- Three play checkpoints: a young republic, a war for Coro, a nation in crisis.

## v2026.10.12 — first playable version
- Found your own nation at a town where you own property (5,000,000 gold, 10 ships, 3 warships); choose Republic, Kingdom or Free State.
- 100 historical, pirate and Caribbean flags; your flag flies on your towns, ships and the sea map.
- National treasury separate from your own gold: taxes, import tariffs, upkeep, monthly accounts, donations and withdrawals.
- Territory: annex towns you conquer in a war; the capital moves if it falls; towns in long unrest secede.
- Diplomacy with England, France, Holland and Spain: war, ceasefire, peace, trade agreements, recognition; the powers act on their own strategies.
- Five forms of government with different strengths: Sovereign, Merchant Republic, Colonial Monarchy, Pirate Republic, Maritime Federation.
- Everything is stored in the normal save game.
