# Null-nation census: where `g_nations[n>=4] == NULL` gets dereferenced

Static RE of `reverse-engineering/_re/PR2.exe.unpacked.exe` (ImageBase 0x400000),
the **unpatched** build. Nothing was run in the game. Tools: pefile + capstone.
Scratch scripts are in the session scratchpad `agent_null/`:
- `sim.py` / `drive.py` / `drive2.py`: a path-sensitive taint simulator. It forces the
  index to 5, follows the NULL pointer through registers, stack slots and calls (3 levels
  deep), and reports derefs, null tests and pass-through.
- `ctx.py`, `callers.py`, `realfn.py`: context, caller and function-start helpers.

Labels:
- **[S] VERIFIED-STATIC**: instruction bytes read at the VA.
- **[H] HYPOTHESIS**: purpose or runtime reachability that is inferred, not observed.

## 0. Answer in one paragraph

All 109 references are bounded, as `check_facts.py` N0-guards says. But "bounded" only
means `n>=4 -> p = 0`.

**60 of the 100 guarded sites then use `p` with no null test.**
- 23 dereference it inline.
- 36 pass it as `this` to a CNation method. 22 of those methods dereference `this`
  unconditionally, 14 only when `other<4`.
- 1 site is unresolved.

Only **12 of the 60** take their index from a **town's nation byte**, so only these can
fire for a nation-5 town. They sit in **4 functions**, plus route-cost IsAtWar, which P01
already fixed:

| Fn | What | Sites |
|---|---|---|
| `0x5C8650` | Lager: per-good share for administrative towns (the observed crash) | `0x5C86BD`, `0x5C86E1`, `0x5C8702` |
| `0x5B40D0` | convoy delivers goods into the town it is docked at: 12..15 at `0x5B41C7`/`0x5B41F1`, goods 0..11 at `0x5B4331..40`/`0x5B43AA` (**corrected** by P05; earlier said all 12..15) | `0x5B41C7`, `0x5B41F1`, `0x5B4331..40`, `0x5B43AA` |
| `0x5BC310` | annexation transfer: the old owner is the town's byte | `0x5BC4B5`, `0x5BC4D4`, `0x5BC59D`, `0x5BC5D3`→`0x5BBB20` |
| `0x5E74B0` | `CLetterBuildingLost::Create` (letter UI) | `0x5E75E8`→`0x5BB0F0` |

The other 48 take their index from NPC, Lua, event, convoy or loop values. Those are
0..3 in vanilla, or are validated earlier. They are **latent**: they only fire if a
nation byte ≥4 leaks into those objects (see §3).

## 1. Classification of all 109 references

| Class | Count | Sites |
|---|---|---|
| loop4 / base-walk (no NULL possible) | 6 + 3 | `0x41B2B8` (index is the constant edi=0), `0x42D4CE`, `0x601194`, `0x605D7B`, `0x63AFE7`, `0x63B004`, `0x63BB99`; base walks `0x5BA13F`, `0x63B4BB`, `0x63CADF` |
| **NULL-SAFE**: tested after the lookup | 9 | `0x5B014F` (`test ebp,ebp` 0x5B0163), `0x5C9E01` (AddToNation, `test edi,edi` 0x5C9E1C), `0x61C7B4` (0x61C818), `0x6350E9` (`test eax,eax` 0x6350ED), `0x6370C6`, `0x637106`, `0x63C46B`, plus `0x447B2E` and `0x5F376E`, which pass it as arg0 to `0x640120`; that function tests it (`test ecx,ecx` 0x640126) |
| **NULL-SAFE**: the ≥4 path never uses p, or an outer guard makes it dead | 31 | `0x41DA62`, `0x41DAE2`, `0x41E7FC`, `0x42E74F`, `0x42E823`, `0x42E838` (Lua args rejected first: `0x41DA53 cmp al,4/jae error`, `0x42E6C0 cmp bl,4/jb ok/else throw`); `0x44C95F`, `0x44C986` (index is `and al,3` at 0x44C945); `0x5BA203` (outer `0x5BA1F3 cmp al,4/jae`); `0x5F3D59` (outer `0x5F3D45 cmp cl,4/jb`); `0x605AF0` (loop `xor bl,bl`); plus 20 sites the simulator reported as NONULL: `0x4474B2 0x447A5F 0x5A9E0B 0x5A9E33 0x5B2003 0x5B77D2 0x5C9E14 0x5D33CC 0x5EF98C 0x5F1A2D 0x5F1B40 0x5F3D38 0x601491 0x605DA9 0x605DCD 0x61C3AD 0x636728 0x63674F 0x636776 0x63708D 0x63B3DA 0x63BDCC 0x63BF9F 0x63C29F 0x63CB5E` |
| **DEREF** inline | 15 live (after removing the dead ones above) | §2 table |
| **PASSES-NULL** → IsAtWar `0x5BA0A0` (null-safe since **P01**) | 9 | `0x41D46A 0x448152 0x4482E7 0x448802 0x5AD925 0x5B518A 0x5D456B 0x5F5388 0x63B8D6` |
| **PASSES-NULL** → `0x5BA080` GetRelation (derefs when other<4) | 5 | `0x41C10D 0x5DDD96 0x5F5287 0x5F571A 0x5F578C` |
| **PASSES-NULL** → an unconditional-deref method | 20 | §2 table |
| unresolved | 1 | `0x63C7AB` (ebx=NULL in the military target picker `0x63C6C0`; the simulator hit its step limit) |

The rows do not add up exactly to 100, because a few sites fall into two buckets (dead
outer guard and inline deref). Counting the raw simulator verdicts instead gives 23
inline DEREF, 36 PASSES-NULL, 40 NULL-SAFE and 1 unresolved, which is 100.

### CNation methods vs. a NULL `this` [S]

| Method | First access | Null-safe? |
|---|---|---|
| `0x5BA0A0` IsAtWar | `0x5BA0AB mov al,[eax+ecx]` only if other<4 | **yes since P01** |
| `0x5BA080` GetRelation | `0x5BA090 movzx eax,byte [eax+ecx]` only if other<4 | no (other<4) |
| `0x5BA400` SetX[other] | `0x5BA40F mov [ecx+eax*4+0x158],edx` if other<4 | no (other<4) |
| `0x5BA420` GetX[other] | `0x5BA42B mov eax,[ecx+eax*4+0x158]` if other<4 | no (other<4) |
| `0x5BA3B0` | `0x5BA3D4 mov ecx,[ecx+0x154]` | **no, unconditional** |
| `0x5BA850` | `0x5BA86B mov eax,[ecx+0x1c]` | **no** |
| `0x5BB0F0` | `0x5BB0F3 mov edi,[ecx+0x14]` (town list) | **no** |
| `0x5BB190` | `0x5BB1B9 mov edx,[esi+0x154]` | **no** |
| `0x5BB3F0` | `0x5BB3F0 mov edx,[ecx+0x14]` | **no** |
| `0x5BBB00` | `0x5BBB00 mov edx,[ecx+8]` | **no** |
| `0x5BBB20` | `0x5BBB24 mov ecx,[esi+8]` | **no** |
| `0x5BBE30` | `0x5BBE30 mov edx,[ecx+8]` | **no** |
| `0x5BBF50` | via `0x5BA3B0` / `0x5BBFE6 movzx eax,[edi+0x18]` | **no** |
| `0x5BC100` | `0x5BC19E mov edx,[esi+0x154]` | **no** |
| `0x5BC310` | annexation transfer: `this` kept in ebx/[esp+0x44]; the simulator did not reach a deref within its limits | unresolved [H: unsafe] |

## 2. DEREF and unsafe PASSES-NULL sites, grouped by subsystem

**Index source** decides whether a nation-5 town can reach a site:
- **TOWN**: the raw town byte `+0x390`/`+0x358`. These are the real option-C hazards.
- **NPC**: `0x43EDF0` = NPC data+0x12. It is set from the town with `>=4 -> +0x391`, so it is
  always 0..3 [S per vanilla_nation5_path §3.2].
- **CONV**: convoy `+0xB8`.
- **EVT**: an event or dialog byte.
- **LUA**: a script argument.
- **SELF**: CNation+0x18.

| Subsystem | Site (VA, instruction) | Containing fn | Index | nation-5 town reaches it? |
|---|---|---|---|---|
| **Economy** | `0x5C86BD mov ebp,[edx+0x20]`, `0x5C86E1 mov edx,[eax+edx*4+0x24]`, `0x5C8702 mov ecx,[ecx+0x20]` | `0x5C8650` Lager per-good share | TOWN `+0x358` | **YES**, if the town has Lager+0xC bit 0 (governor or viceroy seat), §4. **Observed crash.** |
| Economy / convoys | `0x5B41C7 cmp [edx+0x20],0`, `0x5B41F1 mov ecx,[ecx+0x20]`, `0x5B4340 rep movsd` from `[null+0x24]`, `0x5B43AA mov ecx,[eax+ecx*4+0xc4]` | `0x5B40D0` (convoy state machine `0x5B53C0` sub-state 2: goods 0xC..0xF unloaded into the convoy's town `0x635C40`). **Corrected (P05):** only `0x5B41C7`/`0x5B41F1` (P05 A1/A2) serve goods 12..15; the `0x5B42EB`/`0x5B438D` loads (P05 B1/B2: `0x5B4340`, `0x5B43AA`) serve goods 0..11, see P05 fix 2 | TOWN `[ebp+0x390]` | **YES** [H] when such a convoy docks at a nation-5 town with population > 0 (`0x5B41A9 test ax,ax` on `+0x38A`) |
| Economy / convoys | `0x5B4144 rep movsd` from `[null+0x24]` | `0x5B40D0` | CONV `+0xB8` | only for a convoy owned by nation ≥4 |
| **Annexation** | `0x5BC4B5 mov eax,[eax+0x14]` (only if town+0x44 & 0x2000, i.e. viceroy), `0x5BC4D4`, `0x5BC59D inc word [eax+0x16c]`, `0x5BC5D3`→`0x5BBB20` | `0x5BC310` transfer (callers `0x6014EB`, `0x605DD7`) | TOWN (old owner = `0x5BC476 mov cl,[edi+0x390]`) | **YES**, if the AI annexes a nation-5 town [H: whether target selection can pick one is not checked] |
| Annexation | `0x6014EB` passes NULL `this` → `0x5BC310` | `0x6013D0` | EVT `+0x59` (new owner) | only if the event names an owner ≥4 |
| Annexation / viceroy | `0x5BC002`, `0x5BC024`, `0x5BC098`, `0x5BC0C6` | `0x5BBF50` SelectNationForAnnexation | SELF / loop bl<4 (`0x5BBFFA cmp bl,4`) | no |
| Annexation re-balance | `0x5BA230` | `0x5BA130` | outer guard | no (dead) |
| **UI / letters** | `0x5E75E8`→`0x5BB0F0` | `0x5E74B0` CLetterBuildingLost::Create | TOWN `0x5E75C7 movzx eax,[eax+0x390]` | **YES**, when a building in a nation-5 town is lost [H] |
| UI: nations page | `0x4B1719 mov ecx,[ecx+0x1c]`, `0x4B18F1`/`0x4B1940`, `0x4B19CD` | `0x4B16B0` | loop/page byte | no (0..3 page rows) [H] |
| NPC dialogs (viceroy/governor) | `0x447439 and byte [eax+0x13c]`, `0x4474FC`, `0x44791D`, `0x447F44`, `0x448124`, `0x4487A7`, `0x4487D0`, `0x44888C`, `0x4488A1` | `0x4473E0`, `0x447490`, `0x4477C0`, `0x447ED0` | NPC (`0x43EDF0`); `0x448876 [eax+0x19]` dialog byte | no (NPC nation = display power) |
| Lua | `0x41DDDD`→`0x5BA420` | `0x41DD50` Global_GetLastBuccActionDate | LUA | only if a script passes ≥4 [H] |
| Events: peace/war | `0x5F52B5`, `0x5F52D1`, `0x5F57BA`, `0x5F57D6`→`0x5BBB20`; `0x5F5583 mov edi,[eax+8]` | `0x5F50F0`, `0x5F56E0` (CEventPeace), `0x5F5360` war start | EVT pair (vanilla pairs <4) | no in vanilla |
| Events: misc | `0x5EEA6E` explicitly calls `0x5BC100(NULL)` on the ≥4 branch; `0x5F3C4D mov edi,[esi+0x168]` | `0x5EEA50`, `0x5F3C30` | EVT `+8` / `+0x19` | only if the event byte is ≥4 |
| Military AI | `0x5B5340`→`0x5BA400` | `0x5B4540` | CONV `+0xB8` | only for a convoy of nation ≥4 |
| Military AI | `0x63C360`→`0x5BBB00`, `0x63C370`→`0x5BB3F0` | `0x63C280` attack-mask builder | arg P (convoy nation) | only for a convoy of nation ≥4 |
| Military AI | `0x63C7AB` (unresolved) | `0x63C6C0` | arg | only for a convoy of nation ≥4 |

"Convoy of nation ≥4": pirate convoys (4) evidently never reach these military paths,
because vanilla runs with pirates. A **nation-5 convoy** could appear [H] if a ship
spawned for a nation-5 town takes the town's raw byte as its owner. Check this next to
`research/nation5_index_safety.md` U1–U3.

## 3. Other per-nation lookups that can return NULL (task 3)  [S]

- `0x417DC0 GetNation(idx)` (ecx=0x702140, `[0x702140+0x9D4+idx*4]`, which is the same array)
  returns NULL for idx≥4 (hostility_map §1). Its callers are **not** among the 109 direct
  refs. The ones that feed `IsAtWar` are covered by P01; the rest are not audited here.
- `0x5EEA50`: a tiny event thunk. On the ≥4 branch it **explicitly** does `xor eax,eax /
  mov ecx,eax / call 0x5BC100` (0x5EEA6A..6E), which is a guaranteed crash for nation ≥4.
- `0x6350D0` (`CConvoyCreate::NewKonvoiMilitary`) is NULL-safe (`test eax,eax`).
  `0x640120` is NULL-safe on arg0.
- Per-nation **data** inside CNation indexed by *other*: `+0x158[other]` (`0x5BA400`/`0x5BA420`)
  and `rel[other]`. All are guarded `other<4`, so a nation-5 *other* reads nothing. Safe.

## 4. The observed crash at 0x5C86BD, explained  [S unless marked]

`0x5C8650` is `thiscall(CStadtLager* this, BYTE good)`, `ret 4`:

```
5C8656 mov eax,[esi+0xc] / mov ecx,1 / test ecx,eax / jne 5C866B   ; Lager+0xC bit0 clear -> return 0
5C866C mov bl,[esp+0x1c]          ; bl = good id
5C8670 cmp bl,0x10 / jb  -> [esp+0x1c]=0
5C8675 cmp bl,0x12 / mov [esp+0x1c],cl(=1) / jbe   ; [esp+0x1c] := (good in 0x10..0x12)
5C8683 cmp bl,0xc / jb -> cl=0
5C8688 cmp bl,0xf / jbe keep cl=1 ; cl := (good in 0x0C..0x0F)
5C868F xor eax,eax                ; return value 0
5C8691 test cl,cl / jne 5C86A5    ; goods 12..15 -> proceed
5C8699 mov cl,[esp+0x1c] / test cl,cl / je 5C8765   ; goods 16..18 -> proceed, else return 0
5C86A5 movzx ecx,[esi+0x358]      ; town nation
5C86AC cmp ecx,4 / jae 5C86BA / mov edx,[ecx*4+0x702b14] / ... / 5C86BA xor edx,edx
5C86BD mov ebp,[edx+0x20]         ; CRASH for nation>=4 (edx=0)
```

So `[esp+0x1c]` is the argument slot, reused as a "good is 16..18" flag, and `cl` is the
"good is 12..15" flag.

**What it computes:**
- `CNation+0x20` = the total population of the power's towns that have Lager+0xC bit 0
  (`0x5BA6A7 test byte [ebp+0x44],1 / add [esi+0x20], word [ebp+0x38A]` in the nation
  statistics fn `0x5BA5A0`).
- `CNation+0x24[good]` = the power's summed town consumption (`0x5BA65F..77`).
- 0x5C8650 returns `+0x24[good] * pop(+0x352) / +0x20 * [+0x2FC] / 256`. That is this
  town's population-weighted share of the power's demand for goods 12..18.

**Caller:** the Lager daily tick `0x5C9460`, called for **every** town (`0x5EF848` →
`0x5C6D70` → `0x5C6D96`). It calls `0x5C8650` for goods 12..15 (`0x5C95ED`) and 16..18
(`0x5C960F`) with no nation guard. This matches the observed stack `0x5c95f2 0x5c6d9b 0x5ef84d`.

**The gate is Lager+0xC bit 0 (CStadt+0x44), "administrative seat":**
- It is set only in `CStadtCreate 0x61C320`:
  - `0x61C3CE call 0x623EC0` (template `+0x16 == 1`) → `push 1 / call 0x624C20` (Lager+0xC |= mask);
  - `0x61C4B0 call 0x623EF0` (`+0x16 == 2`) → `push 0x2001`.
- The staedte.ini loader writes template `+0x16`:
  - `Gouverneur=1` → 1 (`0x624082 push "Gouverneur" … 0x62408E mov byte [esi+0x16],1`);
  - `Vizekoenig=1` → 2 (`0x624098 … and eax,2 / 0x6240A7 mov [esi+0x16],al`).
- The only other writer is the generic event `0x5F1722` (mask taken from the event object).
- The bit is saved and restored (the CStadt loader `0x5FF2C0` reads `+0x44`).

**Why Margarita crashes and Tortuga does not:**
- `staedte.ini`: **Margarita has `Gouverneur=1`**, so bit 0 is set and the function reaches
  0x5C86BD on the first economy tick.
- **Tortuga has neither key**, so it returns at `0x5C8660`.
- It is **not** player property: the player's warehouse and the `0x600000` bits at Lager+8
  play no part.
- So every one of the 8 governor towns and 4 viceroy towns (12 in total) crashes the same
  way if flipped to 5. The other 48 towns do not.

**Vanilla "Your Own Town" is protected:**
- It is created by `0x61BDE0`, not `0x61C320`, so `0x624C20` is never called for it.
  `0x61BDE0` → `0x61CCE0`, `AddToNation(…,1)`, then `0x624D30`, which touches only
  Lager+8. The 4 direct callers of `0x624C20` with a constant mask containing bit 0 are
  both in `0x61C320`.
- The Spezial templates carry no Gouverneur or Vizekoenig key [H: only the key's absence was
  checked].
- So the player town keeps bit 0 = 0, and 0x5C8650 returns 0 before the lookup. Vanilla is
  safe by never combining nation 5 with an administrative seat.

## 5. Patch estimate (task 4)

> **Superseded by `patches/p05_nation5_town_safety.py`** (sites `0x5C86A5`, `0x5B41B0`, `0x5B41DA`, `0x5B42EB`, `0x5B438D`, `0x5BC49E`, `0x5BC59D`, `0x5BC5D1`, `0x5E75C7`, `0x5BC100`); see its docstring. The detours proposed below at `0x5C86AC` and `0x5BC476` were not used as written. Original bytes at every P05 site are pinned as `P5-*` facts in `tools/check_facts.py`.

**Option C, nation byte 5 with no CNation.** The minimum to cover every TOWN-indexed site is
**4 detours**, on top of P01:
1. `0x5C86AC`: replace the 5-byte `cmp ecx,4 / jae` with a jump to a stub that does
   `cmp ecx,4 / jae 0x5C8765 (return 0) / jmp 0x5C86B1`. This covers all 3 derefs. A rel8
   patch cannot reach 0x5C8765. Alternative: clear Lager+0xC bit 0 when flipping a town to 5,
   with no code change; that loses the town's admin role. [H]
2. `0x5B40D0`: for a town ≥4, skip the population-share block (`0x5B41B0` → `0x5B4202`) and
   the `0x5B42EB` block. 2 small detours, or one detour that substitutes the display byte
   `+0x391`. [H]
3. `0x5BC310`: refuse to annex an old owner ≥4, or substitute `+0x391`. 1 detour at `0x5BC476`. [H]
4. `0x5E75C7`: read `+0x391` instead of `+0x390`. That is a 1-byte displacement change, the same
   trick as P03. [H]

**Defensive hardening** of the 48 latent sites:
- ~12 entry stubs (`test ecx,ecx / jz ret-0`) on the unconditional-deref CNation methods
  listed in §1;
- ~8 inline fixes (`0x5EEA50`, `0x5F3C30`, `0x5F5360`, `0x5B40D0` CONV, `0x4B16B0`, `0x447470`
  family).

That makes **4 required + ~20 optional** small patches.

**Alternative, give index 5 a real CNation:**
- It does not help by itself: every site tests `n<4` **before** reading the table, so all
  100 guards still produce NULL.
- It needs:
  - a relocated ≥6-slot `g_nations`, with all 109 disp32 references rewritten;
  - 100 guard immediates changed;
  - objects for index 4 (pirates) as well as 5;
  - a CNation construction that the rest of the code accepts. Its `rel[4]`, `+0x144[4]`
    and `+0x158[4]` arrays and the 6-pair peace table are all sized for 4 powers.
- That is **≥200 edits plus layout risk**, versus ~4–24 for option C.
