"""Where the mod's tools find things that are not part of the mod: settings with defaults.

Each setting is an environment variable. Unset, it takes the default below, which is the layout
of the workspace the mod was made in (the mod's folder next to reverse-engineering/ and
original-game/). In a checkout of the mod on its own, point them at your own copies:

  SN_WORKDIR     the game's archives, extracted (arcd/, arcs/ ... with scripts/, lua/, Data/);
                 the screen generators in art/ and tools/build_data.py read vanilla files there
  SN_BASE_EXE    PR2.exe 1.1.2.3 with SteamStub removed (sha256 9c9250bc...), the base of the
                 patch build (tools/pe_patch.py, tools/export_patches.py)
  SN_PRISTINE    an unmodified copy of the game folder (the test install is copied from it)
  SN_TEST_ENV    the disposable test install (tools/env.py)
  SN_TEST_LOCK   the lock folder that test runs share, so only one runs the test install at a time
  SN_SAVE_DIR    the game's Save folder (default: Documents\\Ascaron Entertainment\\Port Royale 2\\Save,
                 with Documents where Windows says it is, also when it is redirected)
  MINGW32_BIN    the bin folder of a 32-bit MinGW-w64 GCC (default: MSYS2's C:\\msys64\\mingw32\\bin)
"""
import os
from pathlib import Path

MOD = Path(__file__).resolve().parents[1]          # the mod's folder
WORKSPACE = MOD.parent                             # the folder the defaults are relative to


def setting(var: str, default: Path) -> Path:
    v = os.environ.get(var)
    return Path(v).expanduser() if v else default


def documents() -> Path:
    """The user's Documents folder as Windows knows it (it may be redirected to another folder)."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
            try:
                return Path(out.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(out)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Documents"


WORKDIR = setting("SN_WORKDIR", WORKSPACE / "reverse-engineering" / "_workdir")
BASE_EXE = setting("SN_BASE_EXE", WORKSPACE / "reverse-engineering" / "_re" / "PR2.exe.unpacked.exe")
PRISTINE = setting("SN_PRISTINE", WORKSPACE / "original-game" / "original")
TEST_ENV = setting("SN_TEST_ENV", Path.home() / "PR2-nation-env")
TEST_LOCK = setting("SN_TEST_LOCK", Path.home() / "PR2-nation-env.lock")
SAVE_DIR = setting("SN_SAVE_DIR", documents() / "Ascaron Entertainment" / "Port Royale 2" / "Save")
MINGW32_BIN = setting("MINGW32_BIN", Path(r"C:\msys64\mingw32\bin"))
