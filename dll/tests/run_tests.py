"""Build and run the native unit tests of the nation core (no game needed).

    python dll/tests/run_tests.py
        -> _build/tests/test_core.exe, exit code = failures
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DLL = HERE.parent
sys.path.insert(0, str(DLL.parent / "tools"))
from sn_paths import MINGW32_BIN as GCC_BIN  # noqa: E402  (setting MINGW32_BIN)
OUT = DLL.parent / "_build" / "tests" / "test_core.exe"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(GCC_BIN / "gcc.exe"), "-m32", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
           "-o", str(OUT), str(HERE / "test_core.c"), str(DLL / "core.c")]
    env = dict(os.environ, PATH=str(GCC_BIN) + os.pathsep + os.environ["PATH"])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode != 0:
        print("BUILD FAILED")
        return 1
    r = subprocess.run([str(OUT)], env=env)
    print("TESTS PASSED" if r.returncode == 0 else f"TESTS FAILED ({r.returncode} failures)")
    return 1 if r.returncode else 0


if __name__ == "__main__":
    sys.exit(main())
