#!/usr/bin/env python3
"""Choose the locked exposure for frame A by measuring the brightest case.

A locked exposure has to survive the whole fermentation, so it is chosen
against the *brightest* scene it will ever see -- high krausen, close to the
lamp -- and the empty tank at the start is simply darker. Setting it for the
scene in front of you now guarantees clipping later, and clipped frames cannot
be un-clipped.

Run it twice: once with a matte white target at the closest distance the foam
will reach, which is the worst case and brighter than foam actually is, and
once at rest level to confirm the far end is still well clear of the noise.

Works in RGB, deliberately. A YUV420 Y plane is limited range 16-235, and a
saturation test for >= 250 on one can never fire -- that mistake once reported
0 % saturation on a scene clipping 8.8 %.
"""

import argparse
import sys
import time

import numpy as np

SIZE = (2304, 1296)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exposures", default="8000,15000,25000,37000,50000,75000,100000",
                   help="microseconds to try")
    p.add_argument("--gain", type=float, default=1.0,
                   help="analogue gain; leave at 1.0 and buy light with time, "
                        "which costs nothing when the subject rises millimetres "
                        "per minute")
    p.add_argument("--headroom", type=float, default=0.90,
                   help="target for the 99.9th percentile, as a fraction of full "
                        "scale (default 0.90, about half a stop of margin)")
    p.add_argument("--red-gain", type=float, default=0.94)
    p.add_argument("--blue-gain", type=float, default=1.01)
    p.add_argument("--lens-position", type=float, default=None,
                   help="dioptres; omit to leave the lens where it is")
    p.add_argument("--led-pin", type=int, default=17)
    args = p.parse_args()

    from picamera2 import Picamera2
    from illumination import Lamp

    exposures = [int(x) for x in args.exposures.split(",")]
    lamp = Lamp("IR illumination", args.led_pin)
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": SIZE}))
    ctrl = {"AeEnable": False, "AnalogueGain": args.gain, "AwbEnable": False,
            "ColourGains": (args.red_gain, args.blue_gain), "AfMode": 0}
    if args.lens_position is not None:
        ctrl["LensPosition"] = args.lens_position
    picam2.set_controls(ctrl)
    picam2.start()
    time.sleep(1.5)
    lamp.acquire()
    time.sleep(1.0)          # the droop is 2.8 % over 19 min; a second is plenty

    print(f"{'exp us':>8} {'mean':>7} {'p50':>6} {'p99':>6} {'p99.9':>6} "
          f"{'max':>5} {'clipped %':>10}")
    rows = []
    try:
        for e in exposures:
            # A frame cannot be shorter than its own exposure, so the duration
            # limits have to be lifted with it or the request is silently capped.
            d = max(33333, e + 1000)
            picam2.set_controls({"ExposureTime": e, "FrameDurationLimits": (d, d)})
            time.sleep(0.8)
            for _ in range(4):
                picam2.capture_array("main")
            a = picam2.capture_array("main")[:, :, :3]
            y = a.max(axis=2).astype(np.float32)   # worst channel: what clips first
            p50, p99, p999 = np.percentile(y, [50, 99, 99.9])
            clipped = 100.0 * float((y >= 250).mean())
            rows.append((e, float(p999), clipped))
            print(f"{e:8d} {y.mean():7.1f} {p50:6.1f} {p99:6.1f} {p999:6.1f} "
                  f"{y.max():5.0f} {clipped:10.3f}", flush=True)
    finally:
        picam2.stop()
        lamp.shutdown()

    target = args.headroom * 255.0
    ok = [r for r in rows if r[1] <= target]
    print()
    if not ok:
        print(f"Every exposure tried puts the 99.9th percentile above "
              f"{target:.0f}. Go shorter than {min(r[0] for r in rows)} us.")
        return 1
    best = max(ok, key=lambda r: r[0])
    print(f"Longest exposure keeping the 99.9th percentile under {target:.0f}: "
          f"{best[0]} us  (p99.9 = {best[1]:.0f}, {best[2]:.3f} % clipped)")
    print("\nThat is the ceiling, not the answer. Repeat at rest level: if the "
          "mean there is comfortably above the noise, take this value. If it is "
          "not, the lamp is short of light and the fix is more light or a wider "
          "stop -- not a longer exposure, which would clip the near end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
