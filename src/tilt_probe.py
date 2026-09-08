#!/usr/bin/env python3
"""Is the focal plane tilted? Sweep once, find the peak in every sector.

A lens that sits square to the sensor brings the whole field into focus at one
LensPosition. A tilted one does not: the plane of best focus is tilted with it,
so opposite sides of the frame peak at different settings, and the difference
in dioptres measures the tilt.

All sectors are measured from the *same* frames, so nothing that varies with
time -- illumination, the drift itself -- can masquerade as a tilt.

Sectors live in an annulus: inside it the speckle target has its blank landing
disc and no contrast, outside it the tube's mouth cuts the field off.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

SIZE = (2304, 1296)


def sharpness_masked(y: np.ndarray, masks) -> list[float]:
    f = y.astype(np.float32)
    lap = (4.0 * f[1:-1, 1:-1] - f[:-2, 1:-1] - f[2:, 1:-1]
           - f[1:-1, :-2] - f[1:-1, 2:])
    return [float(lap[m].var()) for m in masks]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lo", type=float, default=4.0)
    p.add_argument("--hi", type=float, default=7.6)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--sectors", type=int, default=8)
    p.add_argument("--r-inner", type=float, default=520.0)
    p.add_argument("--r-outer", type=float, default=780.0)
    p.add_argument("--exposure-us", type=int, default=90000)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--settle", type=float, default=0.70)
    p.add_argument("--discard", type=int, default=6)
    p.add_argument("--led-pin", type=int, default=17)
    args = p.parse_args()

    from picamera2 import Picamera2
    from illumination import Lamp

    w, h = SIZE
    yy, xx = np.mgrid[0:h-2, 0:w-2]          # matches the Laplacian's shape
    r = np.hypot(xx - w/2 + 1, yy - h/2 + 1)
    th = np.degrees(np.arctan2(yy - h/2 + 1, xx - w/2 + 1)) % 360
    ring = (r > args.r_inner) & (r < args.r_outer)
    step = 360.0 / args.sectors
    masks, names = [], []
    for i in range(args.sectors):
        c = i * step
        d = np.abs((th - c + 180) % 360 - 180)
        masks.append(ring & (d < step/2))
        names.append(f"{c:.0f}")
    print("sektorer (grader, 0 = hoger, medurs i bild): " + " ".join(names))
    print("pixlar per sektor: " + " ".join(f"{int(m.sum()/1000)}k" for m in masks) + "\n")

    lamp = Lamp("IR illumination", args.led_pin)
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    d = max(33333, args.exposure_us + 1000)
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.exposure_us,
                         "AnalogueGain": args.gain, "AwbEnable": False,
                         "ColourGains": (1.0, 1.0), "AfMode": 0,
                         "FrameDurationLimits": (d, d)})
    picam2.start()
    time.sleep(1.5)
    lamp.acquire()
    time.sleep(1.0)

    positions = np.linspace(args.lo, args.hi, args.steps)
    rows = []
    try:
        prev = None
        print(f"{'dpt':>6} " + " ".join(f"{n:>8}" for n in names))
        for lp in positions:
            travel = abs(lp - prev) if prev is not None else 15.0
            picam2.set_controls({"LensPosition": float(lp)})
            time.sleep(args.settle + 0.06 * travel)
            for _ in range(args.discard):
                picam2.capture_array("main")
            y = picam2.capture_array("main")[:h]
            v = sharpness_masked(y, masks)
            rows.append(v)
            prev = lp
            print(f"{lp:6.2f} " + " ".join(f"{x:8.1f}" for x in v), flush=True)
    finally:
        picam2.stop()
        lamp.shutdown()

    rows = np.array(rows)
    print(f"\n{'sektor':>8} {'topp (dpt)':>11} {'kontrast':>10}")
    peaks = []
    for i, n in enumerate(names):
        c = rows[:, i]
        j = int(np.argmax(c))
        # parabolic interpolation on the three points around the maximum
        if 0 < j < len(c) - 1:
            a, b, d_ = c[j-1], c[j], c[j+1]
            den = a - 2*b + d_
            off = 0.5 * (a - d_) / den if den else 0.0
        else:
            off = 0.0
        pk = positions[j] + off * (positions[1] - positions[0])
        peaks.append(pk)
        print(f"{n:>8} {pk:11.3f} {c.max()/max(c.min(), 1e-9):10.1f}x")

    peaks = np.array(peaks)
    spread = peaks.max() - peaks.min()
    print(f"\nspridning mellan sektorer: {spread:.3f} dpt")
    # A tilt is a *gradient* across the field, so opposite sectors differ most
    # and the pattern goes as cos(angle). Fit that rather than eyeballing.
    ang = np.radians([float(n) for n in names])
    A = np.column_stack([np.ones_like(ang), np.cos(ang), np.sin(ang)])
    sol, *_ = np.linalg.lstsq(A, peaks, rcond=None)
    amp = np.hypot(sol[1], sol[2])
    direction = np.degrees(np.arctan2(sol[2], sol[1])) % 360
    resid = peaks - A @ sol
    print(f"lutningsanpassning: amplitud {amp:.3f} dpt mot {direction:.0f} grader, "
          f"residual {resid.std():.3f}")
    print(f"\n  under ~0.10 dpt: platt sa langt detta kan avgora")
    print(f"  0.10-0.30 dpt  : marginell lutning")
    print(f"  over 0.30 dpt  : tydlig lutning, kameran star inte vinkelratt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
