"""Run Lua in the running game through PR2Nation.dll's dev console.

    python tools/console.py script.lua      (or - for stdin)

The file is written under a temp name and renamed, so the DLL never sees a
half-written script. Prints the PR2Nation.log lines produced by the run.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import env  # noqa: E402

src = sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
log = env.ENV / "PR2Nation.log"
start = log.stat().st_size if log.exists() else 0
tmp = env.ENV / "PR2Nation.cmd.tmp"
tmp.write_text(src)
os.replace(tmp, env.ENV / "PR2Nation.cmd")
for _ in range(100):
    time.sleep(0.2)
    text = log.read_bytes()[start:].decode("latin-1")   # byte offset: the log is CRLF
    if "CONSOLE status" in text:
        break
print(text, end="")
