"""Sovereign Nations' setup is the modding kit's setup for every mod (pr2-modkit/tools/release/mod_setup.py).

The release (tools/release.py) freezes the kit's mod_setup.py into "Sovereign Nations Setup.exe";
it reads the mod's name, window title and image from mod/MANIFEST.json, which the kit's release
builder writes from install.json. This module only lets the mod's own tools say `import sn_setup`
(it is the kit's module, with the names Sovereign Nations' install uses in the game folder):

    python installer/sn_setup.py [status|install|repair|uninstall] [--game DIR]
        (with the package of a release: run it from the release folder, next to mod/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import release  # noqa: E402  (finds the kit)

release.kit_release()
import mod_setup  # noqa: E402  (the kit's tools/release/mod_setup.py)
from mod_setup import *  # noqa: E402,F401,F403

APP = "Sovereign Nations"
STATE = "SovereignNations.install.json"
BACKUP = "_SovereignNations_backup"

if __name__ == "__main__":
    sys.exit(mod_setup.main())
