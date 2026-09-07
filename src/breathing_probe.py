#!/usr/bin/env python3
"""How much does the focus setting move the laser dot?

The triangulation model was fitted at whatever focus each calibration position
used. If changing focus moves the dot, then autofocus and the measurement are
coupled and the model only holds when the operational focus matches the one it
was calibrated at. Focus breathing is 0.72 %/dioptre for this lens, which at
dx = 229 px predicts 1.6 px per dioptre -- worth measuring rather than assuming.

Reads the Y plane of a YUV420 stream, exactly as laser_align does, so the number
is comparable with the calibration.
"""

import argparse, sys, time
import numpy as np
from picamera2 import Picamera2
from illumination import Lamp

SIZE = (2304, 1296)
CX, CY = SIZE[0] / 2.0, SIZE[1] / 2.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--positions", default="7.0,8.0,9.0,9.44,10.0,11.0")
    p.add_argument("--exposure-us", type=int, default=8000)
    p.add_argument("--min-x", type=float, default=100.0)
    p.add_argument("--max-x", type=float, default=450.0)
    p.add_argument("--repeats", type=int, default=4)
    p.add_argument("--led-pin", type=int, default=17)
    p.add_argument("--laser-pin", type=int, default=27)
    args = p.parse_args()

    positions = [float(x) for x in args.positions.split(",")]
    led, laser = Lamp("IR", args.led_pin), Lamp("laser", args.laser_pin, settle_s=0.1)

    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.exposure_us,
                         "AnalogueGain": 1.0, "AwbEnable": False,
                         "ColourGains": (1.0, 1.0), "AfMode": 0,
                         "FrameDurationLimits": (33333, 33333)})
    picam2.start()
    time.sleep(1.5)

    def grab(n=3):
        for _ in range(n):
            picam2.capture_array("main")
        return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)

    yy, xx = np.mgrid[0:SIZE[1], 0:SIZE[0]]
    band = (np.abs(xx - CX) > args.min_x) & (np.abs(xx - CX) < args.max_x)

    def dot():
        with laser.forced_off():
            time.sleep(0.3); dark = grab()
        laser.acquire(); time.sleep(0.3); lit = grab(); laser.release()
        d = lit - dark
        work = np.where(band, d, 0.0)
        pk = float(work.max())
        if pk < 15:
            return None
        y0, x0 = np.unravel_index(int(np.argmax(work)), work.shape)
        near = (xx - x0) ** 2 + (yy - y0) ** 2 <= 70 * 70
        blob = near & (d >= 0.25 * pk)
        w = d[blob]
        return (float((xx[blob] * w).sum() / w.sum()) - CX,
                float((yy[blob] * w).sum() / w.sum()) - CY, pk)

    print(f"{'dpt':>6} {'dx':>9} {'sd':>6} {'dy':>9} {'peak':>6}")
    rows = []
    try:
        with led.forced_off():
            for lp in positions:
                picam2.set_controls({"LensPosition": lp})
                time.sleep(1.6)          # measured: stable from ~1.2 s
                got = [dot() for _ in range(args.repeats)]
                got = [g for g in got if g]
                if not got:
                    print(f"{lp:6.2f}   ingen punkt"); continue
                dxs = np.array([g[0] for g in got])
                dys = np.array([g[1] for g in got])
                pks = np.array([g[2] for g in got])
                rows.append((lp, dxs.mean(), dys.mean()))
                print(f"{lp:6.2f} {dxs.mean():9.2f} {dxs.std():6.2f} "
                      f"{dys.mean():9.2f} {pks.mean():6.0f}", flush=True)
    finally:
        picam2.stop(); laser.shutdown(); led.shutdown()

    if len(rows) >= 2:
        lp = np.array([r[0] for r in rows]); dx = np.array([r[1] for r in rows])
        k, m = np.polyfit(lp, dx, 1)
        print(f"\ndx = {m:.2f} + {k:+.3f} per dioptre "
              f"({100*k/dx.mean():+.2f} %/dpt over {dx.mean():.1f} px)")
        print(f"spannet {dx.max()-dx.min():.2f} px over "
              f"{lp.max()-lp.min():.1f} dpt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
