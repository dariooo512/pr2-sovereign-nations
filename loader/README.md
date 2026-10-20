# The loader (`version.dll`)

Sovereign Nations ships the modding kit's loader, the same `version.dll` for every mod:
`pr2-modkit/loader/` (its `README.md` has the patch data format and the rules for several mods
in one game folder). How it came about: `research/user_install.md`.

* Build: `python loader/build.py` → `_build/loader/version.dll` (the kit's
  `loader/build.py`; the kit is found through the setting `PR2_KIT`).
* Patch data: `python tools/export_patches.py [--check]` →
  `_build/loader/PR2Nation.patches` (the kit's `tools/release/export_patches.py` with
  `install.json`).
* Both go into the game folder next to `PR2.exe`, with `PR2Nation.dll` and the mod's data files;
  the setup (`tools/release.py` builds it from the kit's `tools/release/mod_setup.py`) does that.

## Files and switches

* `PR2Loader.log` (game folder): what the loader did for each mod, or why it left one out.
* `PR2NATION_OFF=1`: start without Sovereign Nations (`PR2LOADER_OFF=1`: without any mod).
  `PR2NATION_SECTION`: set by the loader when the section could not go to its address;
  `PR2Nation.dll` reads it (`dll/main.c`).
* Tests: `tools/loader_probe.py` (in game, test install only), `tools/test_installer.py`.
