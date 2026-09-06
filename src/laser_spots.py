#!/usr/bin/env python3
"""Find every bright spot the laser produces, not only the brightest.

The measurement needs to know which return is the surface. There can be more
than one: a liquid surface passes most of the beam, so the bottom returns a
second spot, and a polished lid can add specular ghosts.

Both live on the same radial line from the image centre, since the laser is
parallel to the camera axis -- distance moves a spot along that line and
nothing else. What separates them is radius, and what identifies the surface is
that its radius is steady while a bottom return dances: ripples refract the beam
on its way down, so the spot below wanders while the surface stays put.

Reports each spot over several frames so that motion is visible rather than
inferred.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from illumination import Lamp

SIZE = (2304, 1296)
CX, CY = SIZE[0] / 2.0, SIZE[1] / 2.0


def grab(picam2, n: int = 6) -> np.ndarray:
    for _ in range(n):
        picam2.capture_array("main")
    return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)


def find_spots(diff: np.ndarray, max_spots: int, frac: float, radius: int,
               min_peak: float = 20.0):
    """Greedy peak picking: take the maximum, blank a disc, repeat.

    Enough for a handful of well-separated spots and needs no scipy.

    The floor is both relative and absolute. A purely relative one tracks the
    strongest spot downwards: when a turbid layer halved the real return, the
    threshold halved with it and started reporting sensor noise at radius 1200
    as spots.
    """
    work = diff.copy()
    floor = max(frac * work.max(), min_peak)
    yy, xx = np.mgrid[0:work.shape[0], 0:work.shape[1]]
    out = []
    for _ in range(max_spots):
        pk = work.max()
        if pk < floor:
            break
        y0, x0 = np.unravel_index(int(np.argmax(work)), work.shape)
        near = (xx - x0) ** 2 + (yy - y0) ** 2 <= radius * radius
        blob = near & (diff >= 0.25 * pk)
        w = diff[blob]
        cx = float((xx[blob] * w).sum() / w.sum())
        cy = float((yy[blob] * w).sum() / w.sum())
        out.append({
            "x": cx, "y": cy, "peak": float(pk), "px": int(blob.sum()),
            "r": float(((cx - CX) ** 2 + (cy - CY) ** 2) ** 0.5),
            "deg": float(np.degrees(np.arctan2(cy - CY, cx - CX))),
        })
        work[near] = 0.0
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--laser-pin", type=int, default=27)
    p.add_argument("--exposure-us", type=int, default=1200)
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--max-spots", type=int, default=4)
    p.add_argument("--frac", type=float, default=0.15,
                   help="keep spots down to this fraction of the strongest")
    p.add_argument("--blank-radius", type=int, default=60)
    p.add_argument("--min-peak", type=float, default=20.0,
                   help="absolute floor, so a weak scene does not report noise")
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

    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    try:
        laser.shutdown(); time.sleep(0.4)
        dark = grab(picam2, 8)
        laser.acquire(); time.sleep(0.5)

        series = []
        for i in range(args.frames):
            spots = find_spots(grab(picam2, 3) - dark, args.max_spots,
                               args.frac, args.blank_radius, args.min_peak)
            series.append(spots)
            line = "  ".join(f"r={s['r']:6.1f} pk={s['peak']:4.0f}" for s in spots)
            print(f"  ruta {i+1}: {len(spots)} flackar   {line}", flush=True)
        laser.release()
    finally:
        laser.shutdown()
        picam2.stop()

    # gruppera pa radie mellan rutorna
    print()
    groups: list[list[dict]] = []
    for spots in series:
        for s in spots:
            for g in groups:
                if abs(g[0]["r"] - s["r"]) < 25:
                    g.append(s); break
            else:
                groups.append([s])
    groups.sort(key=lambda g: -np.mean([s["r"] for s in g]))

    print(f"{'':>10} {'radie':>16} {'vinkel':>8} {'topp':>6} {'pixlar':>7} {'rorlighet':>10}")
    for i, g in enumerate(groups):
        rs = np.array([s["r"] for s in g])
        print(f"{'yttre' if i == 0 else 'inre ' if i == 1 else f'nr {i+1}':>10} "
              f"{rs.mean():8.1f} +-{rs.std():4.2f} "
              f"{np.mean([s['deg'] for s in g]):7.1f}° "
              f"{np.mean([s['peak'] for s in g]):6.0f} "
              f"{np.mean([s['px'] for s in g]):7.0f} "
              f"{rs.std():9.2f} px")
    if len(groups) >= 2:
        sep = groups[0][0]["r"] - groups[1][0]["r"]
        print(f"\nseparation {sep:.1f} px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
