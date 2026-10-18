"""Nation flags as the game's company-logo BMPs (96x64, 24-bit, no alpha).

    python art/make_logos.py      # -> data/nation_flags/flag_NNN.bmp

The game draws the player's logo (Run\\0.bmp) for nation-5 towns, convoys, the
sea map and the sails/mast flags of the player's ships, and waves and shades it
itself. So, like the 36 built-in logos (DefaultLogos/Logo_xx.bmp), these are
flat, full-bleed designs: the source flag scaled to 96x64 with a light sharpen.
Transparent parts (swallow tails, pennants) become sail-cloth white.
"""
import json
from pathlib import Path

from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
SRC = HERE / "flags_src"
DST = HERE.parent / "data" / "nation_flags"
CLOTH = (236, 230, 214)


def logo(path):
    im = Image.open(path).convert("RGBA")
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    im = im.resize((96 * 4, 64 * 4), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, CLOTH + (255,))
    bg.alpha_composite(im)
    small = bg.convert("RGB").resize((96, 64), Image.LANCZOS)
    return small.filter(ImageFilter.UnsharpMask(radius=0.8, percent=60, threshold=2))


def main():
    man = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    DST.mkdir(parents=True, exist_ok=True)
    for m in man:
        logo(SRC / m["file"]).save(DST / f"flag_{m['index']:03d}.bmp")   # PIL: BI_RGB, 24-bit, bottom-up
    print(f"{len(man)} logos -> {DST}")


if __name__ == "__main__":
    main()
