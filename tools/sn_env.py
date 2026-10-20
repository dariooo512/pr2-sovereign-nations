"""Sovereign Nations' view of the modding kit's test install (the kit's tools/test/env.py).

    python tools/sn_env.py setup | status | backup-saves | restore-saves [DIR] | undeploy
    python tools/sn_env.py windowed on|off | fast-boot on|off | dpi-aware on|off|list
    python tools/sn_env.py deploy <built.exe>        a patched build as PR2_nation.exe, with the DLL

Everything is the kit's env.py (see its help); this adds only what is the mod's:
  - the mod's files in the test install: PR2_nation.exe (the patched build), PR2Nation.dll
    (_build/dll, loaded by patch P06) and PR2Nation.log;
  - deploy BUILT: the kit's deploy of the build as PR2_nation.exe plus the DLL, recorded, so
    `undeploy` and the DPI flag know them;
  - backup_saves() returns the snapshot's Save folder (the suites copy the saves back from it
    themselves and leave the scenario saves made since in place), restore_run(that folder) puts
    the Run folder's logo files back (the mod writes the nation's flag there).
Settings: tools/sn_paths.py (the kit's names, the mod's defaults).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sn_paths  # noqa: E402  (finds the kit, sets the settings)
import env as _kit  # noqa: E402  (the kit's tools/test/env.py)

HERE = sn_paths.MOD                  # the mod's folder
REPO = sn_paths.WORKSPACE
WORKDIR = sn_paths.WORKDIR           # the game's archives, extracted
MOD_EXE = _kit.ENV / "PR2_nation.exe"     # patched build deployed by deploy()
MOD_DLL = _kit.ENV / "PR2Nation.dll"      # nation logic, loaded by patch P06
MOD_LOG = _kit.ENV / "PR2Nation.log"

_kit.OWN |= {MOD_EXE.name, MOD_DLL.name, MOD_LOG.name}   # not drift (status)
_kit.TOOL_EXES.add(MOD_EXE.name.lower())                 # a test exe of the tools (dpi-aware)


def deploy(built):
    """A pe_patch build (sn_patch.py) into the test install as PR2_nation.exe, and the DLL."""
    _kit.deploy([built], name=MOD_EXE.name)
    dll = HERE / "_build" / "dll" / MOD_DLL.name
    if dll.exists():
        _kit.deploy([dll])


def backup_saves():
    """The kit's snapshot of the Save and Run folders; returns its Save folder."""
    return _kit.backup_saves() / "Save"


def restore_run(backup):
    """The Run folder (the player's logo files) back from the snapshot whose Save folder is `backup`."""
    _kit.restore_run(Path(backup).parent if Path(backup).name == "Save" else Path(backup))


def __getattr__(name):                   # everything else is the kit's (ENV, SAVE_DIR, windowed ...)
    return getattr(_kit, name)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["deploy"] and len(argv) == 2:
        deploy(argv[1])
        return 0
    return _kit.main(argv)


if __name__ == "__main__":
    sys.exit(main())
