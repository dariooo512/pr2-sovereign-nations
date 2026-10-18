"""Send a command to a running gamehost.py and print its reply.

    python tools/cmd.py towns 0x<vtable>
    python tools/cmd.py setnation 0x<lager> 5 3
    python tools/cmd.py read 0x<addr> [n]
    python tools/cmd.py write 0x<addr> <hex>
"""
import sys
sys.stdout.reconfigure(errors="replace")
import time

from gamehost import CMD_FILE, env

done = CMD_FILE.with_suffix(".done")
done.unlink(missing_ok=True)
log = max((env.HERE / "_build" / "runs").glob("*/gamehost.log"))
start = log.stat().st_size
CMD_FILE.write_text(" ".join(sys.argv[1:]) + "\n")
for _ in range(600):
    if done.exists():
        break
    time.sleep(0.1)
else:
    sys.exit("no reply in 60s (is gamehost.py running?)")
with open(log, encoding="utf-8", errors="replace") as f:
    f.seek(start)
    print(f.read(), end="")
