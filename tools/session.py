"""Scripted game session: launch under gamehost, start a free-play game, and
hand back control -- all in the background (no focus, no mouse).

    python tools/session.py newgame [--exe PR2_nation.exe] [--bp SPEC ...]
    python tools/session.py load "Quick Save" [--exe ...] [--bp ...]

Leaves the game running at the sea/town view with the welcome dialog closed and
writes the 60 town objects (index = staedte.ini order, with names) to
_build/towns.tsv. Use cmd.py for everything after that.

Waits are readiness signals, not fixed sleeps: the main menu's state byte, and
the lines PR2Nation.dll writes once a new game or a load is ready (read from the
byte offset of PR2Nation.log taken just before the call, so only this run's
lines count). Every wait has a timeout that stops the run with what was missing.
A new game always starts at Margarita: the free-play setup remembers the last
start town in Save\\options.dat, so newgame() sets it there first (restored by
restore_options() and by the suites' Save-folder backup).
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402
from gamehost import CMD_FILE  # noqa: E402

TOWN_VTABLE = "0x6a6bc0"   # CStadtLager vtable (observed at AddToNation, 2026-10-11)
MENU_FREEPLAY = (1045, 65)  # 1280x800 window coordinates
SETUP_START = (1045, 65)
WELCOME_OK = (605, 519)
MARGARITA = 56              # staedte.ini order; the suites' start town (Spanish governor seat)
APP = 0x6E5958              # *APP = the app object; *(app + 0xE8) = the main-menu controller
MENU_STATE, MENU_SETUP = 0x3C, 0x1C   # menu state (1 main menu, 6 free-game setup, 12 loading); setup screen
START_TOWN = 0x701EAC       # the settings block's start town (written by the setup screen's Commit)
RUNNING = 0x700500 + 0xE44  # the sim clock runs while this byte is 1 (research/game_flow_entry_points.md §4)
SETTLE = float(os.environ.get("SN_SETTLE", "1"))   # seconds the world runs after it is ready

LOG = env.MOD_LOG           # PR2Nation.log (the DLL recreates it at every launch)
_host = None                # the running gamehost.py process (launch)
_run_log = None             # this launch's gamehost.log


# ---------------------------------------------------------------- the logs --
def latest_log():
    if _run_log is not None:
        return _run_log
    return max((env.HERE / "_build" / "runs").glob("*/gamehost.log"))


def wait_for(pattern, after, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        text = latest_log().read_text(errors="replace")[after:]
        if re.search(pattern, text):
            return text
        time.sleep(0.25)
    raise SystemExit(f"timeout waiting for {pattern!r}")


def log_mark():
    """Byte offset of the end of PR2Nation.log (the log is CRLF: always slice by bytes)."""
    try:
        return LOG.stat().st_size
    except OSError:
        return 0


def log_since(mark):
    try:
        data = LOG.read_bytes()
    except OSError:
        return ""
    return data[mark:].decode("latin-1")


def wait_log(patterns, mark, timeout, what):
    """Wait until every regex in `patterns` has appeared in PR2Nation.log after byte offset `mark`
    (each one after the previous one's match, in order). Fails at once when the game is gone, and
    after `timeout` s with the patterns still missing and the log's tail."""
    t0 = time.time()
    while True:
        text, pos, missing = log_since(mark), 0, []
        for p in patterns:
            m = re.compile(p).search(text, pos)
            if not m:
                missing.append(p)
                break
            pos = m.end()
        if not missing:
            return text
        if not host_alive() or "EXIT code=" in latest_log().read_text(errors="replace"):
            raise SystemExit(f"{what}: the game exited while waiting for {missing[0]!r}")
        if time.time() - t0 > timeout:
            tail = text[-500:].replace("\r\n", " | ")
            raise SystemExit(f"{what}: {missing[0]!r} not in PR2Nation.log within {timeout:.0f}s (log tail: {tail})")
        time.sleep(0.2)


# ------------------------------------------------------- talking to gamehost --
def host_alive():
    return _host is None or _host.poll() is None


def cmd(*args, timeout=60):
    """Send one command to gamehost and return its log lines (what cmd.py prints), in-process.
    Once the host has died, fail at once instead of waiting 60 s per call (a dead host also
    takes the game with it)."""
    if not host_alive():
        raise SystemExit(f"gamehost is gone (exit {_host.returncode}); see the run dir's host_stderr.txt")
    line = " ".join(map(str, args))
    done = CMD_FILE.with_suffix(".done")
    done.unlink(missing_ok=True)
    log = latest_log()
    start = log.stat().st_size
    CMD_FILE.write_text(line + "\n")
    t0 = time.time()
    while not done.exists():
        if time.time() - t0 > timeout:
            if not host_alive():
                raise SystemExit(f"gamehost died during '{line}'")
            print(f"no reply in {timeout}s to '{line}' (is gamehost.py running?)", flush=True)
            return ""
        time.sleep(0.02)
    with open(log, encoding="utf-8", errors="replace") as f:
        f.seek(start)
        return f.read()


def u32(addr):
    """A dword of game memory (None if unreadable)."""
    m = re.search(r": ((?:[0-9a-f]{2} ){3}[0-9a-f]{2})", cmd("read", f"{addr:#x}", "4"))
    return int.from_bytes(bytes.fromhex(m.group(1)), "little") if m else None


def menu_ptr():
    app = u32(APP)
    return u32(app + 0xE8) if app else None


def menu_state():
    """(main-menu controller, its state, its free-game setup screen); Nones while it does not exist."""
    menu = menu_ptr()
    if not menu:
        return None, None, None
    return menu, u32(menu + MENU_STATE), u32(menu + MENU_SETUP)


def wait_menu(state, timeout, what, setup=False):
    t0 = time.time()
    while time.time() - t0 < timeout:
        menu, st, scr = menu_state()
        if st == state and (scr or not setup):
            return menu
        time.sleep(0.2)
    raise SystemExit(f"{what}: the main menu did not reach state {state} within {timeout}s (state {st})")


def town_names():
    txt = (env.WORKDIR / "arcs" / "Data" / "staedte.ini").read_text("latin1")
    rows = []
    for name, body in re.findall(r"^\[([^\]]+)\]([^\[]*)", txt, re.M):
        m = re.search(r"^\s*Nation\s*=\s*(\w+)", body, re.M)
        if m and m.group(1) in ("England", "Frankreich", "Holland", "Spanien"):
            rows.append(name)
    return rows


def input_desktop():
    """Name of the desktop receiving input: 'Default' normally, 'Screen-saver'
    or 'Winlogon' when the PC is idle/locked -- D3D8 cannot start then."""
    import ctypes
    u = ctypes.windll.user32
    h = u.OpenInputDesktop(0, False, 0x0100)
    if not h:
        return "Winlogon"
    buf, n = ctypes.create_unicode_buffer(256), ctypes.c_ulong()
    u.GetUserObjectInformationW(h, 2, buf, 512, ctypes.byref(n))
    u.CloseDesktop(h)
    return buf.value


def _runs():
    return {p.parent.name for p in (env.HERE / "_build" / "runs").glob("*/gamehost.log")}


def launch(bps, exe=None, max_hits=None):
    """Start the game under gamehost and wait until the main menu is up.
    Always enforces the test settings first (windowed, intro skipped, no DPI
    doubling): a fullscreen launch would take over the user's screen."""
    env.windowed(True)
    env.fast_boot(True)
    env.dpi_aware(True)
    env.mute_sound()                  # no sound from test games
    args = [sys.executable, str(HERE / "gamehost.py")] + (["--exe", exe] if exe else []) \
        + (["--max-hits", str(max_hits)] if max_hits else [])
    for b in bps:
        args += ["--bp", b]
    desk = input_desktop()
    if desk != "Default":
        raise SystemExit(f"the PC's input desktop is {desk!r} (screen saver or locked): "
                         "the game's Direct3D cannot start; rerun when the PC is in use")
    global _host, _run_log
    for attempt in range(3):
        before = _runs()
        _run_log = None
        err = open(env.HERE / "_build" / "host_stderr.txt", "ab")      # a host crash leaves its traceback here
        host = _host = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=err)
        t0 = time.time()
        while time.time() - t0 < 30:                   # this launch's run dir (never an older one's log)
            new = _runs() - before
            if new:
                _run_log = env.HERE / "_build" / "runs" / max(new) / "gamehost.log"
                break
            if host.poll() is not None:
                break
            time.sleep(0.1)
        if _run_log is None:
            raise SystemExit("gamehost did not start (see _build/host_stderr.txt)")
        # engine up (the benign font throw); a start-up D3D failure right after the previous
        # instance was killed exits within seconds -> retry
        text = wait_for(r"PAVCGenericException|EXIT code=", 0)
        if "PAVCGenericException" in text:
            try:
                wait_menu(1, 30, "launch")            # the main menu controller exists and is idle
            except SystemExit:
                if not host_alive() or "EXIT code=" in latest_log().read_text(errors="replace"):
                    print(f"game exited during start-up (attempt {attempt + 1}); retrying")
                    time.sleep(2)
                    continue
                raise
            return host
        print(f"game exited during start-up (attempt {attempt + 1}); retrying")
        try:
            host.wait(timeout=30)
        except subprocess.TimeoutExpired:
            host.kill()
        time.sleep(5)
    raise SystemExit("game failed to start 3 times")


def scan_towns():
    out = cmd("towns", TOWN_VTABLE)
    return re.findall(r"lager=(0x[0-9a-f]+) nation=(\d+) display=(\d+)", out)


# ------------------------------------------------------------ the start town --
OPTIONS = env.SAVE_DIR / "options.dat"
OPTIONS_ORIG = env.BACKUPS / "options.dat.before-test"


def _start_town_offset(data):
    """Byte offset of the remembered free-play start town in options.dat, or None.
    Layout (reader 0x5BD1A0): 'OPT2', version 0x88E, a 0x84-byte block, a string (u32 len + bytes),
    two wide strings (u32 len + 2*len bytes), then four u32-length-prefixed fields read into the
    options object at +0x131, +0x130, +0x132 (the start town, staedte.ini index) and +0x133."""
    if len(data) < 12 or data[:4] != b"OPT2" or int.from_bytes(data[4:8], "little") != 0x88E:
        return None
    pos = 8 + 0x84
    for unit in (1, 2, 2):
        if pos + 4 > len(data):
            return None
        n = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4 + (unit * n if 0 < n < 0x10000 else 0)
    for field in range(3):                            # +0x131, +0x130, then +0x132
        if pos + 4 > len(data):
            return None
        n = int.from_bytes(data[pos:pos + 4], "little")
        if field == 2:
            return pos + 4 if n == 1 and pos + 5 <= len(data) else None
        pos += 4 + (n if 0 < n < 0x10000 else 0)


def set_start_town(town=MARGARITA):
    """Make the free-play setup pre-select `town` (it remembers the last start town in options.dat).
    The first change keeps the original as _backup/options.dat.before-test until restore_options()."""
    try:
        data = OPTIONS.read_bytes()
    except OSError:
        print("no options.dat: the game picks its default start town", flush=True)
        return None
    off = _start_town_offset(data)
    if off is None:
        print("options.dat has an unknown layout: start town left as it is", flush=True)
        return None
    if data[off] != town:
        if not OPTIONS_ORIG.exists():
            OPTIONS_ORIG.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(OPTIONS, OPTIONS_ORIG)
        OPTIONS.write_bytes(data[:off] + bytes([town]) + data[off + 1:])
        print(f"options.dat: free-play start town {data[off]} -> {town}", flush=True)
    return data[off]


def restore_options():
    if OPTIONS_ORIG.exists():
        shutil.copy2(OPTIONS_ORIG, OPTIONS)
        OPTIONS_ORIG.unlink()
        print("options.dat restored", flush=True)


# ------------------------------------------------------------- start a game --
def newgame(bps, exe=None, max_hits=None, town=MARGARITA):
    """New free-play game at `town` (default Margarita, whatever options.dat remembered)."""
    if town is not None:
        set_start_town(town)
    host = launch(bps, exe, max_hits)
    # The two buttons share a position: click again only while the menu is provably still on the
    # same screen (a main menu still sliding in can miss a click), never once it moved on.
    for _ in range(5):
        cmd("click", *MENU_FREEPLAY)
        try:
            wait_menu(6, 8, "free game", setup=True)
            break
        except SystemExit:
            if menu_state()[1] != 1:
                raise
    else:
        raise SystemExit("free game: the setup screen did not open")
    mark = log_mark()
    for _ in range(5):
        cmd("click", *SETUP_START)
        try:
            wait_log([r"WAR reset"], mark, 8, "start game")      # world reset = the generator started
            break
        except SystemExit:
            if menu_state()[1] != 6:
                raise
    else:
        raise SystemExit("start game: the generator did not start")
    wait_log([r"new game ready"], mark, 180, "new game")
    got = u32(START_TOWN)
    if town is not None and got != town:
        raise SystemExit(f"new game started at town {got}, not {town} (options.dat start town not applied)")
    close_welcome(mark)
    lagers = scan_towns()
    names = town_names()
    if len(lagers) != len(names):
        raise SystemExit(f"found {len(lagers)} towns, expected {len(names)}")
    tsv = env.HERE / "_build" / "towns.tsv"
    tsv.write_text("idx\tname\tlager\tnation\tdisplay\n" + "".join(
        f"{i}\t{n}\t{a}\t{nat}\t{d}\n" for i, (n, (a, nat, d)) in enumerate(zip(names, lagers))))
    print(f"game running (gamehost pid {host.pid}); towns -> {tsv}")


def run_flag():
    """The sim clock's running byte [0x700500+0xE44]: 0 while a modal letter (or a pause) holds the game."""
    v = u32(RUNNING)
    return v & 0xFF if v is not None else None


def close_welcome(mark):
    """After 'new game ready' the engine pre-simulates the first weeks behind the loading screen; then
    the world comes up (the top-bar button gets attached) and the welcome letter stops the clock
    (observed 2026-10-20: running byte 1 for a moment, then 0 until OK is pressed, then 1).
    Press OK while the letter holds the clock, until the clock runs."""
    wait_log([r"PANEL: top-bar nation button ready"], mark, 180, "new game")
    t0 = time.time()
    while run_flag() != 0:
        if time.time() - t0 > 15:                     # no letter seen: press where it would be, as before
            print("welcome letter not seen (game clock running); pressing OK once anyway", flush=True)
            cmd("click", *WELCOME_OK)
            time.sleep(1)
            return
        time.sleep(0.2)
    for _ in range(5):
        cmd("click", *WELCOME_OK)
        t1 = time.time()
        while time.time() - t1 < 3:
            time.sleep(0.2)
            if run_flag() == 1:
                time.sleep(SETTLE)
                return
    raise SystemExit("new game: the welcome letter did not close (game clock still stopped after 5 presses of OK)")


def quicksave(timeout=30):
    """QuickSave (0x57EE90) and return once 'Quick Save.pr2' has been rewritten and stopped changing
    (instead of a fixed pause before the game is killed or the file copied)."""
    qs = env.SAVE_DIR / "Quick Save.pr2"
    before = qs.stat().st_mtime_ns if qs.exists() else 0
    cmd("call", "0x57EE90", "0x700500")
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        time.sleep(0.25)
        try:
            st = qs.stat()
        except OSError:
            continue
        now = (st.st_mtime_ns, st.st_size)
        if st.st_mtime_ns != before and st.st_size > 0:
            if now == last:
                time.sleep(0.5)
                return qs
            last = now
    raise SystemExit("QuickSave did not write 'Quick Save.pr2'")


def load(name, bps, exe=None):
    """Launch, load save `name` from the main menu, wait for the world."""
    launch(bps, exe)
    mark = log_mark()
    cmd("call", "0x526470", "menu", "s:" + name.replace(" ", "_"))
    wait_loaded(mark, name)
    print(f"loaded {name!r}")


def wait_loaded(mark, name):
    """A load is ready once the DLL has restored the world ('load complete'), re-registered the
    Nation_* Lua API in the new Lua state and attached the top-bar nation button."""
    wait_log([r"load complete"], mark, 120, f"load {name!r}")
    wait_log([r"load complete", r"Nation_\* Lua API registered"], mark, 30, f"load {name!r}")
    wait_log([r"load complete", r"PANEL: top-bar nation button ready"], mark, 30, f"load {name!r}")
    time.sleep(SETTLE)


if __name__ == "__main__":
    bps = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bp"]
    exe = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--exe"), None)
    hits = next((int(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--max-hits"), None)
    if sys.argv[1] == "newgame":
        newgame(bps, exe, hits)
    elif sys.argv[1] == "load":
        load(sys.argv[2], bps, exe)
