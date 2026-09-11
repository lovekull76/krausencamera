#!/usr/bin/env python3
"""Drive the target stage: a TinyG v8 over serial, one axis.

Replaces the stack of loose blocks. Two things that bought:

**No rebuild between heights.** A restacked pile moves 0.2-0.35 mm afterwards,
measured photometrically on 2026-09-11, and the wait for it to stop is not a
fixed time -- two stacks settled at rates eight times apart.

**A height can be revisited exactly**, which is what makes bracketing possible:
measure A, B, A, C, A, and the repeated A tracks whatever the camera is doing
while the table is taken. Drift that can be measured can be subtracted. That is
the real prize, and it is unavailable with loose blocks because a height can
never be returned to.

The absolute distance does not have to be right -- the focus model's offset
absorbs a constant, and krausen height is a difference from a zero taken at
fill, so a constant cancels twice over. **The spacing does.** With a leadscrew
that reduces the whole distance calibration to one number, `$1tr` (travel per
revolution), which is calibrated once over a long move with a caliper: 0.1 mm
of caliper error over 150 mm is 0.07 % of scale. The folding rule was 0.5 mm
out, systematically, at every height.

Hardware, from the Synthetos documentation for v8 / firmware 0.97:

    logic inputs   3.3 V MAX -- the Pi's GPIO level, so no level shifting
    USB            FTDI, 115200 default (9600-230400)
    motors         12-30 V, TI DRV8818, 2.5 A/winding, microstepping to 1/8
    $1pm           0 off, 1 always, 2 in cycle, 3 only while moving
    $mt            seconds before motor power is released

`$1pm=3` is what this tool assumes: the coil is dead the moment the move ends.
A trapezoidal screw self-locks, so nothing is holding the platform but friction
and thread geometry -- **check that by pushing on it with the power off before
trusting it**. The point is not tidiness: a motor drawing current a hand's width
from the optics is exactly the heat source that cost us a day.

⚠️ UNTESTED against real hardware. Written before the board was connected.

    python3 stage.py --status
    python3 stage.py --to 108.16
    python3 stage.py --zero-here          # calls this position Z0
    python3 stage.py --calibrate 150      # move 150 mm, then measure and tell it
"""

from __future__ import annotations

import argparse
import json
import sys
import time

# TinyG machine states. Anything in READY is safe to read a position from.
READY = (1, 3, 4)          # ready, program stop, program end
MOVING = (5, 8, 9)         # run, cycle, homing


class Stage:
    def __init__(self, port, baud=115200, timeout=2.0, zmin=0.0, zmax=200.0):
        import serial                       # pyserial, apt: python3-serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.zmin, self.zmax = zmin, zmax
        time.sleep(2.0)                     # FTDI settling; the board may reboot
        self.ser.reset_input_buffer()

    def send(self, line, wait=3.0):
        """Send one line and collect whatever comes back until it goes quiet.

        TinyG answers in JSON or text depending on $ej, and an `ok` means the
        line was *accepted*, not that the machine has stopped. Motion completion
        is a separate question -- see wait_idle().
        """
        self.ser.write((line.strip() + "\n").encode())
        self.ser.flush()
        out, t0 = [], time.time()
        while time.time() - t0 < wait:
            raw = self.ser.readline()
            if not raw:
                break
            s = raw.decode(errors="replace").strip()
            if s:
                out.append(s)
        return out

    def status(self):
        """Machine state and position, as a dict, or None if it cannot be read."""
        for line in self.send('{"sr":null}'):
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            sr = d.get("r", d).get("sr", d.get("sr"))
            if isinstance(sr, dict):
                return sr
        return None

    def wait_idle(self, timeout=120.0, settle=0.5):
        """Block until the machine reports a ready state.

        Polling the status report rather than counting on `ok`, because `ok`
        arrives when the planner accepts the move and the platform is still
        travelling at that point. Reading a position then gives the target, not
        where it is.
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            sr = self.status()
            if sr and sr.get("stat") in READY:
                time.sleep(settle)
                return True
            time.sleep(0.3)
        return False

    def move_to(self, z, feed=200.0, approach=None):
        """Absolute move to z in mm, always arriving from the same direction.

        A trapezoidal screw has backlash of a tenth of a millimetre or so, which
        is larger than everything else left in the measurement chain. Arriving
        from one side consistently removes it from the spacing, which is the
        quantity that has to be right. `approach` is how far past to overshoot
        before coming back; None disables it.
        """
        if not self.zmin <= z <= self.zmax:
            raise ValueError(f"z {z} utanfor {self.zmin}-{self.zmax} mm")
        self.send("G21 G90")
        if approach:
            over = z - abs(approach)
            if over >= self.zmin:
                self.send(f"G1 Z{over:.4f} F{feed:.0f}")
                self.wait_idle()
        self.send(f"G1 Z{z:.4f} F{feed:.0f}")
        ok = self.wait_idle()
        self.power_off()
        return ok

    def power_off(self):
        """Release the motors. The screw holds; the coil would only make heat."""
        self.send('{"1pm":3}')
        self.send('{"md":0}')      # motor disable, ignored on firmware without it

    def zero_here(self):
        """Call the present position Z0 without homing.

        No endstops needed: the model's offset absorbs wherever this happens to
        be, so a caliper reading at one height is all the absolute reference the
        calibration ever wants.
        """
        return self.send("G28.3 Z0")

    def travel_per_rev(self, value=None):
        if value is None:
            return self.send('{"1tr":null}')
        return self.send(json.dumps({"1tr": round(float(value), 4)}))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--to", type=float, metavar="MM", help="absolute move")
    p.add_argument("--feed", type=float, default=200.0, help="mm/min")
    p.add_argument("--approach", type=float, default=3.0,
                   help="overshoot this far and come back, so every height is "
                        "reached from the same side and the backlash drops out "
                        "of the spacing. 0 disables.")
    p.add_argument("--zmin", type=float, default=0.0)
    p.add_argument("--zmax", type=float, default=200.0)
    p.add_argument("--status", action="store_true")
    p.add_argument("--zero-here", action="store_true")
    p.add_argument("--travel-per-rev", type=float, metavar="MM",
                   help="set $1tr. Calibrate it: command a long move, measure "
                        "what actually happened with a caliper, and scale the "
                        "current value by measured/commanded.")
    args = p.parse_args()

    try:
        st = Stage(args.port, args.baud, zmin=args.zmin, zmax=args.zmax)
    except Exception as e:                      # noqa: BLE001 -- report and stop
        print(f"kan inte oppna {args.port}: {e}")
        print("  OTG-adapter isatt? 'dmesg | tail' ska visa ftdi_sio och ttyUSB")
        return 1

    if args.travel_per_rev is not None:
        for l in st.travel_per_rev(args.travel_per_rev):
            print(l)
        return 0
    if args.zero_here:
        for l in st.zero_here():
            print(l)
        print("denna position ar nu Z0")
        return 0
    if args.to is not None:
        ok = st.move_to(args.to, args.feed,
                        args.approach if args.approach > 0 else None)
        print("framme" if ok else "** TIMEOUT, maskinen rapporterade aldrig klar **")
        if not ok:
            return 1

    sr = st.status()
    print(json.dumps(sr, indent=2) if sr else
          "ingen statusrapport -- ar $ej satt till JSON?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
