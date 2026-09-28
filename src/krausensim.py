#!/usr/bin/env python3
"""Play a fermentation on the stage: krausen that starts slowly, accelerates,
peaks and falls back -- a dry run of the whole chain, from batch to timelapse.

    python3 krausensim.py --new-batch --zero 123.40 --peak-mm 80 --peak-h 4 --hours 12

With `--new-batch` it opens a batch through the service's own API, waits for
the service to report a valid point with the target at the fill level, sets the
zero there, and then walks the target up and down the curve

    h(t) = H * (t/tp)^k * exp(k * (1 - t/tp))

which is zero at the start, peaks at H when t = tp, and decays after -- k sets
how slow the start is and how sharp the peak (3 looks like a real krausen, and
by 3*tp it is back below 7 % of the peak).

**The stage moves only straight after a measurement**, never during one: the
service measures every 300 s on its own clock, so this watches its daily CSV
for each new row and moves then. The curve is therefore sampled once per
point, which is also how often the timelapse gets a frame. Every move is
logged beside the height it was meant to show, so the service's readings can
be checked against it afterwards.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage import Stage                                     # noqa: E402

SERVICE = "http://localhost:8080"


def rows(path):
    try:
        with open(path) as f:
            return [l.rstrip("\n").split(",") for l in f
                    if l[:1].isdigit()]
    except FileNotFoundError:
        return []


def today_csv():
    return os.path.expanduser(f"~/krausencamera/matningar/matning-{time.strftime('%Y%m%d')}.csv")


def wait_new_row():
    """Block until the service writes its next point; return that row."""
    path = today_csv()
    n = len(rows(path))
    while True:
        time.sleep(5)
        if today_csv() != path:              # midnight: a new file starts
            path, n = today_csv(), 0
        r = rows(path)
        if len(r) > n:
            return r[-1]


def post(path):
    req = urllib.request.Request(SERVICE + path, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zero", type=float, default=123.40,
                    help="the fill level, mm below the lid")
    ap.add_argument("--peak-mm", type=float, default=80.0, help="krausen at the peak")
    ap.add_argument("--peak-h", type=float, default=4.0, help="hours to the peak")
    ap.add_argument("--k", type=float, default=3.0, help="shape: higher is slower start, sharper peak")
    ap.add_argument("--hours", type=float, default=12.0, help="length of the run")
    ap.add_argument("--d0", type=float, default=27.4, help="lid to target at stage Z0")
    ap.add_argument("--nearest", type=float, default=32.4,
                    help="never bring the target nearer than this, mm")
    ap.add_argument("--new-batch", action="store_true",
                    help="open a batch and set the zero through the service first")
    ap.add_argument("--log", default="krausensim.csv")
    args = ap.parse_args()

    if args.zero - args.peak_mm < args.nearest:
        print(f"toppen hamnar pa {args.zero - args.peak_mm:.1f} mm, narmare an {args.nearest} -- avbryter")
        return 1

    st = Stage("/dev/ttyUSB0", zmin=0, zmax=200, hold=True)
    log = open(args.log, "a", buffering=1)
    log.write(f"# krausensim {time.strftime('%Y-%m-%dT%H:%M:%S')}  noll {args.zero}  "
              f"topp {args.peak_mm} mm vid {args.peak_h} h  k {args.k}\n")
    log.write("# tid,t_h,krausen_mm,d_mm,Z\n")

    def go(d):
        z = d - args.d0
        if not st.move_to(z, 150.0, 5.0):
            raise SystemExit(f"bordet kom aldrig fram till {d:.2f} mm")
        return z

    wait_new_row()                           # never move mid-measurement
    go(args.zero)
    print(f"bordet pa fyllnadsnivan {args.zero} mm", flush=True)

    if args.new_batch:
        post("/api/batch")
        print("ny batch oppnad -- vantar pa en giltig matning for nollan", flush=True)
        while True:
            r = wait_new_row()
            if r[1] == "ok":
                break
            print(f"  {r[0]} {r[1]}", flush=True)
        post("/api/zero")
        print("nolla satt", flush=True)

    t0 = time.time()
    while True:
        wait_new_row()
        # Aim at the middle of the coming interval: the next point is taken
        # about 300 s from now.
        th = (time.time() - t0 + 150.0) / 3600.0
        if th > args.hours:
            break
        x = th / args.peak_h
        h = args.peak_mm * x ** args.k * math.exp(args.k * (1.0 - x))
        d = args.zero - h
        z = go(d)
        log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')},{th:.3f},{h:.2f},{d:.2f},{z:.2f}\n")
        print(f"{time.strftime('%H:%M')}  +{th:4.1f} h  krausen {h:5.1f} mm  -> bordet {d:6.2f} mm",
              flush=True)

    wait_new_row()
    go(args.zero)
    print("klart, bordet tillbaka pa fyllnadsnivan", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
