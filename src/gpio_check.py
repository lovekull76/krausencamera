#!/usr/bin/env python3
"""Verify that the GPIO lines really switch the illumination and the laser.

Captures a frame with the load off and one with it on, and reports the
difference. A large difference proves the whole chain end to end: GPIO pin,
MOSFET gate, supply, and the emitter itself. A small one narrows the fault to
the wiring rather than the software.

The live view must be stopped first -- it holds both the camera and GPIO17,
and a second process cannot claim either.

The laser stays off unless --laser is passed. Check the polarity of its enable
input before running that: if enable is active low, the pin's boot-time
pull-down turns the laser on before any code runs, and no flag here will help.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from illumination import Lamp

SIZE = (2304, 1296)


def stats(y: np.ndarray) -> dict:
    return {
        "mean": float(y.mean()),
        "max": float(y.max()),
        "p99": float(np.percentile(y, 99)),
    }


def grab(picam2, discard: int = 4) -> np.ndarray:
    for _ in range(discard):
        picam2.capture_array("main")
    return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)


def check(picam2, lamp: Lamp, settle: float, find_spot: bool) -> bool:
    lamp.shutdown()
    time.sleep(settle)
    off = grab(picam2)
    o = stats(off)

    lamp.acquire()
    time.sleep(settle)
    on = grab(picam2)
    n = stats(on)
    lamp.release()
    time.sleep(settle)

    print(f"  off:  mean {o['mean']:7.2f}   p99 {o['p99']:6.1f}   max {o['max']:5.0f}")
    print(f"  on:   mean {n['mean']:7.2f}   p99 {n['p99']:6.1f}   max {n['max']:5.0f}")

    delta = n["mean"] - o["mean"]
    print(f"  change in mean level: {delta:+.2f}")

    if find_spot:
        d = on - off
        yy, xx = np.unravel_index(int(np.argmax(d)), d.shape)
        print(f"  brightest new pixel: x={xx} y={yy}  (+{d.max():.0f})")

    ok = delta > 2.0
    print(f"  => {'SWITCHES' if ok else 'NO DETECTABLE CHANGE'}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--led-pin", type=int, default=17)
    p.add_argument("--laser-pin", type=int, default=27)
    p.add_argument("--laser", action="store_true",
                   help="also switch the laser on briefly -- verify enable polarity first")
    p.add_argument("--exposure-us", type=int, default=12000)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--settle", type=float, default=0.6)
    args = p.parse_args()

    from picamera2 import Picamera2

    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    picam2.set_controls({
        "AfMode": 0, "LensPosition": 7.35,
        "AeEnable": False, "ExposureTime": args.exposure_us, "AnalogueGain": args.gain,
        "AwbEnable": False, "ColourGains": (1.0, 1.0),
    })
    picam2.start()
    time.sleep(1.2)

    results = {}
    try:
        led = Lamp("IR illumination", args.led_pin)
        print(f"\nIR illumination on GPIO{args.led_pin}:")
        results["led"] = check(picam2, led, args.settle, find_spot=False)
        led.shutdown()

        if args.laser:
            laser = Lamp("laser", args.laser_pin, settle_s=0.1)
            print(f"\nLaser on GPIO{args.laser_pin}:")
            results["laser"] = check(picam2, laser, args.settle, find_spot=True)
            laser.shutdown()
        else:
            print(f"\nLaser on GPIO{args.laser_pin}: skipped (pass --laser to test)")
    finally:
        picam2.stop()

    print()
    for name, ok in results.items():
        print(f"{name:16} {'OK' if ok else 'FAILED'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
