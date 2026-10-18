"""Restyle real-world flags into Port Royale 2's own flag art.

    python art/restyle.py            # all flags in flags_src/ -> flags_game/

Every game flag asset is the Dutch tricolour (red/white/blue, no emblem) drawn
with the game's lighting: bevels, cloth folds, waving silhouettes, frames and
drop shadows. For each asset we measure, pixel by pixel, how much lighter or
darker the game drew it than the flat stripe colour (the "shade"), then draw a
new flag through the same shade and silhouette. The result keeps the game's
look and exact resolution; only the design changes.

Outputs per flag NNN (flags_game/NNN/):
  town_strip.png   128x512  waving flagpole animation (layout of Flagge_Holland.aim)
  icon.png          25x15   framed nation icon (Pr2_Flagge_<nation>)
  marker.png        16x16   sea-map convoy/ship flag (SM_Konvoi_Nation_*, Seekarte_Schiff_Flagge_*)
  shipinfo.png      16x13   ship info flag (Pr2_Seekarte_SchiffInfo_*)
  big.png           66x42   big waving flag (Pr2_Flagge_User_Big)
  preview.png               all of the above on a game-coloured card (for the chooser)
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REF = HERE / "game_flags"
SRC = HERE / "flags_src"
OUT = HERE / "flags_game"


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] + 1.0


def median(cols):
    if not cols:
        return (128, 128, 128)
    return tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))


def sample(flag, u, v):
    """Bilinear sample of an RGBA flag at u,v in [0,1]."""
    w, h = flag.size
    x, y = min(max(u, 0), 1) * (w - 1), min(max(v, 0), 1) * (h - 1)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    fx, fy = x - x0, y - y0
    p = flag.load()
    out = []
    for i in range(4):
        a = p[x0, y0][i] * (1 - fx) + p[x1, y0][i] * fx
        b = p[x0, y1][i] * (1 - fx) + p[x1, y1][i] * fx
        out.append(a * (1 - fy) + b * fy)
    return out


def prefilter(flag, w, h):
    """Shrink the source flag to ~3x the target size first (box filter) so the
    bilinear samples see an anti-aliased design, like the game's art."""
    return flag.resize((max(2, w * 3), max(2, h * 3)), Image.LANCZOS)


def shade_of(ref_px, band_med):
    s = lum(ref_px) / lum(band_med)
    return min(max(s, 0.30), 1.70)


def paint(px_ref, flag_rgba, shade):
    r, g, b, a = flag_rgba
    return (int(min(255, r * shade)), int(min(255, g * shade)), int(min(255, b * shade)))


# ------------------------------------------------------------- rect assets --
def restyle_rect(ref_file, rect, flag):
    """rect = interior (x0, y0, x1, y1) exclusive; outside it the ref is copied."""
    ref = Image.open(REF / ref_file).convert("RGBA")
    out = ref.copy()
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    small = prefilter(flag, w, h)
    rp = ref.load()
    bands = [[], [], []]
    for y in range(y0, y1):
        for x in range(x0, x1):
            bands[min(2, (y - y0) * 3 // h)].append(rp[x, y])
    meds = [median(b) for b in bands]
    op = out.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            band = min(2, (y - y0) * 3 // h)
            s = shade_of(rp[x, y], meds[band])
            f = sample(small, (x - x0 + 0.5) / w, (y - y0 + 0.5) / h)
            rgb = paint(rp[x, y], f, s)
            a = int(rp[x, y][3] * f[3] / 255)
            if a < 255 and rp[x, y][3] > 0:          # transparent design parts show the frame colour
                bg = meds[1]
                k = f[3] / 255
                rgb = tuple(int(rgb[i] * k + bg[i] * 0.55 * (1 - k)) for i in range(3))
                a = rp[x, y][3]
            op[x, y] = rgb + (a,)
    return out


# ---------------------------------------------------------- waving assets --
def frames_of(img):
    """Connected opaque blobs (frames of a waving-flag strip) as bounding boxes."""
    a = img.split()[3].load()
    w, h = img.size
    seen = [[False] * w for _ in range(h)]
    boxes = []
    for y in range(h):
        for x in range(w):
            if a[x, y] and not seen[y][x]:
                stack, bx = [(x, y)], [x, y, x, y]
                seen[y][x] = True
                while stack:
                    cx, cy = stack.pop()
                    bx = [min(bx[0], cx), min(bx[1], cy), max(bx[2], cx), max(bx[3], cy)]
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < w and 0 <= ny < h and a[nx, ny] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                if (bx[2] - bx[0]) >= 3 and (bx[3] - bx[1]) >= 3:
                    boxes.append(tuple(bx))
    return boxes


def restyle_waving(ref_file, flag, tricolour=True):
    """Per frame, per column: v runs from the cloth's top to its bottom edge, u
    across the frame; shade = ref luminance / its stripe's median (tricolour
    refs) or / the frame's median luminance (grey cloth templates)."""
    ref = Image.open(REF / ref_file).convert("RGBA")
    out = Image.new("RGBA", ref.size, (0, 0, 0, 0))
    rp, op = ref.load(), out.load()
    for (x0, y0, x1, y1) in frames_of(ref):
        cols = {}
        for x in range(x0, x1 + 1):
            ys = [y for y in range(y0, y1 + 1) if rp[x, y][3] > 0]
            if ys:
                cols[x] = (min(ys), max(ys))
        if not cols:
            continue
        fw, fh = x1 - x0 + 1, y1 - y0 + 1
        small = prefilter(flag, fw, fh)
        bands = [[], [], []]
        for x, (t, b) in cols.items():
            for y in range(t, b + 1):
                v = (y - t + 0.5) / (b - t + 1)
                bands[min(2, int(v * 3))].append(rp[x, y])
        meds = [median(bd) for bd in bands]
        allmed = median(sum(bands, []))
        for x, (t, b) in cols.items():
            u = (x - x0 + 0.5) / fw
            for y in range(t, b + 1):
                if rp[x, y][3] == 0:
                    continue
                v = (y - t + 0.5) / (b - t + 1)
                med = meds[min(2, int(v * 3))] if tricolour else allmed
                s = shade_of(rp[x, y], med)
                f = sample(small, u, v)
                rgb = paint(rp[x, y], f, s)
                op[x, y] = rgb + (int(rp[x, y][3] * f[3] / 255),)
    return out


# --------------------------------------------------------------- per flag --
ASSETS = {
    # name: (builder, args)
    "icon.png": ("rect", "Pr2_Flagge_Holland__TexPage12.png", (1, 2, 24, 13)),
    "marker.png": ("rect", "SM_Konvoi_Nation_Holland__TexPage8.png", (0, 0, 15, 14)),
    "shipinfo.png": ("rect", "Pr2_Seekarte_SchiffInfo_Holland__TexPage12.png", (1, 1, 15, 12)),
    "town_strip.png": ("wave", "Flagge_Holland.png", True),
    "big.png": ("wave", "Pr2_Flagge_User_Big__TexPage9.png", False),
}


def load_flag(path):
    im = Image.open(path).convert("RGBA")
    bb = im.getbbox()
    return im.crop(bb) if bb else im


def card(flag_name, imgs, index):
    """Preview card: the big waving flag, the town flagpole frame, icon, marker."""
    W, H = 300, 150
    c = Image.new("RGBA", (W, H), (60, 47, 33, 255))
    d = ImageDraw.Draw(c)
    d.rectangle((2, 2, W - 3, H - 3), outline=(181, 153, 105, 255), width=2)
    big = imgs["big.png"]
    bb = big.getbbox() or (0, 0, 1, 1)
    big = big.crop(bb).resize(((bb[2] - bb[0]) * 2, (bb[3] - bb[1]) * 2), Image.NEAREST)
    c.alpha_composite(big, (12, 14))
    strip = imgs["town_strip.png"]
    fr = frames_of(strip)[0]
    f = strip.crop((fr[0], fr[1], fr[2] + 1, fr[3] + 1))
    f = f.resize((f.size[0] * 3, f.size[1] * 3), Image.NEAREST)
    c.alpha_composite(f, (170, 18))
    ic = imgs["icon.png"].resize((50, 30), Image.NEAREST)
    c.alpha_composite(ic, (170, 82))
    mk = imgs["marker.png"].resize((32, 32), Image.NEAREST)
    c.alpha_composite(mk, (236, 80))
    try:
        font = ImageFont.truetype("georgia.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    d.text((12, H - 26), f"{index:02d}  {flag_name}", fill=(238, 222, 189, 255), font=font)
    return c


def build(only=None):
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    for m in manifest:
        if only is not None and m["index"] not in only:
            continue
        flag = load_flag(SRC / m["file"])
        d = OUT / f"{m['index']:03d}"
        d.mkdir(exist_ok=True)
        imgs = {}
        for name, (kind, ref, arg) in ASSETS.items():
            img = restyle_rect(ref, arg, flag) if kind == "rect" else restyle_waving(ref, flag, arg)
            img.save(d / name)
            imgs[name] = img
        card(m["name"], imgs, m["index"]).save(d / "preview.png")
        print(f"{m['index']:03d} {m['name']}")
    sheet(manifest)


def sheet(manifest):
    cards = [Image.open(OUT / f"{m['index']:03d}" / "preview.png") for m in manifest
             if (OUT / f"{m['index']:03d}" / "preview.png").exists()]
    if not cards:
        return
    cols = 5
    rows = (len(cards) + cols - 1) // cols
    W, H = cards[0].size
    s = Image.new("RGBA", (cols * W, rows * H), (40, 30, 20, 255))
    for i, c in enumerate(cards):
        s.paste(c, ((i % cols) * W, (i // cols) * H))
    s.save(HERE / "flags_sheet.png")


if __name__ == "__main__":
    only = {int(x) for x in sys.argv[1].split(",")} if len(sys.argv) > 1 else None
    build(only)
