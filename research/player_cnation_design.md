# Option C+: a real CNation for the player nation (index 5)

Static RE and design only. Nothing was run, nothing was patched.
Target: `reverse-engineering/_re/PR2.exe.unpacked.exe` (pinned build, ImageBase 0x400000).
Every VA was disassembled with capstone from the real bytes. Scripts are in the session
scratchpad (`agent_cnation/pe.py`, `sweep.py`, `classify.py`, `flag.py`, `table.py`).

Labels:
- **VERIFIED-STATIC**: read from the exe bytes.
- **HYPOTHESIS**: an inference that still needs a check.

## 0. Answer in one paragraph

A player CNation is cheap to build, because the class is self-contained:
- it is 0x170 bytes;
- its ctor `0x5BBC70(idx)` only zero-fills fields and allocates 5 empty list heads;
- its dtor `0x5BBDB0` only frees those lists;
- it has symmetric `Save`/`Load` methods (`0x5BB630`/`0x5BB820`).

`g_nations` is not a free global. It is the member `World+0x9D4` of the static World object
at `0x702140`, and slots [4]/[5] would overlap the next member, `World+0x9E4`, an array of
60 dwords. So index 5 needs an array somewhere else.

**Recommendation:** C+ in a *mirror* form:
- Add a 6-slot `nations6` array in `.nation`. Slots [0..3] mirror the vanilla slots, [4]=NULL, [5]=player.
- Keep it in sync at the 3 VERIFIED writers of `World+0x9D4`.
- Opt sites in one at a time: rewrite the disp32 to `nations6` and change `cmp r,4` to `cmp r,6`. That is 5 bytes in place, with no stub.
- Only the 68 ternary-shaped sites (plus 6 ternary-equivalent ones) are array-safe to enable. All 25 block guards stay at 4.
- Persist the player object as one extra blob inside the World save stream, behind a magic tag.

Plain C (per-site detours) and full relocation, option (a), are both worse; see §7.

## 1. CNation (VERIFIED-STATIC unless marked)

### 1.1 Allocation, ctor, dtor
| What | Evidence |
|---|---|
| Size **0x170** | `0x5D14B0 push 0x170` / `0x5D14B5 call 0x404070` (operator new wrapper, cdecl). The same appears in load: `0x5D2345 push 0x170` / `0x5D234A call 0x404070` |
| **Ctor `0x5BBC70`**: `__thiscall CNation(int idx)`, `ret 4`, has an SEH frame | `0x5D14D1 push ecx` (the loop byte) / `0x5D14D2 mov ecx, eax` / `0x5D14D4 call 0x5bbc70`. The arg sits at `[esp+0x38]` after 5 outstanding `push 0xc` → `0x5BBD2B mov al, byte ptr [esp + 0x38]` / `0x5BBD39 mov byte ptr [esi + 0x18], al` |
| Ctor body | It allocates five 12-byte list sentinels through `call dword ptr [0x67f9d0]` (STLport node alloc) into +4, +8, +0xC, +0x10, +0x14, each with `next=prev=self`. It then zeroes: +0x24/+0x74/+0xC4 (`rep stosd` ×0x14 each, twice), +0 (`0x5BBD3C mov dword ptr [esi], ebx`, so rel[0..3]=0), +0x1C, +0x20, +0x13C, +0x168, word +0x16C, and +0x158..+0x167. It sets `+0x144 = 0xFFFFFFFF` (`0x5BBD83`) and `+0x154 = 0x10FFFF` (`0x5BBD2F`). It does not touch any global |
| **Dtor `0x5BBDB0`**: `__thiscall`, no args, plain `ret` | `0x5A93E0` (list clear + free sentinel) on +0x14, +0x10, +0xC, +8, +4. Nothing else |
| Free | `0x5D12D2 push ebp` / `0x5D12D3 call 0x4040b0` (operator delete, cdecl) after the dtor |

### 1.2 Field layout (from ctor, `Load 0x5BB820`, `Save 0x5BB630`, and readers)
| Off | Type | Meaning / evidence |
|---|---|---|
| +0x00 | `byte rel[4]` | Relation to power 0..3; `&0x7F` = state, 1 = war. `IsAtWar 0x5BA0A0` and `GetRelation 0x5BA080` (`cmp al,4; jb; or al,0xff; ret 4`): both return a fixed value for other≥4 |
| +0x04 | list | Loaded by `0x5BB410` |
| +0x08 | list | Loaded by `0x5A9470`. Base walk `0x63B4DA add eax, 8` and `0x63CB1B mov esi, [esi+8]` |
| +0x0C, +0x10 | lists | Loaded by `0x5A9470`. `0x44C7EB mov eax, dword ptr [0x702b20]` / `add eax, 0x10` (Spain's +0x10 list) |
| +0x14 | list of town handles | Loaded by `0x5BB520`. Node = {next, prev, handle at +8}. Insert-unique `0x5C97D0` (`ret 4`, returns AL); remove `0x636630` (`ret 4`, AL=0 if absent, safe). Both are used by `AddToNation` (`0x5C9E35`, `0x5C9E4B`) |
| +0x18 | byte | Own index. Written by the ctor, and **overwritten by Load** (`0x5BB896 mov byte ptr [ebx + 0x18], al`) |
| +0x1C, +0x20 | dword | Read by the crash site `0x5C86BD mov ebp, dword ptr [edx + 0x20]` |
| +0x24 / +0x74 / +0xC4 | `dword[20]` each | e.g. `0x5C86E1 mov edx, dword ptr [eax + edx*4 + 0x24]` (guarded `cmp bl,0x14`) |
| +0x114 | `dword[10]` | Load copies 0x28 bytes |
| +0x13C | dword | |
| +0x144 | `byte[4]` | Viceroy candidate sites (FF = none). See vanilla_nation5_path.md |
| +0x154 | dword | Handle-style bitfield; bits 16..20 are rechecked on load |
| +0x158 | 16 bytes | Save version > 0x414 |
| +0x168 | dword | Save version > 0x423; read at `0x5F1A3C`, `0x5F1B48` |
| +0x16C | word | Annex counter (version > 0x429). Zeroed by `SetRelation` at `0x5D10ED`/`0x5D1105` |

### 1.3 Where `g_nations` lives and who writes it
- **`g_nations` = `World+0x9D4`**, with **World a static singleton at `0x702140`**. `0x702140+0x9D4 = 0x702B14`.
  - All 22 callers of `World::GetNation` (`0x417DC0`: `cmp eax,4; jae → 0`, else `mov eax, dword ptr [ecx + eax*4 + 0x9d4]`, `ret 4`) do `mov ecx, 0x702140` just before the call.
  - **Whoever reads `World+0x9E4` (60 dwords) reads exactly where slots [4]/[5] would go** (`0x5D1290 lea eax,[edi+0x9e4]`, loop 0x3C). In-place growth is impossible.
- The **only writers** go through `this+0x9D4`. None is an absolute store; there are 0 absolute writes among the 109 refs:

| Writer | Code |
|---|---|
| `World::Reset 0x5D1270` | `0x5D12B7 lea esi, [edi + 0x9d4]`; dtor + delete each; `0x5D12DF mov dword ptr [esi], ebx` (0) |
| `World::CreateNations 0x5D1480` | `0x5D149C call 0x5d1270` (reset first); `0x5D14A7 add esi, 0x9d4`; loop `bl=0..3`: new(0x170), ctor(bl), `0x5D14DF mov dword ptr [esi], eax` |
| `World::Load 0x5D2250` (`ret`, stream at `[esp+0xa4]`, version at `[esp+0xa8]` in-frame) | `0x5D2271 call 0x5d1270`; `0x5D233F lea ebx, [ebp + 0x9d4]`; loop: new, ctor(i), `0x5D23B3 mov dword ptr [ebx], eax`, `0x5D23B5 call 0x5bb820` (CNation::Load(stream, version), `ret 8`) |
| `World::~World 0x5CE070` (no direct callers; static-object teardown, HYPOTHESIS atexit) | `0x5CE09A lea ebx, [esi + 0x9d4]`; dtor + delete, no clear |

- Other `World+0x9D4` users (read-only):

| Function | Code |
|---|---|
| `World::Save 0x5D1120` | `0x5D118D add edi, 0x9d4`, 4× `call 0x5bb630` |
| Daily tick `0x5D27BA..` | `0x5D286E lea ebx, [edi + 0x9d4]`, 4× `call 0x5ba5a0` |
| `World::SetRelation 0x5D0FA0` (rejects a or b ≥ 4) | `0x5D0FD2`, `0x5D0FEC`, `0x5D0FF6`, `0x5D109C`, `0x5D10BA`, `0x5D10E6`, `0x5D10FE` |
| `GetNation` | `0x417DC9` |

  Unrelated classes also have a `+0x9D4` field (`0x450B10 cmp dword ptr [ecx + 0x9d4], 1`, `0x506526`, `0x582980`): HYPOTHESIS, not World.
- An absolute reference outside the 109 counted by check_facts: **`0x44C7EB mov eax, dword ptr [0x702b20]`** (= `g_nations[3]`).

### 1.4 When the objects exist
- New game: `0x522A60` → generator `0x580C20` (`[0x700500+0x40]` = phase).

  | Phase | Call |
  |---|---|
  | 0 | `0x580C2D call 0x5809a0` (session clear → World reset) |
  | 3 | `0x580CC5 call 0x5d1480` (create 4) |
  | 8 | per nation: `0x580DA6 GetNation` → `0x5BA5A0`, `0x580DCE` → `0x5BBEB0` (sites) |
  | 9 | events/peace (`0x5F6690` ×4 …) |

- Load: `0x581070` (from `0x5816AC`/`0x5819C2`) → `0x58107C call 0x5809a0` → … → `0x581238 call 0x5d2250`.
- Save: `0x580E70` → `0x5807C0` (size pass + fill pass) → `0x580891 call 0x5d1120`.
- Session clear `0x5809A0` (callers `0x4037DD`, `0x580C2D`, `0x58107C`, `0x581707`, `0x581930`, `0x5819E9`, `0x581A5A`) frees the nations.

## 2. Serialization (VERIFIED-STATIC)

CNation **is** serialized inside the `.pr2` stream:
- `World::Save` writes 4 blobs with `CNation::Save 0x5BB630` (`thiscall(stream)`, `ret 4`), then a `'{'` marker (`0x5D11B0 mov byte ptr [eax], 0x7b`).
- `World::Load` creates 4 fresh objects and calls `CNation::Load 0x5BB820` (`thiscall(stream, version)`, `ret 8`). It then requires `'{'` (`0x5D2403 cmp cl, 0x7b` / `je`, else throw `0x64DC32`).
- The count is fixed at 4 and there is no length prefix.

Stream object layout:
- `[+0]` base, `[+4]` cursor.
- `[+8]`: size when loading; capacity when saving, where 0 = the size-only pass. Writes are skipped when `[+8]==0` (`0x5D11A6 mov eax,[esi+8]; test eax,eax; je`).
- `0x411280(n)` checks that n bytes are available and throws otherwise.

Town nation bytes are restored raw (`0x5C9AF6`).

## 3. Making index 5 resolve

### 3.1 Site census (109 refs to 0x702B14, re-derived; check_facts buckets them 100/6/3, mine 99/7/3)
Every guard is `cmp r32, imm8` (`83 F8..FF xx 04`, 3 bytes, imm last). Every load has disp32 at byte offset 3 (99 sites), 2 (7), 1 (2) or 4 (1). All the edits below have the same length. VERIFIED-STATIC (`table.py`, assert on every site). Each guard compares the same register that indexes the load.

| Class | n | Bound raise 4→6 (with nations6[4]=NULL) |
|---|---|---|
| **TERNARY** `cmp r,4; jae L; mov R,[r*4+G]; jmp M; L: xor R,R` | 68 | **Array-safe.** The guard protects only the load. n=4 and n≥6 still yield NULL |
| **BLOCK, ternary-equivalent** (else path also yields 0) | 6 | Array-safe: `5B4302 5D33C9 5EEA59 5F5555 5F556A 63B8D3` |
| **BLOCK with a NULL test** `cmp;jae SKIP; mov p,..; test p,p; je SKIP; <block>` | 22 | Raising opens the whole block to n=5 (n=4 still skipped). **Keep 4.** Many are setters that would push a 5 into other objects (see below) |
| **BLOCK, must stay 4** | 3 | See below |
| LOOP4 `cmp i,0x10` (byte-offset walk) | 7 | Only the disp changes. They stay 0..3 |
| BASEWALK `mov r, 0x702B14` | 3 | Only the imm changes. They stay 0..3 |

**Bounds that must stay 4 (other 4-sized state behind the guard):**
- `0x5C9E0C cmp eax,4` (block at `0x5C9E11`, `AddToNation` new owner). Raising it would let `AddToNation(5, force=0)` write **display byte = 5** (`0x5C9E5A mov byte ptr [esi + 0x359], bl`). That breaks every display-byte table read (P03, `0x40FC70`).
- `0x6350DC cmp esi,4` (military-convoy builder). The block reads `0x63511A mov al, byte ptr [esi + 0x6ac4b4]`, and `byte[4]` gives **0xF0 for n=5** (same as U1).
- `0x5EF980 cmp eax,4` (town tick, 639-insn block). It re-reads `+0x390` and indexes `0x5EFBD3 mov cl, byte ptr [edx + eax*4 + 0x6a5158]` (`byte[4][4]`) and `0x5EFD81 mov cl, byte ptr [edx + eax + 0x6a5168]` (`byte[4][3]`). n=5 lands in the neighbouring tables (types 07–0D, 03–07: valid by luck), and AI owner logic would run.

**Setters among the NULL-test blocks** (raising them would let a 5 escape into other objects; keep 4):
- `0x5A9E03`/`0x5A9E2B`: convoy nation `+0x24`; research invariant "convoys never carry 5".
- `0x63707A`: military convoy `+0xB8`/`+0x64`.
- `0x61C3A1`: `CStadtCreate` → `AddToNation`.
- `0x41E7F4`: Lua setter `[nation+0x140]`.

**GetNation `0x417DC4 cmp eax,4`** (22 callers, mostly the viceroy dialog `0x444E..0x4486`): keep 4.

**Limits:**
- The block scan follows only the guarded register inside the block. Copies to other registers or the stack, and callees, were not traced.
- For a *ternary* site, enabling does not change array safety, but the code after it now runs with a real object and n=5. That downstream code is the same under (a) and (b) and must be reviewed per site (the other agent's deref list).

### 3.2 Option (a): full relocation
Rewrite every reference so the old slots are dead:
- the 109 absolute refs;
- `0x44C7EB` (→ `nations6+0xC`);
- **14 World-relative refs**:
  - `0x417DC9`, and `0x5D0FD2`/`0x5D0FEC`/`0x5D0FF6`/`0x5D109C`/`0x5D10BA`/`0x5D10E6`/`0x5D10FE`. Each is `mov r,[base+idx*4+0x9d4]` → `mov r,[idx*4+nations6]`, 7→7 bytes;
  - `0x5D118D`, `0x5D12B7`, `0x5D14A7`, `0x5D233F`, `0x5D286E`, `0x5CE09A`. Each is `lea/add r, …0x9d4` (6 bytes) → `mov r, imm32` + `nop`.

That makes 124 same-length edits. They are behavior-neutral by themselves. The risk: any reader I missed (a derived pointer) silently reads the now-dead old slots, which stay NULL forever, and crashes on powers 0..3.

### 3.3 Option (a-mirror) (recommended)
- Leave all 124 sites untouched.
- `nations6[0..3]` is a copy, refreshed by 3 hooks at the only writers (§1.3).
- An enabled site gets the same 5-byte in-place edit as in (a).
- Unknown readers keep using the authoritative vanilla array. Only opted-in sites depend on the mirror.

### 3.4 Option (b): detour each deref site
Each site needs a stub that computes `n==5 ? player : n<4 ? g[n] : 0`.
- The ternary is 16 bytes with rel8 jumps, which `pe_patch.detour` cannot displace. So the whole ternary must be replaced with `jmp stub` + nops.
- That costs ~25 B of code per site and one more capstone-checked detour each.
- The semantics are the same as (a-mirror). (a-mirror) is that same idea done in place.

## 4. Fixed loops and walks (VERIFIED-STATIC)

The following iterate exactly 0..3, so AI powers never see the player object:
- the 7 LOOP4 sites (`41B2B6 42D4CC 601192 605D79 63AFE5 63B002 63BB97`);
- the 3 base walks (`0x5BA13E` counter `ebx=4`; `0x63B4BA` `[esp+0xc]=4`; `0x63CADB` `[esp+0x13]=4`);
- World's own loops: Save, Load, Create, Reset, the daily tick `0x5D2886 → 0x5BA5A0`, the dtor, and SetRelation (`0x5D10D6 cmp al,4`).

The player nation gets no AI tick, no annexation timer, and no peace-pair events: the `0x6AAFDC` table has 6 pairs and is guarded.

## 5. rel[] and P01

- Powers' `rel[4]` has no slot 5. `IsAtWar`/`GetRelation` guard other≥4, and `SetRelation` rejects ≥4. The byte `[p+5]` would be inside the +4 list pointer, but no unguarded `rel[n]` read is known.
- The player object's `rel[0..3]` naturally means player→power. If **the player CNation is placed statically in `.nation`**, then `player_rel` can alias `player_cnation+0`:
  - P01's absolute table and P04's `cmp byte [edx+player_rel],0` keep working unchanged;
  - `IsAtWar(this=player, other<4)` falls into the original code and reads the same bytes.
- **Required P01 fix:** with `this=player` and `other==5`, the stub's power-vs-player path does `movzx eax,[ecx+0x18]` (=5) → `cmp eax,4; jae war`, so it returns *war with itself*. Retarget that `jae` to `notpower` (which already maps 5 → peace).
- Caveat: P04 treats any non-zero byte as war. If ALLIANCE=2 is ever used, P04 must test `(b&0x7F)==1`.
- The ctor zeroes rel (peace) on every reset. Load restores it from the blob (§6).

## 6. Lifecycle and persistence (hook points VERIFIED-STATIC; behaviour HYPOTHESIS)

| Hook | Displaced bytes (all position-independent) | Stub |
|---|---|---|
| H1 Reset end `0x5D12EB` | `mov ecx, 0x702068` (5) | `nations6[0..3]=0`. If `constructed`: `dtor 0x5BBDB0(&player)`. Then `ctor 0x5BBC70(&player, 5)`, `constructed=1`, `nations6[5]=&player` |
| H2 Create end `0x5D14F5` | `mov ecx, dword ptr [esp + 0x10]; pop esi` (5) | `nations6[i]=[0x702B14+4i]`, i=0..3 (run before the displaced code, under pushad/popad) |
| H3 Load after loop `0x5D23C3` | `mov eax, dword ptr [esi + 4]; mov ebx, dword ptr [esi]` (5) | Sync as in H2. Then, if `cursor+8 ≤ base+size` and `dword[cursor]=='PNAT'`: skip the 4 magic bytes and call `0x5BB820(&player, esi, [esp+0xa8 + pushad])`. Otherwise leave the default |
| H4 Save after loop `0x5D11A6` | `mov eax, dword ptr [esi + 8]; test eax, eax` (5; displaced runs last so the flags hold for `je 0x5D11B3`) | If `[esi+8]` is set, write `'PNAT'`. Always do cursor+=4. Then `0x5BB630(&player, esi)` |

How the hooks behave:
- **Allocation:** static, 0x170 bytes in `.nation`. Game code never deletes it, because only slots 0..3 are freed. That removes heap lifetime from the problem. H1 runs at phase 0, inside Create, and inside Load, so the object is always fresh before any world exists.
- **Atomicity:** the blob is part of the single `fwrite` of the `.pr2`, so it can never disagree with the saved town bytes. Both passes (size, fill) go through the same `CNation::Save`.
- **Compatibility:**
  - Vanilla saves load in the patched exe: no magic means a default player.
  - Patched saves fail in a vanilla exe at the `'{'` check (a throw). That is acceptable, because a nation-5 town already crashes vanilla (E3).
  - A sidecar would keep vanilla-loadability, but it needs save-name plumbing for the STLport string and loses atomicity, so I don't recommend it.
- **Town list +0x14:** the MVP keeps it empty. All list walkers handle an empty list. A later step:
  - insert in the force path (after `0x5C9DD7 mov byte ptr [esi + 0x358], 5`) using `0x5C97D0`;
  - enable the *old-owner* ternary `0x5C9DF9` (safe: `0x636630` tolerates absent items) so a conquered player town leaves the list.

## 7. P05 implementation plan (ordered)

1. **check_facts:** add the VERIFIED facts above (ctor/dtor/size, the 3 writers, the hook-point bytes, `0x44C7EB`, World=`0x702140`, `0x9E4` neighbour, `Save`/`Load` rets).
2. **P05a (lifecycle, no behaviour change):**
   - `player_cnation` (0x170, align 4), `constructed` (dword), `nations6` (0x18, all 0);
   - hooks H1–H4;
   - P01 changes: `player_rel` becomes `player_cnation+0`, and the `jae war` retarget.

   Test: new game, run 30 days, SAV-01 save/reload. Expected result: identical to today, no exceptions, and the blob round-trips (read `player+0x18==5` and the rel bytes after reload).
3. **P05b (enable):** for each deref site from the other agent's list that is in the TERNARY or ternary-equivalent class, patch the load disp to `nations6` and the guard imm `04`→`06` (`pe_patch.patch_bytes` with the old bytes checked). Never touch the 3 must-stay-4 sites, the 22 NULL-test blocks, or `0x417DC4`. Deref sites inside non-ternary shapes get a per-site review or a P03-style display-byte fix.
4. Re-run E3 with Tortuga=5 at 20x for 30+ days. Then flip a visible town and check the UI.
5. Optional P06: maintain the town list and add the save/load rebuild from nation bytes.

**Risks:**
- Downstream code at enabled ternaries now runs CNation methods with `this->index==5`. Seen consumers: `0x5F4E80`, `0x5F1B30`, `0x5F3630`, `0x63C780` all guard <4; `AddToNation(5,0)` is silently ignored; `0x63ADC0` takes no index.
- The `nations6` mirror is stale if a fourth writer exists (none found).
- H3 depends on the frame offset `[esp+0xa8]`.
- The `PNAT` probe collides only if a vanilla stream had `'{'` replaced (impossible).

**Recommendation:** use **C+ (a-mirror)**.
- Its fixed cost is 4 hooks.
- Each site costs 5 in-place bytes.
- It gives one coherent "empty player nation" semantics.
- Both directions of relations persist atomically.

Plain C scales poorly: every deref site needs its own NULL policy and a stub. Full (a) adds 124 edits for no extra capability. (b) is (a-mirror) with more code.
