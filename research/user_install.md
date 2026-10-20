# Installing the mod into the player's own game (the player setup)

Result: **the in-memory route works** for the game build the mod is made for, and the public
release is the setup program plus the mod files; no game file is shipped, `PR2.exe` and the saves
are never changed. Status of each acceptance point at the end.

> Since then (the loader and release tools for other mods) the loader, the patch export and the setup are the modding kit's, one for
> every mod: `pr2-modkit/loader/` (it reads every `*.patches` next to the exe) and
> `pr2-modkit/tools/release/` (`export_patches.py`, `mod_setup.py`, `build_release.py`, driven by
> this mod's `install.json`). The design below is unchanged in them; file names below are the
> ones of the time.

## 1. The loader: `version.dll` in the game folder

`PR2.exe` (1.1.2.3, Steam: SteamStub v2.1) imports `VERSION.dll` (`GetFileVersionInfoA`,
`GetFileVersionInfoSizeA`, `VerQueryValueA`) and `WINMM.dll` (`timeGetTime`). Neither is a
KnownDLL, so Windows loads a `version.dll` from the game folder first. `version.dll` is the better
proxy: 17 exports (winmm has ~180), and dgVoodoo2 does not use it (its `D3D8.dll`, `D3DImm.dll`,
`DDraw.dll` stay free). The loader (`loader/loader.c`, built by `loader/build.py`) exports all 17
names; each stub loads the system `version.dll` (`GetSystemDirectory`, SysWOW64 in this 32-bit
process) on first use and jumps to the real function with the arguments untouched.

## 2. When to patch: the CRT's call to `MSVCR71!__set_app_type`

SteamStub decrypts `.text` and then jumps to the original entry point `0x64E03F`; `.rdata`,
`.data` and `.rsrc` are not encrypted, and the import table in `.rdata` is the original one, so
the Windows loader binds the game's imports as usual before any DLL's `DllMain` runs. The CRT
start-up code right after the entry point calls `__set_app_type` through the import slot
`0x67F6F0` (return address `0x64E0B6`, verified by disassembly in `tools/export_patches.py`). By
then the game code is in memory exactly as in the DRM-free image, and no game code has run yet.

So in `DllMain` the loader only swaps that one import slot. When the hook is called from
`0x64E0B6` it puts the slot back, then:

1. checks the original bytes of **every** patch site against the patch data; on any difference it
   writes nothing, logs the address (`PR2Loader.log`) and lets the game start without the mod;
2. allocates the patch section at its file address `0x9F7000` if that memory is free, or anywhere
   else, applying the data's relocations and telling `PR2Nation.dll` the address in
   `PR2NATION_SECTION` (`dll/main.c` `find_section`). In the test runs `0x9F7000` was taken, the
   section went to `0x017B0000` and the relocated mod ran normally (LDR-01);
3. writes the 22 patches, flushes the instruction cache, loads `PR2Nation.dll` (what patch P06's
   entry-point cave does in the file route), and calls the real `__set_app_type`.

The loader never removes or alters the DRM: SteamStub runs and checks the copy as always. An exe
that already carries the patches on disk (`PR2_nation.exe`, the file route used by the test
machines) is detected (patch sites already new, section present) and the loader stays idle.
`PR2NATION_OFF=1` starts the game without the mod.

## 3. One source for the patches: `PR2Nation.patches`

`tools/export_patches.py` runs `patches/p01..p07` through `pe_patch.py`'s `PatchBuilder` as the file
build does and writes the result as text: section VA/size/contents, every patch (VA, original
bytes, new bytes), the relocations (found by building at three section addresses, not written by
hand), the trigger, and a sha256 end line over the body. `--check` proves that applying the data to
the DRM-free image gives exactly the image of the file build (`PR2_nation.exe`, sha256 4387712c…),
and that a relocated section matches a build at that address.

## 4. The setup program and the release

* `installer/sn_setup.py` (window and command line): finds Steam's install through the registry and
  `libraryfolders.vdf` / `appmanifest_12470.acf` (read only), or a folder the player picks;
  identifies `PR2.exe` by sha256 (Steam build `5295c066…`, DRM-free image `9c9250bc…`) and refuses
  anything else; asks before installing next to another mod's `towns\*.tow`; installs the loader,
  `PR2Nation.dll`, the patch data and the loose data files; backs up every file it replaces to
  `_SovereignNations_backup\`; records everything in `SovereignNations.install.json`; Install over
  an older version updates in place; Repair restores changed or missing files; Uninstall removes
  what it added, restores what it replaced and removes the folders it created. Saves are never
  touched. dgVoodoo2 (Intel D3D9on12 hang) is installed only when ticked and only when the release
  carries it (`tools/release.py --dgvoodoo DIR` from an official release; its licence, ReadmeGeneral
  §1, allows shipping unmodified dgVoodoo files with a game mod).
* `tools/release.py` builds `dist/release/SovereignNations_v<date>-<commit>/` + zip: setup, `mod/`
  with `MANIFEST.json` (sha256 per file), player docs. It refuses to build if any file equals one of
  the game's files (the test install's game files and the extracted archive contents, 6297 files)
  or is a game file type. The setup is a script + `.bat` until PyInstaller is installed; then
  `release.py` freezes it into `Sovereign Nations Setup.exe`.
* A private package of the whole test install stays the package for test machines.

## 5. Tests

* `tools/test_installer.py` (9 checks, throw-away folders with a copy of the Steam `PR2.exe`):
  install, `PR2.exe` unchanged, repair, update in place, uninstall byte-identical, a replaced loose
  file restored, the other-mod question, an unknown exe refused, Steam discovery.
* `tools/loader_probe.py` (in the test install, inside its lock; 3/3 pass on 2026-10-18): LDR-01 the DRM-free
  `PR2_target.exe` + loader runs the full mod from memory (patches applied, DLL loaded, the save's
  nation and the Lua API there); LDR-02 the patched `PR2_nation.exe` + loader: loader idle, the DLL
  loads once; LDR-03 patch data with one wrong original byte: nothing patched, the DLL not loaded,
  the game still runs.

## 6. Not done here, and why

* **Starting the Steam-wrapped `PR2.exe`.** It was never started in these tests: SteamStub carries
  `steam.exe` / `-applaunch` and relaunches through Steam when started outside it, which would start
  the user's real Steam install (it carries another mod, the 4x towns, and is off limits for tests).
  The loader's trigger fires after SteamStub has decrypted the code, on the same CRT call as in the
  DRM-free exe, so the DRM-free run checks the same path; the one difference not exercised is
  SteamStub itself running first. **Pending the user's approval:** in a fresh Steam install (or the
  user's, without the 4x mod), run `sn_setup.py install`, start the game from Steam
  (`steam://run/12470`), check `PR2Loader.log` ("22 patches applied in memory") and `PR2Nation.log`,
  then run the feature suite with the Steam start; uninstall and diff the folder.
* **GOG.** Not investigated (no GOG copy here). If a GOG `PR2.exe` is byte-identical to the DRM-free
  image (`9c9250bc…`), the same patch data works; the setup already accepts that hash.
* **Derived data files.** The release contains no game file, but some mod files are built from game
  files: the `FNN_*` screens are clones of vanilla controls (`art/make_*.py`), `TOPMENUBAR` is a
  modified vanilla screen and `include.ini` extends the vanilla one. The release ships them built
  (decided 19 Oct 2026); the source repository ships only their generators (`tools/build_data.py`).
* **dgVoodoo2** is not bundled by default (no official copy here; the release takes it from a folder
  the maintainer downloads from the official site).
