# Lua bridge: talking to the game's Lua from an injected C DLL

Static research (2026-10-11). Nothing was run. Targets:
`reverse-engineering/_re/PR2.exe.unpacked.exe` (the M0 target base) and the
install's `lua.dll` (`$Lua: Lua 4.1.0 (ASCARON_LUA,modified 4.0.1 source)`,
pdb `...\Ascaron\LUA\Release\lua.pdb`) plus `Ascaron.Scripting-2.6.dll`, which
owns the states. Tools were pefile + capstone; the scripts are in the session
scratchpad (`agent_lua/`: `pdis.py`, `xref.py`, `win.py`, `bindings.tsv` = all
559 binding names mapped to impl VAs).

Labels: **VERIFIED-STATIC** means read from the bytes at the given VA.
**HYPOTHESIS** means inferred and not yet run.

---

## 0. Summary

| Question | Answer |
|---|---|
| Calling convention | Every `lua.dll` export is **cdecl**: callers do `add esp,N` and the exports end in a plain `ret`. A `lua_CFunction` is `int __cdecl f(lua_State*)`. |
| Numbers | **`lua_Number` is a 32-bit `int`**: `lua_tonumber` returns it in `eax`, and `lua_pushnumber(L,int)` takes 4 bytes. Doubles are a separate type, used through `lua_tofloat` and `lua_pushfloat`. |
| Game state | `"Missions"`, obtained with `State* p = ((State*(*)(void))0x4337B0)(); lua_State* L = p->L;`. It runs `mstart.ini`, `missions.bin` and every engine binding. The only other state is `"default"`, used by the Credits screen. |
| Lifetime | The state is created once and never closed (the process lives with one `lua_State`). **The globals table is replaced** on New Game and on Load (`0x438D90` runs `lua_newtable` + `lua_setglobals`). Any function you register is lost then, so register again after it. |
| Lua errors | The engine's `_ERRORMESSAGE` (`0x438920`) **throws a C++ `CException`**, and it is called before Lua unwinds. Any Lua error in Missions is therefore fatal. This includes errors inside `lua_dostring` and `lua_call`. Swap `_ERRORMESSAGE` for a harmless C function around your own calls (§1.4). |
| Engine impl ABI | `int __cdecl impl(State* s)` where `State = {lua_State* L; bool borrowed;}`. It reads its arguments with **negative** indices and returns the number of results. |
| New functions | Use plain `lua_pushcclosure(L,f,0)` and `lua_setglobal(L,name)`, with `f` a standard `lua_CFunction`. |
| Town handle | `idx | 1<<16 | gen<<21`. `idx` is the slot in the town pool `0x702068`. For towns created by a New Game, the slot equals the `staedte.ini` order (HYPOTHESIS, strong). |

---

## 1. `lua.dll` API in this build

### 1.1 Exports (69, all cdecl). VERIFIED-STATIC (export table; ImageBase 0x10000000)

```
lua_call lua_close lua_concat lua_copytagmethods lua_dobuffer lua_dofile
lua_dostring lua_equal lua_error lua_getgccount lua_getgcthreshold
lua_getglobal lua_getglobals lua_getinfo lua_getlocal lua_getn lua_getref
lua_getstack lua_gettable lua_gettagmethod lua_gettop lua_insert
lua_iscfunction lua_isfloat lua_isnumber lua_isstring lua_lessthan
lua_newtable lua_newtag lua_newuserdata lua_next lua_open lua_pushcclosure
lua_pushfloat lua_pushlstring lua_pushnil lua_pushnumber lua_pushstring
lua_pushusertag lua_pushvalue lua_rawcall lua_rawget lua_rawgeti lua_rawset
lua_rawseti lua_ref lua_remove lua_setcallhook lua_setgcthreshold
lua_setglobal lua_setglobals lua_setlinehook lua_setlocal lua_settable
lua_settag lua_settagmethod lua_settop lua_stackspace lua_strlen lua_tag
lua_tocfunction lua_tofloat lua_tonumber lua_topointer lua_tostring
lua_touserdata lua_type lua_typename lua_unref
```

- There is no `lua_baselibopen` or any other lualib. The base library (`print`, `error`, `call`, `tostring`, `format`, `import`, `require`, bit ops and so on) is installed by `Ascaron.Scripting` through `ScriptManager` vtbl+8.
- `lua.dll` **statically links its own CRT and heap**. Never `free()` anything it returns. A `lua_tostring` pointer is valid only while that value stays on the stack.
- `PR2.exe` imports 40 of these exports (IAT `0x67F8FC..0x67F998`, thunks `0x64D7EC..0x64D8D6`). It does **not** import `lua_open`. Get the exports with `GetModuleHandleA("lua.dll")` + `GetProcAddress` to bind to the same instance the game uses.

### 1.2 Modified types. VERIFIED-STATIC

Type-name table at `0x100157B8`:

| Id | Type | Notes |
|---|---|---|
| 0 | userdata | |
| 1 | nil | |
| 2 | **number = int32** | value at `TObject+8`, 4 bytes |
| 3 | **float = double** | 8 bytes |
| 4 | string | |
| 5 | table | |
| 6 | function | |

`TObject` is 16 bytes.

| Function | Signature | Evidence |
|---|---|---|
| `lua_tonumber` | `int (L, idx)`; returns 0 when the value is not a number | `0x100013D0`: `mov eax,[o+8]` |
| `lua_pushnumber` | `void (L, int)` | `0x10001590` stores a dword and tt=2 |
| `lua_tofloat` | `double (L, idx)` | `0x10001400`: `fld qword` |
| `lua_pushfloat` | `void (L, double)` | `0x100015C0` |
| `lua_isnumber`, `lua_isfloat` | `int (L, idx)`; true when the value is of that type or convertible to it | |
| `lua_tostring` | `const char* (L, idx)`; converts the value in place | |
| `lua_pushcclosure` | `void (L, lua_CFunction, int nup)` | `0x10001680`, which jumps to `0x100098C0` |
| `lua_pushusertag` | `void (L, void*, int tag)`; tag must be 0 or -1 unless created with `lua_newtag` | `0x10001690` |
| `lua_getglobal` | `void (L, const char*)`; pushes the value | `0x10001700` |
| `lua_setglobal` | `void (L, const char*)`; pops the value | `0x10001960` |
| `lua_open` | `lua_State* (int stacksize)` | `0x10008000` |

A C function is called as `cl->f(L)`, cdecl (`0x1000399E`). Upvalues are pushed after the arguments, so upvalue *k* is at the top. The return value *n* means "the top *n* stack values are the results". This is stock Lua 4.0 behaviour.

### 1.3 Calls, protection and errors. VERIFIED-STATIC

- **`lua_dostring(L,s)`** (`0x10003DC0`) calls `lua_dobuffer(L,s,strlen(s),s)`; the chunk name is the source text itself.
- **`lua_dobuffer`** (`0x10003D90`) runs a protected parse (`0x10003D40`; byte `0x1B` = precompiled chunk). It then calls `lua_call(L,0,LUA_MULTRET)`. It returns a status: 0 = OK, 1 = RUN, 3 = SYNTAX, 4 = MEM (the Lua 4.0 codes). **The results stay on the stack**, so save the top with `lua_gettop` and restore it with `lua_settop`.
- **`lua_call(L,nargs,nres)`** (`0x10003B50`) is **protected**. It goes through `luaD_runprotected` (`0x10003700`): `_setjmp3` at `0x1000AFE0`, `L->errorJmp` at `L+0x14`. On error it sets `L->top = func` and returns the status.
- **`lua_rawcall`** (`0x10001B60`) is unprotected: it jumps straight to `luaD_call` `0x100039C0`.
- **`lua_error(L,msg)`** (`0x100036D0`):
  1. If `msg` is set, it calls `message()` (`0x10003DF0`). That looks up the global **`_ERRORMESSAGE`** and calls it with the message.
  2. It then calls `breakrun` (`0x10003E60`). If `L->errorJmp` is set, it does `longjmp` (`0x1000B5DC`). Otherwise it prints "unable to recover; exiting" and calls **`exit(1)`** (`0x1000B5A9`).
  3. So an error outside any protected call kills the process.
  4. There is no `_ALERT` in `lua.dll`.

### 1.4 The engine's `_ERRORMESSAGE` throws. VERIFIED-STATIC

`0x438D90` ends with `_ERRORMESSAGE = <dispatcher 0x4383E0, impl 0x438920>`. The handler `0x438920`:
1. builds `"Error\n----\n<msg>\nExecuted script: '…'\nLUA callstack\n…Source\n…"` from `lua_getstack` and `lua_getinfo("Slun")`;
2. then calls `CException` ctor + `_CxxThrowException(…, 0x6AE830)` (`0x438D70`, `0x438D83`).

It throws **inside `message()`, before Lua's `longjmp`**. Consequences:
- Any Lua error in the Missions state (syntax, runtime, `error()`, or `lua_error` from a binding that got bad arguments) becomes a C++ exception. That holds even inside `lua_dostring` or `lua_call`, and the exception is not turned into a status code.
- The exception unwinds through `lua.dll`'s C frames, so `luaD_runprotected` never restores `L->errorJmp`, `top` or `Cbase`. The state is left inconsistent.
- HYPOTHESIS: the exception ends in the Ascaron.Exception `catch_all` crash dialog.

**Rule for the DLL: never let a Lua error reach that handler.** Wrap every call like this:
```c
int top = lua_gettop(L);
lua_getglobal(L, "_ERRORMESSAGE");          /* save engine handler (stack slot top+1) */
lua_pushcclosure(L, dll_errmsg, 0);         /* dll_errmsg: copy lua_tostring(L,1) to a buffer; return 0; */
lua_setglobal(L, "_ERRORMESSAGE");
int st = lua_dostring(L, code);             /* or lua_call(L, nargs, nres) */
lua_pushvalue(L, top + 1);                  /* restore engine handler */
lua_setglobal(L, "_ERRORMESSAGE");
lua_settop(L, top);
```
- With the harmless handler in place, `message()` returns and `breakrun` does `longjmp` to the protected frame. `lua_dostring` then returns `st != 0` (STATIC reasoning from `0x100036D0`, `0x10003E60` and `0x10003700`).
- Keep `dll_errmsg` trivial: it runs while Lua is already handling an error.

**C++ exceptions not raised by Lua are not caught by this.** Example: `0x5C2200`, the town handle resolver, throws `"CStadtHandle::operator->() - object pointer is 0"` for a dead or invalid handle (VERIFIED-STATIC `0x5C2276`). Validate handles before passing them to `Town_*` bindings (§5).

The `"default"` state keeps `Ascaron.Scripting`'s own handler (`"*** SCRIPT ERROR ***"`, `"Local variables:"`). That one is not overridden. HYPOTHESIS: it does not throw.

---

## 2. States, ownership and lifetime

### 2.1 ScriptManager. VERIFIED-STATIC

`Ascaron.Scripting-2.6.dll!ScriptManager` (`0x10009BE0`) returns a singleton: `new` 0x50 bytes, ctor `0x1000B140`, vtbl `0x1000E930`. Its default state name is `"default"`, stored at `+0x2C`. The vtable slots used:

| Slot | VA | Method |
|---|---|---|
| +0x08 | `0x1000B370` | `Register(State*)`: pushes every registry function (map at `+0x44`) through its own dispatcher `0x100091C0`, which is identical to the engine's `0x4383E0`. |
| +0x10 | `0x1000BF10` | `CreateState(const std::string& name, int stack)`. Idempotent. Runs `new State{ lua_open(stack), borrowed=0 }`, then `Register`, then the creation callbacks. |
| +0x14 | `0x1000B4F0` | `DestroyState(name)`: `~State` (`0x100082C0`) calls `lua_close` when `!borrowed`. **Never called from PR2.exe.** |
| +0x18 | `0x1000B530` | `GetState(name)`. Creates the state with stack 1000 if it is missing. Returns `State*`. |
| +0x1C | `0x1000B320` | `GetDefaultState()` = `GetState("default")` |
| +0x50 | `0x1000C790` | Shutdown, called at exit (`0x404999`). |

`struct State { lua_State* L; bool borrowed; }` (8 bytes, heap). A `State*` returned by the manager is stable for the life of the process.

### 2.2 The two states PR2 uses. VERIFIED-STATIC

`PR2.exe` references `ScriptManager` at exactly 7 sites:

| State | Sites | Use |
|---|---|---|
| **`"Missions"`** (name pointer at `0x6E0CC4`) | `0x4337EE` (+0x18), `0x43468C` (+0x18), `0x43758F` (+0x18), `0x433D55` (+0x10, stack 0x800, in the ctor of every type-5 script object `0x433CB0`), `0x438DB1` (+8, inside the binding registrar) | The game state: `mstart.ini`, `missions.bin`, every engine binding, saving and loading. |
| **`"default"`** | `0x4DF9CB` (+0x1C) | Only the Credits screen (`0x4DF9B0`). It registers its own callback `0x4DF2E0` and runs `lua_dobuffer("scripts/Credits.lua")` at `0x4DFB69`. |

**Getter:** `0x4337B0` (cdecl, no arguments, plain `ret`) returns `ScriptManager()->GetState("Missions")`. It has 934 call sites. Use it from the DLL.

`.screen` files are not run by any `lua_*` caller in the exe, and A2dLib imports no Lua. HYPOTHESIS: they are A2dLib's own format and contain no Lua.

### 2.3 What runs when. VERIFIED-STATIC

| Event | Path |
|---|---|
| **New Game** | `0x522800` queues `0x580C20` (world generator). Phase 0 calls `0x5809A0` (world reset), which calls `0x43E200` (`ecx = *0x6E735C`, the mission manager from `0x418A90`). That calls **`0x438D90`**, which resets globals and registers all bindings. Phase 10 (`0x580E44`) calls `0x435DF0`, which loads `lua/data/…missions.bin` into the new table `SCRIPT_TABLE` (name at `0x6E0CCC`). The queued task `0x51FE00` then calls `0x57F3A0`, which calls **`0x437510`**: `lua_dobuffer(Missions, "mstart.ini")`. `0x437510` has **one caller only** (`0x57F45E`). |
| **Save** | World::Save `0x5807C0` calls `0x4387E0` (`0x580948`). That serialises the Lua table **`GLOBALS`** (name at `0x6E0D18`) as Lua source `GLOBALS = {…}` using `0x42CC60`, and writes it into the `.pr2`. |
| **Load** | `0x581070` calls `0x5809A0` (reset, which runs `0x438D90` once). `0x5813F2` then calls **`0x43E8B0`**: `0x438D90` again, then `0x435DF0` (`missions.bin` again), then **`lua_dostring(saved GLOBALS source)`** (`0x43E98F`; data version > 0x3FB, converted by `0x433B00` if the version is below 0x419), then mission-object data (`0x43E210`), then per-object script callbacks. **`mstart.ini` is not run again.** |

So the `lua_State` survives every New Game and Load, but its **globals table is replaced each time**. Only the contents of `GLOBALS` come back from a save.

**Useful for M1 (`player_rel` persistence).** Mod data stored as `GLOBALS.FNN = { … }` is saved and restored by the engine itself, with no `.pr2` format work. The serializer `0x42CC60` handles:
- keys of type int, float and string;
- values of type int, float, string and nested table.

Two limits:
- Strings are written as `"` + raw text + `"` **without escaping** (`0x42CE96..0x42CEC0`). Keep them free of `"`, `\` and newlines.
- Functions are written as the bare text `( C function )` or `( LUA function )` (`0x42CEF8`, `0x42CF10`). HYPOTHESIS: that is a syntax error on load, which throws (§1.4). **Store only numbers, simple strings and tables.**

---

## 3. Engine bindings

### 3.1 Registration. VERIFIED-STATIC

`0x438D90` (`void`, cdecl, ends at `0x43E1F6`) performs these steps:
1. `lua_newtable` + `lua_setglobals` (fresh globals);
2. `ScriptManager->Register(state)` (base library);
3. `GLOBALS = {}`;
4. registers 443 bindings and constants inline, plus about 116 bindings through the helper;
5. sets arithmetic tag methods for `add`, `sub`, `mul`, `div` (impl `0x438570`);
6. sets `_ERRORMESSAGE`.

Its callers are `0x43E203` (in `0x43E200`) and `0x43E8CE` (in `0x43E8B0`).

The inline form and the helper do the same thing:
```
lua_pushusertag(L, impl, 0);  lua_pushcclosure(L, 0x4383E0, 1);  lua_setglobal(L, name);
```
The helper is **`0x438460`**: `void __thiscall State::Register(State* this /*ecx*/, const char* name, Impl fn)`, `ret 8`.

**Dispatcher `0x4383E0`**, a real `lua_CFunction`:
1. `fn = lua_touserdata(L,-1)`;
2. `lua_settop(L,-2)` pops the upvalue;
3. builds a stack `State tmp = {L, borrowed=1}`;
4. calls `fn(&tmp)` (cdecl, 1 argument) and returns its `int`;
5. its EH frame calls `lua_close` only if `!borrowed` (never).

### 3.2 Impl ABI. VERIFIED-STATIC (`0x429200`, `0x422030`, `0x421FD0`, `0x424D20`, `0x41F4F0`)

```c
int __cdecl impl(State* s);   /* lua_State* L = s->L; returns #results pushed */
```

Arguments are read with **negative indices relative to the top**. `Town_SetNation(town, nation)` reads town = `-2` and nation = `-1`. **Extra or missing Lua arguments shift them.**

`Town_SetNation` impl `0x429200`:
1. `lea ecx,[esp+4]; call 0x4028A0` sets a local `THandle = 0x1FFFF` (an invalid town handle);
2. checks `lua_isnumber(-2)` and calls `lua_error` if it fails;
3. `h = lua_tonumber(-2)`; if the type bits of `h` are not 1, it uses `(type<<16)|0xFFFF`;
4. `0x5C2200(&h)` gives `CStadt*`;
5. skips the town when `CStadt+0x44` bit 0 is set (governor seat) or when `Lager+8` bit 22 is set (player town);
6. otherwise calls `AddToNation(lager=CStadt+0x38, lua_tonumber(-1), 0)` (`0x5C9DA0`), then `0x624F50`;
7. **returns 0** (no results).

Getters such as `Global_GetFirstTown`, `Global_GetNextTown` and `Town_GetNation` push one number and return 1.

Key impls (from `bindings.tsv`):

| Binding | Impl |
|---|---|
| `Town_SetNation` | `0x429200` |
| `Town_GetNation` | `0x421CC0` (returns the display byte `+0x359` when the nation ≥ 4) |
| `Town_IsPlayerTown` | `0x4273E0` |
| `Global_GetFirstTown` | `0x421FD0` |
| `Global_GetNextTown` | `0x422030` |
| `Global_CreatePopup` | `0x42DAE0` (reads **no** Lua arguments; posts UI request 0x15 via `0x57E7D0`; returns 0) |
| `Global_SaveGame` | `0x424D20` |
| `Global_SetGameSpeed` | `0x41F4F0` |
| `Script_Register` | `0x41D0F0` |
| `Script_SetTimer` | `0x41D290` |
| `Global_AddLogText` | `0x42F8D0` |

### 3.3 Registering new functions from the DLL

Preferred: a standard closure, no engine glue.
```c
static int fnn_hello(lua_State* L) {             /* args are 1..n, as in stock Lua 4 */
    int n = lua_isnumber(L, 1) ? lua_tonumber(L, 1) : 0;
    lua_pushnumber(L, n + 1);
    return 1;                                      /* do NOT lua_error(): see §1.4 */
}
lua_pushcclosure(L, fnn_hello, 0); lua_setglobal(L, "FNN_Hello");
```

Alternative, with engine-style impls: `lua_pushusertag(L, (void*)impl, 0); lua_pushcclosure(L, (lua_CFunction)0x4383E0, 1); lua_setglobal(L, name);`, where `impl` is `int __cdecl impl(State*)`. You can also call the helper `0x438460` (`thiscall`; in gcc use `__attribute__((thiscall))`).

**Re-register after every globals reset.** Redirect the two `E8 rel32` calls at **`0x43E203`** and **`0x43E8CE`**. Their current target is `0x438D90`. Point them at a stub that calls `0x438D90` and then registers your functions. With that, FNN functions exist before the load path restores `GLOBALS` and before `mstart.ini` runs.

---

## 4. Running Lua from the DLL on the main thread

- **Thread:** the Missions state and every engine object are used on the main/UI thread only (HYPOTHESIS, consistent with `game_flow_entry_points.md`). Never touch Lua from `DllMain` or from a worker thread.
- **Per-frame hook (VERIFIED-STATIC site):** App virtual `0x4038C0` (vtbl slot `0x67FECC`) runs `if ([app+0xF4]) { ecx=0x700500; call 0x57F280 }` at **`0x4038D4`**. `0x57F280` is the session tick: `timeGetTime`, and the sim step `0x57F110` while `byte[0x700500+0xE44]` is set.
  - Redirect the call at `0x4038D4` to a stub. The stub calls `0x57F280` with `ecx=0x700500`, then drains your work queue.
  - HYPOTHESIS: `[app+0xF4]` means "a session is active". The world generator and the loader run incrementally across frames (phase `[0x700500+0x40]`).
  - Only run queued Lua after your `0x438D90` post-hook has fired **and** the loader has finished. A good test is `byte[0x700500+0xE44]==1` (the sim is running). For work that changes state, require it explicitly.
- **Executing code:** use the guarded sequence in §1.4. You can also call a global function: `lua_getglobal(L,"Town_SetNation"); push args; lua_call(L,n,r)` inside the same guard.
- **Calling an engine impl directly:** `State s = {L,1}; push args; int nres = impl(&s);`. The results are at the top; restore the top afterwards. It skips the dispatcher but **not** the error path: a bad argument means `lua_error` with no protected frame, then the engine handler throws (or `exit(1)` if `_ERRORMESSAGE` is not a function). Call impls directly only with validated arguments, and wrap the call in a protected `lua_call` of a tiny C closure if you need safety. Through-Lua calls with the guard are the safe default.

---

## 5. Town handles. VERIFIED-STATIC unless marked

**Handle bits** (`0x5C2200`, `0x41F620`, `0x422030`):

| Bits | Field |
|---|---|
| 0..15 | slot index (`0xFFFF` = none) |
| 16..20 | object type (town = **1**; script/mission objects = 5) |
| 21..31 | 11-bit generation, which must equal `word[links + idx*4 + 2] & 0x7FF` |

Lua carries the full handle as a 32-bit int number.

**Town pool** (object at `0x702068`):

| Address | Field |
|---|---|
| `+0` = `0x702068` | `CStadt**` slot table |
| `+4` = `0x70206C` | `links[idx]` = `{word next, word gen}` |
| `+8` = `0x702070` | word capacity |
| `+0xC` = `0x702074` | word first used slot |
| `+0xE` = `0x702076` | word grow step (set to 60 by the world generator) |

To iterate: start at `idx = first`, then `idx = links[idx].next` while `idx < cap`. This is the same walk `Global_GetNextTown` does. `GetFirstTown` and `GetNextTown` return **-1** at the end (`0x422014`, `0x4220F3`).

**Conversions:**

| From → to | How |
|---|---|
| handle → town | **`0x41F620`** `CStadt* __thiscall Pool::Get(ecx=0x702068, uint h)`, `ret 4`. Checks index and generation; returns **NULL** if invalid; ignores the type bits. Use this from the DLL. |
| handle → town (engine way) | `0x5C2200` `CStadt* __thiscall (ecx=&h)` forces the type to 1 and **throws** if invalid. Used by all `Town_*` bindings. |
| town → lager | `CStadtLager* = CStadt + 0x38` |
| lager → handle | `*(uint32*)(lager + 0x91A4)`, i.e. `CStadt+0x91DC`. This is what `CStadtLager` vtbl[0] `0x5C6910` (`GetHandle`) copies, and what `GetFirstTown`/`GetNextTown` push. |
| handle → slot | `h & 0xFFFF` |
| slot → handle | `idx | 0x10000 | ((links[idx].gen & 0x7FF) << 21)` |

**slot ↔ `staedte.ini` index (HYPOTHESIS, strong):** the world generator (`0x61CBB2..0x61CC08`) loops `i = 0..59`:
1. `pool.Add()` (`0x61BF90`) on the fresh pool;
2. `town->Init(cfg, i)` (`0x61C320`), which passes `i` to the town-config table `0x632B60(ecx=0x703BB0, i)`.

So slot *i* is config entry *i*, which is the order of the 60 power towns in `staedte.ini`. That matches `tools/session.py`'s RUNTIME mapping. Loading restores the slots from the save (`0x5CF790`), so the indices persist.

Nation and display bytes: `CStadt+0x390` and `+0x391` (= `Lager+0x358` and `+0x359`), as in the private feasibility study.

---

## 6. Header for the DLL (i686 mingw, cdecl unless noted)

```c
/* pr2_lua.h -- PR2.exe.unpacked.exe (sha 9c9250bc...) + lua.dll "4.1.0 ASCARON_LUA" */
#include <stdint.h>
typedef struct lua_State lua_State;
typedef int (__cdecl *lua_CFunction)(lua_State *L);
typedef int lua_Number;                         /* int32 in this build */
enum { LUA_TUSERDATA=0, LUA_TNIL=1, LUA_TNUMBER=2, LUA_TFLOAT=3,
       LUA_TSTRING=4, LUA_TTABLE=5, LUA_TFUNCTION=6, LUA_MULTRET=-1 };

/* lua.dll exports -- resolve with GetProcAddress(GetModuleHandleA("lua.dll"), ...) */
typedef int         (__cdecl *p_lua_dostring)(lua_State*, const char*);
typedef int         (__cdecl *p_lua_dobuffer)(lua_State*, const char*, size_t, const char*);
typedef int         (__cdecl *p_lua_call)(lua_State*, int nargs, int nres);   /* protected, returns status */
typedef void        (__cdecl *p_lua_rawcall)(lua_State*, int nargs, int nres);/* unprotected */
typedef int         (__cdecl *p_lua_gettop)(lua_State*);
typedef void        (__cdecl *p_lua_settop)(lua_State*, int);
typedef void        (__cdecl *p_lua_pushvalue)(lua_State*, int);
typedef void        (__cdecl *p_lua_getglobal)(lua_State*, const char*);
typedef void        (__cdecl *p_lua_setglobal)(lua_State*, const char*);
typedef void        (__cdecl *p_lua_pushcclosure)(lua_State*, lua_CFunction, int nup);
typedef void        (__cdecl *p_lua_pushusertag)(lua_State*, void*, int tag);
typedef void        (__cdecl *p_lua_pushnumber)(lua_State*, int);
typedef void        (__cdecl *p_lua_pushfloat)(lua_State*, double);
typedef void        (__cdecl *p_lua_pushstring)(lua_State*, const char*);
typedef void        (__cdecl *p_lua_pushnil)(lua_State*);
typedef int         (__cdecl *p_lua_tonumber)(lua_State*, int);
typedef double      (__cdecl *p_lua_tofloat)(lua_State*, int);
typedef const char* (__cdecl *p_lua_tostring)(lua_State*, int);
typedef int         (__cdecl *p_lua_isnumber)(lua_State*, int);
typedef int         (__cdecl *p_lua_isstring)(lua_State*, int);
typedef int         (__cdecl *p_lua_type)(lua_State*, int);
typedef void        (__cdecl *p_lua_newtable)(lua_State*);
typedef void        (__cdecl *p_lua_gettable)(lua_State*, int);
typedef void        (__cdecl *p_lua_settable)(lua_State*, int);
typedef void        (__cdecl *p_lua_error)(lua_State*, const char*);    /* avoid: see §1.4 */

/* engine side (PR2.exe.unpacked.exe, ImageBase 0x400000) */
typedef struct PR2State { lua_State *L; uint8_t borrowed; } PR2State;   /* Ascaron State */
typedef int (__cdecl *PR2Impl)(PR2State *s);                            /* engine binding impl */
#define PR2_GetMissionsState  ((PR2State*(__cdecl*)(void))0x004337B0)  /* -> "Missions" */
#define PR2_LUA_DISPATCHER    ((lua_CFunction)0x004383E0)              /* upvalue = PR2Impl */
typedef void (__attribute__((thiscall)) *PR2_StateRegister_t)(PR2State*, const char*, PR2Impl);
#define PR2_StateRegister     ((PR2_StateRegister_t)0x00438460)        /* ret 8 */
#define PR2_RegisterBindings  ((void(__cdecl*)(void))0x00438D90)       /* resets globals! */
#define PR2_CALLSITE_REG_NEWGAME 0x0043E203   /* E8 -> 0x438D90 (in 0x43E200) */
#define PR2_CALLSITE_REG_LOAD    0x0043E8CE   /* E8 -> 0x438D90 (in 0x43E8B0) */
#define PR2_CALLSITE_FRAME_TICK  0x004038D4   /* E8 -> 0x57F280, ecx=0x700500 */
#define PR2_SESSION              0x00700500
#define PR2_SIM_RUNNING()        (*(volatile uint8_t*)(PR2_SESSION + 0xE44))
#define PR2_ENGINE_ERRORMESSAGE  0x00438920   /* throws CException */

/* impls (call only with validated args, see §4) */
#define PR2_IMPL_Town_SetNation      ((PR2Impl)0x00429200)  /* (town,nation) @ -2,-1 ; 0 results */
#define PR2_IMPL_Town_GetNation      ((PR2Impl)0x00421CC0)
#define PR2_IMPL_Global_GetFirstTown ((PR2Impl)0x00421FD0)
#define PR2_IMPL_Global_GetNextTown  ((PR2Impl)0x00422030)  /* (town) @ -1 ; -1 at end */
#define PR2_IMPL_Global_CreatePopup  ((PR2Impl)0x0042DAE0)  /* reads no Lua args */

/* town pool + handles */
#define PR2_TOWNPOOL        0x00702068
#define PR2_TOWN_SLOTS      (*(void***)0x00702068)
#define PR2_TOWN_LINKS      (*(uint16_t**)0x0070206C)       /* [2*idx]=next, [2*idx+1]=gen */
#define PR2_TOWN_CAP        (*(uint16_t*)0x00702070)
#define PR2_TOWN_FIRST      (*(uint16_t*)0x00702074)
typedef void* (__attribute__((thiscall)) *PR2_PoolGet_t)(void *pool, uint32_t h);
#define PR2_TownFromHandle(h) (((PR2_PoolGet_t)0x0041F620)((void*)PR2_TOWNPOOL, (h)))  /* NULL if bad */
#define PR2_LAGER(town)       ((uint8_t*)(town) + 0x38)
#define PR2_HANDLE_OF(town)   (*(uint32_t*)((uint8_t*)(town) + 0x38 + 0x91A4))
#define PR2_HANDLE_IDX(h)     ((h) & 0xFFFF)
#define PR2_HANDLE_TYPE(h)    (((h) >> 16) & 0x1F)            /* 1 = town */
static inline uint32_t PR2_HandleFromSlot(uint16_t idx) {
    return idx | 0x10000u | ((uint32_t)(PR2_TOWN_LINKS[2*idx+1] & 0x7FF) << 21);
}
```

---

## 7. Open points (to check at runtime)

1. That the `_ERRORMESSAGE` swap in §1.4 really turns an error into a status code. A first test: `dostring("x = = 1")` should return 3 with no dialog.
2. The "game ready" gate for the frame hook during the incremental load and world generation (`[app+0xF4]`, `+0xE44`).
3. That a `GLOBALS.FNN` table round-trips through save and load, and how a function value inside `GLOBALS` behaves (the `( C function )` text).
4. Slot equals `staedte.ini` index: compare `PR2_HandleFromSlot(i)` with `GetFirstTown`/`GetNextTown` and the town names.
