"""Build the loader, version.dll (the player setup, loader/loader.c), with the 32-bit MSYS2 MinGW GCC.

    python loader/build.py   ->  _build/loader/version.dll
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from sn_paths import gcc  # noqa: E402  (setting MINGW32_BIN)

OUT = HERE.parent / "_build" / "loader" / "version.dll"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    gcc_exe = gcc()
    cmd = [str(gcc_exe), "-m32", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-shared", "-static",
           "-static-libgcc", "-o", str(OUT), str(HERE / "loader.c"), str(HERE / "sha256.c"), str(HERE / "version.def"),
           "-Wl,--enable-stdcall-fixup"]
    env = dict(os.environ, PATH=str(gcc_exe.parent) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode == 0:
        print(f"built {OUT} ({OUT.stat().st_size} bytes)")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
