"""Build PR2Nation.dll with the 32-bit MSYS2 MinGW GCC.

    python dll/build.py   ->  _build/dll/PR2Nation.dll
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from sn_paths import gcc  # noqa: E402  (setting MINGW32_BIN)

OUT = HERE.parent / "_build" / "dll" / "PR2Nation.dll"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    srcs = sorted(str(p) for p in HERE.glob("*.c"))
    gcc_exe = gcc()
    cmd = [str(gcc_exe), "-m32", "-std=gnu11", "-O2", "-Wall", "-Wextra",
           "-Wno-unused-parameter", "-shared", "-static", "-static-libgcc",
           "-o", str(OUT), *srcs, "-Wl,--enable-stdcall-fixup", "-luser32", "-lole32"]
    env = dict(os.environ, PATH=str(gcc_exe.parent) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode == 0:
        print(f"built {OUT} ({OUT.stat().st_size} bytes)")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
