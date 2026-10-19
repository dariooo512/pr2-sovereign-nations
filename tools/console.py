"""Run Lua in the running game through PR2Nation.dll's dev console.

    python tools/console.py script.lua      (or - for stdin)

The file is written under a temp name and renamed, so the DLL never sees a
half-written script. Prints the PR2Nation.log lines produced by the run.
The suites call run() in-process (no Python start per Lua call).
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import env  # noqa: E402

LOG = env.ENV / "PR2Nation.log"


def run(src, timeout=20):
    """Run `src` and return the log lines it produced (up to 'CONSOLE status'; whatever is there
    after `timeout` s if the DLL does not answer)."""
    start = LOG.stat().st_size if LOG.exists() else 0
    tmp = env.ENV / "PR2Nation.cmd.tmp"
    tmp.write_text(src)
    os.replace(tmp, env.ENV / "PR2Nation.cmd")
    t0 = time.time()
    text = ""
    while time.time() - t0 < timeout:
        time.sleep(0.05)
        text = LOG.read_bytes()[start:].decode("latin-1")   # byte offset: the log is CRLF
        if "CONSOLE status" in text:
            break
    return text


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    print(run(sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text()), end="")
