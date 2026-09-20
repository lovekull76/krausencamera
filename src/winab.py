#!/usr/bin/env python3
"""Does constraining the AF metering window change what the camera reads --
and does it give back the near height that rails?

Love's argument, 2026-09-19: the fraction of dark tube wall that falls inside
the default metering region is set by how the housing happens to sit, and
hoping it comes out the same at every mount is a latent variable rather than a
design. The earlier left/right test measured the field's own tilt across the
target (0.054 dpt) -- it said nothing about tube wall inside the window,
because both windows sat on the target.

Two questions, in order:
  1. At a mid height, does a tight window shift the reading? Interleaved
     A/B/A/B so the camera's own drift cannot be mistaken for the effect.
  2. At 41.40 mm, which rails 0/2 with the default region, does a tight
     window converge? That is the one that would change the instrument.

Reuses af_calibrate's own warm_up and take_point so the thermal state, the
parking and the exposure are the tested code path, not a reimplementation.
"""
import argparse, statistics, subprocess, sys, time
sys.path.insert(0, "/home/pi/krausencamera")
from picamera2 import Picamera2
from libcamera import controls
import af_calibrate as AC
from illumination import Lamp
from liveview import MAIN_SIZE

ap = argparse.ArgumentParser()
ap.add_argument("--window", type=int, default=700, help="halvbredd i sensorpixlar")
ap.add_argument("--repeats", type=int, default=6)
ap.add_argument("--d0", type=float, default=27.4)
A = ap.parse_args()

args = argparse.Namespace(
    af_range=controls.AfRangeEnum.Full, runs=2,
    park_low=2.5, park_high=12.0, park_after=0.0,
    auto_exposure=True, exposure_target=230.0,
    exposures=[4000, 8000, 15000, 25000, 50000, 100000],
    warmup_interval=300.0, warmup_max=75.0, warmup_min=30.0,
    warmup_slope=0.03, warmup_window=6, af_window=0)

def stage(z):
    subprocess.run([sys.executable, "stage.py", "--to", f"{z:.2f}",
                    "--feed", "400", "--hold"],
                   cwd="/home/pi/krausencamera",
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

lamp = Lamp("IR illumination", 17); lamp.acquire()
if not lamp.is_lit:
    sys.exit("lampan tandes inte -- avbryter hellre an mater i morker")
picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(
    main={"size": MAIN_SIZE}, lores={"size": (1024, 576), "format": "YUV420"}))
picam2.set_controls({"AeEnable": False, "ExposureTime": 15000, "AnalogueGain": 1.0,
                     "AwbEnable": False, "ColourGains": (0.94, 1.01)})
picam2.start()

print("stage -> Z96 (123.40 mm), varmer upp", flush=True)
stage(96.0)
AC.pick_exposure(picam2, args)
AC.warm_up(picam2, controls, args, lamp_is_on=True)

def ab(label, z, d):
    stage(z)
    time.sleep(20)
    exp, lvl = AC.pick_exposure(picam2, args)
    print(f"\n=== {label}   Z{z:.0f} = {d:.2f} mm   exp {exp} us  niva {lvl:.1f} ===",
          flush=True)
    res = {0: [], A.window: []}
    for i in range(A.repeats):
        for w in (0, A.window):
            args.af_window = w
            lo, hi, seq, ts, te = AC.take_point(picam2, controls, args)
            vals = lo + hi
            res[w].append(statistics.mean(vals) if vals else None)
            tag = "Auto  " if w == 0 else f"fonst "
            v = res[w][-1]
            print(f"  {i+1} {tag} {'RAIL/FAIL' if v is None else f'{v:.4f}'}"
                  f"  ({len(vals)}/{args.runs})", flush=True)
    args.af_window = 0
    out = {}
    for w, v in res.items():
        g = [x for x in v if x is not None]
        out[w] = (len(g), len(v), statistics.mean(g) if g else float("nan"),
                  statistics.stdev(g) if len(g) > 1 else float("nan"))
    return out

for label, z, d in (("mitthojd", 96.0, 123.40), ("narhojden som railar", 14.0, 41.40)):
    o = ab(label, z, d)
    print(f"\n  {'':10s} {'ok':>7s} {'medel':>10s} {'sd':>9s}")
    for w in (0, A.window):
        n, tot, m, s = o[w]
        nm = "Auto" if w == 0 else f"fonster {w}"
        print(f"  {nm:<12s} {n}/{tot:<5d} {m:10.4f} {s:9.4f}")
    a0, a1 = o[0], o[A.window]
    if a0[0] and a1[0]:
        d_ = a1[2] - a0[2]
        se = ((a0[3]**2/max(a0[0],1)) + (a1[3]**2/max(a1[0],1)))**0.5
        print(f"  skillnad {d_:+.4f} +- {se:.4f} dpt = {abs(d_/se) if se else 0:.1f} sigma")
    elif a1[0] and not a0[0]:
        print("  ** Auto railar, fonstret konverterar -- narhojden vinns tillbaka **")
    elif a0[0] and not a1[0]:
        print("  ** fonstret railar dar Auto konverterar -- samre **")
    else:
        print("  bada railar")

picam2.stop(); lamp.release()
print("\nklart")
