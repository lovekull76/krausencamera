#!/usr/bin/env python3
"""Report the laser dot's height error repeatedly, for aligning the camera.

The dot's vertical offset from the image centre is set by where the camera
sits in the play of its mount, not by the optics: measured at +56, +37 and +63
px across three mountings, which is 50-70 um of sensor movement. Shimming it to
zero once makes the measurement axis purely horizontal, so the distance
variable is x rather than a radius, and no vertical offset needs calibrating.

Prints continuously so the camera can be nudged while watching.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

from illumination import Lamp

SIZE = (2304, 1296)
CX, CY = SIZE[0] / 2.0, SIZE[1] / 2.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--laser-pin", type=int, default=27)
    p.add_argument("--exposure-us", type=int, default=8000)
    p.add_argument("--seconds", type=float, default=90.0)
    p.add_argument("--baseline-mm", type=float, default=15.0,
                   help="laser offset from the camera axis, used to turn dy "
                        "into millimetres: dx corresponds to this distance, so "
                        "dy_mm = dy * baseline / dx. Self-calibrating, and it "
                        "needs no focal length")
    p.add_argument("--min-x", type=float, default=100.0,
                   help="ignore anything closer to the centre than this, which "
                        "keeps the ghost out")
    p.add_argument("--max-x", type=float, default=450.0,
                   help="and anything further out, which keeps the tube edge "
                        "out. That edge is the brightest thing in the frame -- "
                        "roughly twice the real return -- so choosing by "
                        "brightness picks it every time")
    args = p.parse_args()

    from picamera2 import Picamera2
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    picam2.set_controls({"FrameDurationLimits": (33333, 33333), "AfMode": 0,
                         "LensPosition": 7.7, "AeEnable": False,
                         "ExposureTime": args.exposure_us, "AnalogueGain": 1.0,
                         "AwbEnable": False, "ColourGains": (1.0, 1.0)})
    picam2.start()
    time.sleep(1.2)

    def grab(n: int = 4) -> np.ndarray:
        for _ in range(n):
            picam2.capture_array("main")
        return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)

    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    yy, xx = np.mgrid[0:SIZE[1], 0:SIZE[0]]
    try:
        laser.shutdown(); time.sleep(0.4)
        dark = grab(8)
        laser.acquire(); time.sleep(0.4)

        # Direction: the camera board carries lens and sensor together, so
        # moving it changes the baseline against the fixed laser. Pushing the
        # camera down puts the laser further above the axis and the dot lower,
        # so dy grows -- measured, 63 to 71 px when the camera went down.
        print("dy > 0: punkten under mitten -> skjut kameran UPP")
        print("dy < 0: punkten over mitten  -> skjut kameran NED\n")
        t0 = time.time()
        while time.time() - t0 < args.seconds:
            d = grab(3) - dark
            adx = np.abs(xx - CX)
            band = (adx > args.min_x) & (adx < args.max_x)
            work = np.where(band, d, 0.0)
            pk = work.max()
            if pk < 15:
                print("  ingen punkt hittad", flush=True)
                continue
            y0, x0 = np.unravel_index(int(np.argmax(work)), work.shape)
            near = (xx - x0) ** 2 + (yy - y0) ** 2 <= 70 * 70
            blob = near & (d >= 0.25 * pk)
            w = d[blob]
            cx = float((xx[blob] * w).sum() / w.sum())
            cy = float((yy[blob] * w).sum() / w.sum())
            dy = cy - CY
            dx = cx - CX
            dy_mm = dy * args.baseline_mm / abs(dx) if dx else float("nan")
            bar = "#" * min(40, int(abs(dy) / 2))
            side = "UPP" if dy > 0 else "NED"
            print(f"  t={time.time()-t0:5.1f}s  dy={dy:+7.2f} px "
                  f"({dy_mm:+6.2f} mm)  dx={dx:+7.1f}  topp={pk:4.0f}  "
                  f"{side} {bar}", flush=True)
        laser.release()
    finally:
        laser.shutdown()
        picam2.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
