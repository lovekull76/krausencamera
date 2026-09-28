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
            frames.append([f"bilder/{os.path.basename(p)}", int(t)])
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
    data = {"name": os.path.basename(os.path.normpath(folder)),
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
  canvas { width: 100%; height: 170px; display:block; background: var(--panel);
           border-radius: 4px; cursor: crosshair; }
  .help { color: var(--dim); font-size: 12px; }
  .empty { padding: 40px; text-align:center; color: var(--dim); }
</style>
</head>
<body>
<main>
  <header>
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
  </div>
  <canvas id="chart" aria-label="Krausen height over the batch"></canvas>
  <div class="help">Space plays and pauses &middot; &larr; &rarr; step one frame &middot; click or drag in the curve to jump &middot; dashed lines are zeros</div>
</main>
<script>
const D = /*DATA*/null;
const $ = id => document.getElementById(id);
const F = D.frames, M = D.meas;
$("name").textContent = "Batch " + D.name;
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

// -- frames, with a small preload window so playback does not stall --------
const cache = new Map();
function load(i) {
  if (i < 0 || i >= F.length || cache.has(i)) return;
  const im = new Image(); im.src = F[i][0]; cache.set(i, im);
  if (cache.size > 80) for (const k of cache.keys()) { if (Math.abs(k - i) > 40) cache.delete(k); if (cache.size <= 60) break; }
}
let idx = 0;
function show(i) {
  if (!F.length) return;
  idx = Math.max(0, Math.min(F.length - 1, i));
  $("img").src = F[idx][0];
  for (let k = 1; k <= 24; k++) load(idx + k);
  $("slider").value = idx;
  $("pos").textContent = (idx + 1) + " / " + F.length;
  const t = F[idx][1], m = nearestMeas(t);
  $("ct").textContent = fmtTime(t) + " \u00b7 " + fmtElapsed(t - t0);
  if (!m) { $("ck").textContent = "—"; $("cs").textContent = "no measurement near this frame"; }
  else {
    const v = val(m);
    $("ck").textContent = v === null ? "—" : (hasK ? "krausen " : "surface ") + v.toFixed(1) + " mm";
    $("cs").textContent = words[m[3]] ?? m[3];
  }
  draw();
}

// -- playback ---------------------------------------------------------------
let timer = null;
function play(on) {
  clearInterval(timer); timer = null;
  $("play").innerHTML = on ? "&#10074;&#10074; Pause" : "&#9654; Play";
  if (!on) return;
  if (idx >= F.length - 1) show(0);
  timer = setInterval(() => {
    const next = cache.get(idx + 1);
    if (idx >= F.length - 1) { play(false); return; }
    if (next && !next.complete) return;       // wait for the frame rather than skip it
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
});

// -- the curve --------------------------------------------------------------
const cv = $("chart"), cx = cv.getContext("2d");
const pts = M.filter(m => val(m) !== null);
function draw() {
  const r = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * r; cv.height = H * r; cx.setTransform(r, 0, 0, r, 0, 0);
  const cs = getComputedStyle(document.documentElement);
  const c = n => cs.getPropertyValue(n).trim();
  cx.clearRect(0, 0, W, H);
  const L = 44, R = 10, T = 10, B = 22, w = W - L - R, h = H - T - B;
  if (!pts.length) { cx.fillStyle = c("--dim"); cx.fillText("No heights recorded in this batch yet.", L, T + 20); return; }
  let lo = Math.min(...pts.map(val)), hi = Math.max(...pts.map(val));
  if (hi - lo < 5) { const m = (hi + lo) / 2; lo = m - 2.5; hi = m + 2.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const ta = Math.min(t0, pts[0][0]), tb = Math.max(t1, pts[pts.length - 1][0]);
  const X = t => L + (t - ta) / Math.max(1, tb - ta) * w;
  const Y = v => hasK ? T + (hi - v) / (hi - lo) * h : T + (v - lo) / (hi - lo) * h;
  cx.font = "11px -apple-system, sans-serif"; cx.lineWidth = 1;
  // grid and y labels
  cx.strokeStyle = c("--line"); cx.fillStyle = c("--dim"); cx.textAlign = "right"; cx.textBaseline = "middle";
  const step = [1,2,5,10,20,50,100].find(s => (hi - lo) / s <= 6) || 200;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    cx.beginPath(); cx.moveTo(L, Y(v)); cx.lineTo(W - R, Y(v)); cx.stroke();
    cx.fillText(v + (hasK ? "" : ""), L - 6, Y(v));
  }
  cx.textAlign = "left"; cx.fillText(hasK ? "krausen, mm" : "surface, mm", L + 4, T + 6);
  // time ticks: days over a long batch, hours over a short one
  cx.textAlign = "center"; cx.textBaseline = "top";
  const span = tb - ta;
  const tick = span > 2 * 86400 ? 86400 : span > 12 * 3600 ? 6 * 3600 : span > 3 * 3600 ? 3600 : 1800;
  for (let k = 0; ta + k * tick <= tb; k++) {
    const s = k * tick, x = X(ta + s);
    cx.beginPath(); cx.moveTo(x, T); cx.lineTo(x, T + h); cx.stroke();
    const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), mm = Math.floor(s % 3600 / 60);
    cx.fillText(tick >= 86400 ? "+" + d + " d" : "+" + (d * 24 + hh) + (mm ? ":" + String(mm).padStart(2, "0") : "") + " h", x, T + h + 4);
  }
  // zeros
  cx.strokeStyle = c("--zero"); cx.setLineDash([4, 4]);
  for (const z of D.zeros) { const x = X(z[0]); cx.beginPath(); cx.moveTo(x, T); cx.lineTo(x, T + h); cx.stroke(); }
  cx.setLineDash([]);
  // the curve, broken where there is a gap of more than half an hour
  cx.strokeStyle = c("--accent"); cx.lineWidth = 1.6; cx.beginPath();
  pts.forEach((p, i) => {
    const gap = i && p[0] - pts[i - 1][0] > 1800;
    (i === 0 || gap) ? cx.moveTo(X(p[0]), Y(val(p))) : cx.lineTo(X(p[0]), Y(val(p)));
  });
  cx.stroke();
  // the cursor
  if (F.length) {
    const x = X(F[idx][1]);
    cx.strokeStyle = c("--ink"); cx.lineWidth = 1; cx.beginPath(); cx.moveTo(x, T); cx.lineTo(x, T + h); cx.stroke();
  }
  cv._X = { L, w, ta, tb };
}
function seek(e) {
  const g = cv._X; if (!g || !F.length) return;
  const x = e.clientX - cv.getBoundingClientRect().left;
  const t = g.ta + (x - g.L) / g.w * (g.tb - g.ta);
  let best = 0; F.forEach((f, i) => { if (Math.abs(f[1] - t) < Math.abs(F[best][1] - t)) best = i; });
  play(false); show(best);
}
let dragging = false;
cv.onmousedown = e => { dragging = true; seek(e); };
addEventListener("mousemove", e => { if (dragging) seek(e); });
addEventListener("mouseup", () => dragging = false);
addEventListener("resize", draw);
show(0);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
