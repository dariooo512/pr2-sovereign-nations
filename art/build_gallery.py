"""Build the flag chooser page (art/flag_locker.html) from flags_game/ + manifest.

    python art/build_gallery.py
"""
import base64
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "flags_game"
man = json.loads((HERE / "flags_src" / "manifest.json").read_text(encoding="utf-8"))


def b64(p):
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


flags = []
for m in man:
    d = OUT / f"{m['index']:03d}"
    flags.append({
        "i": m["index"], "name": m["name"], "group": m["group"],
        "tile": b64(d / "tile.png"), "big": b64(d / "big5x.png"),
        "page": m["page_url"], "license": m["license"],
        "author": " ".join(str(m.get("author", "")).split())[:90],
    })

groups = []
for f in flags:
    if f["group"] not in groups:
        groups.append(f["group"])

PAGE = r"""<title>Flag Locker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IM+Fell+English+SC&family=IM+Fell+English:ital@0;1&family=Alegreya+Sans:wght@400;500;700&display=swap">
<style>
/* Layout: a ship's flag locker. Sticky "chart table" on the left shows the chosen
   colours at full size; the right is the locker: a grid of folded flags by group.
   Single dark world on purpose (the game's own wood-and-brass panels). */
:root {
  color-scheme: dark;
  --wood: #241b13;         /* page: tarred deck planking */
  --panel: #382b1e;        /* game panel brown */
  --panel-hi: #45362600;
  --brass: #b8995f;        /* trim, rules, focus */
  --parchment: #ecdcb9;    /* primary text */
  --faded: #a8956f;        /* secondary text */
  --sea: #5fa3b6;          /* the chosen flag */
  --display: "IM Fell English SC", "IM Fell English", Georgia, "Times New Roman", serif;
  --italic: "IM Fell English", Georgia, serif;
  --body: "Alegreya Sans", "Segoe UI", system-ui, sans-serif;
  --step-0: 1rem; --step-1: 1.25rem; --step-2: 1.6rem; --step-3: 2.4rem;
}
* { box-sizing: border-box; }
html, body { background: var(--wood); }
body {
  margin: 0; color: var(--parchment); font-family: var(--body); font-size: var(--step-0); line-height: 1.5;
  padding-inline: clamp(16px, 3vw, 40px); padding-block: 28px 56px;
  background-image:
    repeating-linear-gradient(90deg, rgba(0,0,0,.18) 0 1px, transparent 1px 148px),
    linear-gradient(180deg, #2a2016, var(--wood) 40%);
}
header { display: grid; gap: 6px; max-width: 1400px; margin-inline: auto; margin-bottom: 22px; }
.eyebrow { font-family: var(--body); text-transform: uppercase; letter-spacing: .16em; font-size: .78rem; color: var(--brass); }
h1 { font-family: var(--display); font-weight: 400; font-size: var(--step-3); margin: 0; letter-spacing: .02em; text-wrap: balance; }
header p { margin: 0; max-width: 66ch; color: var(--faded); }
.layout { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 28px; max-width: 1400px; margin-inline: auto; align-items: start; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }

/* chart table */
.chosen {
  position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px);
  background: var(--panel); border: 2px solid var(--brass); padding: 18px 18px 20px;
  box-shadow: inset 0 0 0 4px var(--wood), inset 0 0 0 5px rgba(184,153,95,.45), 0 10px 30px rgba(0,0,0,.45);
  display: grid; gap: 12px;
}
@media (max-width: 860px) { .chosen { position: static; } }
.chosen .no { font-family: var(--display); color: var(--brass); font-size: var(--step-1); letter-spacing: .06em; }
.chosen h2 { font-family: var(--italic); font-style: italic; font-weight: 400; font-size: var(--step-2); margin: 0; line-height: 1.15; text-wrap: balance; }
.mast { display: grid; place-items: center; min-height: 230px; background:
  radial-gradient(ellipse at 50% 60%, rgba(95,163,182,.16), transparent 70%),
  linear-gradient(180deg, #1d2a2f, #18120c); border: 1px solid rgba(184,153,95,.35); }
.mast img { image-rendering: pixelated; max-width: 100%; height: auto; filter: drop-shadow(3px 5px 0 rgba(0,0,0,.35)); }
.meta { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: .92rem; }
.meta dt { color: var(--faded); }
.meta dd { margin: 0; overflow-wrap: anywhere; }
.meta a { color: var(--sea); }
.howto { border-top: 1px solid rgba(184,153,95,.4); padding-top: 12px; font-size: .95rem; color: var(--parchment); }
.howto b { color: var(--brass); font-weight: 700; }
kbd { font-family: var(--body); font-weight: 700; border: 1px solid var(--brass); padding: 0 5px; border-radius: 3px; font-size: .85em; }

/* locker */
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }
.chip {
  font: 500 .9rem var(--body); color: var(--parchment); background: transparent;
  border: 1px solid rgba(184,153,95,.55); padding: 5px 12px; border-radius: 2px; cursor: pointer;
}
.chip[aria-pressed="true"] { background: var(--brass); color: var(--wood); border-color: var(--brass); }
.chip span { font-variant-numeric: tabular-nums; opacity: .75; margin-left: 4px; }
#q {
  margin-left: auto; min-width: 0; width: 220px; max-width: 100%; font: var(--step-0) var(--body);
  background: #17110b; color: var(--parchment); border: 1px solid rgba(184,153,95,.55); padding: 6px 10px;
}
#q::placeholder { color: var(--faded); }
:focus-visible { outline: 2px solid var(--sea); outline-offset: 2px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(256px, 1fr)); gap: 12px; }
.card {
  display: grid; gap: 6px; text-align: left; cursor: pointer; padding: 10px 12px 12px;
  background: var(--panel); color: inherit; border: 1px solid rgba(184,153,95,.35); font: inherit;
  transition: transform .12s ease, border-color .12s ease;
}
.card:hover { transform: translateY(-2px); border-color: var(--brass); }
.card[aria-pressed="true"] { border: 2px solid var(--sea); padding: 9px 11px 11px; background: #2f3a37; }
.card img { image-rendering: pixelated; width: 236px; max-width: 100%; height: auto; }
.card .line { display: flex; gap: 8px; align-items: baseline; }
.card .n { font-family: var(--display); color: var(--brass); font-variant-numeric: tabular-nums; min-width: 2.2em; }
.card .nm { font-weight: 500; }
.card .g { font-size: .78rem; text-transform: uppercase; letter-spacing: .1em; color: var(--faded); }
.empty { color: var(--faded); font-style: italic; }
footer { max-width: 1400px; margin: 28px auto 0; color: var(--faded); font-size: .85rem; }
@media (prefers-reduced-motion: reduce) { .card { transition: none; } .card:hover { transform: none; } }
</style>

<header>
  <div class="eyebrow">Port Royale 2 · Sovereign Nations</div>
  <h1>Flag Locker</h1>
  <p>__COUNT__ flags for your new nation, redrawn in the game's own style: the waving flag on your towns, the flagpole frames, the nation icon and the sea-map marker, at the game's exact sizes. Pick one and remember its number.</p>
</header>

<div class="layout">
  <aside class="chosen" aria-live="polite">
    <div class="no" id="cNo"></div>
    <h2 id="cName"></h2>
    <div class="mast"><img id="cBig" alt=""></div>
    <dl class="meta">
      <dt>Group</dt><dd id="cGroup"></dd>
      <dt>Source</dt><dd><a id="cSrc" target="_blank" rel="noopener">Wikimedia Commons</a></dd>
      <dt>Licence</dt><dd id="cLic"></dd>
      <dt>Author</dt><dd id="cAuth"></dd>
    </dl>
    <div class="howto">To fly it: when you found your nation (<kbd>Ctrl</kbd>+<kbd>N</kbd> → <i>Found a nation</i>), step to flag <b id="cNo2"></b> on the <i>Flag</i> page and take it.</div>
  </aside>

  <main>
    <div class="controls" role="group" aria-label="Filter flags">
      <button class="chip" id="g-all" aria-pressed="true" data-g="">All<span>__COUNT__</span></button>
      __CHIPS__
      <input id="q" type="search" placeholder="Search a name" aria-label="Search flags by name">
    </div>
    <div class="grid" id="grid"></div>
    <p class="empty" id="none" hidden>No flag matches that name.</p>
  </main>
</div>
<footer>All designs are public domain or CC0, from Wikimedia Commons; see the source link of each flag. Restyled for the game by the Sovereign Nations mod.</footer>

<script>
const FLAGS = __DATA__;
const grid = document.getElementById("grid");
let group = "", query = "", chosen = 0;
try { const s = parseInt(localStorage.getItem("flag-locker-choice"), 10); if (!isNaN(s) && FLAGS[s]) chosen = s; } catch (e) {}
const pad = n => String(n).padStart(2, "0");

function show(i) {
  const f = FLAGS[i]; chosen = i;
  document.getElementById("cNo").textContent = "No. " + pad(f.i);
  document.getElementById("cNo2").textContent = "No. " + pad(f.i);
  document.getElementById("cName").textContent = f.name;
  const big = document.getElementById("cBig"); big.src = f.big; big.alt = f.name + " flag";
  document.getElementById("cGroup").textContent = f.group;
  document.getElementById("cSrc").href = f.page;
  document.getElementById("cLic").textContent = f.license;
  document.getElementById("cAuth").textContent = f.author || "unknown";
  for (const c of grid.children) c.setAttribute("aria-pressed", String(+c.dataset.i === i));
  try { localStorage.setItem("flag-locker-choice", String(i)); } catch (e) {}
}

function render() {
  grid.textContent = "";
  const q = query.trim().toLowerCase();
  let n = 0;
  for (const f of FLAGS) {
    if (group && f.group !== group) continue;
    if (q && !f.name.toLowerCase().includes(q)) continue;
    const b = document.createElement("button");
    b.className = "card"; b.dataset.i = f.i; b.setAttribute("aria-pressed", String(f.i === chosen));
    b.innerHTML = `<img alt="" width="236" height="92"><div class="line"><span class="n"></span><span class="nm"></span></div><div class="g"></div>`;
    b.querySelector("img").src = f.tile;
    b.querySelector(".n").textContent = pad(f.i);
    b.querySelector(".nm").textContent = f.name;
    b.querySelector(".g").textContent = f.group;
    b.addEventListener("click", () => show(f.i));
    grid.appendChild(b); n++;
  }
  document.getElementById("none").hidden = n > 0;
}

document.querySelectorAll(".chip").forEach(ch => ch.addEventListener("click", () => {
  group = ch.dataset.g;
  document.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", String(c === ch)));
  render();
}));
document.getElementById("q").addEventListener("input", e => { query = e.target.value; render(); });
render();
show(chosen);
</script>
"""

chips = "\n      ".join(
    f'<button class="chip" data-g="{html.escape(g)}" aria-pressed="false">{html.escape(g)}'
    f'<span>{sum(1 for f in flags if f["group"] == g)}</span></button>' for g in groups)
page = (PAGE.replace("__COUNT__", str(len(flags))).replace("__CHIPS__", chips)
        .replace("__DATA__", json.dumps(flags).replace("</", "<\\/")))
(HERE / "flag_locker.html").write_text(page, encoding="utf-8")
print("wrote", HERE / "flag_locker.html", len(page) // 1024, "KB")
