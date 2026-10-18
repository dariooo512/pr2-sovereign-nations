"""Find the popup's buttons in a screenshot.

Buttons are dark bars (~150 px wide, ~20 px tall) with light text, side by
side on the light popup. Per candidate row we look at a 13-row band: a column
belongs to a button when most of the band is dark (the light text only covers
a few rows). The lowest row with 1-3 equally wide bars wins (the dark title
banner above the body is much wider and single)."""
from PIL import Image


def _bars(px, y, x0, x1):
    cols = []
    for x in range(x0, x1):
        dark = sum(1 for dy in range(-6, 7) if px[x, y + dy] < 80)
        cols.append(dark >= 8)
    runs, start = [], None
    for i, c in enumerate(cols + [False]):
        if c and start is None:
            start = i
        elif not c and start is not None:
            if i - start >= 6:
                runs.append([start + x0, i + x0])
            start = None
    merged = []                                   # bridge gaps left by wide letters
    for r in runs:
        if merged and r[0] - merged[-1][1] <= 12:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if 90 <= b - a <= 260]


def _on_popup(px, y, bars):
    """The bars sit on the light parchment: light just left/right and above."""
    def light(x, yy):
        return 120 <= px[x, yy] <= 250
    a, b = bars[0][0], bars[-1][1]
    side = [light(a - d, y) for d in range(8, 30, 4)] + [light(b + d, y) for d in range(8, 30, 4)]
    above = [light(x, y - 20) for x in range(a, b, 10)]
    return sum(side) >= len(side) * 0.7 and sum(above) >= len(above) * 0.7


# Button centres (x) by count; the popup has a fixed width at the test window size.
LAYOUT = {1: [604], 2: [483, 727], 3: [442, 604, 767]}


def find_buttons_n(path, n):
    """Buttons of a popup known to have n buttons: y from the image (any bar
    on the parchment), x from the fixed layout. Long labels can split a bar,
    so the bar count itself is not trusted."""
    img = Image.open(path).convert("L")
    w, h = img.size
    px = img.load()
    for y in range(int(h * 0.72), int(h * 0.12), -2):
        bars = _bars(px, y, int(w * 0.22), int(w * 0.78))
        if bars and _on_popup(px, y, bars):
            return [(x, y + 6) for x in LAYOUT[n]]
    return []


def find_buttons(path):
    img = Image.open(path).convert("L")
    w, h = img.size
    px = img.load()
    x0, x1 = int(w * 0.22), int(w * 0.78)
    for y in range(int(h * 0.72), int(h * 0.12), -2):
        bars = _bars(px, y, x0, x1)
        if 1 <= len(bars) <= 3:
            widths = [b - a for a, b in bars]
            if max(widths) - min(widths) <= 12 and _on_popup(px, y, bars):
                return [((a + b) // 2, y + 6) for a, b in bars]   # y is near the top edge
    return []


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(p, find_buttons(p))
