"""See and poke the windowed game in the background, without touching the
user's mouse, keyboard or focus.

    python tools/screen.py place [W H]        # small window, bottom-right
    python tools/screen.py shot [name]        # -> _build/shots/<name>.png
    python tools/screen.py click X Y          # client pixel coords of the shot
    python tools/screen.py key ESC|ENTER|F5|... [times]
    python tools/screen.py type "text"

Screenshots use PrintWindow, so they work while the window is covered; they are
cropped to the game's own (DPI-virtualised) resolution, so shot pixel = click coord.
The game reads input through DirectInput, which ignores window messages, so each
click/key briefly brings the game to the front (~0.5 s) and then restores the
user's foreground window and cursor position.
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
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
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


class flash:
    """Bring the game to the front for one input burst, then put the user's
    window and cursor back exactly where they were."""
    def __enter__(self):
        self.prev, self.cur = u.GetForegroundWindow(), W.POINT()
        u.GetCursorPos(C.byref(self.cur))
        self.hwnd = game_window()
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)   # Alt tap: lets us take focus
        u.SetForegroundWindow(self.hwnd)
        time.sleep(0.25)
        if u.GetForegroundWindow() != self.hwnd:
            raise SystemExit("could not focus the game; input not sent")
        return self.hwnd

    def __exit__(self, *exc):
        time.sleep(0.15)
        u.SetCursorPos(self.cur.x, self.cur.y)
        if self.prev:
            u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
            u.SetForegroundWindow(self.prev)


def glide_to(tx, ty):
    """Reach (tx, ty) with small *relative* moves: DirectInput only sees real
    movement deltas, never a SetCursorPos jump."""
    cur = W.POINT()
    for _ in range(400):
        u.GetCursorPos(C.byref(cur))
        dx, dy = tx - cur.x, ty - cur.y
        if abs(dx) <= 1 and abs(dy) <= 1:
            return
        u.mouse_event(0x0001, max(-12, min(12, dx)), max(-12, min(12, dy)), 0, 0)
        time.sleep(0.004)


def click(x, y):
    with flash() as hwnd:
        s = scale(hwnd)
        pt = W.POINT(int(x * s), int(y * s))
        u.ClientToScreen(hwnd, C.byref(pt))
        glide_to(pt.x, pt.y)
        time.sleep(0.12)
        u.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.08)
        u.mouse_event(0x0004, 0, 0, 0, 0)


def key(name, times=1):
    vk = VK[name] if name in VK else ord(name.upper())
    scan = u.MapVirtualKeyW(vk, 0)
    with flash():
        for _ in range(times):
            u.keybd_event(vk, scan, 0, 0)
            time.sleep(0.06)
            u.keybd_event(vk, scan, 2, 0)
            time.sleep(0.15)


def type_text(text):
    with flash():
        for ch in text:
            vk = VK["SPACE"] if ch == " " else ord(ch.upper())
            u.keybd_event(vk, 0, 0, 0); time.sleep(0.05); u.keybd_event(vk, 0, 2, 0); time.sleep(0.08)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "place":
        place(*map(int, args))
    elif cmd == "shot":
        shot(args[0] if args else None)
    elif cmd == "click":
        click(int(args[0]), int(args[1]))
    elif cmd == "key":
        key(args[0], int(args[1]) if len(args) > 1 else 1)
    elif cmd == "type":
        type_text(args[0])
    else:
        sys.exit(__doc__)
