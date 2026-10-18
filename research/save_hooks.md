# Save/load, lifecycle and daily hooks for PR2Nation.dll

Static RE only. Nothing was run or patched. Target: `reverse-engineering/_re/PR2.exe.unpacked.exe`
(ImageBase 0x400000). Every VA was disassembled with capstone from the file bytes. Branch targets
were checked with a brute-force scan of every E8/E9/0F8x/EB/7x in `.text`. Scripts are in the session
scratchpad (`agent_save/dz.py`, `xref.py`, `sites.py`).

Labels: **VERIFIED-STATIC** means read from the exe bytes. **HYPOTHESIS** means inferred and not yet
checked at runtime.

Hook framework assumed: `dll/hook.c`. It emits `pushad; pushfd; call handler(Regs*); popfd; popad`,
then the displaced bytes, then `jmp back`. So `Regs.esp` is the esp at the hook point, and the
displaced bytes must be position-independent. Every site below has PIC displaced bytes only, and no
branch lands inside a displaced range. A target exactly at the hook start is fine.

## 1. The stream (`MemStream`, VERIFIED-STATIC)

### 1.1 What it is
- A plain 12-byte struct from `Simulation/Templates/MemStream.h` (path string at 0x6A4DC0/0x684268).
- It has **no vtable and no methods for raw I/O**. Every write and read is inlined.
- Layout:

```c
typedef struct MemStream {
    uint8_t *base;    /* +0 */
    uint8_t *cur;     /* +4  position: get = s->cur - s->base, set = assign */
    uint32_t cap;     /* +8  load: data size; save: buffer capacity (0 = sizing pass) */
} MemStream;
```

### 1.2 Writing (World::Save, `0x5D1120`)
- Pattern: `if (s->cap) memcpy(s->cur, src, n); s->cur += n;`. For example, `0x5D11A6..0x5D11B6` writes `'{'`.
- **No bounds check on write.**
- The save driver `Session::SaveGame 0x580E70` runs the serializer `0x5807C0` twice:
  1. **Sizing pass** at `0x580EBE` with `{0,0,0}`, so `base = cur = 0`, `cap = 0`.
  2. `malloc(cur - base)` at `0x580ECC`.
  3. **Fill pass** at `0x580F2D` with `{buf, buf, size}`.
- So the DLL must:
  - never dereference `cur` when `cap == 0`;
  - **emit exactly the same byte count in both passes**. Both passes run back to back in one call, with no sim tick between them;
  - otherwise it overruns the heap buffer.
- `0x5807C0` is the only caller of World::Save (`0x580891`). `0x580E70` is the only caller of `0x5807C0`. 0x580E70 has 5 callers: QuickSave, AutoSave, Lua and the UI.

### 1.3 Reading (World::Load, `0x5D2250`)
- Check: `0x411280` `void __thiscall Check(MemStream*, uint32 n)`, `ret 4`, returns nothing.
  - If `cur - base + n > cap`, it builds a **`CLoadExeption`** (RTTI `.?AVCLoadExeption@@`, ThrowInfo 0x6B0580) and calls `_CxxThrowException 0x64DC32`.
- After the check: `memcpy(dst, s->cur, n); s->cur += n`.
- Wrappers:
  - `0x411BB0` ReadDword(out*), `ret 4`;
  - `0x411C10` ReadByte(out*), `ret 4`.
- EOF and errors are signalled **only by that C++ throw**. The catches:
  - `0x581907` in the sync loader `0x5815E0`;
  - `0x581A55` in the incremental loader `0x581940`.
  - Both call Session::Clear `0x5809A0` (load aborts and the world is wiped).
- **Recommendation:** the DLL does its own bounds checks and never calls 0x411280. Throwing a MSVC exception through gcc frames is a HYPOTHESIS.

### 1.4 Save version
- Written first: `0x5807D2 mov dword ptr [eax], 0x441`.
- Load reads it at `0x5810FB` and requires `>= 0x424` (`0x5810FF cmp edi, 0x424`).
- There is no upper bound.
- Inside World::Load it is the 2nd arg, `[esp+0xA8]`. This holds at `0x5D23C3`: `0x5D239D mov edx, dword ptr [esp + 0xa8]` is passed as the version in the same loop at equal depth.
- From a hook there: `*(uint32*)(r->esp + 0xA8)`. The stream is `[esp+0xA4]`, which equals `esi`.
- **Do not bump 0x441.** The tag is self-describing.

## 2. Blob hooks

Blob format (proposed):

| Field | Size | Value |
|---|---|---|
| magic | 4 | `'P','N','A','T'` |
| `fmt_ver` | u32 | |
| `len` | u32 | |
| payload | `len` bytes | |
| `crc32` | u32 | optional |

### Option M: mid-stream, as requested (VERIFIED-STATIC sites)

**(a) Save, H4 `0x5D11A6`:** `8B 46 08 85 C0` = `mov eax, dword ptr [esi + 8]; test eax, eax`
- Runs after the 4× `CNation::Save` loop (`0x5D11A4 jne 0x5d1198`).
- Runs before the `'{'` write (`0x5D11AB je 0x5d11b3` / `0x5D11B0 mov byte ptr [eax], 0x7b`).
- The handler gets `esi` = stream and writes the blob with the 1.2 pattern.
- The displaced `test` runs after the handler, so the flags are correct for the `je`.

**(b) Load, H3 `0x5D23C3`:** `8B 46 04 8B 1E` = `mov eax, dword ptr [esi + 4]; mov ebx, dword ptr [esi]`
- Runs after the 4× `CNation::Load` loop (`0x5D23C1 jb 0x5d2345`).
- Runs before the `'{'` check (`0x5D2403 cmp cl, 0x7b`).
- The displaced code re-reads `cur` after the handler, so advancing `s->cur` in the handler is honoured.
- **Peeking is trivial**, because the position is plain memory:

```c
if (s->cur - s->base >= s->cap) return;                 /* let vanilla throw */
if (*s->cur == '{') { reset_defaults(); return; }       /* vanilla save */
if (s->cap - (s->cur - s->base) >= 12 && memcmp(s->cur,"PNAT",4)==0
    && len <= remaining-12) { copy; s->cur += 12+len; }
/* else leave cur alone -> vanilla reads 'P' != '{' -> CLoadExeption (welt.cpp line 0xCE) */
```

- Vanilla always writes `'{'` there (0x7B), and `'P'` (0x50) differs, so the probe is unambiguous.
- Consequence: **a vanilla exe rejects patched saves**. It throws at 0x5D240B, and the save is caught and cleared. That is graceful, not a crash (HYPOTHESIS for the UI).

### Option T: trailing blob (recommended; keeps saves vanilla-loadable)

- `0x581070`, Session::LoadFromStream, never checks that the stream was fully consumed. After its last read, `0x5814CF call 0x5a7220`, `esi` is reused (`0x58154E xor esi, esi`). Neither caller (`0x581726`, `0x581A22`) touches the stream again. VERIFIED-STATIC.
- So bytes appended after the last section are ignored by vanilla. That the decompressed size equals the written size is a HYPOTHESIS: `0x581B30` returns `[0x6E56AC]`.

| Hook | Site and bytes | Notes |
|---|---|---|
| Save tail | `0x580996` `5F 5E C2 04 00` = `pop edi; pop esi; ret 4` | End of `0x5807C0`, after the last section `0x580991 call 0x5a71f0`. `esi` = stream. Runs in both passes. Not a branch target. |
| Load tail | `0x5814D4` `81 FF 3E 04 00 00` = `cmp edi, 0x43e` | After `0x5814CF call 0x5a7220`. `esi` = stream, `edi` = version. A branch target at its start (`0x5814C4 jbe`) is OK. Probe: if `remaining >= 12` and magic is `PNAT`, read the blob; else use defaults. Garbage is never fatal. |

## 3. Lifecycle hooks (VERIFIED-STATIC bytes; semantics noted)

| Event | VA and bytes | Context |
|---|---|---|
| World reset (new game phase 0, load start, load failure, leave to menu) | `0x5809B3` `B9 EC 3A 70 00` `mov ecx, 0x703aec` | Session::Clear `0x5809A0`, right after `0x5809AE call 0x5d1270` (World::Reset frees the nations). Callers: `0x4037DD 0x580C2D 0x58107C 0x581707 0x581930 0x5819E9 0x581A5A`. "Before destroy" variant: `0x5809A9` `B9 40 21 70 00` `mov ecx, 0x702140` |
| New game complete | `0x580E5E` `B8 0B 00 00 00` `mov eax, 0xb` | The final step of the generator `0x580C20` (phase counter `[0x700500+0x40]`). Earlier phases: phase 3 created the nations (`0x580CC5 call 0x5d1480`), phase 8 the sites, phase 9 the events. Returning 0xB means "done" (HYPOTHESIS). `esi`=0x700500. Generic for every game the generator builds; scenario starts are untraced (HYPOTHESIS) |
| Load complete (towns valid) | `0x5815CF` `81 C4 8C 00 00 00` `add esp, 0x8c` | Epilogue of `0x581070`, used by both loaders. Reached only on success, because a throw skips it |
| Leave to main menu | `0x4037D8` `B9 00 05 70 00` `mov ecx, 0x700500` | Inside `0x4037A0`, vtable slot `0x67FF70` (MainGame leave, HYPOTHESIS), just before `0x4037DD call 0x5809a0`. Branch target at its start (`0x4037D1 je`), which is OK. The world-reset hook already covers this event |
| (design H1/H2) | `0x5D12EB` `B9 68 20 70 00` `mov ecx, 0x702068` (end of World::Reset); `0x5D14F5` `8B 4C 24 10 5E` `mov ecx, dword ptr [esp + 0x10]; pop esi` (end of CreateNations) | Optional |

Order on load: reset (0x5809B3) → blob (H3 or tail) → load complete (0x5815CF).
Order on new game: reset → nations (phase 3) → done (0x580E5E).

## 4. Date and daily tick (VERIFIED-STATIC)

### 4.1 Where the time lives
- **World time:** `dword [0x702C14]` = World `0x702140` + 0xAD4.
- **Lua `Global_GetWorldTime`** is the impl `0x41CE50 mov eax, dword ptr [0x702c14]` → `lua_pushnumber`.
  - Registered at `0x43932B push 0x41ce50`, as the upvalue of the thunk `0x4383E0`.
- **256 ticks per day:** day number = `time >> 8`.

### 4.2 The world tick
- **World::Tick `0x5D2790`** (thiscall, ecx=World). Its only caller is `0x57F0BA`.
- Each call does `time++`.
- When `(time & 0xFF) == 0`, it runs the new-day block `0x5D27AC..0x5D28A7`; otherwise `0x5D27A6 jne 0x5d28a8` skips it.

### 4.3 Date fields
- The fields are filled by `Date_FromTime 0x5CDDC0(time, u8* day, u8* month, u16* year)`, `ret 0x10`. It uses 365-day years with no leap years. The month table at `0x6A4F00` is `0, 31, 59, …, 365`.

| Field | Address | Range / meaning |
|---|---|---|
| day | **`byte [0x702C1C]`** | 1..31 |
| month | **`byte [0x702C1D]`** | 1..12 |
| year | **`word [0x702C1A]`** | `day / 365` |
| day of year | `word [0x702C18]` | `day % 365` |

- `World::SetTime 0x5CDF50` writes the start time.

### 4.4 Hooks
- **Daily hook:** `0x5D286C` `33 F6 8D 9F D4 09 00 00` = `xor esi, esi; lea ebx, [edi + 0x9d4]` (8 bytes).
  - It is inside the new-day block, after `0x5D2855 call 0x5cddc0`, so day, month and year are already today's.
  - `[0x702C18]` is still yesterday's here: it is written at `0x5D2877`. Use `edx`, or compute the day of year yourself.
  - It runs before the 4 `CNation` daily ticks (`0x5D2886 call 0x5ba5a0`). `edi` = World.
- **Monthly boundary:** vanilla uses `day == 1`. `0x5BA75F cmp byte ptr [0x702c1c], 1` sits inside CNation daily `0x5BA5A0`, and the yearly test is `0x5BA785 cmp word ptr [0x702c18], 0`. The DLL should test `[0x702C1C]==1` in the daily hook.
- **Per-tick hook (alternative):** `0x5D2790` `51 56 57 8B F9` = `push ecx; push esi; push edi; mov edi, ecx`.

Everything runs on the main thread. That is a HYPOTHESIS for autosave, but it is called from Session code.
