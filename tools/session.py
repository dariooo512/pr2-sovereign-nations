"""Scripted game session: launch under gamehost, start a free-play game, and
hand back control -- all in the background (no focus, no mouse).

    python tools/session.py newgame [--exe PR2_nation.exe] [--bp SPEC ...]
    python tools/session.py load "Quick Save" [--exe ...] [--bp ...]

Leaves the game running at the sea/town view with the welcome dialog closed and
writes the 60 town objects (index = staedte.ini order, with names) to
_build/towns.tsv. Use cmd.py for everything after that.
"""
import re
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


def latest_log():
    return max((env.HERE / "_build" / "runs").glob("*/gamehost.log"))


def wait_for(pattern, after, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        text = latest_log().read_text(errors="replace")[after:]
        if re.search(pattern, text):
            return text
        time.sleep(0.5)
    raise SystemExit(f"timeout waiting for {pattern!r}")


_host = None          # the running gamehost.py process (launch)


def host_alive():
    return _host is None or _host.poll() is None


def cmd(*args):
    """Send one command to gamehost. Once the host has died, fail at once instead of
    waiting 60 s per call (a dead host also takes the game with it)."""
    if not host_alive():
        raise SystemExit(f"gamehost is gone (exit {_host.returncode}); see the run dir's host_stderr.txt")
    out = subprocess.run([sys.executable, str(HERE / "cmd.py"), *map(str, args)],
                         capture_output=True, text=True, errors="replace")
    if "no reply in 60s" in (out.stdout + out.stderr) and not host_alive():
        raise SystemExit(f"gamehost died during '{' '.join(map(str, args))}'")
    return out.stdout


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


def launch(bps, exe=None, max_hits=None):
    """Start the game under gamehost and wait until the main menu is up.
    Always enforces the test settings first (windowed, intro skipped, no DPI
    doubling): a fullscreen launch would take over the user's screen."""
    env.windowed(True)
    env.fast_boot(True)
    env.dpi_aware(True)
    env.mute_sound()                  # no sound from test games
    args = [sys.executable, str(HERE / "gamehost.py")] + (["--exe", exe] if exe else [])         + (["--max-hits", str(max_hits)] if max_hits else [])
    for b in bps:
        args += ["--bp", b]
    desk = input_desktop()
    if desk != "Default":
        raise SystemExit(f"the PC's input desktop is {desk!r} (screen saver or locked): "
                         "the game's Direct3D cannot start; rerun when the PC is in use")
    global _host
    for attempt in range(3):
        err = open(env.HERE / "_build" / "host_stderr.txt", "ab")      # a host crash leaves its traceback here
        host = _host = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=err)
        time.sleep(2)
        # engine up (the benign font throw); a start-up D3D failure right after
        # the previous instance was killed exits within seconds -> retry
        text = wait_for(r"PAVCGenericException|EXIT code=", 0)
        if "PAVCGenericException" in text:
            time.sleep(4)
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


def newgame(bps, exe=None, max_hits=None):
    host = launch(bps, exe, max_hits)
    cmd("click", *MENU_FREEPLAY); time.sleep(3)
    cmd("click", *SETUP_START)
    time.sleep(40)                                  # world generation + town load
    cmd("click", *WELCOME_OK); time.sleep(1)
    lagers = scan_towns()
    names = town_names()
    if len(lagers) != len(names):
        raise SystemExit(f"found {len(lagers)} towns, expected {len(names)}")
    tsv = env.HERE / "_build" / "towns.tsv"
    tsv.write_text("idx\tname\tlager\tnation\tdisplay\n" + "".join(
        f"{i}\t{n}\t{a}\t{nat}\t{d}\n" for i, (n, (a, nat, d)) in enumerate(zip(names, lagers))))
    print(f"game running (gamehost pid {host.pid}); towns -> {tsv}")


def load(name, bps, exe=None):
    """Launch, load save `name` from the main menu, wait for the world."""
    launch(bps, exe)
    cmd("call", "0x526470", "menu", "s:" + name.replace(" ", "_"))
    time.sleep(45)
    print(f"loaded {name!r}")


if __name__ == "__main__":
    bps = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bp"]
    exe = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--exe"), None)
    hits = next((int(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--max-hits"), None)
    if sys.argv[1] == "newgame":
        newgame(bps, exe, hits)
    elif sys.argv[1] == "load":
        load(sys.argv[2], bps, exe)
