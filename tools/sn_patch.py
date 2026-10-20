#!/usr/bin/env python3
"""Sovereign Nations' patch build: the modding kit's tools/exe/pe_patch.py with the mod's section.

    python tools/sn_patch.py OUT.exe [--size 0x1000] [--patch-module patches/p01_....py ...]

Everything is the kit's pe_patch.py (see its help and docs/techniques/03-the-exe.md in the kit);
this only makes the mod's new section `.nation` the default (the kit's is `.mod`), so the patched
exe, its section at 0x9F7000 and the loader's patch data stay what the mod's DLL and docs expect.
From Python: `import sn_patch as pe_patch`, then pe_patch.build(...), pe_patch.PatchBuilder() ...
as with the kit's module. Settings: tools/sn_paths.py (PR2_BASE_EXE, PR2_BUILD).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sn_paths  # noqa: E402  (finds the kit, sets the settings)
import pe_patch as _kit  # noqa: E402  (the kit's tools/exe/pe_patch.py)

SECTION_NAME = ".nation"
NATION_DIR = sn_paths.MOD                # the mod's folder (patches/ is in it)
BUILD_DIR = _kit.BUILD_DIR               # the mod's _build/ (setting PR2_BUILD)
BASE_EXE = _kit.BASE_EXE
BASE_SHA256 = _kit.BASE_SHA256
PatchError = _kit.PatchError
sha256 = _kit.sha256
manifest_path = _kit.manifest_path
_load_module = _kit._load_module


class PatchBuilder(_kit.PatchBuilder):
    def __init__(self, base_path=BASE_EXE, expected_sha256=BASE_SHA256, section_size=0x1000,
                 section_name=SECTION_NAME, *args, **kw):
        super().__init__(base_path, expected_sha256, section_size, section_name, *args, **kw)


def build(out_path, patches, section_size=0x1000, base_path=BASE_EXE, expected_sha256=BASE_SHA256,
          section_name=SECTION_NAME):
    return _kit.build(out_path, patches, section_size, base_path, expected_sha256, section_name)


def __getattr__(name):                   # everything else is the kit's
    return getattr(_kit, name)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not any(a == "--section-name" or a.startswith("--section-name=") for a in argv):
        argv += ["--section-name", SECTION_NAME]
    return _kit.main(argv)


if __name__ == "__main__":
    sys.exit(main())
