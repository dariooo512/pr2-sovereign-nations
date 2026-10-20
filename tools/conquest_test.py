"""Real player conquest, in-game and in the background (CON-01, CON-02).

    python tools/conquest_test.py [--build] [--town IDX] [--route A|B]
        [--resolve api|ui] [--no-speedup]

Recipe: research/conquest_trigger.md §4 (route A = vanilla land assault through
the siege object; route B = create the CCoastBattle directly). Labels in the
comments: [S] = verified statically from PR2.exe bytes, [H] = hypothesis that
the first run has to confirm.

  CON-02  attacking a nation-5 town is refused: war.c hook #1 (0x60309F) logs
          "WAR refuse: player attack on own-nation town ..." and no siege
          question (type 2) is posted.
  CON-01  a player convoy with troops takes a Spanish town in a land assault:
          hook #3 records the conquest, war_frame reports it ready,
          Nation_ResolveConquest(1, town) annexes it -> member 1, owner byte 5,
          Spain one town fewer, no unhandled exception.

Assumes feature_suite.py already built and deployed PR2_nation.exe +
PR2Nation.dll (pass --build to do that here). The user's Save folder and
settings are backed up first and always restored. Every wait has a timeout;
a stall FAILs with the step name and the last state seen, so the first run
shows exactly which [H] needs adjusting. Report: CONQUEST_RESULTS.md.
"""
import argparse
import re
import shutil
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sn_env as env  # noqa: E402
import feature_suite as F  # noqa: E402  (lua(), LOG, log_since(), build())
import m0_suite as M  # noqa: E402
import sn_session as session  # noqa: E402

REPORT = env.HERE / "CONQUEST_RESULTS.md"
CAPITAL = 56                  # Margarita (start town)
SPAIN = 3
CANDIDATES = [52, 57, 54, 58, 59, 53]   # Coro first (annexed fine in TER-02), then towns near Margarita

# ---- game addresses (research/conquest_trigger.md) --------------------------
QSTORE_PTR = 0x6E7368         # [S] question store singleton: store = u32(0x6E7368) (0x42D076)
ON_JA = 0x57DF00              # [S] thiscall(store): answer front question, button 0 ("yes" / land / Annex)
ON_NEIN = 0x577780            # [S] thiscall(store): button 1 (abort / Withdraw)
Q_CLOSE = 0x57DDD0            # [S] thiscall(store): drop the front question (what OnJa does after vfn6)
NEW_TOWN_ATTACK = 0x603030    # [S] cdecl(convoyH): creates the siege object (war.c: "NewCoastBattle")
BOOST = 0                     # --boost: landing cap override (test aid)
ATTACK_CLICKS = True          # --no-attack-clicks: leave the troops on the beach
ZERO_DEFENDERS = False        # --zero-defenders: [H] probe the "defenders gone" win path
COAST_VFN6 = 0x5FF310         # [S] thiscall(battle, n): state 1 -> troops landed = min(n, +0x44), state 2
COAST_CREATE = 0x601720       # [S] cdecl(THandle* out, convoyH) -> CCoastBattle (route B)
CONVOY_ENTER = 0x5AD5C0       # [S] thiscall(convoy*, townH) (route B step 1, as siege state 4 does)
CONVOY_ANCHOR = 0x635870      # [S] thiscall(convoy*+0x4C): docked -> anchored (state 4) (route B step 2)
BP_BATTLE = 0x6017F6          # [S] `call 0x5FF9B0` with ecx = edi = the new CCoastBattle
BP_SEA = 0x602D1D             # [S] siege state 2 found a defending fleet: `call 0x5FEF80` real-time sea battle; ebp = siege
POOL_CONVOYS = 0x701EE8       # [S] handle pools: {u32 array, u32 meta(gen words), u16 count} (PoolGet 0x41F620)
POOL_BATTLES = 0x7036C0
PLAYER_H = 0x701ED0           # [S] human player handle
PLAYERS = 0x701EC0            # [S] CPlayer array, stride 0x94; convoy list sentinel at +0x2C, node+8 = handle
WORLD_TIME = 0x702C14         # [S] compared with CStadt+0x50 (protection) by 0x624430; [H] u32 compare
VT_COAST = 0x6AB578           # [S] CCoastBattle vtable

# CStadtLager offsets (towns.tsv "lager" = CStadt + 0x38, so CStadt+X = lager+X-0x38)
L_FLAGS = 0x40 - 0x38         # [S] CStadt+0x40: bit 19/20 block the land battle, bit 22 = player town
L_FLAGS2 = 0x44 - 0x38        # [S] CStadt+0x44 & 0x2000 = viceroy seat
L_PROT = 0x50 - 0x38          # [S] CStadt+0x50 protected-until time
L_NATION = 0x390 - 0x38       # [S] CStadt+0x390 owner byte (= lager+0x358, what `towns` prints)
L_HANDLE = 0x91A4             # [S] lager+0x91A4 = town handle (war.c)

# CKonvoi
K_FLAGS = 0x48                # [S] byte, 0x40 = "attack towns"
K_STATE = 0x90                # [S] 2 = in harbour, 4 = anchored outside
K_TOWN = 0x9C                 # [S] town handle
K_TYPE = 0xB4                 # [S] 1 = player

# CCoastBattle
B_HANDLE, B_ATTACKER, B_TOWN = 0x04, 0x14, 0x18   # [S]
B_QID, B_LANDED, B_MAXTROOPS = 0x2C, 0x3C, 0x44   # [S]
B_TICK, B_STATE, B_OUTCOME, B_ANNEXER, B_DUEL, B_LEN = 0x4C, 0x54, 0x58, 0x59, 0x5A, 0x84   # [S]

results = []
steps = []
T0 = time.time()


class Stall(Exception):
    """A step did not complete: (step, detail)."""


def log(step, msg):
    line = f"[{time.time() - T0:7.1f}s] {step:<16} {msg}"
    steps.append(line)
    print(line, flush=True)


def record(test, ok, detail):
    results.append((test, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<14} {detail}", flush=True)


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def toint(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


# ---- harness access -----------------------------------------------------------
def mem(addr, n):
    out = session.cmd("read", f"{addr:#x}", str(n))
    m = re.findall(rf"{addr:#x}: ([0-9a-f ]+)\s*$", out, re.M)
    if not m:
        return None
    data = bytes.fromhex(m[-1].replace(" ", ""))
    return data if len(data) == n else None


def u32(addr):
    d = mem(addr, 4)
    return struct.unpack("<I", d)[0] if d else None


def u16(addr):
    d = mem(addr, 2)
    return struct.unpack("<H", d)[0] if d else None


def u8(addr):
    d = mem(addr, 1)
    return d[0] if d else None


def write(addr, data):
    session.cmd("write", f"{addr:#x}", data.hex())


def hlog_mark():
    return len(session.latest_log().read_text(errors="replace"))


def hlog_since(mark):
    return session.latest_log().read_text(errors="replace")[mark:]


def nlog_mark():
    return F.LOG.stat().st_size if F.LOG.exists() else 0


def check_alive(step):
    bad = M.crashes()
    if bad:
        raise Stall(f"{step}: UNHANDLED exception in the game: {bad[0]}")
    if not M.game_alive():
        raise Stall(f"{step}: the game process exited")


def call(step, va, this, *args, timeout=30):
    """Queue a harness call on the UI thread and wait for its return; returns eax."""
    mark = hlog_mark()
    session.cmd("call", f"{va:#x}", f"{this:#x}" if isinstance(this, int) else this,
                *[a if isinstance(a, str) else f"{a & 0xFFFFFFFF:#x}" for a in args])
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = re.search(rf"CALL {va:#x} returned eax=(0x[0-9a-f]+)", hlog_since(mark))
        if m:
            log(step, f"call {va:#x} this={this if isinstance(this, str) else hex(this)} "
                      f"args={list(args)} -> eax={m.group(1)}")
            return int(m.group(1), 16)
        check_alive(step)
        time.sleep(0.5)
    raise Stall(f"{step}: harness call {va:#x} did not return within {timeout}s "
                f"(gamehost log tail: {hlog_since(mark)[-300:]!r})")


def bp_hits(mark, va):
    """[(hit#, {reg/expr: value})] for `BP va` lines in the gamehost log since mark."""
    out = []
    for m in re.finditer(rf"BP {va:#x} hit#(\d+) tid=\d+ (.*)", hlog_since(mark)):
        vals = dict(re.findall(r"(\S+?)=(\S+)", m.group(2)))
        out.append((int(m.group(1)), vals))
    return out


def pool_get(pool, h):
    """Python copy of PoolGet 0x41F620 [S]: index range + 11-bit generation check."""
    if h is None:
        return None
    hdr = mem(pool, 12)
    if not hdr:
        return None
    arr, meta, count = struct.unpack_from("<IIH", hdr)
    idx = h & 0xFFFF
    if idx >= count:
        return None
    gen = u16(meta + 4 * idx + 2)
    if gen is None or ((h >> 21) ^ gen) & 0x7FF:
        return None
    return u32(arr + 4 * idx)


def front_question():
    """The question-store front node [S, OnJa 0x57DF3F]: {type, id, handle} or None if empty."""
    store = u32(QSTORE_PTR)
    if not store:
        return None
    sent = u32(store + 4)
    first = u32(sent) if sent else None
    if first is None or first == sent:
        return None
    d = mem(first, 0x14)
    if not d:
        return None
    qid, h = struct.unpack_from("<II", d, 0xC)
    return {"type": d[8], "id": qid, "handle": h, "node": first, "store": store}


def store_ptr():
    return u32(QSTORE_PTR)


# ---- game objects ---------------------------------------------------------------
def towns():
    rows = {}
    for line in (env.HERE / "_build" / "towns.tsv").read_text().splitlines()[1:]:
        idx, name, lager, nat, disp = line.split("\t")
        rows[int(idx)] = (name, int(lager, 16))
    return rows


def town_info(idx):
    name, lager = towns()[idx]
    d = mem(lager, 0x20)
    if not d:
        return None
    flags, flags2 = struct.unpack_from("<II", d, L_FLAGS)
    prot = struct.unpack_from("<I", d, L_PROT)[0]
    return {"idx": idx, "name": name, "lager": lager, "flags": flags, "flags2": flags2, "prot": prot,
            "nation": u8(lager + L_NATION), "handle": u32(lager + L_HANDLE)}


def player_convoys():
    """Handles in the human player's convoy list [S economy_data.md §3]."""
    ph = u32(PLAYER_H)
    base = u32(PLAYERS)
    if ph is None or not base or (ph & 0xFFFF) == 0xFFFF:   # 0x0009FFFF: no player yet (human_handle_presim.md)
        return []
    sent = u32(base + (ph & 0xFFFF) * 0x94 + 0x2C)
    node, out = (u32(sent) if sent else None), []
    while node and node != sent and len(out) < 64:
        h = u32(node + 8)
        if h is not None:
            out.append(h)
        node = u32(node)
    return out


def convoy_lua(c):
    """Town index (65535/-1 = none), state, sailors, max sailors, cutlasses, muskets via the game's Lua."""
    r = F.lua(f'''local c = {s32(c)}
local t = Convoy_GetTown(c)
local ti = -1
if t ~= nil and t ~= -1 then ti = Nation_TownIndex(t) end
Nation_Log("cv", ti, Convoy_GetState(c), Convoy_GetSailors(c), Convoy_GetMaxSailors(c), Convoy_GetWeapAmmoAmount(c, 0), Convoy_GetWeapAmmoAmount(c, 1))''')
    v = [toint(x) for x in r.get("cv", [])]
    return v + [None] * (6 - len(v)) if len(v) < 6 else v


def convoy_ptr(c):
    return pool_get(POOL_CONVOYS, c)


def set_attack_flag(c, on=True):
    p = convoy_ptr(c)
    if not p:
        raise Stall(f"attack flag: convoy {c:#x} not found in the convoy pool")
    old = u8(p + K_FLAGS)
    if old is None:
        raise Stall(f"attack flag: cannot read convoy {c:#x} +48h at {p:#x}")
    new = (old | 0x40) if on else (old & ~0x40)
    write(p + K_FLAGS, bytes([new]))
    log("attack-flag", f"convoy {c:#x} @ {p:#x} +48h {old:#04x} -> {u8(p + K_FLAGS):#04x}")
    return p


def battle_alive(b, bh):
    return b is not None and pool_get(POOL_BATTLES, bh) == b and u32(b) == VT_COAST


def read_battle(b):
    d = mem(b, 0x88)
    if not d:
        return None
    g = lambda off: struct.unpack_from("<I", d, off)[0]  # noqa: E731
    return {"vt": g(0), "handle": g(B_HANDLE), "attacker": g(B_ATTACKER), "town": g(B_TOWN),
            "qid": g(B_QID), "landed": g(B_LANDED), "max": g(B_MAXTROOPS), "tick": g(B_TICK),
            "state": g(B_STATE), "outcome": d[B_OUTCOME], "annexer": d[B_ANNEXER], "duel": d[B_DUEL],
            "len": g(B_LEN)}


def shot(name):
    try:
        import screen
        screen.shot(name)
    except Exception as e:                       # informational only
        print("screenshot failed:", e)


# ---- steps ------------------------------------------------------------------------
def setup_nation():
    M.kill_game()
    session.newgame([], "PR2_nation.exe")
    nlog = F.LOG.read_text(errors="replace") if F.LOG.exists() else ""
    hooks = re.findall(r"WAR hooks installed: (\d)/7", nlog)
    log("setup", f"game up; war hooks installed {hooks[-1] if hooks else '?'}/7")
    r = F.lua(f'''Nation_DevSetRequirements(10000, 1, 0)
local ok, why = Nation_Found({CAPITAL}, "Free Republic of Margarita", "Margaritan", 0, 0)
Nation_Log("found", ok, why)
Nation_Log("town", Nation_GetTown({CAPITAL}))''')
    ok = r.get("found", ["0"])[0] == "1" and r.get("town", ["0"])[0] == "1"
    log("found", f"Nation_Found({CAPITAL}) -> {r.get('found')} member {r.get('town')}")
    if not ok:
        raise Stall(f"found: founding at Margarita failed: {r}")
    M.speed_up()


def pick_convoy():
    hs = player_convoys()
    log("convoy", f"player convoy handles (memory list): {[hex(h) for h in hs]}")
    best = None
    for h in hs:
        p = convoy_ptr(h)
        typ = u32(p + K_TYPE) if p else None
        info = convoy_lua(h)
        log("convoy", f"  {h:#x} ptr={p and hex(p)} type={typ} town/state/sailors/max/cut/musk={info}")
        if typ != 1:                              # [S] +0xB4 == 1 player convoy
            continue
        if best is None or (info[0] == CAPITAL and best[1][0] != CAPITAL):
            best = (h, info)
    if best is None:
        raise Stall("convoy: no player convoy found (player list at CPlayer+0x2C empty or unreadable)")
    log("convoy", f"using convoy {best[0]:#x} (town {best[1][0]})")
    return best[0], best[1]


def pick_town(forced):
    now = u32(WORLD_TIME)
    ok, protected = [], []
    for idx in ([forced] if forced is not None else CANDIDATES):
        t = town_info(idx)
        if not t:
            log("target", f"  town {idx}: unreadable")
            continue
        member = toint(F.lua(f'Nation_Log("m", Nation_GetTown({idx}))').get("m", ["?"])[0])
        why = []
        if t["nation"] != SPAIN:
            why.append(f"owner {t['nation']}")
        if t["flags2"] & 0x2000:
            why.append("viceroy seat")
        if t["flags"] & ((1 << 19) | (1 << 20) | (1 << 22)):
            why.append(f"flags {t['flags']:#010x} (bit 19/20/22)")
        if member:
            why.append("already a member")
        if not t["handle"]:
            why.append("town handle unreadable")
        prot = now is not None and t["prot"] > now          # [H] u32 time compare
        log("target", f"  town {idx} {t['name']}: owner {t['nation']} flags {t['flags']:#010x} "
                      f"flags2 {t['flags2']:#010x} prot {t['prot']} now {now} handle {t['handle']:#x} "
                      f"-> {'REJECT: ' + ', '.join(why) if why else ('protected?' if prot else 'ok')}")
        if not why:
            (protected if prot else ok).append(t)
    pick = (ok or protected or [None])[0]
    if pick is None:
        raise Stall(f"target: no usable Spanish town among {[forced] if forced is not None else CANDIDATES}")
    lua_h = toint(F.lua(f'Nation_Log("h", Nation_TownHandle({pick["idx"]}))').get("h", ["?"])[0])
    log("target", f"target town {pick['idx']} {pick['name']} handle {pick['handle']:#x} "
                  f"(Nation_TownHandle {lua_h if lua_h is None else hex(lua_h & 0xFFFFFFFF)})")
    return pick


def con02(c, idx):
    """Negative test: a player attack on a nation-5 town is refused by hook #1."""
    t = town_info(idx)
    nmark, hmark = nlog_mark(), hlog_mark()
    before = front_question()
    log("CON-02", f"town {idx} {t['name']} owner byte {t['nation']} (expect 5); front before {before}")
    set_attack_flag(c, True)
    call("CON-02", NEW_TOWN_ATTACK, 0, c)
    time.sleep(6)                                   # war_frame / ticker message
    out = F.log_since(nmark)
    m = re.search(rf"WAR refuse: player (?:convoy arrival )?attack on own-nation town {idx} \([^)]*\) blocked.*", out)
    q = front_question()
    siege_q = q is not None and q["type"] == 2 and (before is None or q["id"] != before["id"])
    if siege_q:                                     # refusal failed: abort the siege cleanly (vfn6(0))
        log("CON-02", f"siege question posted despite nation 5: {q}; answering OnNein (abort)")
        call("CON-02", ON_NEIN, store_ptr())
    set_attack_flag(c, False)
    sea = bp_hits(hmark, BP_SEA)
    record("CON-02", t["nation"] == 5 and m is not None and not siege_q and not M.crashes(),
           f"attack on own town {idx} ({t['name']}, owner {t['nation']}): "
           f"{m.group(0).strip() if m else 'NO refuse line in PR2Nation.log'}; "
           f"siege question posted={siege_q}; front now {q}{'; sea bp hit' if sea else ''}")


def grant_troops(c):
    r = F.lua(f'''local c = {s32(c)}
Convoy_AddSailors(c, Convoy_GetMaxSailors(c))
Convoy_AlterWeapAmmoAmount(c, 0, 200)
Convoy_AlterWeapAmmoAmount(c, 1, 200)
Nation_Log("tr", Convoy_GetSailors(c), Convoy_GetMaxSailors(c), Convoy_GetWeapAmmoAmount(c, 0), Convoy_GetWeapAmmoAmount(c, 1))''')
    v = [toint(x) for x in r.get("tr", [])]
    log("troops", f"sailors/max/cutlasses/muskets = {v} {r.get('__error__', [''])[0][-200:]}")
    # [S] precondition 0x5FF3E0: sailors > 0 and cutlasses + muskets > 0
    if len(v) < 4 or not v[0] or not ((v[2] or 0) + (v[3] or 0)):
        raise Stall(f"troops: convoy has no sailors or no weapons after the Convoy_* grants: {v} {r}")
    return v


def sail(c, target, route):
    r = F.lua(f'Nation_Log("mv", Convoy_MoveToTown({s32(c)}, {s32(target["handle"])}))')
    log("sail", f"Convoy_MoveToTown -> {r.get('mv')} {r.get('__error__', [''])[0][-200:]}")
    if route == "A":
        time.sleep(5)                               # [H] MoveToTown may reset +0x48; set the flag after it
        set_attack_flag(c, True)
    t0, last = time.time(), None
    while time.time() - t0 < 12 * 60:
        check_alive("sail")
        info = convoy_lua(c)
        q = front_question()
        if info != last:
            log("sail", f"town/state/sailors/max/cut/musk={info} front={q}")
            last = info
        if info[0] == target["idx"] and info[1] in (2, 4):   # [S] +0x90: 2 in harbour, 4 anchored
            log("sail", f"arrived at {target['name']} (state {info[1]})")
            return
        if q is not None and q["type"] == 2:                 # arrival already started the siege
            log("sail", f"siege question already posted on arrival: {q}")
            return
        time.sleep(2)                               # poll interval
    raise Stall(f"sail: convoy did not reach town {target['idx']} in 12 min (last town/state {last}); "
                "check Convoy_MoveToTown's handle argument / game speed")


def declare_war():
    r = F.lua(f'Nation_Log("war", Nation_DeclareWar({SPAIN}))\nNation_Log("rel", Nation_GetRelation({SPAIN}))')
    table = u8(0x9F7000 + SPAIN)
    log("war", f"Nation_DeclareWar(Spain) -> {r.get('war')} status {r.get('rel')} player_rel[Spain]={table}")
    if r.get("rel", ["?"])[0] != "4":                         # TREATY_WAR, required by conquest_applies()
        raise Stall(f"war: not at war with Spain after Nation_DeclareWar: {r}")


def route_b(c, target):
    """Skip the siege (and its defender sea battle) [H: same calls as siege state 4, 0x6035EE..0x603637]."""
    p = convoy_ptr(c)
    call("route-B", CONVOY_ENTER, p, target["handle"])
    call("route-B", CONVOY_ANCHOR, p + 0x4C)
    log("route-B", f"convoy state now {u32(p + K_STATE)} (precondition 0x5FF3E0 needs 4)")
    call("route-B", COAST_CREATE, 0, "s:x", c)      # s:x = 12 bytes of scratch for the hidden out pointer


DEADLINES = {"siege question": 90, "battle create": 90, "troop question": 120,
             "land battle": 15 * 60, "raid/end questions": 5 * 60}


def drive(c, target, route, speedup):
    """Answer the siege/battle questions until war_frame logs the conquest ready."""
    normal_speed, last_click, clicks, zeroed = False, 0.0, 0, False
    T, hmark, nmark = target["idx"], hlog_mark(), nlog_mark()
    session.cmd("bp", f"{BP_BATTLE:#x}=edi")
    session.cmd("bp", f"{BP_SEA:#x}=ebp,ebp+0x10:4")
    if route == "B":
        route_b(c, target)
    step = "siege question" if route == "A" else "battle create"
    step_t0 = time.time()
    battle = bh = None
    manual_attack = siege_answered = recorded = len_patched = False
    attempts, foreign, last = {}, {}, ""

    def goto(s):
        nonlocal step, step_t0
        log(s, f"(after {time.time() - step_t0:.0f}s in '{step}')")
        step, step_t0 = s, time.time()

    while True:
        check_alive(step)
        waited = time.time() - step_t0
        if waited > DEADLINES[step]:
            raise Stall(f"{step}: no progress in {DEADLINES[step]}s; last seen: {last}")
        out = F.log_since(nmark)
        m = re.search(rf"WAR coast victory at town {T} .*", out)
        if m:
            raise Stall(f"hook #3: conquest_applies() said no: {m.group(0).strip()}")
        if not recorded and re.search(rf"WAR conquest recorded: town {T} ", out):
            recorded = True
            log(step, "PR2Nation.log: " + re.search(r"WAR conquest recorded: .*", out).group(0).strip())
            goto("raid/end questions")
        m = re.search(rf"WAR conquest of town {T} \([^)]*\) ready.*", out)
        if m:
            log(step, "PR2Nation.log: " + m.group(0).strip())
            return battle, bh
        for _, v in bp_hits(hmark, BP_SEA):           # siege state 2 for OUR town -> real-time sea battle
            siege_town = v.get("[ebp+0x10]")
            if siege_town and siege_town != "??" and \
                    struct.unpack("<I", bytes.fromhex(siege_town))[0] & 0xFFFF == T:
                shot("conquest_sea_battle")
                raise Stall("siege state 2: a defending military convoy is docked -> real-time sea "
                            f"battle started (bp {BP_SEA:#x} {v}); rerun with --town <other> or --route B")

        if battle is None:                           # the CCoastBattle from bp 0x6017F6 (edi)
            for _, v in reversed(bp_hits(hmark, BP_BATTLE)):
                b = int(v.get("edi", "0"), 16)
                tb = u32(b + B_TOWN) if b else None
                if b and u32(b) == VT_COAST and tb is not None and tb & 0xFFFF == T:
                    battle, bh = b, u32(b + B_HANDLE)
                    log(step, f"CCoastBattle {battle:#x} handle {bh:#x} (bp {BP_BATTLE:#x})")
                    if step in ("siege question", "battle create"):
                        goto("troop question")
                    break

        st = read_battle(battle) if battle is not None and battle_alive(battle, bh) else None
        if st:
            if st["state"] < 5 and st["duel"]:
                write(battle + B_DUEL, b"\x00")       # [S] +0x5A=0: no duel / fencing mini-game
                log(step, f"cleared duel flag +5Ah ({st['duel']} -> 0)")
            if st["state"] >= 2 and not normal_speed:
                # the land battle is real time: run it at normal speed, as a player would
                session.cmd("call", "0x57F550", "0x700500", "1")
                normal_speed = True
                log(step, "game speed -> normal for the land battle")
            if st["state"] == 3 and ZERO_DEFENDERS and not zeroed:
                # [H] probe: the defender army (+1Ch) holds a unit vector at +E29C/+E2A0 (10-byte
                # entries); 0x575F50 returns false when an entry's word +8 is 0, which the battle
                # evaluation treats as "defenders gone" -> player win (+58h = 1)
                army = u32(battle + 0x1C)
                vb, ve = u32(army + 0xE29C), u32(army + 0xE2A0)
                n_units = (ve - vb) // 10 if army and ve >= vb else 0
                raw = mem(vb, min(n_units, 16) * 10) if n_units else b""
                log(step, f"defender army {army:#x}: {n_units} unit(s) " +
                    " ".join(raw[i:i + 10].hex() for i in range(0, len(raw), 10)))
                sim = u32(battle + 0x28)
                log(step, f"sim object +28h {sim:#x}: {(mem(sim, 0x30) or b'').hex() if sim else '-'}")
                for i in range(n_units):
                    write(vb + 10 * i + 8, bytes(2))
                zeroed = True
                log(step, f"zeroed word +8 of {n_units} defender unit(s) (--zero-defenders)")
            if st["state"] == 3 and ATTACK_CLICKS and time.time() - last_click > 4:
                # order the assault like a player: melee and musket attack buttons (battle HUD, bottom right)
                for xy in ((915, 617), (915, 683)):
                    session.cmd("click", *xy)
                    time.sleep(0.3)
                last_click = time.time()
                clicks += 1
                if clicks in (1, 5, 15):
                    shot(f"conquest_battle_{clicks}")
                    log(step, f"attack orders clicked ({clicks}); landed {st['landed']}, tick {st['tick']}/{st['len']}")
            if st["state"] == 3 and speedup and not len_patched:
                write(battle + B_LEN, struct.pack("<I", st["tick"]))   # [H] sim ends next tick via 0x600670
                len_patched = True
                log(step, f"battle length +84h {st['len']} -> {st['tick']} (speed-up)")
            if st["state"] >= 2 and step == "troop question":      # troops landed (vfn6 -> state 2)
                goto("land battle")
            # +58h is only meaningful once the battle has been evaluated (state >= 4);
            # before that it holds 0xFF (seen at state 1 on the first run)
            if st["state"] == 0xC or (st["state"] >= 4 and st["outcome"] != 0xFF and st["outcome"] & 0x80):
                shot("conquest_lost")
                raise Stall(f"land battle LOST (state {st['state']:#x}, +58h={st['outcome']:#04x}): "
                            f"[H] attackers too weak; landed {st['landed']} of max {st['max']}")
            if st["state"] in (6, 7):
                shot("conquest_duel")
                raise Stall(f"duel / fencing mini-game started despite +5Ah=0 (state {st['state']})")

        q = front_question()
        last = f"battle={st} front={q}"
        if q is None:
            pass
        elif q["type"] == 0x27:
            raise Stall(f"{step}: town is protected (question 0x27, 0x6030CE); pick another --town")
        elif q["type"] == 2 and route == "A" and not siege_answered:
            call(step, ON_JA, q["store"])            # [S] OnJa -> vfn6(1) = land assault
            siege_answered = True
            goto("battle create")
        elif battle is not None and (q["handle"] == bh or (st is not None and st["qid"] == q["id"])):
            # ours: the front's battle handle, or the battle's own open question id (+0x2C) [S]
            n = attempts[q["id"]] = attempts.get(q["id"], 0) + 1
            if n > 3:
                raise Stall(f"{step}: battle question {q} still at the front after 3 answers")
            if q["type"] == 9:                        # troop count: land everyone, then close (as OnJa does)
                if BOOST:                             # test aid: raise the landing cap (+44h) first
                    write(battle + B_MAXTROOPS, struct.pack("<I", BOOST))
                    log(step, f"landing cap +44h -> {BOOST} (--boost)")
                call(step, COAST_VFN6, battle, 0x7FFF)
                call(step, Q_CLOSE, q["store"])
            elif q["type"] == 8:                      # [H] duel offer: decline
                call(step, ON_NEIN, q["store"])
            else:                                     # raid (6 / variable), 0x1B end, 5/0xB/4 [S/H]
                call(step, ON_JA, q["store"])
            time.sleep(1)
        elif q["type"] == 0x15:
            pass                                      # the mod's conquest popup: handled after 'ready'
        else:                                         # adopt a battle known only by its handle
            obj = pool_get(POOL_BATTLES, q["handle"])
            if battle is None and obj and u32(obj) == VT_COAST and (u32(obj + B_TOWN) or 0) & 0xFFFF == T:
                battle, bh = obj, q["handle"]
                log(step, f"CCoastBattle {battle:#x} handle {bh:#x} (from question {q})")
                if step in ("siege question", "battle create"):
                    goto("troop question")
                continue
            first = foreign.setdefault(q["id"], time.time())
            if time.time() - first > 12:              # an unrelated message blocks the front: drop it
                log(step, f"dropping unrelated front question {q}")
                call(step, Q_CLOSE, q["store"])
                foreign[q["id"]] = time.time() + 3600

        # route A fallback: arrival did not start a siege -> set the flag and call 0x603030 by hand
        if step == "siege question" and not manual_attack and waited > 20 and not siege_answered:
            manual_attack = True
            log(step, "no siege question 20s after arrival: setting +48h|=40h and calling 0x603030 directly")
            set_attack_flag(c, True)
            call(step, NEW_TOWN_ATTACK, 0, c)
        time.sleep(1)


def con01(c, target, route, resolve, speedup):
    T = target["idx"]
    spain0 = toint(F.lua(f'Nation_Log("n", Nation_GetNumTowns({SPAIN}))').get("n", ["?"])[0])
    nmark = nlog_mark()
    grant_troops(c)
    sail(c, target, route)
    declare_war()                                   # only now: no interception by Spanish fleets at sea
    battle, bh = drive(c, target, route, speedup)
    out = F.log_since(nmark)
    rec = re.search(rf"WAR conquest recorded: town {T} .*", out)
    coast = re.search(r"WAR coast: vanilla annexer .*", out)
    record("CON-01/battle", rec is not None,
           f"hook #3: {rec.group(0).strip() if rec else 'no record line'}; {coast.group(0).strip() if coast else ''}")

    r = F.lua('Nation_Log("pc", Nation_PendingConquest())')
    pc = r.get("pc", ["?"])
    record("CON-01/pending", pc[:2] == [str(T), str(SPAIN)], f"Nation_PendingConquest() = {pc} (expect {T}, {SPAIN})")

    nmark2 = nlog_mark()
    q = front_question()
    log("resolve", f"front question before resolve: {q}")
    if resolve == "ui":
        # the DLL opens the script's conquest popup itself once the conquest is ready
        # (menu event sub 1000 + town); press Annex (button 0 of page 10) like a player
        t0 = time.time()
        while f"UI: conquest popup for town {T}" not in F.log_since(0):
            if time.time() - t0 > 30:
                raise Stall("resolve: the DLL never opened the conquest popup (no 'UI: conquest popup' line)")
            time.sleep(1)
        time.sleep(2)
        if not F.press(0, 10, "conquest_popup", 2):
            raise Stall("resolve: clicking Annex in the conquest popup did not close page 10 with button 0")
        time.sleep(2)
        F.press(1, 6, "conquest_info", 2)              # close the result page
    else:
        r = F.lua(f'Nation_Log("res", Nation_ResolveConquest(1, {T}))')
        log("resolve", f"Nation_ResolveConquest(1, {T}) -> {r.get('res')}")
        q = front_question()
        if q is not None and q["type"] == 0x15:     # close the now-obsolete Annex/Withdraw popup
            call("resolve", Q_CLOSE, q["store"])
    time.sleep(3)
    out = F.log_since(nmark2)
    annex = re.search(rf"WAR conquest of town {T} \([^)]*\) from \w+: ANNEX -> (\S+)", out)
    r = F.lua(f'Nation_Log("t", Nation_GetTown({T}))\nNation_Log("n", Nation_GetNumTowns({SPAIN}))')
    member = r.get("t", ["?"])[0]
    spain1 = toint(r.get("n", ["?"])[0])
    owner = u8(target["lager"] + L_NATION)
    record("CON-01/annex", annex is not None and annex.group(1) == "ok" and member == "1" and owner == 5
           and spain0 is not None and spain1 == spain0 - 1,
           f"{annex.group(0).strip() if annex else 'no ANNEX line'}; Nation_GetTown({T}) member {member}; "
           f"owner byte {owner} (expect 5); Spain towns {spain0} -> {spain1}")
    alive = M.game_alive() and not M.crashes()
    record("CON-01", alive and all(ok for t, ok, _ in results if t.startswith("CON-01/")),
           f"real conquest of {target['name']} ({T}) by route {route}; game alive={M.game_alive()}, "
           f"unhandled exceptions: {M.crashes()[:1] or 'none'}")


def scenario(a):
    try:
        setup_nation()
        c, info = pick_convoy()
        target = pick_town(a.town)
        did_con02 = False
        if not a.skip_con02 and info[0] == CAPITAL:
            did_con02 = True
            try:
                con02(c, CAPITAL)
            except Stall as e:                      # keep going: CON-01 is independent
                record("CON-02", False, f"stalled: {e}")
        con01(c, target, a.route, a.resolve, not a.no_speedup)
        if not a.skip_con02 and not did_con02:      # convoy did not start at the capital: use the new town
            con02(c, target["idx"])
    except Stall as e:
        shot("conquest_stall")
        record("STALL", False, str(e))
    except SystemExit as e:                         # session.py harness abort
        record("RUN", False, f"aborted: {e}")
    if not any(t == "CON-01" for t, _, _ in results):
        record("CON-01", False, "did not complete (see STALL/RUN above)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true", help="run feature_suite.build() first (tests, DLL, patches, deploy)")
    ap.add_argument("--town", type=int, help=f"target town index (default: first usable of {CANDIDATES})")
    ap.add_argument("--route", choices="AB", default="A", help="A = vanilla siege (default), B = create the land battle directly")
    ap.add_argument("--resolve", choices=("api", "ui"), default="api",
                    help="api = Nation_ResolveConquest(1, town); ui = press Annex in the conquest popup")
    ap.add_argument("--no-speedup", action="store_true", help="do not shorten the land battle (+84h)")
    ap.add_argument("--skip-con02", action="store_true")
    ap.add_argument("--no-attack-clicks", action="store_true", help="do not click the battle HUD attack buttons")
    ap.add_argument("--zero-defenders", action="store_true", help="[H] test aid: empty the defender army in the battle")
    ap.add_argument("--boost", type=int, default=0,
                    help="test aid: raise the battle's landing cap (+44h) to N troops before landing")
    a = ap.parse_args()
    global BOOST
    BOOST = a.boost
    global ATTACK_CLICKS
    ATTACK_CLICKS = not a.no_attack_clicks
    global ZERO_DEFENDERS
    ZERO_DEFENDERS = a.zero_defenders
    backup = env.backup_saves()
    try:
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        if a.build:
            F.build()
            results.extend(F.results)
        scenario(a)
    finally:
        M.kill_game()
        for f in backup.iterdir():
            if f.is_file():
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig_cfg = env.BACKUPS / "settings.cfg.orig"
        if orig_cfg.exists():
            shutil.copy2(orig_cfg, env.SAVE_DIR / "settings.cfg")
        print(f"restored the Save folder from {backup}")
    REPORT.write_text("# Conquest run " + time.strftime("%Y-%m-%d %H:%M")
                      + f"\n\nArgs: `{' '.join(sys.argv[1:]) or '(defaults)'}`\n\n"
                      + "| Test | Result | Detail |\n|---|---|---|\n"
                      + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {str(d).replace('|', '/')} |\n"
                                for t, ok, d in results)
                      + "\n## Step log\n\n```\n" + "\n".join(steps) + "\n```\n")
    failed = [t for t, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
