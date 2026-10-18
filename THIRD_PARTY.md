# Third-party material

This repository contains none of Port Royale 2's files. The flags are the only third-party
material in it; everything else below is used or referred to, keeps its own licence, and comes
from its own source.

| Item | Used for | Licence | In this repository? | Notes |
|---|---|---|---|---|
| Port Royale 2 (Ascaron Entertainment) | the game being modded | commercial | **no** | players and builders need their own copy; no exe, archive, save or extracted file is here |
| Flags from Wikimedia Commons (`art/flags_src/`) | the 100 nation flags | public domain (78), CC0 (22) | yes | authors and source pages per flag in `art/flags_src/CREDITS.md` |
| dgVoodoo2 (Dege) | optional Direct3D 8 wrapper for PCs where DX8 hangs (Intel D3D9on12) | freeware; its ReadmeGeneral section 1 allows shipping unmodified dgVoodoo files with a game mod | **no** | `tools/release.py --dgvoodoo DIR` adds the unmodified files of an official release to the zip; the setup installs them only when ticked |
| MSYS2 / MinGW-w64 GCC | builds `PR2Nation.dll`, `version.dll` and the unit tests | GPL with the GCC Runtime Library Exception | no | the DLLs link libgcc statically, which the runtime exception covers; the DLLs stay under the mod's own licence |
| Python, Tcl/Tk | the setup program | PSF licence, Tcl/Tk licence (BSD-style) | no | the frozen setup exe in the release contains the Python runtime and Tk |
| PyInstaller | freezes the setup into an exe | GPL-2.0 with the bootloader exception | no | the exception allows distributing the frozen exe under any licence |
| pefile, capstone, Pillow | the build and test tools | MIT, BSD-3-Clause, MIT-CMU (HPND) | no | `pip install pefile capstone Pillow` |
| Google Fonts (IM Fell English, Alegreya Sans) | the flag chooser page `art/flag_locker.html` | SIL Open Font License | no | loaded from Google when the page is opened |
| Steamless (atom0s) | removing SteamStub from a builder's own exe for the patch build | CC BY-NC-ND 4.0 | **no, never** | players never need it; see the modding kit's [docs/techniques/03-the-exe.md](https://github.com/dariooo512/pr2-modkit/blob/main/docs/techniques/03-the-exe.md) |

The Sovereign Nations artwork is the mod's own (an AI-generated image, see `art/CREDITS.md`) and is
covered by the repository's MIT licence.
