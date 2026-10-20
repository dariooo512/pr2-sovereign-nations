"""Build the loader, version.dll: the modding kit's loader (pr2-modkit/loader/), one for every mod.

    python loader/build.py   ->  _build/loader/version.dll

The kit is found through the setting PR2_KIT (tools/release.py kit_dir()). The compiler: the
32-bit MSYS2 MinGW GCC (setting MINGW32_BIN).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import release  # noqa: E402

OUT = HERE.parent / "_build" / "loader" / "version.dll"


def main():
    release.kit_release()                                # the mod's settings (MINGW32_BIN) for the kit
    return subprocess.run([sys.executable, str(release.kit_dir() / "loader" / "build.py"), "--out", str(OUT)]).returncode


if __name__ == "__main__":
    sys.exit(main())
