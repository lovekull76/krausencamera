#!/usr/bin/env python3
"""Calibrate phase-detect autofocus against known distances.

Focus, not the laser, is the candidate primary sensor: it has no baseline, so
it is blind to the camera-versus-laser motion that wrecked three days of work,
and it needs no dark frame, so the live view never has to pause.

**Calibrate the PDAF reading itself**, not the contrast peak. The two differ by
about half a dioptre on this build, and it is the phase reading that would be
used in service -- calibrating it directly absorbs whatever causes the
difference, and no explanation is needed.

The lamp is 850 nm, so this is automatically an IR calibration. A daylight one
would not transfer: the focal plane for 850 nm is not where it is for visible.

Parking alternates low/high/high/low rather than low/high/low/high. A plain
alternation puts every high-park later than every low-park on average, so a rig
that is still settling produces a drift that reads as hysteresis -- measured
once at -0.0225 dpt, of which -0.0115 was simply the trend. The balanced order
cancels a linear drift exactly.

A drift inside one run means the rig has not settled and the point's mean is
wrong by however far it moved, so the trend is reported and flagged.

    python3 af_calibrate.py --distance 150 --append af.csv
    ...repeat at several heights...
    python3 af_calibrate.py --fit af.csv
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np


def fit_hyperbola(d, y, offsets):
    """Least squares for y = a + b/(d + c): scan c, solve a and b exactly."""
    best = None
    for c in offsets:
        if np.any(d + c <= 1.0):
            continue
        A = np.column_stack([np.ones_like(d), 1.0 / (d + c)])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        rms = float(np.sqrt((resid ** 2).mean()))
        if best is None or rms < best[0]:
            best = (rms, float(coef[0]), float(coef[1]), float(c), resid)
    return best


def report(path):
    rows = np.loadtxt(path, delimiter=",", ndmin=2)
    d, dpt, sd = rows[:, 0], rows[:, 1], rows[:, 2]
    order = np.argsort(d)
    d, dpt, sd = d[order], dpt[order], sd[order]
    print(f"{len(d)} punkter\n")
    print(f"{'avstand':>9} {'dpt':>9} {'sd':>8} {'-> mm':>8}")
    for a, b, c in zip(d, dpt, sd):
        sens = 1000.0 / b ** 2 if b else float("nan")
        print(f"{a:9.1f} {b:9.4f} {c:8.4f} {c*sens:8.3f}")
    if len(d) < 4:
        print("\nfyra punkter behovs innan en trepara-modell sager nagot alls.")
        return
    rms, a, b, c, resid = fit_hyperbola(d, dpt, np.arange(-80.0, 80.0, 0.05))
    print(f"\nPDAF:  dpt = {a:.4f} + {b:.1f}/(d {c:+.2f})     rms {rms:.4f} dpt")
    print(f"\n{'avstand':>9} {'matt':>9} {'modell':>9} {'fel':>8} {'fel mm':>8}")
    for di, yi, ri in zip(d, dpt, resid):
        sens = 1000.0 / yi ** 2
        print(f"{di:9.1f} {yi:9.4f} {yi-ri:9.4f} {ri:+8.4f} {ri*sens:+8.2f}")
    # leave-one-out: the discipline that caught the earlier model failing
    print("\nutelamna-en-punkt (varje punkt forutsagd av de ovriga):")
    for i in range(len(d)):
        m = np.ones(len(d), bool); m[i] = False
        r2, a2, b2, c2, _ = fit_hyperbola(d[m], dpt[m], np.arange(-80.0, 80.0, 0.05))
        pred = a2 + b2 / (d[i] + c2)
        sens = 1000.0 / dpt[i] ** 2
        print(f"  d={d[i]:6.1f}   matt {dpt[i]:.4f}   forutsagt {pred:.4f}   "
              f"fel {(dpt[i]-pred)*sens:+6.2f} mm")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--distance", type=float, help="known distance, mm")
    p.add_argument("--append", metavar="FILE")
    p.add_argument("--fit", metavar="FILE")
    p.add_argument("--runs", type=int, default=8,
                   help="AF cycles per point, alternating the parking position")
    p.add_argument("--park-low", type=float, default=2.5)
    p.add_argument("--park-high", type=float, default=12.0)
    p.add_argument("--exposure-us", type=int, default=15000)
    p.add_argument("--led-pin", type=int, default=17)
    args = p.parse_args()

    if args.fit:
        report(args.fit)
        return 0
    if args.distance is None:
        p.error("--distance kravs om inte --fit anges")

    from picamera2 import Picamera2
    from libcamera import controls
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from illumination import Lamp

    lamp = Lamp("IR illumination", args.led_pin)
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": (2304, 1296)}))
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.exposure_us,
                         "AnalogueGain": 1.0, "AwbEnable": False,
                         "ColourGains": (0.94, 1.01)})
    picam2.start()
    time.sleep(1.5)
    lamp.acquire()
    time.sleep(1.2)

    lo, hi, seq = [], [], []
    try:
        print(f"{'fran':>7} {'tillstand':>10} {'s':>5} {'dpt':>9}")
        # low, high, high, low -- balanced against a linear drift
        pattern = [args.park_low, args.park_high, args.park_high, args.park_low]
        for i in range(args.runs):
            park = pattern[i % 4]
            picam2.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                 "LensPosition": park})
            time.sleep(1.8)
            picam2.set_controls({"AfMode": controls.AfModeEnum.Auto})
            time.sleep(0.3)
            t0 = time.time()
            picam2.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
            st = lp = None
            while time.time() - t0 < 9.0:
                md = picam2.capture_metadata()
                st, lp = md.get("AfState"), md.get("LensPosition")
                if st in (2, 3):
                    break
            ok = st == 2 and lp
            print(f"{park:7.1f} {'focused' if ok else 'FAILED':>10} "
                  f"{time.time()-t0:5.1f} " + (f"{lp:9.4f}" if ok else " " * 9),
                  flush=True)
            if ok:
                seq.append((i, park, lp))
                (lo if park == args.park_low else hi).append(lp)
    finally:
        picam2.stop()
        lamp.shutdown()

    v = np.array(lo + hi)
    if len(v) < 3:
        print("\nfor fa lyckade konvergeringar for att saga nagot")
        return 1
    print(f"\n{len(v)}/{args.runs} lyckade   medel {v.mean():.4f}   "
          f"1sigma {v.std(ddof=1):.4f} dpt")
    if lo and hi:
        # Hysteresis would show as a split between the two parking directions,
        # not as extra scatter, so it has to be looked for separately.
        split = np.mean(hi) - np.mean(lo)
        pooled = np.sqrt((np.var(lo, ddof=1) + np.var(hi, ddof=1)) / 2) if \
            len(lo) > 1 and len(hi) > 1 else float("nan")
        print(f"  nerifran {np.mean(lo):.4f}   uppifran {np.mean(hi):.4f}   "
              f"skillnad {split:+.4f} dpt"
              + (f"  ({abs(split)/pooled:.1f}x spridningen)" if pooled == pooled else ""))
    sens = 1000.0 / v.mean() ** 2
    idx = np.array([q[0] for q in seq], float)
    val = np.array([q[2] for q in seq])
    detr = val
    if len(val) > 3:
        k = np.polyfit(idx, val, 1)[0]
        detr = val - np.polyval(np.polyfit(idx, val, 1), idx)
        span = k * (idx[-1] - idx[0])
        print(f"  trend inom korningen {span:+.4f} dpt ({span*sens:+.2f} mm)")
        if abs(span) > 2.5 * detr.std(ddof=1):
            print(f"  ** RIGGEN SATTER SIG FORTFARANDE ** trenden ar "
                  f"{abs(span)/detr.std(ddof=1):.1f}x det avtrendade bruset.")
            print(f"     Punktens medelvarde ar fel med storleksordningen "
                  f"{abs(span)*sens/2:.2f} mm. Vanta och mat om.")
    print(f"  precision vid {args.distance:.0f} mm: {v.std(ddof=1)*sens:.3f} mm"
          + (f"   (avtrendad {detr.std(ddof=1)*sens:.3f} mm)"
             if len(val) > 3 else ""))

    if args.append:
        with open(args.append, "a") as fh:
            fh.write(f"{args.distance:.1f},{v.mean():.5f},{v.std(ddof=1):.5f}\n")
        print(f"  -> {args.append}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
