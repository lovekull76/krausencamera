#!/usr/bin/env python3
"""Locate the laser dot and report its position in image and object space.

The first calibration measurement. With the laser mounted parallel to the
camera axis at a known baseline, the dot's radial distance from the image
centre encodes the distance to the surface -- that is the triangulation the
brief describes, and this is the measurement the calibration table is built
from.

Two details decide whether the number means anything:

* **The dot must not be saturated.** A clipped peak has a flat top, so the
  centroid is computed over a plateau rather than a profile and the sub-pixel
  precision is lost. The exposure is swept down until the peak is comfortably
  inside range.
* **The pedestal must be removed first.** A YUV420 Y plane sits at 16 for
  black, and a centroid over a uniform pedestal is pulled toward the frame
  centre. Everything here works on (frame - dark frame).
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from illumination import Lamp

SIZE = (2304, 1296)


def grab(picam2, discard: int = 4) -> np.ndarray:
    for _ in range(discard):
        picam2.capture_array("main")
    return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)


def centroid(diff: np.ndarray, frac: float = 0.2):
    """Intensity-weighted centroid over pixels above frac of the peak."""
    peak = diff.max()
    mask = diff >= peak * frac
    ys, xs = np.nonzero(mask)
    w = diff[ys, xs]
    return (float((xs * w).sum() / w.sum()),
            float((ys * w).sum() / w.sum()),
            int(mask.sum()), float(peak))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--laser-pin", type=int, default=27)
    p.add_argument("--px-per-mm", type=float, default=12.71,
                   help="image scale at the current working distance")
    p.add_argument("--baseline-mm", type=float, default=15.5,
                   help="laser offset from the camera axis")
    p.add_argument("--target-peak", type=float, default=200.0)
    args = p.parse_args()

    from picamera2 import Picamera2
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    picam2.set_controls({"AfMode": 0, "LensPosition": 7.35,
                         "AwbEnable": False, "ColourGains": (1.0, 1.0),
                         "AeEnable": False, "AnalogueGain": 1.0})
    picam2.start()
    time.sleep(1.2)

    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    try:
        print(f"{'exp us':>8} {'peak-dark':>10} {'pixlar':>8}")
        best = None
        for exp in (12000, 6000, 3000, 1500, 800, 400, 200, 100):
            picam2.set_controls({"ExposureTime": exp})
            time.sleep(0.5)
            laser.shutdown(); time.sleep(0.3)
            dark = grab(picam2)
            laser.acquire(); time.sleep(0.3)
            lit = grab(picam2)
            laser.release()
            diff = lit - dark
            cx, cy, npx, peak = centroid(diff)
            print(f"{exp:8d} {peak:10.0f} {npx:8d}", flush=True)
            if peak <= args.target_peak and best is None:
                best = (exp, cx, cy, npx, peak)
        if best is None:
            print("\nkunde inte fa punkten under mattnad -- prova kortare exponering")
            return 1

        exp, cx, cy, npx, peak = best
        print(f"\nvald exponering: {exp} us   peak {peak:.0f}   {npx} pixlar over troskeln")
        h, w = SIZE[1], SIZE[0]
        dx, dy = cx - w / 2.0, cy - h / 2.0
        r = (dx * dx + dy * dy) ** 0.5
        print(f"centroid:  x={cx:.2f}  y={cy:.2f}")
        print(f"fran mitten: dx={dx:+.1f}  dy={dy:+.1f}  radie={r:.1f} px")
        print(f"i objektrymd: {r/args.px_per_mm:.2f} mm  (baslinjen ar {args.baseline_mm} mm)")
        print(f"avvikelse: {100*(r/args.px_per_mm - args.baseline_mm)/args.baseline_mm:+.1f} %")
        print(f"\nkanslighet dr/dd = r/d; vid {r:.0f} px och 130 mm avstand "
              f"blir det {r/130:.2f} px per mm hojdandring")
    finally:
        laser.shutdown()
        picam2.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
