# Port Royale 2 — Sovereign Nations

**Game Design Document / Engineering Specification**  
**Version:** 1.0  
**Target:** Port Royale 2 (2004)  
**Feature:** Found Your Own Nation  
**Status:** Proposed; engine feasibility unverified

> **Agent instructions:** Treat the requirements below as desired behavior, not as evidence that the game's executable already supports these features. Before implementing, inspect the target game version, identify verified symbols/data structures/hook points, document assumptions and compatibility constraints, and deliver a small working proof of concept. Do not assume that nation IDs, save layouts, Lua hooks, or source code are extensible. Preserve vanilla behavior unless an explicit feature requires changing it.

## 1. Vision and objective

Allow the player to transform a commercial empire into a sovereign Caribbean nation with territory, diplomacy, economy, military, identity, and long-term strategic objectives. The system should integrate with trade, towns, ships, combat, production and reputation, without replacing existing merchant gameplay.

Core pillars:

1. Nation founding and identity.
2. Territorial sovereignty and annexation.
3. Nation-to-nation diplomacy, recognition, war and peace.
4. National treasury, taxation and tariffs.
5. National fleet administration and defense.
6. Town loyalty and internal stability.
7. AI understanding of the new nation.
8. Save/load persistence and compatibility.

## 2. Player progression

1. **Merchant Empire:** Accumulate wealth, companies, ships and influence.
2. **Road to Independence:** Control an eligible capital, prepare defenses and meet founding conditions.
3. **Nation Founded:** Declare sovereignty, create political identity and receive reactions from existing countries.
4. **Colonial Power:** Annex towns, negotiate treaties, finance fleets and govern territory.
5. **Caribbean Hegemony:** Pursue economic, military and diplomatic dominance.

The player must retain access to trading, business ownership and ship command after independence.

## 3. Founding a nation

### 3.1 Proposed eligibility (configurable balance defaults)

| Condition | Default |
|---|---|
| Fully player-controlled town | At least 1 |
| Personal wealth | 5,000,000 gold |
| Ships available | At least 10 |
| Armed warships | At least 3 |
| Eligible capital | At least 1 |
| Existing player sovereign nation | None |

The exact meanings of "fully controlled," "warship," and "wealth" need to be mapped to real game data. An optional rebellion path may allow earlier independence at greater risk (post-MVP).

### 3.2 Player workflow

Entry point: **Town Hall → Political Affairs → Declare Independence** (or closest feasible native UI).

1. Enter nation name and adjective, select leader title.
2. Choose flag and national color.
3. Select capital and any eligible joining towns.
4. Review risks and projected consequences.
5. Confirm declaration.

### 3.3 Effects

- Create one new player-controlled sovereign nation.
- Assign selected town(s) and capital to it.
- Initialize national treasury, government and diplomatic relations.
- Apply reactions from former sovereign and other colonial powers.
- Expose nation-management UI.
- Update world map, fleet identity, town tooltips and hostile-target logic.
- Raise a nation-founded game event.
- Persist all new state.

**Atomicity:** all critical changes succeed together or restore the previous state. Avoid half-completed founding transitions.

Example flavor event: "The Free Republic of Tortuga has declared its independence." Responses from Spain, England, France, and the Netherlands should be driven by actual circumstances, not hardcoded example values.

## 4. Territory ownership

### 4.1 Essential distinction

**Sovereignty is not private property.** A player may own a factory or warehouse in a foreign town without politically controlling it. Ownership of private businesses must survive national sovereignty transfers unless a specific, explicit mechanic changes that.

Suggested political attributes:

- `SovereignNationId`
- `TownAdministrator` or governor, if feasible
- `CapitalOfNationId` or capital indicator
- `Loyalty` (0–100)
- `Stability` or unrest state
- `OccupationGarrison`
- Existing population, defenses, production and property ownership should be reused rather than duplicated.

### 4.2 Acquisition pathways

1. **Military conquest:** After a successful existing siege, annex, sack, demand tribute, liberate or withdraw; MVP requires annex or withdraw.
2. **Diplomatic acquisition:** Transfer sovereignty by treaty, purchase or compensation (later).
3. **Voluntary allegiance:** Eligible town petitions to join based on prosperity and loyalty (later).
4. **New settlement:** Create a colony only if town slots, map representation and simulation permit it (advanced, explicitly out of MVP).

### 4.3 Conquest resolution

After successful town capture, the game should present possible actions:

| Action | Result |
|---|---|
| Annex | Transfer sovereignty; start occupation/loyalty mechanics |
| Sack | Gain resources but damage town and stability (later) |
| Tribute | Leave sovereign owner, transfer money (later) |
| Liberate | Restore eligible prior sovereign owner (later) |
| Withdraw | Restore/retain original sovereign owner |

Ownership transfers must notify trade, UI, military AI, town AI, diplomatic state and persistence layers.

### 4.4 Occupation and loyalty

Each national town has loyalty 0–100, modified by conquest history, taxes, garrison, supply of essential goods, prosperity, previous allegiance and national stability. Suggested ranges: 80–100 Loyal; 60–79 Stable; 40–59 Dissatisfied; 20–39 Unrest; 0–19 Rebellion risk. Initial MVP may express low loyalty as an income penalty and unrest events; armed rebellions and secession are later scope.

## 5. Nation management

### 5.1 National overview UI

Show at minimum: name, flag, government title, capital, controlled towns, population, national treasury, number of national fleets, stability, and international recognition.

### 5.2 Separate treasury

Keep national funds separate from personal wealth. Revenue can include taxes, tariffs and diplomatic payments; expenses include fleet maintenance, garrisons, infrastructure and administration. Permit personal-to-national donations; national-to-personal transfers should be restricted or have consequences.

### 5.3 Taxation

Allow a national default tax and optionally town-specific overrides. Monthly revenue:

`TaxRevenue = Σ(TownTaxableBase_i × TaxRate_i × CollectionEfficiency_i)`

The taxable base must be defined from accessible game production/consumption data and balanced against vanilla economics. Higher taxation should reduce loyalty and/or growth. Avoid generating money disconnected from real economic activity.

### 5.4 Spending and insolvency

Treasury pays national obligations. If insolvent, block optional new expenditures and apply readiness or stability penalties. Complex sovereign debt is future scope.

### 5.5 Optional government types (post-MVP)

- Merchant Republic: stronger commerce and trade diplomacy.
- Colonial Monarchy: stronger administration/defense.
- Pirate Republic: privateering specialization.
- Maritime Federation: regional autonomy and town loyalty.

Each must include meaningful trade-offs. MVP uses one generic sovereign government.

## 6. Diplomacy

### 6.1 Relationship model

Represent relation score (suggested −100 to +100), treaty state, recognition, treaty expiry and war status as distinct data where appropriate. Proposed treaty states: Peace, Trade Agreement, Non-Aggression Pact, Alliance, War, Ceasefire. Recognition is independent of war; nations can recognize one another while fighting.

### 6.2 Actions

- Propose peace or ceasefire.
- Seek recognition.
- Propose trade agreement or non-aggression pact.
- Form/dissolve alliance.
- Declare war with stated objective.
- Negotiate tribute, reparations or territory transfers.
- Request military assistance (advanced).

The diplomacy UI should show requirements, costs and qualitative likelihood of acceptance.

### 6.3 AI diplomacy

Decisions should weigh relations, relative naval strength, trading dependence, border proximity, existing wars, claims and treaty violations. These values and weights should be configurable. Critically, AI countries must be able to initiate as well as respond to interactions with the player's nation.

## 7. Military and fleet integration

### 7.1 Ownership categories

- **Private fleets:** Player's ordinary convoys and commercial ships, maintaining vanilla gameplay.
- **National fleets:** Player-controlled or state-assigned fleets funded by the national treasury and authorized for government missions.

MVP may implement national designation on regular convoys without autonomous fleets.

### 7.2 Planned fleet missions

- Defend designated town.
- Patrol route/region.
- Escort trading convoy.
- Blockade enemy harbor.

These must respect normal movement, naval combat and supply constraints. Autonomous fleet missions are post-MVP unless existing AI primitives enable low-risk integration.

### 7.3 War mechanics

On war declaration, update both nations' targeting and hostility state. Player-national towns must become valid targets; foreign fleets can attack eligible national military and trade assets. Peace must terminate invalid hostile orders. Unprovoked attacks outside war should have defined diplomatic consequences.

Prefer reusing existing combat/siege systems. Increasing the simultaneous number of combat vessels is an independent project.

## 8. National trade policy and economy

Optional import tariff presets: 0% free trade, 5% low, 10% moderate, 20% protectionist; values are illustrative. Charge only at clearly defined imports, never repeatedly on the same internal transfer.

Allow policy goals such as raising revenue, growing towns, prioritizing essential supplies, supporting shipbuilding and encouraging exports. Initially represent these via government incentives/notifications rather than rewriting trade automation.

Later public infrastructure: defenses, warehouse logistics, military shipyards and government offices, subject to town slot/layout constraints. Strong economic play should not create effortless perpetual victory.

## 9. Internal politics

National stability (0–100) depends on prosperity, treasury solvency, taxes, military outcomes, war exhaustion, recently occupied territory and essential goods supply. Town-level loyalty is separate: a prosperous capital can remain loyal while a recently annexed town resists.

Rebellion in MVP: economic penalties and unrest. Armed uprisings, breakaway states and AI independence movements are advanced features.

## 10. AI requirements

**Minimum:** all four established colonial powers must recognize the player nation as an entity in ownership checks, relation state, diplomacy, fleet targeting, defense/siege, peace and trade permissions. Preserve their original behavior relative to each other.

**Advanced:** dynamic expansionist, commercial, defensive and opportunistic strategies based on current conditions, not static national stereotypes. Bound AI money, fleets, attack frequency and conquest to avoid destabilizing gameplay.

## 11. Engine feasibility and architecture

### 11.1 Mandatory reconnaissance

Document, with evidence from the actual targeted binary/version:

- Nation records: fixed four-entry array or extensible collection?
- Nation IDs and all bounds checks/hardcoded comparisons.
- Town sovereign owner representation and transfer paths.
- Diplomacy and warfare representation.
- Fleet identification, targeting, and merchant hostility.
- Special status/behavior of viceroy towns.
- Rendering and flag/color asset selection.
- World map ownership displays.
- Save format and serialization of nation references.
- UI menus and available scripting/mission hooks.
- Community patch version and compatibility, if used.

### 11.2 Architecture options

**A. Native fifth nation (preferred if proven feasible).** Extend existing political-system structures and all dependent code paths so the player nation is first-class. Very high risk of hardcoded four-nation assumptions.

**B. Sovereignty overlay (fallback).** Keep shadow political state outside the original records and intercept ownership/diplomacy/military calls. Also very high risk because every unhooked vanilla subsystem may disagree with the overlay.

Do not commit to either before a vertical proof of concept.

### 11.3 Logical modules

- Nation Feature Controller: founding validations and transactions.
- Nation Registry: player sovereign identity and lifecycle.
- Territory Service: sovereignty and ownership notifications.
- Diplomacy Service: relations, war and treaties.
- Treasury/Economy Service: taxes, tariffs, expenses.
- Military Adapter: fleets, targets, sieges and hostility.
- Governance Service: stability and town loyalty.
- Engine Integration Layer: verified hooks and mapped game data.
- Save Adapter: load, versioning, migration and integrity.

Prefer typed commands/events and central authority for changing sovereignty and diplomatic state, rather than scattered memory writes.

### 11.4 Conceptual C# domain model

**This is illustrative architecture, not proof that the game or mod is written in C#.** Use native C++, scripting, or a hybrid bridge as required by engine findings.

```csharp
public enum NationType { ColonialPower, PlayerSovereign }
public enum DiplomaticStatus { Peace, TradeAgreement, NonAggression, Alliance, War, Ceasefire }

public sealed class NationState
{
    public int Id { get; init; }
    public string Name { get; set; } = "";
    public NationType Type { get; init; }
    public int CapitalTownId { get; set; }
    public long Treasury { get; set; }
    public float Stability { get; set; } = 75;
    public int FlagAssetId { get; set; }
    public HashSet<int> TerritoryIds { get; } = new();
    public HashSet<int> MilitaryConvoyIds { get; } = new();
}

public sealed class NationRelationship
{
    public int NationAId { get; init; }
    public int NationBId { get; init; }
    public DiplomaticStatus Status { get; set; }
    public int Reputation { get; set; }
    public bool IsRecognized { get; set; }
    public long TreatyExpiryTick { get; set; }
}

public sealed class TownPoliticalState
{
    public int TownId { get; init; }
    public int SovereignNationId { get; set; }
    public float Loyalty { get; set; } = 75;
    public float TaxRate { get; set; } = 0.05f;
    public int OccupationGarrison { get; set; }
}
```

Suggested interfaces:

```csharp
public interface INationService
{
    FoundingResult FoundNation(FoundingRequest request);
    bool CanFoundNation(int playerId);
    NationState? GetNation(int nationId);
}

public interface ITerritoryService
{
    TransferResult TransferSovereignty(int townId, int newNationId, TransferReason reason);
}

public interface IDiplomacyService
{
    TreatyResult ProposeTreaty(int proposerId, int targetId, DiplomaticStatus proposedStatus);
    void DeclareWar(int attackerId, int defenderId);
}

public interface INationalTreasury
{
    bool TrySpend(int nationId, long amount);
    void Credit(int nationId, long amount);
}
```

### 11.5 Founding transaction order

1. Validate eligibility and intended capital.
2. Verify the player does not already own a sovereign nation.
3. Record prior sovereign affiliation of all joining towns.
4. Create player nation record.
5. Assign capital and territory.
6. Initialize diplomatic relations and treasury.
7. Register new nation in AI, military, map and UI adapters.
8. Persist a valid coherent state.
9. Publish event to the game.

Use rollback journal or game-state snapshot where native atomic transactions are impossible.

### 11.6 Simulation cadence

- Hostility checks: on targeting and relation changes.
- Territorial changes: event-driven.
- Taxes: monthly in-game.
- Town loyalty: daily in-game.
- AI strategic evaluation: every several in-game days.
- Treaty expiry: daily or event-driven.
- UI: when underlying state changes.

Adapt exact cadence to actual engine facilities.

## 12. UI requirements

Screens/panels:

| Priority | Screen | Functions |
|---|---|---|
| P0 | Found Nation | Name, flag, capital, consequences, confirm |
| P0 | Nation Overview | Treasury, territory, population, recognition, stability |
| P0 | Diplomacy | Relationship display, war and peace |
| P1 | Town Governance | Taxes and loyalty |
| P1 | National Military | Fleet assignments, costs |
| P2 | Foreign Affairs | Advanced treaties, claims |
| P2 | Nation Statistics | Comparative national strength |

Town tooltips and world map must reflect actual political ownership. National colors should be distinguishable, fleets must receive correct allegiance markers, and all hostilities/sieges must reference coherent ownership state. Keep native visual style and minimize micromanagement.

## 13. Saving/loading and compatibility

Persist nation identity, capital, territory, treasury, relations, treaties, wars, taxes, stability, town loyalty, fleet assignment and pending events.

If vanilla saves cannot accommodate nation data, implement a versioned sidecar (unique game-save ID, checksum, mod version) or another verified extension. Save base and mod data as one logical transaction. Never silently load mismatched nation data.

Compatibility targets:

- New modded game fully functional.
- Vanilla pre-independence saves initialize defaults while preserving ownership.
- Modded saves round-trip all nation state.
- Missing/mismatched sidecars produce safe errors or a verified recovery path.
- Unsupported mod versions fail clearly.
- Loading sovereign modded saves in unmodded game is unsupported unless a validated conversion exists.

## 14. Development milestones

### M0 — Feasibility spike (release blocker)

Identify binary structures, nation limits, hooks, ownership propagation, military AI and saves. Produce a working fifth-nation experiment: assign one town, advance simulation, confirm hostility, save/reload. If it fails, document obstacles and choose architecture deliberately.

### M1 — Founding MVP

Eligibility, declaration UI/event, nation ID, capital, visual identity, save persistence. **Done when:** founding works and normal trade/navigation continues.

### M2 — Territory

Annex and lose towns; update all systems; preserve personal businesses and population. **Done when:** sovereignty transfers are coherent and saved.

### M3 — War/diplomacy

Relations, declare war, peace, AI hostility and reciprocal response. **Done when:** all four original powers can interact militarily/diplomatically with player nation.

### M4 — Economy

Treasury, tax revenue, maintenance and nation overview UI. **Done when:** finances are balanced and no money is created without economic cause.

### M5 — Governance/AI

Loyalty, stability, occupation consequences, strategic responses. **Done when:** extended campaigns work without AI collapse or uncontrolled exploits.

### M6 — Advanced expansion

Government types, advanced treaties, admirals, rebellion, privateering and optional new colonies, subject to verified technical capacity.

**First playable public release:** founding, at least one capital town, correct sovereign ownership, map identity, basic war/peace and safe save/load. Prioritize a narrow functioning vertical slice over breadth.

## 15. Acceptance tests

| Test ID | Scenario | Expected result |
|---|---|---|
| FND-01 | Found without prerequisites | Block with explanation |
| FND-02 | Valid declaration | Create sovereign nation |
| FND-03 | Second founding attempt | Reject duplicate |
| TER-01 | Annex conquered town | Transfer sovereignty |
| TER-02 | Annex town containing private businesses | Preserve property |
| TER-03 | Capital lost | Apply defined recovery/relocation policy |
| DIP-01 | Declare war on Spain | Mutual war state |
| DIP-02 | Make peace | Clear invalid hostile orders |
| MIL-01 | Enemy meets national convoy | Correct hostility targeting |
| ECO-01 | Collect taxes | Treasury updated accurately |
| ECO-02 | Pay upkeep | Funds deducted exactly once |
| SAV-01 | Save/reload after founding | Identical political state |
| SAV-02 | Save/reload during war | Preserve war and territories |
| REG-01 | Play without declaring independence | Vanilla behavior intact |
| REG-02 | Long simulation | No crashes, corruption or runaway economy |

Additional edge cases: no towns remaining; former sovereign retakes town; simultaneous sieges; peace during battle; capital falls with fleets at sea; treasury zero; viceroy town special cases; save on ownership transfer boundary; save schema mismatch; treaty changes while trade fleets sail.

Performance: benchmark normal and accelerated gameplay versus vanilla across identical scenarios; measure tick time, frame rate, memory, save/load and crashes. Use reproducible test saves/snapshots.

## 16. Major risks and safeguards

1. **Hardcoded four-nation implementation (critical):** Nation ID bounds, arrays, fixed UI and old save structs. Map all relevant paths before writing.
2. **AI not recognizing fifth nation (critical):** Must verify defense, war targets, convoy hostility and peaceful relations independently.
3. **Save corruption (critical):** Version and validate all added state; maintain backups and rollback.
4. **Special viceroy towns (high):** Confirm rules for capitals and elimination; avoid breaking colonial powers.
5. **Mod and patch conflicts (high):** Record supported executable hashes/builds and hook compatibility.
6. **Trade/economy imbalance (high):** Restrict passive money production and duplicated tariffs.
7. **Territory/property conflation (high):** Never let annexation silently erase unrelated privately owned businesses.

## 17. Suggested development responsibilities

- Reverse engineering / engine integration: executable mapping, hooks, save format, builds.
- Gameplay systems: nation registry, founding, territory, finance, governance.
- AI: diplomacy, fleet hostility, strategic decisions.
- UI/art: dialogs, nation display, flags and map indicators.
- QA: save migration, regression, long-simulation testing and balancing.

Roles can overlap. Do not commit schedule/cost until M0 is complete.

## 18. Definition of done

The user can independently found a persistent country, with a capital and at least one town, without replacing an original nation. Other nations can recognize, fight, trade and negotiate with it. Territory can be acquired and lost. Government revenues/expenses operate; AI recognizes all state changes; save/load works; original commercial gameplay remains intact; prolonged campaigns stay strategically meaningful and stable.

## 19. Future extensions (not in core scope)

- New colonies / settlements along available coastlines.
- Admirals, automated navy patrols and large fleet battles.
- Embassies, coalitions, claims and multi-nation wars.
- Pirate republic and alternative government structures.
- Monopolies, embargoes, advanced trade diplomacy.
- Autonomous independence movements and civil wars.

## 20. First task for the coding agent

**Do not implement the full feature yet.** Begin with a targeted feasibility report and reproducible technical proof:

1. Identify the exact supported game executable build/hash and existing patch environment.
2. Locate nation registry/storage and determine whether it assumes exactly four nations.
3. Locate a town's sovereign owner and one relevant military-hostility check.
4. Test an isolated fifth-nation identity in a disposable game session.
5. Transfer one town, verify world-map/UI behavior and advance the simulation.
6. Save/reload and confirm pointer/identifier integrity.
7. Record verified binary offsets, calling conventions and findings for the target build.
8. Provide go/no-go recommendation for native fifth nation versus overlay, with blockers and smallest safe next implementation step.

**Deliverables:** the private feasibility study, reproducible proof-of-concept patch/source, test instructions, version/build compatibility matrix, and known-issues list.

## References / context

- [Port Royale 2 Community Patch on ModDB](https://www.moddb.com/mods/port-royale-2-community-patch) — inspect current release, API claims and compatibility independently.
- Game community discussions and guides regarding towns, diplomacy, viceroy rules and executable limitations should be independently verified for the exact game build.

