#!/usr/bin/env python3
"""Write timelapse.html into a batch folder: a flip-book of frame A with the
krausen curve under it, playable straight off the NAS in a browser.

    python3 timelapse.py /mnt/krausen_cam/krausencamera/2026-10-02_1430

No film is built and no server is needed. The list of frames and the
measurements are baked into the page itself, so it works from a file:// URL --
a browser will not let such a page read a directory or fetch a CSV -- and it
keeps working as long as the folder exists. The images load by relative path,
so the folder can be moved or copied whole.

`arkivsynk.sh` runs this against the NAS copy after every sync, for folders
with frames newer than their page, so the page always lists everything on the
NAS -- including frames already pruned from the Pi.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
import time

FRAME_RE = re.compile(r"A-(\d{8})-(\d{6})\.jpg$")


def epoch(ts: str) -> float | None:
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def num(v):
    try:
        f = float(v)
        return None if f != f else round(f, 2)
    except (TypeError, ValueError):
        return None


def build(folder: str) -> str:
    frames = []
    for p in sorted(glob.glob(os.path.join(folder, "bilder", "A-*.jpg"))):
        m = FRAME_RE.search(p)
        if m:
            t = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
            # Play the half-size copy when there is one (forhandsbilder.py);
            # the film export reads the original, the third field.
            name = os.path.basename(p)
            small = os.path.exists(os.path.join(folder, "sma", name))
            frames.append([f"sma/{name}" if small else f"bilder/{name}", int(t), f"bilder/{name}"])
    meas = []
    path = os.path.join(folder, "matningar.csv")
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(l for l in f if not l.startswith("#")):
                t = epoch(r.get("tid", ""))
                if t is not None:
                    meas.append([int(t), num(r.get("krausen_mm")), num(r.get("d_mm")),
                                 r.get("status", "")])
    zeros = []
    path = os.path.join(folder, "nollningar.csv")
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(f):
                t = epoch(r.get("tid", ""))
                if t is not None:
                    zeros.append([int(t), num(r.get("d_mm"))])
    # The archive's start page sits at the share's root, two levels up for a
    # batch and three for a no-batch day. Found rather than assumed, so a
    # folder copied elsewhere simply gets no link.
    index, up = None, os.path.normpath(folder)
    for depth in range(1, 5):
        up = os.path.dirname(up)
        if os.path.exists(os.path.join(up, "index.html")):
            index = "../" * depth + "index.html"
            break
    data = {"name": os.path.basename(os.path.normpath(folder)), "index": index,
            "live": "http://krausenlive/",
            "frames": frames, "meas": meas, "zeros": zeros,
            "made": time.strftime("%Y-%m-%d %H:%M")}
    return PAGE.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    html = build(folder)
    out = os.path.join(folder, "timelapse.html")
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        f.write(html)
    os.replace(tmp, out)
    return 0


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Krausen timelapse</title>
<style>
  :root { --bg:#0e1113; --panel:#161b1e; --ink:#e4e8ea; --dim:#8a969d;
          --line:#2a3237; --accent:#e0a33a; --zero:#5fb3c9; --bad:#7a5a3a; }
  * { box-sizing: border-box; }
  html, body { margin:0; background:var(--bg); color:var(--ink);
               font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  main { max-width: 1200px; margin: 0 auto; padding: 12px 16px 24px;
         display: flex; flex-direction: column; gap: 10px; }
  header { display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }
  h1 { font-size: 16px; font-weight: 600; margin: 0; letter-spacing:.01em; }
  .sub { color: var(--dim); font-size: 12px; }
  .stage { position: relative; background: #000; border-radius: 4px; overflow: hidden;
           aspect-ratio: 16 / 9; }
  .stage img { width: 100%; height: 100%; object-fit: contain; display:block; }
  .cap { position:absolute; left:10px; top:10px; display:flex; flex-direction:column; gap:2px;
         background: rgba(0,0,0,.55); padding: 6px 10px; border-radius: 4px;
         font-variant-numeric: tabular-nums; }
  .cap .k { font-size: 26px; font-weight: 600; color: var(--accent); line-height: 1.1; }
  .cap .t { font-size: 13px; }
  .cap .s { font-size: 12px; color: var(--dim); }
  .bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  button, select { font: inherit; color: var(--ink); background: var(--panel);
                   border: 1px solid var(--line); border-radius: 4px; padding: 5px 10px; cursor: pointer; }
  button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  input[type=range] { flex: 1; min-width: 160px; accent-color: var(--accent); }
  .pos { color: var(--dim); font-variant-numeric: tabular-nums; min-width: 9ch; text-align:right; }
  #dl { color: var(--accent); }
  .nav { display: flex; gap: 8px; width: 100%; }
  .nav a { font-size: 13px; color: var(--accent); text-decoration: none; border: 1px solid var(--line);
           border-radius: 999px; padding: 4px 12px; }
  .nav a#live { margin-left: auto; }
  button:disabled { opacity: .5; cursor: default; }
  canvas { width: 100%; height: 170px; display:block; background: var(--panel);
           border-radius: 4px; cursor: crosshair; touch-action: none; }
  .help { color: var(--dim); font-size: 12px; }
  .empty { padding: 40px; text-align:center; color: var(--dim); }
</style>
</head>
<body>
<main>
  <header>
    <nav class="nav"><a id="back" hidden>&larr; All batches</a><a id="live">&#9679; Live view</a></nav>
    <h1 id="name"></h1>
    <span class="sub" id="meta"></span>
  </header>
  <div class="stage" id="stage">
    <img id="img" alt="Frame A from the krausen camera">
    <div class="cap"><span class="k" id="ck"></span><span class="t" id="ct"></span><span class="s" id="cs"></span></div>
  </div>
  <div class="bar">
    <button id="play" aria-label="Play">&#9654; Play</button>
    <select id="speed" aria-label="Playback speed">
      <option value="6">6 fps</option><option value="12">12 fps</option>
      <option value="24" selected>24 fps</option><option value="48">48 fps</option>
    </select>
    <input type="range" id="slider" min="0" value="0" aria-label="Frame">
    <span class="pos" id="pos"></span>
    <button id="export">Export film</button>
  </div>
  <div class="bar">
    <button id="setin" title="Start the range at this frame (I)">[ Start here</button>
    <button id="setout" title="End the range at this frame (O)">End here ]</button>
    <button id="full" hidden>Whole batch</button>
    <span class="pos" id="range" style="text-align:left">whole batch</span>
  </div>
  <div class="bar" id="exportbar" hidden>
    <span id="exportmsg"></span>
    <button id="cancel">Cancel</button>
    <a id="dl" hidden></a>
  </div>
  <canvas id="chart" aria-label="Krausen height over the batch"></canvas>
  <div class="help">Export film records every frame at the chosen speed, with the time, the height and the curve burned in, at the frames' own resolution. It plays through in real time, so keep this tab visible while it runs. &middot; Start here / End here (or I / O) limit playback and the film to the krausen, without the weeks of tail &middot; Space plays and pauses &middot; &larr; &rarr; step one frame &middot; click or drag in the curve to jump &middot; dashed lines are zeros</div>
</main>
<script>
const D = /*DATA*/null;
const $ = id => document.getElementById(id);
const F = D.frames, M = D.meas;
$("name").textContent = "Batch " + D.name;
if (D.index) { $("back").href = D.index; $("back").hidden = false; }
$("live").href = D.live;
$("meta").textContent = F.length + " frames · page made " + D.made;
if (!F.length) {
  $("stage").innerHTML = '<div class="empty">No frames in this folder yet.</div>';
}
const t0 = F.length ? F[0][1] : 0, t1 = F.length ? F[F.length - 1][1] : 1;
const hasK = M.some(m => m[1] !== null);
const val = m => hasK ? m[1] : m[2];

function fmtTime(t) {
  const d = new Date(t * 1000);
  return d.toLocaleDateString(undefined, {weekday:"short", month:"short", day:"numeric"})
    + " " + d.toLocaleTimeString(undefined, {hour:"2-digit", minute:"2-digit"});
}
function fmtElapsed(s) {            // time since the batch's first frame
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (d ? d + " d " : "") + h + " h " + String(m).padStart(2, "0") + " min in";
}
function nearestMeas(t) {           // the measurement closest in time, within 10 min
  let lo = 0, hi = M.length - 1, best = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (M[mid][0] <= t) { best = mid; lo = mid + 1; } else hi = mid - 1; }
  const c = [best, best + 1].filter(i => i >= 0 && i < M.length)
    .sort((a, b) => Math.abs(M[a][0] - t) - Math.abs(M[b][0] - t))[0];
  return c !== undefined && Math.abs(M[c][0] - t) <= 600 ? M[c] : null;
}
const words = {ok:"", uppvarmning:"warming up", i_halsen:"IN THE NECK",
  utanfor_kalibrering:"beyond calibration", misslyckad:"no focus", morkt:"lamp off"};

// -- frames, read ahead so playback does not stall --------------------------
// The page plays the half-size copies (sma/, ~130 kB); over a slow link 1 MB
// originals stalled it outright. A request that has not finished after a few
// seconds is retried, since one stuck image used to stop playback for good.
const AHEAD = 48;
const cache = new Map();
function load(i, retry) {
  if (i < 0 || i >= F.length || (cache.has(i) && !retry)) return;
  const im = new Image(); im._t = performance.now();
  im.src = F[i][0] + (retry ? (F[i][0].includes("?") ? "&" : "?") + "r=" + Date.now() : "");
  cache.set(i, im);
  if (cache.size > 2 * AHEAD + 40) for (const k of cache.keys()) { if (k < i - 20 || k > i + AHEAD + 20) cache.delete(k); if (cache.size <= 2 * AHEAD) break; }
}
function caption(i) {
  const t = F[i][1], m = nearestMeas(t);
  const out = { t: fmtTime(t) + " \u00b7 " + fmtElapsed(t - t0) };
  if (!m) return { ...out, k: "\u2014", s: "no measurement near this frame" };
  const v = val(m);
  return { ...out, k: v === null ? "\u2014" : (hasK ? "krausen " : "surface ") + v.toFixed(1) + " mm",
           s: words[m[3]] ?? m[3] };
}
let idx = 0;
function show(i) {
  if (!F.length) return;
  idx = Math.max(0, Math.min(F.length - 1, i));
  $("img").src = F[idx][0];
  for (let k = 1; k <= AHEAD; k++) load(idx + k);
  $("slider").value = idx;
  $("pos").textContent = (idx + 1) + " / " + F.length;
  const c = caption(idx);
  $("ck").textContent = c.k; $("ct").textContent = c.t; $("cs").textContent = c.s;
  draw();
}

// -- playback ---------------------------------------------------------------
// -- range: the part of the batch to play and to export ------------------------
// A fermentation is a day or two of krausen and then weeks of tail. The range
// keeps a film to the part worth sending. Remembered per batch in this browser.
let inI = 0, outI = Math.max(0, F.length - 1);
const rkey = "krausen-range:" + D.name;
try {
  const r = JSON.parse(localStorage.getItem(rkey) || "null");
  if (r && r.a < r.b && r.b < F.length) { inI = r.a; outI = r.b; }
} catch (e) {}
const ranged = () => inI > 0 || outI < F.length - 1;
function setRange(a, b) {
  inI = Math.max(0, Math.min(a, F.length - 1)); outI = Math.max(inI, Math.min(b, F.length - 1));
  try { ranged() ? localStorage.setItem(rkey, JSON.stringify({ a: inI, b: outI })) : localStorage.removeItem(rkey); } catch (e) {}
  const n = outI - inI + 1;
  $("range").textContent = ranged()
    ? `${fmtElapsed(F[inI][1] - t0).replace(" in", "")} \u2192 ${fmtElapsed(F[outI][1] - t0)} \u00b7 ${n} frames`
    : "whole batch";
  $("full").hidden = !ranged();
  draw();
}
$("setin").onclick = () => setRange(idx, idx >= outI ? F.length - 1 : outI);
$("setout").onclick = () => setRange(idx <= inI ? 0 : inI, idx);
$("full").onclick = () => setRange(0, F.length - 1);

let timer = null;
function play(on) {
  clearInterval(timer); timer = null;
  $("play").innerHTML = on ? "&#10074;&#10074; Pause" : "&#9654; Play";
  if (!on) return;
  if (idx < inI || idx >= outI) show(inI);
  timer = setInterval(() => {
    const next = cache.get(idx + 1);
    if (idx >= outI) { play(false); return; }
    if (next && !next.complete) {             // wait for the frame rather than skip it
      $("pos").textContent = (idx + 1) + " / " + F.length + " \u00b7 loading";
      if (performance.now() - next._t > 4000) load(idx + 1, true);
      return;
    }
    show(idx + 1);
  }, 1000 / +$("speed").value);
}
$("play").onclick = () => play(!timer);
$("speed").onchange = () => { if (timer) play(true); };
$("slider").max = Math.max(0, F.length - 1);
$("slider").oninput = e => show(+e.target.value);
addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT") return;
  if (e.code === "Space") { e.preventDefault(); play(!timer); }
  else if (e.key === "ArrowRight") { play(false); show(idx + 1); }
  else if (e.key === "ArrowLeft") { play(false); show(idx - 1); }
  else if (e.key === "i") $("setin").click();
  else if (e.key === "o") $("setout").click();
});

// -- the curve --------------------------------------------------------------
// One drawing routine for the page and for the exported film, so what is burned
// into the film is exactly what the page shows. `s` scales text and lines.
const cv = $("chart"), cx = cv.getContext("2d");
const pts = M.filter(m => val(m) !== null);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function chart(g, W, H, s, cursorT, fill, opts = {}) {
  if (fill) { g.fillStyle = css("--panel"); g.fillRect(0, 0, W, H); } else g.clearRect(0, 0, W, H);
  const L = 44 * s, R = 10 * s, T = 10 * s, B = 22 * s, w = W - L - R, h = H - T - B;
  g.font = `${11 * s}px -apple-system, "Segoe UI", sans-serif`; g.lineWidth = s;
  if (!pts.length) { g.fillStyle = css("--dim"); g.fillText("No heights recorded in this batch yet.", L, T + 20 * s); return null; }
  // opts.zoom = {a, b}: draw only that span, scaled to it -- the film of a
  // chosen range. opts.shade = {a, b}: whole batch, dimmed outside the span.
  const z = opts.zoom;
  const inZ = z ? pts.filter(p => p[0] >= z.a - 300 && p[0] <= z.b + 300) : pts;
  const vs = (inZ.length ? inZ : pts).map(val);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi - lo < 5) { const m = (hi + lo) / 2; lo = m - 2.5; hi = m + 2.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const ta = z ? z.a : Math.min(t0, pts[0][0]), tb = z ? z.b : Math.max(t1, pts[pts.length - 1][0]);
  const X = t => L + (t - ta) / Math.max(1, tb - ta) * w;
  const Y = v => hasK ? T + (hi - v) / (hi - lo) * h : T + (v - lo) / (hi - lo) * h;
  g.strokeStyle = css("--line"); g.fillStyle = css("--dim"); g.textAlign = "right"; g.textBaseline = "middle";
  const step = [1,2,5,10,20,50,100].find(k => (hi - lo) / k <= 6) || 200;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - R, Y(v)); g.stroke();
    g.fillText(String(v), L - 6 * s, Y(v));
  }
  g.textAlign = "left"; g.fillText(hasK ? "krausen, mm" : "surface, mm", L + 4 * s, T + 6 * s);
  // time ticks: days over a long batch, hours over a short one
  g.textAlign = "center"; g.textBaseline = "top";
  const span = tb - ta;
  const tick = span > 2 * 86400 ? 86400 : span > 12 * 3600 ? 6 * 3600 : span > 3 * 3600 ? 3600 : 1800;
  for (let tt = t0 + Math.ceil((ta - t0) / tick) * tick; tt <= tb; tt += tick) {
    const e = tt - t0, x = X(tt);
    g.beginPath(); g.moveTo(x, T); g.lineTo(x, T + h); g.stroke();
    const d = Math.floor(e / 86400), hh = Math.floor(e % 86400 / 3600), mm = Math.floor(e % 3600 / 60);
    g.fillText(tick >= 86400 ? "+" + d + " d" : "+" + (d * 24 + hh) + (mm ? ":" + String(mm).padStart(2, "0") : "") + " h", x, T + h + 4 * s);
  }
  // zeros
  g.strokeStyle = css("--zero"); g.setLineDash([4 * s, 4 * s]);
  for (const z of D.zeros) { const x = X(z[0]); g.beginPath(); g.moveTo(x, T); g.lineTo(x, T + h); g.stroke(); }
  g.setLineDash([]);
  // the curve, broken where there is a gap of more than half an hour
  g.save(); g.beginPath(); g.rect(L, T - 2 * s, w, h + 4 * s); g.clip();
  g.strokeStyle = css("--accent"); g.lineWidth = 1.6 * s; g.beginPath();
  pts.forEach((p, i) => {
    const gap = i && p[0] - pts[i - 1][0] > 1800;
    (i === 0 || gap) ? g.moveTo(X(p[0]), Y(val(p))) : g.lineTo(X(p[0]), Y(val(p)));
  });
  g.stroke();
  if (opts.shade) {
    g.fillStyle = "rgba(14,17,19,.62)";
    const xa = X(opts.shade.a), xb = X(opts.shade.b);
    g.fillRect(L, T - 2 * s, Math.max(0, xa - L), h + 4 * s);
    g.fillRect(xb, T - 2 * s, Math.max(0, L + w - xb), h + 4 * s);
  }
  g.restore();
  // the cursor, with a dot where it meets the curve
  if (cursorT !== null) {
    const x = X(cursorT);
    g.strokeStyle = css("--ink"); g.lineWidth = s; g.beginPath(); g.moveTo(x, T); g.lineTo(x, T + h); g.stroke();
    const m = nearestMeas(cursorT);
    if (m && val(m) !== null) {
      g.fillStyle = css("--accent"); g.beginPath(); g.arc(x, Y(val(m)), 3.5 * s, 0, 2 * Math.PI); g.fill();
    }
  }
  return { L, w, ta, tb };
}
function draw() {
  const r = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * r; cv.height = H * r; cx.setTransform(r, 0, 0, r, 0, 0);
  cv._X = chart(cx, W, H, 1, F.length ? F[idx][1] : null, false,
                 ranged() ? { shade: { a: F[inI][1], b: F[outI][1] } } : {});
}
function seek(e) {
  const g = cv._X; if (!g || !F.length) return;
  const x = e.clientX - cv.getBoundingClientRect().left;
  const t = g.ta + (x - g.L) / g.w * (g.tb - g.ta);
  let best = 0; F.forEach((f, i) => { if (Math.abs(f[1] - t) < Math.abs(F[best][1] - t)) best = i; });
  play(false); show(best);
}
// Pointer events, so a finger on a phone scrubs the curve as a mouse does.
let dragging = false;
cv.onpointerdown = e => { dragging = true; cv.setPointerCapture(e.pointerId); seek(e); };
cv.onpointermove = e => { if (dragging) seek(e); };
cv.onpointerup = cv.onpointercancel = () => dragging = false;
addEventListener("resize", draw);

// -- export -----------------------------------------------------------------
// Draw each frame, its caption and the curve onto one canvas and record that.
// MediaRecorder runs in real time, so frames are paced at the chosen rate; the
// recorder is paused while a frame is still loading from the NAS, so a slow
// read stretches the recording, not the film.
function burnCaption(g, i, s) {
  const c = caption(i), big = `600 ${26 * s}px -apple-system, "Segoe UI", sans-serif`,
        mid = `${13 * s}px -apple-system, "Segoe UI", sans-serif`, small = `${12 * s}px -apple-system, "Segoe UI", sans-serif`;
  g.font = big; let bw = g.measureText(c.k).width;
  g.font = mid; bw = Math.max(bw, g.measureText(c.t).width);
  g.font = small; bw = Math.max(bw, g.measureText(c.s).width);
  g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(10 * s, 10 * s, bw + 20 * s, 72 * s);
  g.textAlign = "left"; g.textBaseline = "top";
  g.fillStyle = css("--accent"); g.font = big; g.fillText(c.k, 20 * s, 15 * s);
  g.fillStyle = css("--ink"); g.font = mid; g.fillText(c.t, 20 * s, 46 * s);
  g.fillStyle = css("--dim"); g.font = small; g.fillText(c.s, 20 * s, 63 * s);
}
// Opened as a file -- straight off the NAS -- every image counts as foreign to
// the page, and drawing one onto a canvas taints it: the recorder then gets
// nothing and the film comes out empty. So in that case the export asks for the
// batch folder once and reads the frames itself, which the browser allows
// (Chrome and Edge). Served over http the images are same-origin and load as
// usual.
let bilderDir = null;
async function frameSource() {
  // The film uses the originals (third field), not the half-size copies played.
  if (location.protocol !== "file:") return i => new Promise((ok, bad) => {
    const im = new Image(); im.onload = () => ok(im); im.onerror = bad; im.src = F[i][2] || F[i][0];
  });
  if (!window.showDirectoryPicker) return null;
  if (!bilderDir) {
    $("exportmsg").textContent = "Choose this batch's folder (" + D.name + ") so the export can read the frames.";
    let dir;
    try { dir = await showDirectoryPicker({ id: "krausen-batch", mode: "read" }); }
    catch (e) { return null; }
    let b;
    try { b = await dir.getDirectoryHandle("bilder"); }
    catch (e) { alert("That folder has no bilder/ in it. Choose the batch folder itself (" + D.name + ")."); return null; }
    // The dialog opens where it was last used -- often the previous batch --
    // so check the folder really holds this page's frames, first and last,
    // before recording a film of the wrong fermentation.
    try {
      for (const f of [F[0], F[F.length - 1]]) await b.getFileHandle((f[2] || f[0]).split("/").pop());
    } catch (e) {
      alert("That folder is not batch " + D.name + " -- its frames are not there. Choose " + D.name + ".");
      return null;
    }
    bilderDir = b;
  }
  return async i => {
    const name = (F[i][2] || F[i][0]).split("/").pop();
    return createImageBitmap(await (await bilderDir.getFileHandle(name)).getFile());
  };
}
let cancelled = false;
$("cancel").onclick = () => { cancelled = true; };
$("export").onclick = async () => {
  if (!F.length) return;
  play(false);
  const fps = +$("speed").value;
  const mime = ["video/mp4;codecs=avc1.640033", "video/mp4", "video/webm;codecs=vp9", "video/webm"]
    .find(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m));
  if (!mime) { alert("This browser cannot record video. Try Chrome or Edge."); return; }
  $("exportbar").hidden = false; $("dl").hidden = true;
  const get = await frameSource();
  if (!get) {
    $("exportmsg").textContent = location.protocol === "file:" && !window.showDirectoryPicker
      ? "Opened as a file, this browser cannot hand the frames to the recorder. Open the page in Chrome or Edge."
      : "Export cancelled.";
    return;
  }
  // Read ahead a few frames so decoding keeps up with the chosen rate.
  const ahead = new Map();
  const fetchFrame = i => { if (i < F.length && !ahead.has(i)) ahead.set(i, get(i)); return ahead.get(i); };
  const i0 = inI, i1 = outI, zoom = ranged() ? { zoom: { a: F[i0][1], b: F[i1][1] } } : {};
  const first = await fetchFrame(i0);
  const IW = first.naturalWidth || first.width, IH = first.naturalHeight || first.height;
  const s = IW / 1200, CH = Math.round(IH * 0.26 / 2) * 2;
  const film = document.createElement("canvas");
  film.width = IW; film.height = IH + CH;
  const g = film.getContext("2d");
  const track = film.captureStream(0).getVideoTracks()[0];
  const rec = new MediaRecorder(new MediaStream([track]), { mimeType: mime, videoBitsPerSecond: 16e6 });
  const chunks = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  const stopped = new Promise(r => rec.onstop = r);
  // Refuse rather than record black: a tainted canvas yields an empty film.
  g.drawImage(first, 0, 0, IW, IH);
  try { g.getImageData(0, 0, 1, 1); }
  catch (e) { $("exportmsg").textContent = "The browser will not let the page record these images. Open it in Chrome or Edge."; return; }
  cancelled = false;
  $("export").disabled = true; $("cancel").hidden = false;
  rec.start(1000);
  let due = performance.now();
  for (let i = i0; i <= i1 && !cancelled; i++) {
    for (let k = 1; k <= 8; k++) fetchFrame(i + k);
    let im = null;
    const p = fetchFrame(i);
    im = await Promise.race([p, new Promise(r => setTimeout(() => r(null), 5))]);
    if (!im) { rec.pause(); im = await p; rec.resume(); due = performance.now(); }
    ahead.delete(i);
    g.drawImage(im, 0, 0, IW, IH);
    if (im.close) im.close();
    burnCaption(g, i, s);
    g.save(); g.translate(0, IH); chart(g, IW, CH, s, F[i][1], true, zoom); g.restore();
    track.requestFrame();
    if (i % 2 === 0) show(i);      // let the page play along, so it is visibly working
    $("exportmsg").textContent = `Recording frame ${i - i0 + 1} of ${i1 - i0 + 1} at ${fps} fps — keep this tab visible`;
    due += 1000 / fps;
    await new Promise(r => setTimeout(r, Math.max(0, due - performance.now())));
  }
  rec.stop(); await stopped;
  $("export").disabled = false; $("cancel").hidden = true;
  if (cancelled) { $("exportmsg").textContent = "Export cancelled."; return; }
  const ext = mime.startsWith("video/mp4") ? "mp4" : "webm";
  const a = $("dl");
  a.href = URL.createObjectURL(new Blob(chunks, { type: mime.split(";")[0] }));
  const part = ranged() ? `-${Math.round((F[i0][1] - t0) / 3600)}h-${Math.round((F[i1][1] - t0) / 3600)}h` : "";
  a.download = `krausen-${D.name}${part}-${fps}fps.${ext}`;
  a.textContent = `Save ${a.download} (${(chunks.reduce((n, b) => n + b.size, 0) / 1e6).toFixed(0)} MB)`;
  a.hidden = false;
  $("exportmsg").textContent = `${IW}×${IH + CH}, ${i1 - i0 + 1} frames, ${((i1 - i0 + 1) / fps).toFixed(1)} s.`;
  a.click();
};
setRange(inI, outI);
show(inI);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
