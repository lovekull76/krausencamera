#!/usr/bin/env python3
"""Write index.html at the root of the NAS share: every batch, newest first,
with a link to its timelapse and its recordings.

    python3 arkivindex.py /mnt/krausen_cam

Served by the NAS's own web server (Synology Web Station), so a phone on the
LAN reaches the timelapses at http://<nas>/... without SMB and without the Pi
carrying any of the traffic. Served over http the timelapse page and its
frames share an origin, so the film export works in any browser, not only
through the folder picker Chrome offers for file:// pages.

`arkivsynk.sh` runs this after each sync. It reads only the NAS copy, so the
list includes batches long since pruned from the Pi -- and any other camera
syncing into the same share gets its own section.
"""

from __future__ import annotations

import csv
import glob
import html
import os
import re
import sys
import time

FRAME_RE = re.compile(r"A-(\d{8})-(\d{6})\.jpg$")


def frame_time(name):
    m = FRAME_RE.search(name)
    return time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")) if m else None


def summarise(folder):
    frames = sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "bilder", "A-*.jpg")))
    times = [t for t in (frame_time(f) for f in frames) if t]
    peak, zeros = None, 0
    path = os.path.join(folder, "matningar.csv")
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(l for l in f if not l.startswith("#")):
                try:
                    k = float(r.get("krausen_mm") or "nan")
                except ValueError:
                    continue
                if k == k and r.get("status") == "ok":
                    peak = k if peak is None else max(peak, k)
    path = os.path.join(folder, "nollningar.csv")
    if os.path.exists(path):
        with open(path) as f:
            zeros = max(0, sum(1 for _ in f) - 1)
    videos = sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "video", "*.mp4")))
    return {"frames": len(frames), "t0": min(times) if times else None,
            "t1": max(times) if times else None, "peak": peak, "zeros": zeros,
            "videos": videos, "page": os.path.exists(os.path.join(folder, "timelapse.html"))}


def span(t0, t1):
    if not t0:
        return ""
    s = t1 - t0
    d, h = int(s // 86400), int(s % 86400 // 3600)
    when = time.strftime("%a %d %b %Y, %H:%M", time.localtime(t0))
    return f"{when} &middot; {d} d {h} h" if d else f"{when} &middot; {h} h {int(s % 3600 // 60)} min"


def row(rel, name, s, sub=False):
    e = html.escape
    title = f'<a href="{e(rel)}/timelapse.html">{e(name)}</a>' if s["page"] else e(name)
    facts = [f'{s["frames"]} frames']
    if s["peak"] is not None:
        facts.append(f'peak krausen <b>{s["peak"]:.0f} mm</b>')
    if s["zeros"]:
        facts.append(f'{s["zeros"]} zero{"s" if s["zeros"] > 1 else ""}')
    vids = "".join(f'<a class="vid" href="{e(rel)}/video/{e(v)}">&#9654; {e(v[len("live_recording_"):-4] if v.startswith("live_recording_") else v)}</a>'
                   for v in s["videos"])
    return (f'<li class="{"sub" if sub else "batch"}"><div class="name">{title}</div>'
            f'<div class="when">{span(s["t0"], s["t1"])}</div>'
            f'<div class="facts">{" &middot; ".join(facts)}</div>'
            + (f'<div class="vids">{vids}</div>' if vids else "") + "</li>")


def build(root):
    sections = []
    for dev in sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)) and not d.startswith((".", "#", "@"))):
        base = os.path.join(root, dev)
        batches = sorted((b for b in os.listdir(base)
                          if re.match(r"\d{4}-\d{2}-\d{2}_\d{4}", b)
                          and os.path.isdir(os.path.join(base, b))), reverse=True)
        loose = sorted((d for d in glob.glob(os.path.join(base, "utan-batch", "*"))
                        if os.path.isdir(os.path.join(d, "bilder"))), reverse=True)
        if not batches and not loose:
            continue
        items = [row(f"{dev}/{b}", f"{b[:10]} {b[11:13]}:{b[13:15]}{b[15:]}",
                     summarise(os.path.join(base, b)))
                 for b in batches]
        items += [row(f"{dev}/utan-batch/{os.path.basename(d)}", "no batch · " + os.path.basename(d),
                      summarise(d), sub=True) for d in loose]
        sections.append(f'<section><h2>{html.escape(dev)}</h2><ul>{"".join(items)}</ul></section>')
    body = "".join(sections) or '<p class="empty">No batches yet.</p>'
    return PAGE.replace("{body}", body).replace("{made}", time.strftime("%Y-%m-%d %H:%M"))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Krausen archive</title>
<style>
  :root { --bg:#0e1113; --panel:#161b1e; --ink:#e4e8ea; --dim:#8a969d; --line:#2a3237; --accent:#e0a33a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 20px 16px 40px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .made { color: var(--dim); font-size: 12px; margin-bottom: 20px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--dim);
       margin: 24px 0 8px; font-weight: 600; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  li { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; }
  li.sub { background: transparent; }
  .name { font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; }
  li.sub .name { font-size: 14px; font-weight: 500; color: var(--dim); }
  .name a { color: var(--ink); text-decoration: none; }
  .name a:hover, .name a:focus-visible { color: var(--accent); }
  .when, .facts { color: var(--dim); font-size: 13px; font-variant-numeric: tabular-nums; }
  .facts b { color: var(--accent); font-weight: 600; }
  .vids { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .vid { font-size: 12px; color: var(--ink); background: var(--bg); border: 1px solid var(--line);
         border-radius: 999px; padding: 3px 10px; text-decoration: none; font-variant-numeric: tabular-nums; }
  .empty { color: var(--dim); }
</style>
</head>
<body>
<main>
  <h1>Krausen archive</h1>
  <div class="made">Updated {made} &middot; newest first &middot; tap a batch for its timelapse</div>
  {body}
</main>
</body>
</html>
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = sys.argv[1]
    out = os.path.join(root, "index.html")
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        f.write(build(root))
    os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
