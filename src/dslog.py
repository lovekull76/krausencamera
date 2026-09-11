#!/usr/bin/env python3
"""Log every DS18B20 on the 1-Wire bus, timestamped, until stopped.

Separate from `af_calibrate.py` on purpose. The measurement session owns the
camera for hours and must not be restarted to add a column -- a restart costs
the thermal equilibrium, which is the very thing being measured. So this writes
its own file and the two are joined afterwards on the timestamp, which the
session's CSV carries.

**Why this matters more than it sounds.** `af_calibrate` already records
`SensorTemperature` with every point, but the sensor reports whole degrees, and
at 0.63 mm per degree one count is 0.63 mm of measurement error. On 2026-09-11
the garage door was opened for 72 seconds; the reading moved 0.79 mm and the
camera's own sensor moved **one count**. A DS18B20 resolves 0.0625 C, which is
0.04 mm -- sixteen times finer, and it sees what the other is blind to.

    dtoverlay=w1-gpio,gpiopin=18        in /boot/firmware/config.txt
    VDD 3.3 V  ·  DQ GPIO18  ·  GND  ·  4.7 kohm between DQ and 3.3 V

Sensor ids are random and carry no position. `hardware/ds18b20-sensors.md` says
which is where, and gives the offsets measured with all of them bundled
together -- 0.125 C between the extremes, two quantisation steps. Absolute
accuracy is +/- 0.5 C and does not matter here: what is measured is change.
The offsets matter only when two sensors are compared with each other, say the
lid against the air around it.

    python3 dslog.py --out temps.csv --interval 30

A conversion takes about 750 ms per sensor at 12 bits, so an interval below
about 5 s with several sensors just samples the bus as fast as it will go.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time


def sensors():
    """Every DS18B20 currently on the bus, sorted so columns stay put.

    Sorted rather than taken in glob order because a sensor that drops off and
    comes back must land in the same column. Unplugging one mid-run is
    survivable -- 1-Wire enumerates live -- but a shifting column order would
    silently scramble the file.
    """
    return sorted(glob.glob("/sys/bus/w1/devices/28-*"))


def read(path):
    """Degrees, or None. A failed read is a gap, never a fabricated value."""
    try:
        with open(os.path.join(path, "temperature")) as fh:
            return int(fh.read()) / 1000.0
    except (OSError, ValueError):
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="temps.csv")
    p.add_argument("--interval", type=float, default=30.0, help="seconds")
    p.add_argument("--duration", type=float, default=0.0,
                   help="hours; 0 runs until killed")
    args = p.parse_args()

    ids = sensors()
    if not ids:
        print("inga DS18B20 pa bussen -- ar overlagget aktiverat och pullupen "
              "kopplad till 3.3 V?")
        return 1
    names = [os.path.basename(d) for d in ids]
    print(f"{len(ids)} givare: " + ", ".join(names), flush=True)

    new = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    with open(args.out, "a", buffering=1) as fh:
        if new:
            fh.write(f"# dslog {time.strftime('%Y-%m-%dT%H:%M:%S')}  "
                     f"intervall {args.interval:.0f} s\n")
            fh.write("# placering och offset: hardware/ds18b20-sensors.md\n")
            fh.write("tid," + ",".join(names) + "\n")
        t0 = time.time()
        n = 0
        while args.duration <= 0 or time.time() - t0 < args.duration * 3600:
            start = time.time()
            # Re-enumerate every round: a sensor may be added or lost while
            # running, and the file should say so rather than carry the last
            # value forward.
            now = {os.path.basename(d): read(d) for d in sensors()}
            vals = [now.get(k) for k in names]
            fh.write(time.strftime("%Y-%m-%dT%H:%M:%S") + "," +
                     ",".join("" if v is None else f"{v:.4f}" for v in vals) + "\n")
            n += 1
            if n % 20 == 1:
                print(f"  {time.strftime('%H:%M:%S')}  " +
                      "  ".join(f"{k[3:9]}={'--' if v is None else f'{v:.3f}'}"
                                for k, v in zip(names, vals)), flush=True)
            extra = [k for k in now if k not in names]
            if extra:
                print(f"  ** ny givare pa bussen: {', '.join(extra)} -- "
                      f"starta om loggaren for att fa med den **", flush=True)
            wait = args.interval - (time.time() - start)
            if wait > 0:
                time.sleep(wait)
    print(f"{n} rader -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
