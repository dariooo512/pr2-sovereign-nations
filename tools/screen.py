"""See and poke the windowed game in the background, without touching the
user's mouse, keyboard or focus.

    python tools/screen.py place [W H]        # small window, bottom-right
    python tools/screen.py shot [name]        # -> _build/shots/<name>.png
    python tools/screen.py click X Y          # client pixel coords of the shot
    python tools/screen.py key ESC|ENTER|F5|... [times]

Screenshots use PrintWindow, so they work while the window is covered; they are
cropped to the game's own (DPI-virtualised) resolution, so shot pixel = click coord.

Input goes through gamehost.py only (cmd.py "click" / "key": the host queues the
input inside the game process), so the game must run under gamehost (session.py).
The old helpers here that focused the game and moved the real cursor (flash,
glide_to, type_text: SetForegroundWindow + mouse_event / keybd_event) were removed:
tests must never take the user's focus or move the real mouse.
"""
import ctypes as C
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image

u = C.WinDLL("user32", use_last_error=True)
g = C.WinDLL("gdi32")
C.windll.shcore.SetProcessDpiAwareness(2)
u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
SHOTS = Path(__file__).resolve().parents[1] / "_build" / "shots"
VK = {"ESC": 0x1B, "ENTER": 0x0D, "SPACE": 0x20, "TAB": 0x09, "BACK": 0x08,
      "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
      **{f"F{i}": 0x6F + i for i in range(1, 13)}}
SWP_NOACTIVATE, SWP_NOZORDER = 0x10, 0x4


GAME_EXES = {"pr2_target.exe", "pr2_nation.exe"}   # env.ENV_EXE / env.MOD_EXE


def owner_exe(hwnd):
    pid = W.DWORD()
    u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    k = C.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
    buf, n = C.create_unicode_buffer(520), W.DWORD(520)
    ok = h and k.QueryFullProcessImageNameW(h, 0, buf, C.byref(n))
    if h:
        k.CloseHandle(h)
    return Path(buf.value).name if ok else ""


def game_window():
    """The game's top-level window, matched by owning process (not title:
    an editor open on this repo is also titled 'Port Royale 2')."""
    found = []

    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd) and owner_exe(hwnd).lower() in GAME_EXES:
            found.append(hwnd)
        return True
    u.EnumWindows(cb, 0)
    if not found:
        sys.exit("game window not found")
    return found[0]


def client_size(hwnd):
    r = W.RECT()
    u.GetClientRect(hwnd, C.byref(r))
    return r.right, r.bottom


def scale(hwnd):
    """Physical pixels per game pixel: >1 only when Windows DPI-virtualises the
    game (no HIGHDPIAWARE flag, see env.py dpi-aware)."""
    u.GetWindowDpiAwarenessContext.restype = C.c_void_p
    u.GetAwarenessFromDpiAwarenessContext.argtypes = [C.c_void_p]
    aware = u.GetAwarenessFromDpiAwarenessContext(u.GetWindowDpiAwarenessContext(hwnd))
    return u.GetDpiForSystem() / 96 if aware == 0 else 1


def place(w=1152, h=720):
    hwnd = game_window()
    mon = W.RECT()
    u.SystemParametersInfoW(0x30, 0, C.byref(mon), 0)          # work area
    u.SetWindowPos(hwnd, None, mon.right - w, mon.bottom - h, w, h, SWP_NOACTIVATE | SWP_NOZORDER)
    print("client", client_size(hwnd))


def shot(name=None):
    hwnd = game_window()
    w, h = client_size(hwnd)
    hdc = u.GetDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 1 | 2)          # client only, render full (DirectX) content
    buf = C.create_string_buffer(w * h * 4)
    bmi = (C.c_uint32 * 10)(40, w, -h, 0x200001, 0, 0, 0, 0, 0, 0)  # BITMAPINFOHEADER, 32bpp top-down
    g.GetDIBits(mdc, bmp, 0, h, buf, bmi, 0)
    g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(hwnd, hdc)
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name or time.strftime('%H%M%S')}.png"
    s = scale(hwnd)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    img.crop((0, 0, int(w / s), int(h / s))).save(path)
    print(path, (int(w / s), int(h / s)))
    try:                                        # keep a copy for later (screenshots/<topic>/)
        import shots_archive
        shots_archive.archive(path)
    except Exception as e:                      # archiving must never break a test
        print("screenshot archive failed:", e)
    return path


def _host(*args):
    """One command to the running gamehost (background input, see the module doc)."""
    import subprocess
    out = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "cmd.py"), *map(str, args)],
                         capture_output=True, text=True, errors="replace")
    return out.stdout + out.stderr


def click(x, y):
    """Left click at client pixel (x, y) of a shot, through gamehost (no focus, no real mouse)."""
    return _host("click", int(x), int(y))


def key(name, times=1):
    """A key press through gamehost (no focus): ESC, ENTER, F5, ... or a letter."""
    vk = VK[name] if name in VK else ord(name.upper())
    return _host("key", hex(vk), int(times))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "place":
        place(*map(int, args))
    elif cmd == "shot":
        shot(args[0] if args else None)
    elif cmd == "click":
        print(click(int(args[0]), int(args[1])), end="")
    elif cmd == "key":
        print(key(args[0], int(args[1]) if len(args) > 1 else 1), end="")
    else:
        sys.exit(__doc__)
