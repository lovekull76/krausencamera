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
that reduces the whole distance calibration to one number, `$3tr` (travel per
revolution), which is calibrated once over a long move with a caliper: 0.1 mm
of caliper error over 150 mm is 0.07 % of scale. The folding rule was 0.5 mm
out, systematically, at every height.

Hardware, from the Synthetos documentation for v8 / firmware 0.97:

    logic inputs   3.3 V MAX -- the Pi's GPIO level, so no level shifting
    USB            FTDI, 115200 default (9600-230400)
    motors         12-30 V, TI DRV8818, 2.5 A/winding, microstepping to 1/8
    $3pm           0 off, 1 always, 2 in cycle, 3 only while moving
                   (motor 3 is mapped to Z on this board: $3ma=2)
    $mt            seconds before motor power is released

`$3pm=3` is what this tool assumes: the coil is dead the moment the move ends.
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
    def __init__(self, port, baud=115200, timeout=2.0, zmin=0.0, zmax=200.0,
                 motor=3):
        import serial                       # pyserial, apt: python3-serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.zmin, self.zmax = zmin, zmax
        # Which driver the Z axis is wired to. On this board motor 3 is mapped
        # to axis 2 (Z) -- $3ma=2 -- so the power-management setting to write
        # is $3pm, not $1pm. Getting this wrong silently leaves the coil live.
        self.motor = motor
        time.sleep(2.0)                     # FTDI settling; the board may reboot
        self.ser.reset_input_buffer()
        # Silence the unsolicited reports. They are useful to a GUI watching a
        # job run and actively harmful to a script that asks a question and
        # expects the next line to be the answer.
        self.send("$sv=0")
        self.send("$qv=0")
        self.reset()

    def reset(self):
        """Start from a known state: stop, empty the queue, clear any alarm.

        In that order, and the order matters. A soft-limit violation latches an
        alarm and every later command is refused with status 203 -- including
        `G21 G90`, which makes it look like the board has died rather than that
        it is holding a grudge. Clearing the alarm then releases whatever is
        still queued, so an innocent-looking `$clear` can set the machine moving
        through a backlog. Flush first, clear second.
        """
        self.ser.write(b"!")            # feedhold
        self.ser.flush()
        time.sleep(0.3)
        self.ser.write(b"%")            # flush the planner queue
        self.ser.flush()
        time.sleep(0.3)
        self.send("$clear")
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
        """Machine state and position, as a dict, or None if it cannot be read.

        The input buffer is dropped first. TinyG emits status reports unasked --
        $sv sets the verbosity and $si the interval -- so whatever is sitting in
        the buffer is a report from some earlier moment, quite possibly from
        mid-move. Reading that as the answer to a fresh query returns a stale
        position, and worse, a stale `stat` makes wait_idle() believe a move has
        finished while the platform is still travelling. Seen for real: a
        commanded return to Z0 reported posz 2.0.
        """
        self.ser.reset_input_buffer()
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
        # Position only means anything once stat says the machine has stopped:
        # during a move the report carries the planner's position, which runs
        # ahead of the platform. Reading it mid-flight showed -7.6 on a move
        # whose target was -5.
        t0 = time.time()
        while time.time() - t0 < timeout:
            sr = self.status()
            if sr and sr.get("stat") in READY:
                time.sleep(settle)
                return True
            time.sleep(0.3)
        return False

    def move_to(self, z, feed=200.0, approach=None):
        """Absolute move to z in mm, always arriving from below.

        +Z is downward on this rig, away from the lid-mounted camera, so
        "from below" means overshooting to a *larger* Z and finishing with an
        upward move.

        These screws have backlash of a tenth of a millimetre or so, larger than
        everything else left in the measurement chain, so every height has to be
        reached the same way or the spacing carries it.

        > I first argued the opposite: that gravity preloads the nut against one
        > flank, so the approach direction cannot matter, and that finishing
        > upward would let the platform fall back through the backlash when the
        > coil releases. Love's answer is that friction in this mechanism is
        > considerably higher than the platform's weight -- so the nut is not
        > pressed against either flank, nothing settles when the power drops,
        > and consistency is the only thing that helps. The preload argument
        > needs a load, and there is not one here.
        """
        if not self.zmin <= z <= self.zmax:
            raise ValueError(f"z {z} utanfor {self.zmin}-{self.zmax} mm")
        self.send("G21 G90")
        if approach:
            over = z + abs(approach)
            if over <= self.zmax:
                self.send(f"G1 Z{over:.4f} F{feed:.0f}")
                self.wait_idle()
            else:
                print(f"  ** {over:.2f} over zmax {self.zmax} -- ingen underfart, "
                      f"punkten blir inte jamforbar med de andra **")
        self.send(f"G1 Z{z:.4f} F{feed:.0f}")
        ok = self.wait_idle()
        self.power_off()
        return ok

    def jog(self, a, b, cycles=6, feed=60.0):
        """Run back and forth so the current trimpot can be adjusted live.

        The pot is on the board, one per axis, and it cannot be set against a
        de-energised motor -- and with $3pm=3 the motor is dead the moment a
        move ends. So give it a long continuous travel to listen to: at 60
        mm/min a 40 mm leg lasts 40 seconds, which is enough to turn the pot
        and hear the result.

        Start the pot at 12 o'clock. It only travels 8 o'clock to 4, and it
        breaks if forced. Err low: this lifts a light plate slowly, not a heated
        bed, and every extra amp is heat a hand's width from the optics. A motor
        that hums without turning is too low -- that is the only signal worth
        turning it up for.
        """
        self.send("G21 G90")
        for i in range(cycles):
            for z in (a, b):
                if not self.zmin <= z <= self.zmax:
                    raise ValueError(f"z {z} utanfor {self.zmin}-{self.zmax} mm")
                print(f"  varv {i+1}/{cycles}  -> Z{z:.1f}", flush=True)
                self.send(f"G1 Z{z:.4f} F{feed:.0f}")
                self.wait_idle(timeout=600)
        self.power_off()

    def power_off(self):
        """Release the motor. The screw holds; the coil would only make heat."""
        self.send(f"${self.motor}pm=3")
        self.send("$md")           # motor disable, all axes

    def home(self, normalise=10.0, feed=60.0, timeout=180.0):
        """Home against the switch, then redefine Z0 with the usual approach.

        The switch sits at the top, which is both the reference and the end we
        keep crashing into. TinyG's own sequence is search, back off `$zlb`,
        latch back slowly at `$zlv`, then retreat `$zzb` and call that zero.

        **That last retreat is downward**, and every measurement height is
        reached going up. So Z0 alone would be defined against the other flank
        of the thread. A constant offset is harmless -- the focus model's offset
        absorbs it -- but it is a constant we do not need, and removing it costs
        two seconds: drop below zero and come back up to it, exactly as every
        other point is reached.

        Love spotted this; I had the whole sequence in front of me and read past
        it.
        """
        self.reset()
        self.send("$me")
        self.send("G21 G90")
        self.send("G28.2 Z0")
        if not self.wait_idle(timeout=timeout, settle=1.0):
            return False
        h = self.send('{"hom":null}')
        if not any('"z":1' in line for line in h):
            print("  ** hemningen rapporterar inte Z som hemmad **")
            return False
        if normalise:
            self.send(f"G1 Z{abs(normalise):.3f} F{feed*2:.0f}")
            self.wait_idle(timeout=timeout)
            self.send(f"G1 Z0 F{feed:.0f}")
            self.wait_idle(timeout=timeout)
        self.power_off()
        return True

    def zero_here(self):
        """Call the present position Z0 without homing.

        No endstops needed: the model's offset absorbs wherever this happens to
        be, so a caliper reading at one height is all the absolute reference the
        calibration ever wants.
        """
        return self.send("G28.3 Z0")

    def travel_per_rev(self, value=None):
        if value is None:
            return self.send(f"${self.motor}tr")
        return self.send(f"${self.motor}tr={float(value):.4f}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--to", type=float, metavar="MM", help="absolute move")
    p.add_argument("--feed", type=float, default=200.0, help="mm/min")
    p.add_argument("--approach", type=float, default=3.0,
                   help="overshoot this far past the target and come back "
                        "up, so every height is reached from below and the "
                        "backlash drops out of the spacing. 0 disables.")
    p.add_argument("--zmin", type=float, default=0.0)
    p.add_argument("--zmax", type=float, default=200.0)
    p.add_argument("--motor", type=int, default=3,
                   help="which driver the Z axis is wired to ($Nma=2)")
    p.add_argument("--jog", nargs=2, type=float, metavar=("A", "B"),
                   help="run between two heights so the current trimpot can be "
                        "set against a moving motor")
    p.add_argument("--cycles", type=int, default=6)
    p.add_argument("--status", action="store_true")
    p.add_argument("--home", action="store_true",
                   help="home against the switch, then redefine Z0 by "
                        "approaching it from below like every other height")
    p.add_argument("--zero-here", action="store_true")
    p.add_argument("--travel-per-rev", type=float, metavar="MM",
                   help="set $3tr. Calibrate it: command a long move, measure "
                        "what actually happened with a caliper, and scale the "
                        "current value by measured/commanded.")
    args = p.parse_args()

    try:
        st = Stage(args.port, args.baud, zmin=args.zmin, zmax=args.zmax,
                   motor=args.motor)
    except Exception as e:                      # noqa: BLE001 -- report and stop
        print(f"kan inte oppna {args.port}: {e}")
        print("  OTG-adapter isatt? 'dmesg | tail' ska visa ftdi_sio och ttyUSB")
        return 1

    if args.travel_per_rev is not None:
        for l in st.travel_per_rev(args.travel_per_rev):
            print(l)
        return 0
    if args.home:
        ok = st.home()
        print("hemmad och normaliserad" if ok else "** HEMNINGEN MISSLYCKADES **")
        sr = st.status()
        if sr:
            print(f"  Z = {sr.get('posz')}")
        return 0 if ok else 1
    if args.zero_here:
        for l in st.zero_here():
            print(l)
        print("denna position ar nu Z0")
        return 0
    if args.jog:
        print("svep igang -- justera potentiometern for motor 3 nu")
        print("  borja pa klockan 12, vrid medurs bara om den brummar utan att ga")
        st.jog(args.jog[0], args.jog[1], args.cycles, args.feed)
        print("svep klart, motorn stromlos")
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
