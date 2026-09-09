#!/usr/bin/env python3
"""One position of the rotation study: tilt sweep plus a frame for the mouth.

Rotating the housing in its dummy separates two errors that look identical from
a single position. In image coordinates the observed mouth offset is

    R(-theta) . m  -  a0

so the part that **rotates** with the housing belongs to the mouth or the dummy,
and the part that stays **constant** belongs to the camera in its housing. The
same reading applies to the tilt's direction.

Run at 0, 90, 180, 270 and 360 degrees, always the same way round. Wait about
15 minutes after each rotation: the joint's own transient has a 6 minute time
constant and an amplitude comparable to the offset being measured.
"""

import argparse
import os
import subprocess
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("angle", type=int, help="nominal housing angle in degrees")
    p.add_argument("--out", default=os.path.expanduser("~/rotation"))
    p.add_argument("--exposure-us", type=int, default=15000)
    p.add_argument("--lens-position", type=float, default=4.45)
    p.add_argument("--skip-tilt", action="store_true")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))

    if not args.skip_tilt:
        print(f"=== lutningssvep, {args.angle} grader ===", flush=True)
        r = subprocess.run(
            [sys.executable, os.path.join(here, "tilt_probe.py"),
             "--lo", "2.0", "--hi", "11.0", "--steps", "31",
             "--exposure-us", str(args.exposure_us)],
            capture_output=True, text=True)
        tail = [l for l in r.stdout.splitlines() if l.strip()][-14:]
        print("\n".join(tail))
        with open(os.path.join(args.out, f"tilt-{args.angle:03d}.txt"), "w") as fh:
            fh.write(r.stdout + r.stderr)

    print(f"\n=== bildruta, {args.angle} grader ===", flush=True)
    from picamera2 import Picamera2
    from PIL import Image
    sys.path.insert(0, here)
    from illumination import Lamp

    lamp = Lamp("IR illumination", 17)
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": (2304, 1296)}))
    d = max(33333, args.exposure_us + 1000)
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.exposure_us,
                         "AnalogueGain": 1.0, "AwbEnable": False,
                         "ColourGains": (0.94, 1.01), "AfMode": 0,
                         "LensPosition": args.lens_position,
                         "FrameDurationLimits": (d, d)})
    picam2.start()
    time.sleep(1.5)
    lamp.acquire()
    try:
        time.sleep(1.0)
        for _ in range(5):
            picam2.capture_array("main")
        a = picam2.capture_array("main")
        path = os.path.join(args.out, f"R-{args.angle:03d}-"
                            + time.strftime("%H%M%S") + ".jpg")
        Image.fromarray(a[:, :, :3][:, :, ::-1]).save(path, quality=90)
        print(f"sparad {os.path.basename(path)}   medelniva {a[:, :, :3].mean():.0f}")
    finally:
        picam2.stop()
        lamp.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
