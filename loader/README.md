# The in-memory loader (`version.dll`)

How it works and why: `research/user_install.md`. Build: `python loader/build.py`
→ `_build/loader/version.dll`. Patch data: `python tools/export_patches.py [--check]`
→ `_build/loader/PR2Nation.patches`. Both go into the game folder next to `PR2.exe`, with
`PR2Nation.dll` and the mod's data files (the setup, `installer/sn_setup.py`, does that).

## `PR2Nation.patches` format (text, one record per line)

```
PR2NATION-PATCHDATA 1                      magic and format version (first line)
# ...                                      comments
mod <commit>                               the mod build the data was exported from
base <sha256>                              the DRM-free PR2.exe image the patches were made against
hook <slot VA> <return VA> <dll> <name>    the import slot to hook and the CRT call that triggers
section <VA> <size> <sha256>               the patch section: file address, size
data <offset> <hex>                        section contents (32 bytes per line)
patch <VA> <original hex> <new hex> ; ...  one image patch (the loader checks every original first)
reloc S <offset> <+|->                     a 4-byte field in the section that moves with it
reloc P <patch index> <offset> <+|->       a 4-byte field in a patch's new bytes that moves with it
dll <name>                                 the DLL to load after patching
end <sha256>                               sha256 of every line before this one ("\n" line ends)
```

`+` fields gain the section's displacement (absolute addresses or rel32 into the section), `-`
fields lose it (rel32 from the section back into the image).

## Files and switches

* `PR2Loader.log` (game folder): what the loader did, or why it left the game unmodded.
* `PR2NATION_OFF=1`: start without the mod. `PR2NATION_SECTION`: set by the loader when the section
  could not go to its file address; `PR2Nation.dll` reads it (`dll/main.c`).
* Tests: `tools/loader_probe.py` (in game, test install only), `tools/test_installer.py`.
