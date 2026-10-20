"""Where the mod's tools find the modding kit and everything that is not part of the mod.

The test tools (test install, game host, sessions, screenshots, console, patch builder, screen
files) are the modding kit's, not copies: https://github.com/dariooo512/pr2-modkit. Importing
this module finds the kit and puts its tool folders (tools/, tools/test/, tools/exe/,
tools/files/) on sys.path, so `import env`, `import session`, `import pe_patch` ... are the kit's.
The mod's own wrappers around them are sn_env.py, sn_session.py and sn_patch.py.

Finding the kit (setting PR2_KIT): the folder in PR2_KIT, else a checkout named `pr2-modkit`
next to this repository (clone both into one folder), else next to the workspace's main checkout.

The settings are the kit's (tools/kit_paths.py in the kit), with the mod's own defaults:

  PR2_WORKDIR     the game's archives, extracted (arcd/, arcs/ ... with scripts/, lua/, Data/);
                  the screen generators in art/ and tools/build_data.py read vanilla files there
  PR2_BASE_EXE    PR2.exe 1.1.2.3 with SteamStub removed (sha256 9c9250bc...), the base of the
                  patch build (sn_patch.py, tools/export_patches.py)
  PR2_PRISTINE    an unmodified copy of the game folder (the test install is copied from it)
                  These three default to the workspace the mod was made in when it is there
                  (../reverse-engineering/_workdir, ../reverse-engineering/_re/, ../original-game/original),
                  else to the kit's defaults (the kit's _game/ folder, see its docs/getting-started.md).
  PR2_TEST_ENV    the disposable test install          default %USERPROFILE%\\PR2-nation-env
  PR2_TEST_LOCK   the lock that test runs share         default the test install's path + ".lock"
  PR2_SAVE_DIR    the game's Save folder (default: Documents\\Ascaron Entertainment\\Port Royale 2\\Save,
                  with Documents where Windows says it is, also when it is redirected)
  PR2_BUILD       where the tools write runs, logs and screenshots   default _build/ of the mod
  PR2_BACKUP_DIR  where the Save folder backups go                   default _backup/ of the mod
  MINGW32_BIN     the bin folder of a 32-bit MinGW-w64 GCC (default: MSYS2's C:\\msys64\\mingw32\\bin)

The defaults are written into os.environ, so the kit's tools started as programs from here
(gamehost.py, mute_game.ps1 ...) use the same settings. The older names SN_WORKDIR, SN_BASE_EXE,
SN_PRISTINE, SN_TEST_ENV, SN_TEST_LOCK, SN_SAVE_DIR and SN_SETTLE still work for now, with a
one-line note; the PR2_ name wins when both are set.

    python tools/sn_paths.py      prints the kit and every setting, where it comes from and whether it exists
"""
import os
import subprocess
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parents[1]          # the mod's folder
WORKSPACE = MOD.parent                             # the folder the workspace defaults are relative to


def main_workspace(ws: Path) -> Path:
    """In a git worktree the reverse-engineering folders and the kit live next to the main checkout."""
    if (ws / "reverse-engineering").is_dir():
        return ws
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=MOD, capture_output=True,
                                text=True).stdout.strip()
    except OSError:
        return ws
    main = (MOD / common).resolve().parent if common else ws
    return main if (main / "reverse-engineering").is_dir() else ws


WORKSPACE = main_workspace(WORKSPACE)

ALIASES = {"SN_WORKDIR": "PR2_WORKDIR", "SN_BASE_EXE": "PR2_BASE_EXE", "SN_PRISTINE": "PR2_PRISTINE",
           "SN_TEST_ENV": "PR2_TEST_ENV", "SN_TEST_LOCK": "PR2_TEST_LOCK", "SN_SAVE_DIR": "PR2_SAVE_DIR",
           "SN_SETTLE": "PR2_SETTLE"}
SOURCE = {}                                        # setting -> where its value came from (for main())


def _workspace_default(path: Path):
    """The workspace layout's default, only where that workspace is (a plain clone gets the kit's)."""
    return path if path.exists() else None


def _defaults() -> dict:
    re_ = WORKSPACE / "reverse-engineering"
    return {
        "PR2_WORKDIR": _workspace_default(re_ / "_workdir"),
        "PR2_BASE_EXE": _workspace_default(re_ / "_re" / "PR2.exe.unpacked.exe"),
        "PR2_PRISTINE": _workspace_default(WORKSPACE / "original-game" / "original"),
        "PR2_TEST_ENV": Path.home() / "PR2-nation-env",
        "PR2_BUILD": MOD / "_build",
        "PR2_BACKUP_DIR": MOD / "_backup",
    }


def _apply_settings():
    for old, new in ALIASES.items():
        if os.environ.get(old):
            if os.environ.get(new):
                if os.environ[new] != os.environ[old]:
                    print(f"note: {old} is ignored, {new} is set (the old SN_ names are deprecated)", file=sys.stderr)
            else:
                os.environ[new] = os.environ[old]
                SOURCE[new] = f"{old} (deprecated)"
                print(f"note: {old} is deprecated, set {new} instead (same meaning)", file=sys.stderr)
    for var, path in _defaults().items():
        if os.environ.get(var):
            SOURCE.setdefault(var, "env")
        elif path is not None:
            os.environ[var] = str(path)
            SOURCE[var] = "mod default"


def find_kit() -> Path:
    """The modding kit's checkout: PR2_KIT, else pr2-modkit next to this repository or the workspace."""
    v = os.environ.get("PR2_KIT")
    if v:
        kit = Path(v).expanduser()
        if not (kit / "tools" / "kit_paths.py").exists():
            raise SystemExit(f"PR2_KIT={kit} is not a checkout of the modding kit (no tools/kit_paths.py in it)")
        SOURCE["PR2_KIT"] = "env"
        return kit.resolve()
    for kit in (MOD.parent / "pr2-modkit", WORKSPACE / "pr2-modkit"):
        if (kit / "tools" / "kit_paths.py").exists():
            SOURCE["PR2_KIT"] = "next to the repository"
            return kit.resolve()
    raise SystemExit(
        "the modding kit was not found. Sovereign Nations' tools use the kit's test and build tools:\n"
        f"  git clone https://github.com/dariooo512/pr2-modkit {MOD.parent / 'pr2-modkit'}\n"
        "or, for a checkout somewhere else, set PR2_KIT to its folder.")


_apply_settings()
KIT = find_kit()
os.environ["PR2_KIT"] = str(KIT)
KIT_TOOLS = KIT / "tools"
for _d in reversed([KIT_TOOLS, KIT_TOOLS / "test", KIT_TOOLS / "exe", KIT_TOOLS / "files"]):
    if str(_d) not in sys.path:
        sys.path.insert(1 if sys.path else 0, str(_d))   # after the running script's own folder

import kit_paths  # noqa: E402  (the kit's settings, read from os.environ set above)

WORKDIR = kit_paths.WORKDIR
BASE_EXE = kit_paths.BASE_EXE
PRISTINE = kit_paths.PRISTINE
TEST_ENV = kit_paths.TEST_ENV
TEST_LOCK = kit_paths.TEST_LOCK
SAVE_DIR = kit_paths.SAVE_DIR
BUILD = kit_paths.BUILD
BACKUP_DIR = kit_paths.BACKUP_DIR
MINGW32_BIN = kit_paths.MINGW32_BIN
gcc = kit_paths.gcc


def main():
    print(f"{'PR2_KIT':<15} {SOURCE.get('PR2_KIT', ''):<22} {'exists':<8} {KIT}")
    for var, p in [("PR2_WORKDIR", WORKDIR), ("PR2_BASE_EXE", BASE_EXE), ("PR2_PRISTINE", PRISTINE),
                   ("PR2_TEST_ENV", TEST_ENV), ("PR2_TEST_LOCK", TEST_LOCK), ("PR2_SAVE_DIR", SAVE_DIR),
                   ("PR2_BUILD", BUILD), ("PR2_BACKUP_DIR", BACKUP_DIR), ("MINGW32_BIN", MINGW32_BIN)]:
        src = SOURCE.get(var) or ("env" if os.environ.get(var) else "kit default")
        print(f"{var:<15} {src:<22} {'exists' if p.exists() else 'missing':<8} {p}")


if __name__ == "__main__":
    main()
