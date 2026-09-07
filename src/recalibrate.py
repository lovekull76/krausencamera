#!/usr/bin/env python3
"""Check the geometry after a rebuild, from one known distance.

Both models carry the distance from the housing face to the optical reference
as an additive constant, and it is the *same* constant:

    dx  = X_PP  + K/(d + C)          C   ->  C   - delta
    dpt = F_OFF + F_K/(d + F_C)      F_C ->  F_C - delta

So if the camera and laser are remounted as a rigid pair -- same baseline, same
angle -- and only the pair's depth in the housing changed, one measurement
against a known distance recovers delta and both models are current again.

Solving delta from each model separately says which happened:

    they agree      the pair is intact, only the mounting depth moved
    they disagree   the geometry between camera and laser has changed, and the
                    four-position series has to be repeated (--append, --fit)

Use page 2 of targets/focus-target-A4.pdf: focus needs contrast and the laser
centroid needs a uniform surface, and that sheet has both. Landing the dot on a
grating was measured to shift it 1.08 px, which is 0.7 mm of distance.
"""

from __future__ import annotations

import argparse
import sys
import time
from types import SimpleNamespace

import numpy as np

from focus_sweep import SIZE, sweep
from focus_tracker import (X_PP, K_LASER, C_LASER, F_OFF, F_K, F_C,
                           LENS_REF, DY_NOMINAL, DY_HALFWIDTH,
                           normalise_dx)
from illumination import Lamp

CX, CY = SIZE[0] / 2.0, SIZE[1] / 2.0


def measure_dx(picam2, laser, lens_position, exposure_us, min_x, max_x,
               repeats, band_y=DY_NOMINAL, halfwidth=DY_HALFWIDTH):
    """Dot centroid offset, normalised to the focus the models were fitted at."""
    picam2.set_controls({"ExposureTime": exposure_us, "LensPosition": lens_position})
    time.sleep(1.6)

    yy, xx = np.mgrid[0:SIZE[1], 0:SIZE[0]]
    # Both axes: |dx| excludes the tube edge, dy excludes anything bright
    # directly above or below the dot. Same window the tracker uses.
    band = ((np.abs(xx - CX) > min_x) & (np.abs(xx - CX) < max_x)
            & (np.abs(yy - CY - band_y) < halfwidth))

    def grab(n=4):
        for _ in range(n):
            picam2.capture_array("main")
        return picam2.capture_array("main")[:SIZE[1]].astype(np.float32)

    out = []
    for _ in range(repeats):
        with laser.forced_off():
            time.sleep(0.3)
            dark = grab()
        laser.acquire()
        try:
            time.sleep(0.3)
            lit = grab()
        finally:
            laser.release()
        d = lit - dark
        work = np.where(band, d, 0.0)
        pk = float(work.max())
        if pk < 15:
            continue
        y0, x0 = np.unravel_index(int(np.argmax(work)), work.shape)
        near = (xx - x0) ** 2 + (yy - y0) ** 2 <= 70 * 70
        blob = near & (d >= 0.25 * pk)
        w = d[blob]
        out.append((float((xx[blob] * w).sum() / w.sum()) - CX,
                    float((yy[blob] * w).sum() / w.sum()) - CY))
    if not out:
        return None
    dxs = np.array([o[0] for o in out])
    dys = np.array([o[1] for o in out])
    return {"dx": dxs.mean(), "dx_sd": dxs.std(), "dy": dys.mean(),
            "dx_ref": normalise_dx(dxs.mean(), lens_position)}


def fit_hyperbola(d, y, offset_range):
    """Least squares for y = a + b/(d + c), scanning c and solving a,b linearly.

    Nonlinear only in the offset, so a scan over it plus an exact linear solve
    beats an optimiser and brings no dependency. numpy is already required.
    """
    best = None
    for c in offset_range:
        if np.any(d + c <= 1.0):
            continue
        A = np.column_stack([np.ones_like(d), 1.0 / (d + c)])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        rms = float(np.sqrt((resid ** 2).mean()))
        if best is None or rms < best[0]:
            best = (rms, float(coef[0]), float(coef[1]), float(c), resid)
    return best


def report_fit(name, d, y, unit, per_unit):
    best = fit_hyperbola(d, y, np.arange(-60.0, 60.0, 0.05))
    rms, a, b, c, resid = best
    print(f"\n{name}:  y = {a:.3f} + {b:.1f}/(d {c:+.2f})   rms {rms:.3f} {unit}")
    for di, yi, ri in zip(d, y, resid):
        print(f"    d={di:6.1f}   measured {yi:9.3f}   residual {ri:+7.3f} {unit}"
              f"  ({ri*per_unit:+.2f} mm)")
    return a, b, c


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--distance", type=float,
                   help="known distance to the target, mm from the housing face")
    p.add_argument("--append", metavar="FILE",
                   help="append this point to FILE for a later --fit")
    p.add_argument("--fit", metavar="FILE",
                   help="refit both models from FILE and exit without measuring")
    p.add_argument("--exposure-us", type=int, default=8000)
    p.add_argument("--focus-exposure-us", type=int, default=37000)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--lo", type=float, default=4.0)
    p.add_argument("--hi", type=float, default=15.0)
    p.add_argument("--coarse-steps", type=int, default=12)
    p.add_argument("--fine-steps", type=int, default=9)
    p.add_argument("--fine-span", type=float, default=1.2)
    p.add_argument("--settle", type=float, default=0.60)
    p.add_argument("--discard", type=int, default=6)
    p.add_argument("--min-x", type=float, default=100.0)
    p.add_argument("--max-x", type=float, default=450.0)
    p.add_argument("--band-y", type=float, default=DY_NOMINAL,
                   help="centre of the vertical search window, px below centre")
    p.add_argument("--band-halfwidth", type=float, default=DY_HALFWIDTH)
    p.add_argument("--repeats", type=int, default=4)
    p.add_argument("--min-contrast", type=float, default=3.0,
                   help="reject the focus sweep below this peak-to-floor "
                        "ratio (a good target gives about 14)")
    p.add_argument("--led-pin", type=int, default=17)
    p.add_argument("--laser-pin", type=int, default=27)
    args = p.parse_args()

    if args.fit:
        rows = np.loadtxt(args.fit, delimiter=",", ndmin=2)
        if len(rows) < 4:
            print(f"{args.fit}: {len(rows)} points; the models have three "
                  f"parameters each, so four is the minimum that validates "
                  f"anything at all.")
        d, dpt, dx = rows[:, 0], rows[:, 1], rows[:, 2]
        # px per mm and dpt per mm, for reporting residuals in the unit that matters
        report_fit("FOCUS", d, dpt, "dpt", 1.0 / (F_K / (d.mean() + F_C) ** 2))
        report_fit("LASER", d, dx, "px", 1.0 / (K_LASER / (d.mean() + C_LASER) ** 2))
        return 0

    if args.distance is None:
        p.error("--distance is required unless --fit is given")

    from picamera2 import Picamera2
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": SIZE, "format": "YUV420"}))
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.focus_exposure_us,
                         "AnalogueGain": args.gain, "AwbEnable": False,
                         "ColourGains": (1.0, 1.0), "AfMode": 0,
                         "FrameDurationLimits": (args.focus_exposure_us + 1000,
                                                 args.focus_exposure_us + 1000)})
    led = Lamp("IR illumination", args.led_pin)
    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    picam2.start()
    time.sleep(1.5)

    # Full frame, not the centred half focus_sweep defaults to: the landing disc
    # sits in the middle and contributes no gradient, so a centred ROI would be
    # mostly blank. It cannot bias the peak -- a featureless region lowers the
    # metric everywhere equally -- but it can leave too little to measure.
    roi = (0, SIZE[1], 0, SIZE[0])
    sw = SimpleNamespace(settle=args.settle, discard=args.discard)

    try:
        led.acquire()
        time.sleep(0.5)
        for _ in range(6):
            picam2.capture_array("main")
        probe = picam2.capture_array("main")[:SIZE[1]].astype(np.float32)
        print(f"frame level: mean {probe.mean():.1f}, std {probe.std():.1f}")
        if probe.mean() < 25:
            print("WARNING: nearly dark. A dark sweep gives a flat curve that "
                  "looks like a focus problem.")

        print("\n=== coarse sweep ===")
        coarse = sweep(picam2, np.linspace(args.lo, args.hi, args.coarse_steps), roi, sw)
        best = max(coarse, key=lambda r: r[1])[0]
        lo = max(args.lo, best - args.fine_span)
        hi = min(args.hi, best + args.fine_span)
        print(f"\n=== fine sweep {lo:.2f} .. {hi:.2f} ===")
        fine = sweep(picam2, np.linspace(lo, hi, args.fine_steps), roi, sw,
                     previous=coarse[-1][0])
        dpt = max(fine, key=lambda r: r[1])[0]
        dpt_grad = max(fine, key=lambda r: r[2])[0]
        print(f"\nsharpest: {dpt:.2f} dpt (Laplacian), {dpt_grad:.2f} (gradient)")
        if abs(dpt - dpt_grad) > 0.3:
            print("  the two metrics disagree -- check the target has contrast")

        # A contrast-free target gives a flat curve with a peak somewhere in the
        # noise, and both metrics agree on that peak because they are computed
        # from the same flat frames -- so agreement is no guard at all. The
        # curve's own dynamic range is. A good target measured 14x peak to
        # floor; blank white paper measures 1.2x.
        laps = [r[1] for r in coarse + fine]
        ratio = max(laps) / max(min(laps), 1e-6)
        print(f"sweep contrast: {ratio:.1f}x peak to floor")
        if ratio < args.min_contrast:
            print(f"\nABORTING: below {args.min_contrast:.1f}x, the focus peak is "
                  f"noise, not focus. Is the target patterned? Page 2 of "
                  f"targets/focus-target-A4.pdf is the one to use -- white paper "
                  f"alone has nothing to focus on.")
            return 1
        led.release()

        print("\n=== laser ===")
        spot = measure_dx(picam2, laser, dpt, args.exposure_us,
                          args.min_x, args.max_x, args.repeats,
                          args.band_y, args.band_halfwidth)
    finally:
        picam2.stop()
        laser.shutdown()
        led.shutdown()

    if spot is None:
        print(f"no laser dot found in the window "
              f"(|dx| {args.min_x:.0f}-{args.max_x:.0f}, "
              f"dy {args.band_y-args.band_halfwidth:.0f} to "
              f"{args.band_y+args.band_halfwidth:.0f}) -- nothing to compare")
        return 1
    print(f"dx = {spot['dx']:.2f} +/- {spot['dx_sd']:.2f} at {dpt:.2f} dpt "
          f"-> {spot['dx_ref']:.2f} normalised to {LENS_REF:.1f}   "
          f"dy = {spot['dy']:.2f}")

    d = args.distance
    delta_focus = F_C - (F_K / (dpt - F_OFF) - d)
    delta_laser = C_LASER - (K_LASER / (spot["dx_ref"] - X_PP) - d)
    # What a millimetre of delta is worth in each observable, for the verdict
    px_per_mm = K_LASER / (d + C_LASER) ** 2

    print(f"\n{'':14}{'delta':>10}")
    print(f"{'from focus':14}{delta_focus:10.2f} mm")
    print(f"{'from laser':14}{delta_laser:10.2f} mm")
    disagreement = abs(delta_focus - delta_laser)
    print(f"{'they differ by':14}{disagreement:10.2f} mm "
          f"({disagreement * px_per_mm:.2f} px of dx)")

    print()
    if disagreement < 1.0:
        print(f"VERDICT: consistent. The camera and laser are intact as a pair; "
              f"only the mounting depth moved, by {0.5*(delta_focus+delta_laser):+.2f} mm.")
        print(f"  Update the constants:  C -> {C_LASER - delta_laser:.2f}   "
              f"F_C -> {F_C - delta_focus:.2f}")
        print("  One point fixes an offset but cannot see a scale change. If the "
              "baseline may have moved, take a second distance and check that "
              "delta comes out the same.")
    else:
        print("VERDICT: inconsistent. The two models want different offsets, so "
              "this is not a pure depth shift -- the geometry between camera and "
              "laser has changed.")
        print("  Repeat the four-position series: run with --append FILE at each "
              "distance, then --fit FILE.")

    if args.append:
        with open(args.append, "a") as fh:
            fh.write(f"{d:.1f},{dpt:.4f},{spot['dx_ref']:.4f}\n")
        print(f"\nappended to {args.append}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
