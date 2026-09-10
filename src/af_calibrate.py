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


def _mini(picam2, controls, args, n=4):
    """A short reading used only to judge whether the camera has settled."""
    vals = []
    pattern = [args.park_low, args.park_high, args.park_high, args.park_low]
    for i in range(n):
        picam2.set_controls({"AfMode": controls.AfModeEnum.Manual,
                             "LensPosition": pattern[i % 4]})
        time.sleep(1.5)
        picam2.set_controls({"AfMode": controls.AfModeEnum.Auto,
                             "AfRange": args.af_range})
        time.sleep(0.3)
        t0 = time.time()
        picam2.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
        st = lp = None
        while time.time() - t0 < 9.0:
            md = picam2.capture_metadata()
            st, lp = md.get("AfState"), md.get("LensPosition")
            if st in (2, 3):
                break
        if st == 2 and lp and not (abs(lp - 15.0) < 0.001 or abs(lp - 12.0) < 0.001):
            vals.append(lp)
    return float(np.mean(vals)) if vals else float("nan")


def warm_up(picam2, controls, args):
    """Wait until the AF reading stops moving. Not the temperature.

    Measured 2026-09-10 over a 60-minute session at a fixed 126.39 mm: from a
    cold start the reading walks +0.379 dioptres, which at that distance is
    **10.9 mm**, and it does not arrive until about **36 minutes**. Once there
    it is dead flat -- the scatter of nine point-means over 24 minutes was
    0.00247 dpt against 0.00257 predicted by counting noise alone.

    The old criterion asked the sensor temperature to rise less than 0.6 C
    between samples 30 s apart. Over that session the temperature climbed 53 to
    58 C in eighteen minutes, which is 0.14 C per half-minute -- **always under
    the threshold**. It therefore fired after two minutes every single time, no
    matter how cold the camera was, and every calibration point was taken about
    ten millimetres out. The criterion was on the wrong quantity, and it was
    also the wrong shape: a difference between two neighbours drowns in the
    noise long before the underlying trend does.

    So: judge the quantity that matters, and judge it by a fitted trend over
    several readings rather than by one step. The camera is also warmed by AF
    activity here, which is the same duty cycle the measurement itself runs at.
    """
    print("varmer upp -- kor AF tills avlasningen slutar rora sig", flush=True)
    t0 = time.time()
    ts, vs = [], []
    while time.time() - t0 < args.warmup_max * 60:
        v = _mini(picam2, controls, args)
        el = time.time() - t0
        ts.append(el)
        vs.append(v)
        temp = picam2.capture_metadata().get("SensorTemperature", float("nan"))
        line = f"  {el/60:5.1f} min   {v:8.4f} dpt   {temp:.1f} C"
        if len(vs) >= args.warmup_window:
            a = np.array(ts[-args.warmup_window:])
            b = np.array(vs[-args.warmup_window:])
            slope = np.polyfit(a, b, 1)[0] * 3600.0
            line += f"   trend {slope:+7.3f} dpt/h"
            if abs(slope) < args.warmup_slope:
                print(line + "   STILLA", flush=True)
                print(f"  jamvikt efter {el/60:.0f} min vid {temp:.1f} C, "
                      f"trend {slope:+.3f} dpt/h\n")
                return
        print(line, flush=True)
        time.sleep(max(0.0, args.warmup_interval - (time.time() - t0 - el)))
    print(f"  planade aldrig ut inom {args.warmup_max:.0f} min -- "
          f"matningen ar sannolikt fel\n")


def take_point(picam2, controls, args):
    """One point: args.runs AF cycles with the parking balanced low/high/high/low.

    Returns the readings split by parking direction, the sequence in order, and
    the sensor temperature either side, so the caller can judge drift.
    """
    t_start = picam2.capture_metadata().get("SensorTemperature", float("nan"))
    lo, hi, seq = [], [], []
    print(f"{'fran':>7} {'tillstand':>10} {'s':>5} {'dpt':>9}")
    pattern = [args.park_low, args.park_high, args.park_high, args.park_low]
    for i in range(args.runs):
        park = pattern[i % 4]
        picam2.set_controls({"AfMode": controls.AfModeEnum.Manual,
                             "LensPosition": park})
        time.sleep(1.8)
        picam2.set_controls({"AfMode": controls.AfModeEnum.Auto,
                             "AfRange": args.af_range})
        time.sleep(0.3)
        t0 = time.time()
        picam2.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
        st = lp = None
        while time.time() - t0 < 9.0:
            md = picam2.capture_metadata()
            st, lp = md.get("AfState"), md.get("LensPosition")
            if st in (2, 3):
                break
        # Railed against the lens stop is not focus, but AfState says 2 all
        # the same -- the same shape of failure as the laser reading a tank
        # bottom through clear water. Treat it as a failure.
        railed = False
        if lp is not None:
            railed = abs(lp - 15.0) < 0.001 or abs(lp - 12.0) < 0.001
        ok = st == 2 and lp and not railed
        print(f"{park:7.1f} "
              f"{('focused' if ok else ('RAILED' if railed else 'FAILED')):>10} "
              f"{time.time()-t0:5.1f} " + (f"{lp:9.4f}" if ok else " " * 9),
              flush=True)
        if ok:
            seq.append((i, park, lp))
            (lo if park == args.park_low else hi).append(lp)
    t_end = picam2.capture_metadata().get("SensorTemperature", float("nan"))
    return lo, hi, seq, t_start, t_end


def summarise(lo, hi, seq, t_start, t_end, args, label):
    """Print the summary for one point. Returns (mean, std, drifted).

    On foam the convergence rate is itself a measurement, so the failed cycles
    are reported rather than merely subtracted -- a surface that focuses six
    times out of eight is telling you something a mean cannot.
    """
    # Temperature is reported, not used to reject. The warm-up check idles the
    # camera while the measurement drives the lens eight times, so AF activity
    # heats it a degree or two even from equilibrium -- the check measures the
    # wrong phase. What matters is whether the readings themselves drift, and
    # that is measured directly below.
    if t_start == t_start and t_end == t_end:
        print(f"\nsensortemperatur {t_start:.1f} -> {t_end:.1f} C  "
              f"({t_end-t_start:+.1f})")

    v = np.array(lo + hi)
    if len(v) < 3:
        print(f"\n{len(v)}/{args.runs} lyckade -- for fa for att saga nagot")
        return None, None, False
    print(f"\n{len(v)}/{args.runs} lyckade   medel {v.mean():.4f}   "
          f"1sigma {v.std(ddof=1):.4f} dpt   sensor {t_end:.1f} C")
    if lo and hi:
        # Hysteresis would show as a split between the two parking directions,
        # not as extra scatter, so it has to be looked for separately.
        split = np.mean(hi) - np.mean(lo)
        pooled = np.sqrt((np.var(lo, ddof=1) + np.var(hi, ddof=1)) / 2) if \
            len(lo) > 1 and len(hi) > 1 else float("nan")
        print(f"  nerifran {np.mean(lo):.4f}   uppifran {np.mean(hi):.4f}   "
              f"skillnad {split:+.4f} dpt"
              + (f"  ({abs(split)/pooled:.1f}x spridningen)"
                 if pooled == pooled else ""))
    sens = 1000.0 / v.mean() ** 2
    idx = np.array([q[0] for q in seq], float)
    val = np.array([q[2] for q in seq])
    detr, drifted = val, False
    if len(val) > 3:
        k = np.polyfit(idx, val, 1)[0]
        detr = val - np.polyval(np.polyfit(idx, val, 1), idx)
        span = k * (idx[-1] - idx[0])
        print(f"  trend inom korningen {span:+.4f} dpt ({span*sens:+.2f} mm)")
        if abs(span) > 2.5 * detr.std(ddof=1):
            drifted = True
            print(f"  ** DRIFT UNDER MATNINGEN ** trenden ar "
                  f"{abs(span)/detr.std(ddof=1):.1f}x det avtrendade bruset.")
            print(f"     Medelvardet ar fel med storleksordningen "
                  f"{abs(span)*sens/2:.2f} mm.")
    print(f"  precision vid {label}: {v.std(ddof=1)*sens:.3f} mm"
          + (f"   (avtrendad {detr.std(ddof=1)*sens:.3f} mm)"
             if len(val) > 3 else ""))
    return float(v.mean()), float(v.std(ddof=1)), drifted


def run_session(picam2, controls, args):
    """Repeat a point without ever closing the camera.

    Closing it is what costs. The camera cools whenever it is closed, and from
    cold the reading is 10.9 mm out and takes 36 minutes to come back. Running
    one invocation per height therefore put every calibration point somewhere
    different on its own warm-up curve -- which is a confound that correlates
    with distance, and a fit absorbs that into its parameters instead of showing
    it as a residual.

    Two ways to ask for a point:

    **Timed** -- a point every `--interval` seconds for `--duration` minutes.
    For a scene that changes by itself, which is what foam does: it drains and
    sinks over tens of minutes, and the only way to tell that from an
    instrumental drift is to watch an unchanging scene the same way first.

    **On request** -- with `--request FILE`, the session sleeps until that file
    appears, takes a point, and deletes it. Write the distance in mm into the
    file and it is recorded with the point; write `stop` to end the session.
    That is what lets a whole calibration table be measured on one thermal
    state: Love rebuilds the height, the file is touched, the point is taken,
    and the camera never closes.
    """
    t0 = time.time()
    n = 0
    with open(args.session, "a") as fh:
        fh.write(f"# session {time.strftime('%Y-%m-%d %H:%M:%S')}  "
                 f"exp {args.exposure_us} us  runs {args.runs}"
                 + (f"  d {args.distance:.2f}" if args.distance else "") + "\n")
        fh.write("# t_s,d_mm,medel_dpt,sigma_dpt,n_ok,n_runs,sensor_C\n")
        fh.flush()
        while True:
            dist = args.distance
            if args.request:
                print(f"\nvantar pa {args.request}  "
                      f"(skriv avstandet i mm, eller 'stop')", flush=True)
                while not os.path.exists(args.request):
                    time.sleep(2.0)
                try:
                    text = open(args.request).read().strip()
                finally:
                    try:
                        os.remove(args.request)
                    except OSError:
                        pass
                if text.lower().startswith("stop"):
                    break
                try:
                    dist = float(text.split()[0])
                except (ValueError, IndexError):
                    print(f"  kunde inte lasa ett avstand ur {text!r} -- "
                          f"tar punkten anda, utan avstand")
                    dist = None
            el = time.time() - t0
            n += 1
            print(f"\n=== punkt {n}   {el/60:5.1f} min"
                  + (f"   d {dist:.2f} mm" if dist else "") + " ===", flush=True)
            lo, hi, seq, ts, te = take_point(picam2, controls, args)
            label = f"{dist:.0f} mm" if dist else f"{el/60:.0f} min"
            mean, std, _ = summarise(lo, hi, seq, ts, te, args, label)
            dcol = f"{dist:.2f}" if dist else ""
            if mean is not None:
                fh.write(f"{el:.0f},{dcol},{mean:.5f},{std:.5f},"
                         f"{len(lo)+len(hi)},{args.runs},{te:.2f}\n")
            else:
                fh.write(f"{el:.0f},{dcol},,,"
                         f"{len(lo)+len(hi)},{args.runs},{te:.2f}\n")
            fh.flush()
            if not args.request:
                if time.time() - t0 >= args.duration * 60:
                    break
                wait = args.interval - (time.time() - t0 - el)
                if wait > 0:
                    time.sleep(wait)
    print(f"\n{n} punkter -> {args.session}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--distance", type=float, help="known distance, mm")
    p.add_argument("--append", metavar="FILE")
    p.add_argument("--fit", metavar="FILE")
    p.add_argument("--session", metavar="FILE",
                   help="keep the camera open and repeat the point, so the "
                        "whole series shares one thermal state and one "
                        "untouched rig. For a scene that changes by itself.")
    p.add_argument("--request", metavar="FILE",
                   help="session takes a point when this file appears, instead "
                        "of on a timer. Put the distance in mm in it, or "
                        "'stop' to finish. Keeps one thermal state across a "
                        "whole calibration table.")
    p.add_argument("--interval", type=float, default=120.0,
                   help="seconds between points in a timed session")
    p.add_argument("--duration", type=float, default=30.0,
                   help="minutes a session runs for")
    p.add_argument("--warmup-max", type=float, default=50.0,
                   help="minutes allowed for the reading to settle. From cold "
                        "it takes about 36; the old 25 would have timed out.")
    p.add_argument("--warmup-interval", type=float, default=120.0,
                   help="seconds between warm-up readings")
    p.add_argument("--warmup-window", type=int, default=6,
                   help="readings the settling trend is fitted over")
    p.add_argument("--warmup-slope", type=float, default=0.03,
                   help="dpt/h below which the camera counts as settled. The "
                        "tail of the warm-up runs at +0.088; equilibrium is 0.")
    p.add_argument("--runs", type=int, default=8,
                   help="AF cycles per point, alternating the parking position")
    p.add_argument("--af-range", type=int, default=2, choices=(0, 1, 2),
                   help="0 normal, 1 macro, 2 full. Normal rails at 12.0 "
                        "dioptres; macro and full reach 15.0, which is the "
                        "lens's actual travel. Free range, so full by default.")
    p.add_argument("--park-low", type=float, default=2.5)
    p.add_argument("--park-high", type=float, default=12.0)
    p.add_argument("--exposure-us", type=int, default=15000)
    p.add_argument("--led-pin", type=int, default=17)
    args = p.parse_args()

    if args.fit:
        report(args.fit)
        return 0
    if args.distance is None and not args.session:
        p.error("--distance kravs om inte --fit eller --session anges")

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
    warm_up(picam2, controls, args)
    lamp.acquire()
    time.sleep(1.2)

    try:
        if args.session:
            return run_session(picam2, controls, args)
        lo, hi, seq, ts, te = take_point(picam2, controls, args)
    finally:
        picam2.stop()
        lamp.shutdown()

    mean, std, drifted = summarise(lo, hi, seq, ts, te, args,
                                   f"{args.distance:.0f} mm")
    if mean is None:
        return 1
    if drifted:
        print("     Punkten sparas inte -- vanta och mat om.")
        return 1
    if args.append:
        with open(args.append, "a") as fh:
            fh.write(f"{args.distance:.2f},{mean:.5f},{std:.5f}\n")
        print(f"  -> {args.append}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
