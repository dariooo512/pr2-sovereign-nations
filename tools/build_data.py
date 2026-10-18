"""Build the mod's loose data files from your own copy of the game.

    python tools/build_data.py            (in the workspace: python tools/build_data.py)

Some of the mod's data files are made from the game's own files, so they are not published;
everyone builds them from their own Port Royale 2:

  data/scripts/FNN_*.screen, TOPMENUBAR_800x600.screen
        the nation panel's screens and the top bar with the nation button: each art/make_*.py
        screen generator reads vanilla screens and writes its screen(s);
  data/lua/config/default/include.ini
        the game's include.ini (one line) followed by the mod's mission script, lua/include_body.ini
        (in the workspace, where that file does not exist, the script part of the current
        include.ini is kept);
  data/nation_flags/flag_NNN.bmp
        the 100 nation flags as game logos (art/make_logos.py, from art/flags_src/).

Needs the game's archives extracted (setting SN_WORKDIR, see tools/sn_paths.py): the folder with
arcd/scripts/*.screen and arcs/lua/config/default/include.ini, as reverse-engineering's
cpr_extract_full.py writes them from the game's .cpr archives.
"""
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from sn_paths import MOD, WORKDIR  # noqa: E402

ART = MOD / "art"
INCLUDE = MOD / "data" / "lua" / "config" / "default" / "include.ini"
VANILLA_INCLUDE = WORKDIR / "arcs" / "lua" / "config" / "default" / "include.ini"
BODY = MOD / "lua" / "include_body.ini"
NOT_SCREENS = {"make_logos.py", "make_banner.py"}      # art/make_*.py that do not write screens


def crlf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def include_ini() -> Path:
    vanilla = VANILLA_INCLUDE.read_bytes().rstrip(b"\r\n")
    if BODY.exists():
        body = BODY.read_bytes()
    else:
        current = INCLUDE.read_bytes()
        first, sep, body = current.partition(b"\n")    # the checkout may have LF or CRLF line ends
        if not sep or first.rstrip(b"\r") != vanilla:
            raise SystemExit(f"{INCLUDE}: its first line is not the game's include.ini; nothing written")
    INCLUDE.parent.mkdir(parents=True, exist_ok=True)
    INCLUDE.write_bytes(vanilla + b"\r\n" + crlf(body))
    return INCLUDE


def main():
    missing = [p for p in (WORKDIR / "arcd" / "scripts", VANILLA_INCLUDE) if not p.exists()]
    if missing:
        raise SystemExit("the game's extracted archives are needed (setting SN_WORKDIR, now "
                         f"{WORKDIR}); missing: {', '.join(map(str, missing))}")
    for gen in sorted(ART.glob("make_*.py")):
        if gen.name not in NOT_SCREENS:
            subprocess.run([sys.executable, str(gen)], check=True)
    print(f"{include_ini()}: the game's line 1 + the mod's script")
    subprocess.run([sys.executable, str(ART / "make_logos.py")], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
