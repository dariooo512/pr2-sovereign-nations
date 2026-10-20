"""Watch the powers' military convoys in a running game (research aid for the national navy).

    python tools/milprobe.py [--save "FNN 10 - Nation founded"] [--days 20]

Loads the save in the corner window, then once per game day dumps every convoy
whose type (+0xB4) is 4 (military): nation +0xB8, state +0x90, town +0x9C,
attack mask +0x48, mission bytes +0x170..+0x173, sailors +0x86. Output:
_build/milprobe.tsv (one row per convoy per day) and a summary on stdout.
"""
import argparse
import struct
import sys
import time

import sn_env as env
import sn_session as session
import conquest_test as C
import feature_suite as F

OUT = env.HERE / "_build" / "milprobe.tsv"
KEYS = ["type", "nation", "state", "town", "mask", "flags7c", "sailors", "maxs", "m170", "b4c"]
CONVOY_TABLE = 0x701EE8


def convoys():
    hdr = C.mem(CONVOY_TABLE, 12)
    base, _, cnt = struct.unpack("<III", hdr)
    n = cnt & 0xFFFF
    arr = C.mem(base, 4 * n) or b""
    for i in range(len(arr) // 4):
        p = struct.unpack_from("<I", arr, 4 * i)[0]
        if p:
            yield i, p


def dump(p):
    d = C.mem(p, 0x180)
    if not d:
        return None
    u8 = lambda o: d[o]                                   # noqa: E731
    u16 = lambda o: struct.unpack_from("<H", d, o)[0]     # noqa: E731
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]     # noqa: E731
    return {"type": u32(0xB4), "nation": u8(0xB8), "state": u32(0x90), "town": u32(0x9C),
            "mask": u32(0x48), "flags7c": u32(0x7C), "sailors": u16(0x86), "maxs": u16(0x88),
            "m170": d[0x170:0x174].hex(), "b4c": u32(0x4C), "raw": d.hex()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="FNN 10 - Nation founded")
    ap.add_argument("--days", type=int, default=20)
    a = ap.parse_args()
    backup = env.backup_saves()
    rows = []
    try:
        env.windowed(True)
        env.fast_boot(True)
        env.dpi_aware(True)
        session.load(a.save, [], "PR2_nation.exe")
        out = open(OUT, "w")
        out.write("day\tdom\tslot\tptr\t" + "\t".join(KEYS) + "\traw\n")
        for day in range(a.days + 1):
            date = C.u8(0x702C1C)
            mil = 0
            for i, p in convoys():
                r = dump(p)
                if r and r["type"] == 4:
                    mil += 1
                    rows.append(r)
                    out.write(f"{day}\t{date}\t{i}\t{p:#x}\t" + "\t".join(
                        hex(r[k]) if isinstance(r[k], int) else r[k] for k in KEYS) + f"\t{r['raw']}\n")
            out.flush()
            print(f"day {day} (dom {date}): {mil} military convoys", flush=True)
            if day < a.days:
                for attempt in range(3):              # a console call can time out at a busy moment
                    try:
                        F.run_days(1)
                        break
                    except KeyError:
                        time.sleep(5)
    finally:
        F.M.kill_game()
        for f in backup.iterdir():
            if f.is_file():
                import shutil
                shutil.copy2(f, env.SAVE_DIR / f.name)
        env.restore_run(backup)
        orig = env.BACKUPS / "settings.cfg.orig"
        if orig.exists():
            import shutil
            shutil.copy2(orig, env.SAVE_DIR / "settings.cfg")
    print(f"{len(rows)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
