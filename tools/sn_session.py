"""Sovereign Nations' game sessions: the modding kit's tools/test/session.py with the mod's signals.

    python tools/sn_session.py newgame [--exe PR2_nation.exe] [--town N] [--bp SPEC ...]
    python tools/sn_session.py load "Quick Save" [--exe ...] [--bp ...]
    python tools/sn_session.py stop

Everything is the kit's session.py (see its help); this sets only what is the mod's:
  - the readiness signals are the lines PR2Nation.dll writes to PR2Nation.log: the world reset
    when the generator starts, "new game ready", the top-bar nation button once the world is up,
    and for a load "load complete", the Nation_* Lua API and the button again;
  - a new game always starts at Margarita (staedte.ini index 56, the suites' start town),
    whatever options.dat remembered, and stops when the town scan misses a town;
  - every screenshot is also archived by topic (tools/shots_archive.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sn_env  # noqa: E402  (finds the kit, the mod's files in the test install)
import session as _kit  # noqa: E402  (the kit's tools/test/session.py)

MARGARITA = 56              # staedte.ini order; the suites' start town (Spanish governor seat)

_kit.LOG = sn_env.MOD_LOG   # PR2Nation.log (the DLL recreates it at every launch)
_kit.MARKERS = {
    "started": [r"WAR reset"],                          # world reset = the generator started
    "ready": [r"new game ready"],
    "world": [r"PANEL: top-bar nation button ready"],
    "loaded": [([r"load complete"], 120),               # the DLL restored the world
               ([r"load complete", r"Nation_\* Lua API registered"], 30),
               ([r"load complete", r"PANEL: top-bar nation button ready"], 30)],
}
_kit.DEFAULT_TOWN = MARGARITA
_kit.STRICT_TOWNS = True


def _archive(path):
    import shots_archive
    shots_archive.archive(path)


try:                                    # keep a copy of every screenshot (screenshots/<topic>/)
    import screen as _screen  # noqa: E402
    if _archive not in _screen.AFTER_SHOT:
        _screen.AFTER_SHOT.append(_archive)
except ImportError:                     # no Pillow: no screenshots either
    pass


def __getattr__(name):                  # everything else is the kit's (cmd, newgame, load, _host ...)
    return getattr(_kit, name)


if __name__ == "__main__":
    _kit.main()
