#!/usr/bin/env python3
"""Restart a stalled calibration night. A watchdog for `af_calibrate --session`.

The service has one; the calibration session does not, and the difference cost
a night on 2026-09-07. The failure is quiet: the camera stops delivering
frames, the process stays alive, the HTTP server keeps answering, and nothing
says anything is wrong. It happened again at 01:05 on 2026-09-12 -- the
service's watchdog caught it after seventeen minutes and systemd restarted it.

A session has no such cover. `autocal.py` keeps asking for points, every AF
cycle times out, and each point writes a row with an empty mean -- so the file
grows all night and contains nothing.

**Watch for valid rows, not for rows.** A stalled camera still produces rows.
What stops is rows with a measurement in them.

    python3 afwatch.py --session af4.csv --stale 20 \\
        --af "python3 af_calibrate.py --session af4.csv --request GO ..." \\
        --cal "python3 autocal.py --d0 27.4 ..."

Restarting costs the thermal equilibrium: `af_calibrate` warms up again, which
is twenty minutes and a discontinuity in the drift the reference height is
measuring. That is a real cost, and it is still far better than eight hours of
empty rows -- and the reference height is revisited often enough that a
restart shows up as a step rather than corrupting the fit silently.

⚠️ Written at two in the morning against a running experiment, and the restart
path is necessarily untested against a real stall. The detection path is
testable and was checked against a healthy session before this was started.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
import time


def last_good(path, since=None):
    """Timestamp of the newest row that actually carries a measurement.

    The session CSV is `tid,t_s,d_mm,medel_dpt,...`, and a point that failed
    writes the row with medel_dpt empty. Returns None if the file has no valid
    row at all, which is also the state during warm-up -- so the caller must
    not treat "no valid row" as a stall until it has seen one.

    ⚠️ `since` is not optional in practice, and leaving it out destroyed most of
    the night of 2026-09-18. The file accumulates sessions: a restart appends to
    the same CSV. Without a lower bound the newest valid row was `01:17:18` from
    a session that had already been killed by hand, so a freshly started
    warm-up looked fifty minutes stale and was killed -- three times, until the
    restart budget ran out. **Staleness has to be measured against the session
    now running, not against whatever the file happens to remember.**
    """
    newest = None
    try:
        with open(path) as fh:
            for ln in fh:
                if ln.startswith("#") or not ln.strip():
                    continue
                f = ln.split(",")
                if len(f) < 4 or not f[3].strip():
                    continue
                try:
                    ts = dt.datetime.strptime(f[0], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    continue
                if since is not None and ts < since:
                    continue
                if newest is None or ts > newest:
                    newest = ts
    except FileNotFoundError:
        return None
    return newest


def running(pattern):
    """PIDs matching `pattern`, never this process or its parent.

    `pkill -f` was the obvious thing and it was wrong: this watchdog carries
    the commands it supervises as its own arguments, so its command line
    contains both `autocal.py` and `af_calibrate.py`. `pkill -f "[a]utocal.py"`
    therefore matched the watchdog itself and killed it on its first action,
    before it had restarted anything -- the same trap that bit three times from
    an ssh command line two days earlier, and the code carried a comment
    claiming it did not apply.

    The bracket protects a pattern from matching *itself*. It does nothing
    about the same text appearing elsewhere on the line.
    """
    me = {os.getpid(), os.getppid()}
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(x) for x in out.stdout.split() if x.isdigit() and int(x) not in me]


def kill(pattern, log):
    pids = running(pattern)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    log(f"  dodade {pattern}: {pids or 'inget att doda'}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", required=True, help="CSV af_calibrate appends to")
    p.add_argument("--af", required=True, help="command line that starts af_calibrate")
    p.add_argument("--cal", required=True, help="command line that starts autocal")
    p.add_argument("--af-log", default="af4.log")
    p.add_argument("--cal-log", default="autocal.out")
    p.add_argument("--stale", type=float, default=20.0,
                   help="minutes without a valid row before restarting. Must "
                        "comfortably exceed the visit interval plus the time a "
                        "measurement takes.")
    p.add_argument("--warmup-wait", type=float, default=45.0,
                   help="minutes to allow for the warm-up after a restart")
    p.add_argument("--max-restarts", type=int, default=3,
                   help="give up after this many, rather than loop all night "
                        "against hardware that is actually broken")
    p.add_argument("--log", default="afwatch.log")
    args = p.parse_args()

    fh = open(args.log, "a", buffering=1)

    def log(msg):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}  {msg}"
        print(line, flush=True)
        fh.write(line + "\n")

    log(f"vakthund igang: {args.session}, stale {args.stale:.0f} min")
    restarts = 0
    seen_any = False
    # Rows older than this belong to a session that is no longer running, and
    # must not count as evidence that this one is alive -- nor as evidence that
    # it is stale. Reset on every restart, for the same reason.
    baseline = dt.datetime.now()

    while True:
        time.sleep(60)
        # A finished schedule looks exactly like a stalled camera from the
        # file alone: no new valid rows. It is not a fault, and restarting a
        # healthy session throws away an hour of thermal equilibrium for
        # nothing. Ask whether the thing that requests measurements is still
        # alive before concluding anything from their absence.
        if not running("autocal.py"):
            log("autocal kor inte langre -- schemat klart eller avbrutet, "
                "slutar bevaka")
            return 0
        good = last_good(args.session, since=baseline)
        if good is None:
            # Still warming up, or restarted and not yet measuring. Never treat
            # this as a stall: there is nothing to be stale relative to.
            continue
        seen_any = True
        age = (dt.datetime.now() - good).total_seconds() / 60.0
        if age < args.stale:
            continue

        log(f"** ingen giltig matning pa {age:.0f} min (grans {args.stale:.0f}) **")
        if restarts >= args.max_restarts:
            log(f"   {restarts} omstarter redan gjorda -- ger upp, "
                f"nagot ar fel pa riktigt")
            return 1
        restarts += 1
        log(f"   omstart {restarts}/{args.max_restarts}")

        kill("[a]utocal.py", log)
        time.sleep(3)
        kill("[a]f_calibrate.py", log)
        time.sleep(8)

        marker = f"=== omstartad av afwatch {time.strftime('%H:%M:%S')} ==="
        with open(args.af_log, "a") as x:
            x.write("\n" + marker + "\n")
        baseline = dt.datetime.now()
        subprocess.Popen(f"setsid nohup {args.af} >>{args.af_log} 2>&1 &",
                         shell=True, start_new_session=True)
        log("   af_calibrate startad, vantar pa uppvarmning")

        # The restart appends to af_log, so the previous session's own
        # "vantar pa GO" is still sitting in the tail of the file. Reading the
        # last few kB therefore declared the warm-up complete twenty seconds
        # after a restart, every time, and autocal was started against a camera
        # that had just been switched on. Read only what was written after this
        # restart's marker.
        deadline = time.time() + args.warmup_wait * 60
        ready = False
        while time.time() < deadline:
            time.sleep(20)
            try:
                txt = open(args.af_log).read()
                cut = txt.rfind(marker)
                if cut >= 0 and "vantar pa" in txt[cut + len(marker):]:
                    ready = True
                    break
            except OSError:
                pass
        if not ready:
            log("   ** uppvarmningen blev aldrig klar -- startar autocal anda **")
        else:
            log("   uppvarmning klar")

        subprocess.Popen(f"setsid nohup {args.cal} >>{args.cal_log} 2>&1 &",
                         shell=True, start_new_session=True)
        log("   autocal startad")
        # Let the new run get a measurement in before judging it again.
        time.sleep(args.stale * 60)


if __name__ == "__main__":
    sys.exit(main())
