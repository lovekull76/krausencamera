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
import threading
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


def warm_up(picam2, controls, args, lamp_is_on=True):
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
    if not lamp_is_on:
        print("  ** LAMPAN AR SLACKT ** AF har inget att fokusera pa och "
              "avlasningen blir meningslos.")
        return
    t0 = time.time()
    ts, vs = [], []
    while time.time() - t0 < args.warmup_max * 60:
        # Check the level every round, not only when AF fails. A scene that
        # goes dark is caught by the failure; a scene that comes *back* is not,
        # and then the exposure chosen against the dark one leaves the frame
        # clipped. That happened for real: a hand in the way picked 50 ms, the
        # scene returned, and the warm-up spent minutes judging a blown image.
        if args.auto_exposure:
            p999 = level_p999(picam2)
            if not 0.55 * args.exposure_target <= p999 <= 1.02 * args.exposure_target:
                print(f"  nivan ur band (p99.9 {p999:.0f}) -- valjer om",
                      flush=True)
                pick_exposure(picam2, args)
        v = _mini(picam2, controls, args)
        el = time.time() - t0
        ts.append(el)
        vs.append(v)
        temp = picam2.capture_metadata().get("SensorTemperature", float("nan"))
        line = (f"  {el/60:5.1f} min   "
                + (f"{v:8.4f} dpt" if v == v else "   RAIL/FAIL")
                + f"   {temp:.1f} C")
        if v != v and args.auto_exposure:
            # AF found nothing. The commonest reason during a warm-up is that
            # the scene moved: the exposure was chosen once, at the start, and
            # the rig has been rebuilt since. Re-choose before blaming the lens.
            print(line + "   -> valjer om exponeringen", flush=True)
            pick_exposure(picam2, args)
            time.sleep(max(0.0, args.warmup_interval - (time.time() - t0 - el)))
            continue
        # A single failed reading must not poison the fit. np.polyfit returns
        # nan for the whole window if one sample is nan, and abs(nan) < x is
        # False, so the warm-up would simply never finish -- a hang dressed as
        # patience. Drop them instead, and say how many were dropped.
        slope = None
        good = [(x, z) for x, z in zip(ts, vs) if z == z][-args.warmup_window:]
        if len(good) >= args.warmup_window:
            a = np.array([x for x, _ in good])
            b = np.array([z for _, z in good])
            slope = float(np.polyfit(a, b, 1)[0] * 3600.0)
            line += f"   trend {slope:+7.3f} dpt/h"
            if el < args.warmup_min * 60:
                line += f"   (minst {args.warmup_min:.0f} min)"
        if (slope is not None and el >= args.warmup_min * 60
                and abs(slope) < args.warmup_slope):
            print(line + "   STILLA", flush=True)
            print(f"  jamvikt efter {el/60:.0f} min vid {temp:.1f} C, "
                  f"trend {slope:+.3f} dpt/h\n")
            return
        print(line, flush=True)
        time.sleep(max(0.0, args.warmup_interval - (time.time() - t0 - el)))
    print(f"  planade aldrig ut inom {args.warmup_max:.0f} min -- "
          f"matningen ar sannolikt fel\n")


def level_p999(picam2):
    """One capture, the 99.9th percentile of the worst channel. Cheap."""
    for _ in range(2):
        picam2.capture_array("main")
    a = picam2.capture_array("main")[:, :, :3]
    return float(np.percentile(a.max(axis=2).astype(np.float32), 99.9))


def pick_exposure(picam2, args):
    """Choose the exposure that holds the image level, not the exposure itself.

    The scene brightens as the inverse square, so across 44 to 181 mm it varies
    by a factor of seventeen. One fixed exposure clips at the near end or
    starves the far one; an exposure chosen by hand per height is a second
    variable that correlates with distance -- which is exactly the shape of
    confound that put a thermal state into the last table and hid inside the
    fitted parameters.

    So hold the level and let the exposure follow. Same criterion as
    exposure_probe: the longest exposure keeping the 99.9th percentile under
    the target, read as the worst of R, G and B because whichever channel clips
    first is the one that matters. The 99.9th rather than the maximum because
    a few specular pixels should not drag the whole frame dark.
    """
    best = None
    for e in args.exposures:
        # A frame cannot be shorter than its own exposure, so the duration
        # limits have to be lifted with it or the request is silently capped.
        d = max(33333, e + 1000)
        picam2.set_controls({"ExposureTime": e, "FrameDurationLimits": (d, d)})
        time.sleep(0.6)
        for _ in range(3):
            picam2.capture_array("main")
        a = picam2.capture_array("main")[:, :, :3]
        y = a.max(axis=2).astype(np.float32)
        p999 = float(np.percentile(y, 99.9))
        if p999 <= args.exposure_target:
            best = (e, p999, float(y.mean()))
    if best is None:
        e = min(args.exposures)
        print(f"  ** varje exponering klipper ** anvander kortaste {e} us")
        d = max(33333, e + 1000)
        picam2.set_controls({"ExposureTime": e, "FrameDurationLimits": (d, d)})
        time.sleep(0.6)
        return e, float("nan")
    e, p999, mean = best
    d = max(33333, e + 1000)
    picam2.set_controls({"ExposureTime": e, "FrameDurationLimits": (d, d)})
    time.sleep(0.6)
    print(f"  exponering {e} us   p99.9 {p999:.0f}   medelniva {mean:.1f}")
    return e, mean


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
    # Two is enough. It was three, which silently threw away every point taken
    # with --runs 2 -- the whole rail hunt of 2026-09-12 wrote n_ok 2/2 beside
    # an empty mean, and the night was about to do the same for twelve hours.
    # A visit-based schedule wants few cycles per visit and many visits, so the
    # per-visit scatter is not the point; the mean is.
    if len(v) < 2:
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


def start_preview(broker, port):
    """Serve the lores stream while a session holds the camera.

    A calibration session owns the camera for hours, and the service that
    normally provides the live view has to be stopped for it. Without this there
    is no way to see what the camera is looking at while a height is being
    built -- which matters most at the far end, where the target is small in
    frame and easy to place badly.

    Reuses liveview's FrameBroker rather than reimplementing it, and the same
    two-stream configuration, so the calibration is taken under the exact
    configuration the service runs. A configuration-dependent offset in the AF
    statistics would otherwise sit in the table with nothing to reveal it.
    """
    from http import server as httpserver
    import socketserver

    PAGE = ("<!doctype html><title>krausencamera -- kalibrering</title>"
            "<style>body{margin:0;background:#111;color:#ccc;"
            "font:14px system-ui}img{width:100%;height:auto;display:block}"
            "p{padding:8px}</style>"
            "<img src='/stream'><p>Kalibreringssession pagar. "
            "Kameran far inte stangas -- den ar termiskt utvarmd.</p>")

    class Handler(httpserver.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.rstrip("/") in ("", "/index.html"):
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self.path.startswith("/stream"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            # A viewer that stops reading blocks the socket once the send
            # buffer fills, and would otherwise sit there until TCP keepalive
            # notices -- two hours by default. Same trap as the live view's.
            self.connection.settimeout(10.0)
            try:
                while True:
                    frame = broker.next_frame()
                    if frame is None:
                        continue
                    self.wfile.write(b"--FRAME\r\n"
                                     b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n"
                                     .encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    class Server(socketserver.ThreadingMixIn, httpserver.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = Server(("", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"forhandsgranskning pa http://krausencamera:{port}/", flush=True)
    return srv


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
        fh.write("# tid,t_s,d_mm,medel_dpt,sigma_dpt,n_ok,n_runs,sensor_C,exp_us,niva,drift\n")
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
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            n += 1
            print(f"\n=== punkt {n}   {el/60:5.1f} min"
                  + (f"   d {dist:.2f} mm" if dist else "") + " ===", flush=True)
            exp_us, level = (pick_exposure(picam2, args) if args.auto_exposure
                             else (args.exposure_us, float("nan")))
            lo, hi, seq, ts, te = take_point(picam2, controls, args)
            label = f"{dist:.0f} mm" if dist else f"{el/60:.0f} min"
            mean, std, drifted = summarise(lo, hi, seq, ts, te, args, label)
            if drifted:
                # The single-point path refuses to save a drifting point. A
                # session cannot refuse -- the operator is standing there and
                # the camera must not close -- so it records the verdict
                # instead, and the row can be dropped when the table is fitted.
                print("     ** raden markeras drift=1 i CSV:n **")
            dcol = f"{dist:.2f}" if dist else ""
            if mean is not None:
                fh.write(f"{stamp},{el:.0f},{dcol},{mean:.5f},{std:.5f},"
                         f"{len(lo)+len(hi)},{args.runs},{te:.2f},"
                         f"{exp_us},{level:.1f},{int(drifted)}\n")
            else:
                fh.write(f"{stamp},{el:.0f},{dcol},,,"
                         f"{len(lo)+len(hi)},{args.runs},{te:.2f},"
                         f"{exp_us},{level:.1f},1\n")
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
    p.add_argument("--auto-exposure", action="store_true",
                   help="choose the exposure before every point so the image "
                        "level stays constant across the range instead of the "
                        "exposure. Recommended for a calibration table.")
    p.add_argument("--exposure-target", type=float, default=230.0,
                   help="99.9th percentile the auto exposure aims under")
    p.add_argument("--exposures", type=int, nargs="+",
                   default=[1000, 2000, 4000, 8000, 15000, 25000, 37000, 50000],
                   help="exposures the auto choice picks from, us")
    p.add_argument("--bitrate", type=int, default=12_000_000,
                   help="MJPEG bitrate for the preview. Matches liveview's "
                        "default; a third of it visibly posterises a smooth "
                        "gradient like the tube wall.")
    p.add_argument("--preview", type=int, default=0, metavar="PORT",
                   help="serve the lores stream on this port while the session "
                        "runs, so heights can be placed without stopping it. "
                        "8081 keeps it clear of the service's 8080.")
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
    p.add_argument("--warmup-min", type=float, default=30.0,
                   help="minutes the warm-up runs before it may declare "
                        "equilibrium at all. The trend test judges the AF "
                        "reading, so anything moving in front of the camera -- "
                        "a rig being built -- can flatten it for the wrong "
                        "reason. Measured settling is about 36 minutes.")
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
    # Same two streams as liveview, so the calibration is measured under the
    # configuration the service actually runs.
    from liveview import MAIN_SIZE, FrameBroker
    picam2.configure(picam2.create_video_configuration(
        main={"size": MAIN_SIZE},
        lores={"size": (1024, 576), "format": "YUV420"}))
    picam2.set_controls({"AeEnable": False, "ExposureTime": args.exposure_us,
                         "AnalogueGain": 1.0, "AwbEnable": False,
                         "ColourGains": (0.94, 1.01)})
    picam2.start()
    broker = None
    if args.preview:
        from picamera2.encoders import MJPEGEncoder
        from picamera2.outputs import FileOutput
        broker = FrameBroker()
        picam2.start_recording(MJPEGEncoder(bitrate=args.bitrate),
                               FileOutput(broker), name="lores")
        start_preview(broker, args.preview)
    time.sleep(1.5)
    # The lamp must be lit BEFORE the warm-up, not after. The old warm-up only
    # read the temperature, so it did not care; this one drives AF, and AF in a
    # dark garage converges on nothing. Same trap the focus sweep fell into
    # when the LEDs moved to GPIO17 -- it silently swept a dark scene and
    # returned a plausible-looking result that meant nothing.
    lamp.acquire()
    time.sleep(1.2)
    if args.auto_exposure:
        pick_exposure(picam2, args)
    warm_up(picam2, controls, args, lamp_is_on=lamp.is_lit)

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
            # Absolute time, because the covariates live in another system.
            # Home Assistant keeps full-resolution states for 390 days here, so
            # the garage temperature at the moment of any measurement is
            # retrievable -- but only if this file says when the measurement
            # was. The nine-point table of 2026-09-10 cannot be checked against
            # ambient for exactly this reason: HASS remembers and we did not.
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')},"
                     f"{args.distance:.2f},{mean:.5f},{std:.5f}\n")
        print(f"  -> {args.append}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
