"""The mod's main image in the sizes the docs, GitHub and the setup need.

    python art/make_banner.py [--check]

Source: art/sovereign_nations_thumbnail.png (1448x1086, the master; artwork provided by ferra
for the mod, see art/CREDITS.md). It is never changed: every copy below is only resized,
cropped or compressed.

  docs/banner.jpg          the whole image, 1200x900, JPEG (README and player guide banner)
  docs/social_preview.png  1280x640 for GitHub's Settings -> Social preview: the top 2:1 band of
                           the image (title, subtitle and the nation's flagship), scaled evenly;
                           a 256-colour dithered PNG so it stays under GitHub's 1 MB limit
  installer/header.png     the same 2:1 band at 600x300, the header of the setup window

--check only verifies that the copies exist with the right sizes and limits.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
MASTER = HERE / "sovereign_nations_thumbnail.png"
BANNER = MOD / "docs" / "banner.jpg"
SOCIAL = MOD / "docs" / "social_preview.png"
HEADER = MOD / "installer" / "header.png"

BANNER_SIZE = (1200, 900)
SOCIAL_SIZE = (1280, 640)
HEADER_SIZE = (600, 300)
BANNER_MAX = 500 * 1024
SOCIAL_MAX = 1024 * 1024


def band(im: Image.Image) -> Image.Image:
    """The top 2:1 band, full width: the title starts at the very top, the flagship below it."""
    w, h = im.size
    return im.crop((0, 0, w, w // 2))


def make():
    im = Image.open(MASTER).convert("RGB")
    BANNER.parent.mkdir(parents=True, exist_ok=True)
    im.resize(BANNER_SIZE, Image.LANCZOS).save(BANNER, "JPEG", quality=88, optimize=True, progressive=True)
    social = band(im).resize(SOCIAL_SIZE, Image.LANCZOS)
    palette = social.quantize(colors=256, method=Image.Quantize.MEDIANCUT, kmeans=3)
    social.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).save(SOCIAL, "PNG", optimize=True)
    HEADER.parent.mkdir(parents=True, exist_ok=True)
    band(im).resize(HEADER_SIZE, Image.LANCZOS).save(HEADER, "PNG", optimize=True)


def check() -> int:
    bad = 0
    m = Image.open(MASTER)
    if m.size != (1448, 1086):
        print(f"FAIL {MASTER.name}: {m.size}, expected the 1448x1086 master")
        bad += 1
    for p, size, limit in ((BANNER, BANNER_SIZE, BANNER_MAX), (SOCIAL, SOCIAL_SIZE, SOCIAL_MAX),
                           (HEADER, HEADER_SIZE, None)):
        if not p.exists():
            print(f"FAIL {p.relative_to(MOD)}: missing")
            bad += 1
            continue
        got, n = Image.open(p).size, p.stat().st_size
        ok = got == size and (limit is None or n < limit)
        print(f"{'ok  ' if ok else 'FAIL'} {p.relative_to(MOD)}: {got[0]}x{got[1]}, {n // 1024} KB")
        bad += not ok
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        make()
    return 1 if check() else 0


if __name__ == "__main__":
    sys.exit(main())
