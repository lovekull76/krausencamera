#!/usr/bin/env python3
"""Drive a whole PDAF calibration table overnight, unattended.

Owns the stage over one serial port and pokes a running `af_calibrate.py
--session --request` over a file. The camera is never closed and never cools.

**Why it is built this way, rather than the obvious way.**

*Service duty cycle, not a burst.* The obvious design takes eight AF cycles at
one height, moves, repeats. But the reading follows the camera's thermal state,
and eight convergences back to back are a different thermal state from one
every few minutes -- which is what the instrument actually does in service. The
same mistake has already been made twice on this project: the first table was
taken with a cold camera while the service runs warm, and with a different
stream configuration from the one `liveview` uses. So: **one visit, a couple of
cycles, then wait.** `--interval` should match the service's `--af-interval`.

*Randomised height order.* The first table was measured far to near over one
day, so the camera's temperature correlated with distance -- and a confound
monotonic in the fitted variable is absorbed into the model's parameters
instead of showing up in the residual. It cannot be seen after the fact; it
just makes the calibration wrong at every other temperature. Shuffling turns
that bias into scatter.

*A reference height, revisited.* Every `--ref-every` visits the stage returns to
the same height. That repeated height measures whatever the camera is doing
while the table is taken, and with the other heights shuffled the drift term
and the distance model are separable in one fit. This is the whole reason the
stage exists: with loose blocks a height could never be returned to, so camera
drift and rig error could not be told apart at all.

*Statistics.* A single AF cycle scatters 0.006-0.02 dpt, which is 0.1-0.4 mm
depending on distance. Twelve hours at one visit per five minutes is ~144
visits; over nine heights that is sixteen each, so the mean lands at 0.03-0.10
mm -- as good as the old table's per-point figures, and drift-corrected besides.

Distances are `--d0` plus the stage coordinate. `d0` does not have to be right:
the focus model's offset absorbs a constant, and krausen height is a difference
from a zero taken at fill. The *spacing* has to be right, and that is the
leadscrew's business.

    # camera, in its own long-lived session:
    python3 af_calibrate.py --session af4.csv --request GO --preview 8081 \\
            --auto-exposure --runs 2 --warmup-min 36

    # then, once it says it is warm:
    python3 autocal.py --d0 40.0 --heights 0 12 25 38 52 68 85 104 125 \\
            --ref 52 --interval 300 --session af4.csv --request GO
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage import Stage                                    # noqa: E402


def rows_in(path):
    """Data rows written so far, so a completed point can be waited for."""
    try:
        with open(path) as fh:
            return sum(1 for ln in fh if ln.strip() and not ln.startswith("#"))
    except FileNotFoundError:
        return 0


def schedule(heights, ref, ref_every, visits, rng):
    """Shuffled heights with the reference folded in every ref_every visits.

    Shuffled in blocks rather than globally: a global shuffle can leave one
    height unvisited for hours, which matters when the thing being corrected
    for is a drift in time.
    """
    others = [h for h in heights if h != ref]
    out, bag = [], []
    while len(out) < visits:
        if ref_every and len(out) % ref_every == 0:
            out.append(ref)
            continue
        if not bag:
            bag = others[:]
            rng.shuffle(bag)
        out.append(bag.pop())
    return out[:visits]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--heights", type=float, nargs="+", required=True,
                   metavar="Z", help="stage coordinates to visit, mm")
    p.add_argument("--ref", type=float, required=True,
                   help="the height revisited to track drift")
    p.add_argument("--ref-every", type=int, default=3,
                   help="visit the reference every N visits (0 disables)")
    p.add_argument("--d0", type=float, required=True,
                   help="distance from the lid to the target at stage Z0, mm. "
                        "Only the spacing has to be right; the model's offset "
                        "absorbs an error here.")
    p.add_argument("--interval", type=float, default=300.0,
                   help="seconds between visits. Match the service's AF "
                        "interval -- the point is to hold the camera in the "
                        "thermal state it will actually be measured in.")
    p.add_argument("--visits", type=int, default=200)
    p.add_argument("--session", default="af4.csv",
                   help="the CSV af_calibrate is appending to, watched to know "
                        "when a point has landed")
    p.add_argument("--request", default="GO",
                   help="af_calibrate's request file")
    p.add_argument("--log", default="autocal.log")
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--feed", type=float, default=150.0)
    p.add_argument("--approach", type=float, default=5.0,
                   help="overshoot this far below and come back up, so every "
                        "height is reached the same way")
    p.add_argument("--settle", type=float, default=20.0,
                   help="seconds to stand still after a move before asking for "
                        "a measurement")
    p.add_argument("--zmin", type=float, default=0.0)
    p.add_argument("--zmax", type=float, default=150.0)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="print the schedule and stop, touching nothing")
    args = p.parse_args()

    rng = random.Random(args.seed)
    plan = schedule(args.heights, args.ref, args.ref_every, args.visits, rng)
    if args.dry_run:
        print(f"{len(plan)} besok, {args.interval/60:.1f} min isar = "
              f"{len(plan)*args.interval/3600:.1f} h")
        for h in sorted(set(plan)):
            print(f"  Z {h:7.2f}  ->  d {args.d0+h:7.2f} mm   "
                  f"{plan.count(h):3d} besok" + ("   REFERENS" if h == args.ref else ""))
        print("\nordning: " + " ".join(f"{h:g}" for h in plan[:24]) + " ...")
        return 0

    for h in args.heights + [args.ref]:
        if not args.zmin <= h <= args.zmax:
            print(f"hojd {h} utanfor {args.zmin}-{args.zmax}")
            return 1

    st = Stage(args.port, zmin=args.zmin, zmax=args.zmax, hold=True)
    log = open(args.log, "a", buffering=1)
    log.write(f"# autocal {time.strftime('%Y-%m-%dT%H:%M:%S')}  d0 {args.d0}  "
              f"interval {args.interval}  ref {args.ref}\n")
    log.write("# tid,besok,Z,d_mm,rader_fore,rader_efter\n")

    print(f"{len(plan)} besok, {len(plan)*args.interval/3600:.1f} h")
    try:
        for n, z in enumerate(plan, 1):
            t0 = time.time()
            d = args.d0 + z
            stamp = time.strftime("%H:%M:%S")
            print(f"\n[{n}/{len(plan)}] {stamp}  Z {z:.2f}  d {d:.2f} mm"
                  + ("  (referens)" if z == args.ref else ""), flush=True)

            if not st.move_to(z, args.feed, args.approach):
                print("  ** riggen rapporterade aldrig klar -- hoppar over **")
                log.write(f"{stamp},{n},{z:.3f},{d:.3f},,MOVE_TIMEOUT\n")
                continue
            time.sleep(args.settle)

            before = rows_in(args.session)
            with open(args.request, "w") as fh:
                fh.write(f"{d:.2f}\n")
            # af_calibrate deletes the file when it picks the request up, then
            # measures. Waiting on the row count rather than on the file means
            # a point that fails still counts -- it writes a row either way, so
            # this cannot hang on a bad measurement.
            deadline = time.time() + max(600.0, args.interval)
            while time.time() < deadline:
                time.sleep(5.0)
                if rows_in(args.session) > before:
                    break
            after = rows_in(args.session)
            ok = after > before
            print(f"  {'matt' if ok else '** ingen rad -- kor kameran? **'}"
                  f"   rader {before} -> {after}", flush=True)
            log.write(f"{stamp},{n},{z:.3f},{d:.3f},{before},{after}\n")

            wait = args.interval - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
    except KeyboardInterrupt:
        print("\navbruten")
    finally:
        st.power_off()      # hold=True, so this re-asserts the holding current
        log.close()
    print("klart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
