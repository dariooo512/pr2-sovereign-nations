#!/usr/bin/env python3
"""Export patches/p01..p07 as patch data for the loader: the kit's export with the mod's install.json.

    python tools/export_patches.py [--out FILE] [--version V] [--check]

The work is done by the modding kit's tools/release/export_patches.py (the kit: release.kit_dir(),
setting PR2_KIT), with install.json's patch modules (patches/p0*.py), section (.nation, 0x1000) and
DLL (PR2Nation.dll), on the DRM-free base exe (setting SN_BASE_EXE). Default output:
_build/loader/PR2Nation.patches. --check also proves that applying the data to the
base image gives exactly the image of the file build PR2_nation.exe (sha256 4387712c... for the
current patch set), and that the data still works when the section has to move.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release  # noqa: E402
import sn_paths  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--version", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    release.kit_release()
    path = release.kit_dir() / "tools" / "release" / "export_patches.py"
    spec = importlib.util.spec_from_file_location("kit_export_patches", path)
    kit_export = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit_export)
    args = [str(release.INSTALL_JSON), "--base", str(sn_paths.BASE_EXE)]
    args += ["--out", str(a.out)] if a.out else []
    args += ["--version", a.version] if a.version else []
    args += ["--check"] if a.check else []
    return kit_export.main(args)


if __name__ == "__main__":
    sys.exit(main())
