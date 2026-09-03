#!/usr/bin/env python3
"""Sweep LensPosition and report the sharpest setting.

Step 3 of the brief: find the focus by sweeping against a test target at the
working distance rather than trusting the nominal 1/distance calculation, since
lens calibration varies between units.

Two things make the measurement trustworthy:

* **Exposure, gain and white balance are locked.** With auto-exposure running,
  brightness drifts between steps and a sharpness metric partly measures that
  drift instead of focus.
* **Two independent metrics.** Laplacian variance and mean gradient magnitude
  peak at the same place when the result is real. If they disagree, the target
  probably lacks contrast or the region of interest is wrong.

The sweep is also a **distance measurement**: LensPosition is in dioptres, so
the peak position gives the object distance as 1000/position mm. Useful for
checking a mechanical setup without measuring it mechanically.

Note that the focal plane for 850 nm IR differs from that for visible light, so
a sweep run under work lighting must be repeated under the IR illumination
before the value is locked in for measurement.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
from picamera2 import Picamera2

SIZE = (2304, 1296)


def sharpness(y: np.ndarray) -> tuple[float, float]:
    """Laplacian variance and mean gradient magnitude of a luminance plane."""
    f = y.astype(np.float32)
    lap = (4.0 * f[1:-1, 1:-1]
           - f[:-2, 1:-1] - f[2:, 1:-1]
           - f[1:-1, :-2] - f[1:-1, 2:])
    gx = np.abs(np.diff(f, axis=1)).mean()
    gy = np.abs(np.diff(f, axis=0)).mean()
    return float(lap.var()), float((gx + gy) / 2.0)


def measure(picam2, roi, settle_s: float, discard: int) -> tuple[float, float]:
    time.sleep(settle_s)
    for _ in range(discard):
        picam2.capture_array("main")          # flush frames from the old position
    y = picam2.capture_array("main")[:SIZE[1]]  # Y plane of YUV420
    top, bottom, left, right = roi
    return sharpness(y[top:bottom, left:right])


def settle_for(travel: float, base: float) -> float:
    """Settle time scaled by how far the lens actually has to move.

    A fixed settle is fine for the small steps within a sweep but not for the
    jump between sweeps. Measured 2026-09-03: the coarse sweep ended at 15.0 dpt
    and the fine sweep began at 6.50, and that first point read lap=13.5 where
    its neighbours implied ~45 -- the lens was still in transit when the frame
    was taken. The voice-coil actuator needs roughly a further 40 ms per dioptre
    of travel.
    """
    return base + 0.04 * travel


def sweep(picam2, positions, roi, args, previous: float | None = None):
    rows = []
    for p in positions:
        p = float(p)
        travel = abs(p - previous) if previous is not None else 15.0
        picam2.set_controls({"LensPosition": p})
        lap, grad = measure(picam2, roi, settle_for(travel, args.settle), args.discard)
        previous = p
        rows.append((p, lap, grad))
        print(f"  {p:6.2f} dpt   lap={lap:10.1f}   grad={grad:6.2f}", flush=True)
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exposure-us", type=int, default=60000)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--roi", type=float, default=0.5,
                   help="central fraction of the frame to measure, so the tube "
                        "mouth and vignetting do not dominate (default 0.5)")
    p.add_argument("--coarse-steps", type=int, default=21)
    p.add_argument("--fine-span", type=float, default=1.0)
    p.add_argument("--fine-steps", type=int, default=21)
    p.add_argument("--settle", type=float, default=0.35)
    p.add_argument("--discard", type=int, default=3)
    p.add_argument("--save", default="", help="write a JPEG at the sharpest position")
    args = p.parse_args()

    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    lo, hi, default = picam2.camera_controls["LensPosition"]
    print(f"LensPosition range: {lo} .. {hi} dioptres (default {default})")

    picam2.set_controls({
        "AfMode": 0,
        "AeEnable": False, "ExposureTime": args.exposure_us, "AnalogueGain": args.gain,
        "AwbEnable": False, "ColourGains": (1.5, 1.5),
    })
    picam2.start()
    time.sleep(1.5)   # let the locked exposure take effect

    h, w = SIZE[1], SIZE[0]
    fh, fw = int(h * args.roi / 2), int(w * args.roi / 2)
    roi = (h // 2 - fh, h // 2 + fh, w // 2 - fw, w // 2 + fw)
    print(f"ROI: {roi[3]-roi[2]}x{roi[1]-roi[0]} px, centred\n")

    try:
        print("=== coarse sweep ===")
        coarse = sweep(picam2, np.linspace(lo, hi, args.coarse_steps), roi, args)
        best = max(coarse, key=lambda r: r[1])[0]
        last = coarse[-1][0]

        f_lo = max(lo, best - args.fine_span)
        f_hi = min(hi, best + args.fine_span)
        print(f"\n=== fine sweep around {best:.2f} ({f_lo:.2f} .. {f_hi:.2f}) ===")
        fine = sweep(picam2, np.linspace(f_lo, f_hi, args.fine_steps), roi, args, previous=last)

        peak_lap = max(fine, key=lambda r: r[1])
        peak_grad = max(fine, key=lambda r: r[2])
        print(f"\nsharpest by Laplacian: {peak_lap[0]:.2f} dpt  (lap={peak_lap[1]:.1f})")
        print(f"sharpest by gradient:  {peak_grad[0]:.2f} dpt  (grad={peak_grad[2]:.2f})")
        agree = abs(peak_lap[0] - peak_grad[0])
        print(f"metrics differ by {agree:.2f} dpt "
              f"({'consistent' if agree <= 0.3 else 'INCONSISTENT -- check target contrast'})")
        if peak_lap[0] > 0:
            print(f"implied object distance: {1000.0/peak_lap[0]:.0f} mm "
                  f"(from the lens reference plane, whose exact location is "
                  f"unknown -- good for repeatability, not absolute geometry)")

        if args.save:
            picam2.set_controls({"LensPosition": peak_lap[0]})
            time.sleep(settle_for(abs(peak_lap[0] - fine[-1][0]), args.settle))
            for _ in range(args.discard):
                picam2.capture_array("main")
            picam2.capture_file(args.save)
            print(f"saved sharpest frame to {args.save}")
    finally:
        picam2.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
