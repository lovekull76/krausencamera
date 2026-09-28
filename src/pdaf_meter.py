#!/usr/bin/env python3
"""Measure the surface with phase-detect autofocus, inside the service.

Replaces the laser ranging in `focus_tracker.py`, whose constants are void. It
runs in the process that owns the camera -- the live view -- and every
`interval_s` takes one point exactly the way the calibration nights did.

**Parity with the calibration is the whole design.** Every constant in the
model file was measured under one set of conditions, and each difference found
so far cost a millimetre or more before it was understood:

- *the same code*: `pick_exposure` and `take_point` are imported from
  `af_calibrate`, not reimplemented -- two AF cycles parked low then high,
  railed readings rejected, the lens parked at 0 dpt afterwards;
- *30 fps throughout*: exposures stop at 32 ms, and the live view's frame
  duration must be capped at 33.3 ms too (`--max-frame-duration-us 33333`).
  A slower frame cools the sensor and moved the next reading 24 mdpt
  (2026-09-23). With the lamp off and auto exposure opening up, the live view
  would otherwise sit at 24 fps between measurements;
- *the lamp lit continuously*: the calibration held it for the whole session,
  and it sits in the lid, whose temperature moves the reading 1.6 mm/C.
  Switching it with the viewer count would put a lid temperature into service
  that the table never saw;
- *the lens parked between measurements*: the VCM's holding current heats the
  module, 0.96 C per dioptre (2026-09-12).

The one deliberate exception is a viewer. Someone watching wants a sharp
picture, so while anyone is connected the lens holds the last measured focus,
and it parks again when the last viewer leaves. That is logged, and the
measurement itself always starts from its own parking pattern regardless.

**What it reports.** Distance to the surface from the lid's underside, through
the model file `afmodell.py` writes; krausen height as the zero minus that, the
zero being the distance stored when the tank was filled. The model's offset
drifts between nights by a few millimetres, so the absolute distance is only as
good as that -- the height, being a difference, is not affected.

A reading that rails at 15.0 dpt is not an error: the surface is nearer than
~25 mm, inside the neck, and that is reported as its own state. Readings beyond
the fitted range are reported but flagged, since the hyperbola does not carry
them. For the first `settle_min` minutes after start the camera is still warming
and every reading is flagged as such.

The lid's temperature is logged with each point but not yet used: the
coefficient belongs to the build, and the sensor that will carry it goes into
the aluminium plate of the next housing.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import os
import re
import threading
import time
from types import SimpleNamespace

import numpy as np

log = logging.getLogger(__name__)

RAIL_DPT = 15.0


class Model:
    """`dpt = a + b/(d + c)` from a file written by afmodell.py."""

    def __init__(self, path: str) -> None:
        self.path = path
        text = open(path).read()
        m = re.search(r"dpt\s*=\s*([-\d.]+)\s*\+\s*([-\d.]+)\s*/\s*\(d\s*\+\s*([-\d.]+)\)", text)
        if not m:
            raise ValueError(f"no model line in {path}")
        self.a, self.b, self.c = (float(x) for x in m.groups())
        fm = re.search(r"hojder <= ([\d.]+) mm", text)
        self.fit_max = float(fm.group(1)) if fm else float("inf")
        # Corrections, only where the file says they reproduce.
        self.corr_d, self.corr_mm = [], []
        for row in csv.DictReader(l for l in text.splitlines() if l and not l.startswith("#")):
            if row.get("tillampa_korrektion") == "ja":
                self.corr_d.append(float(row["d_mm"]))
                self.corr_mm.append(float(row["korrektion_mm"]))

    def distance(self, dpt: float) -> float:
        d = self.b / (dpt - self.a) - self.c
        if self.corr_d:
            d += float(np.interp(d, self.corr_d, self.corr_mm))
        return d

    def dpt_for(self, d: float) -> float:
        return self.a + self.b / (d + self.c)


def read_ds18b20(sensor_id: str | None) -> float:
    if not sensor_id:
        return float("nan")
    try:
        with open(f"/sys/bus/w1/devices/{sensor_id}/temperature") as f:
            return int(f.read()) / 1000.0
    except Exception:
        return float("nan")


class PdafMeter:
    """Periodic PDAF measurement, frame A, and lens parking between them."""

    def __init__(self, picam2, lamp, *, model_path, interval_s=300.0,
                 restore_controls=None, snapshot_dir=None,
                 snapshot_interval_s=300.0, snapshot_exposure_us=15000,
                 zero_path="zero.json", log_dir="matningar",
                 lid_sensor=None, settle_min=75.0, lamp_always_on=True,
                 snapshot_quality=95, viewers=lambda: 0) -> None:
        from libcamera import controls
        import af_calibrate as afc

        self._picam2 = picam2
        self._controls = controls
        self._afc = afc
        self._lamp = lamp
        self.model = Model(model_path)
        self._interval = interval_s
        self._restore = dict(restore_controls or {"AeEnable": True})
        self._snap_dir = snapshot_dir
        self._snap_interval = snapshot_interval_s
        self._snap_exposure = snapshot_exposure_us
        self._snap_quality = snapshot_quality
        self._last_snap = 0.0
        self._zero_path = zero_path
        self._log_dir = log_dir
        self._lid_sensor = lid_sensor
        self._settle_s = settle_min * 60.0
        self._viewers = viewers
        self._t_start = time.time()
        self._cam = threading.Lock()
        # The calibration's own settings, and nothing else -- see the module
        # docstring. af_calibrate reads these off an argparse namespace.
        self._args = SimpleNamespace(
            runs=2, park_low=2.5, park_high=12.0, park_after=0.0,
            af_range=2, af_window=0, exposure_target=230.0,
            exposures=[1000, 2000, 4000, 8000, 15000, 25000, 32000])

        self.zero = self._load_zero()
        self.last: dict | None = None
        # Called with (reading, zero_mm) after every point and every new zero.
        self.listeners: list = []
        self.busy = False
        self.last_ok = time.time()
        self._fails = 0
        self._max_fails = 3
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        if snapshot_dir:
            os.makedirs(snapshot_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        self.lamp_always_on = False
        self.set_lamp_mode(lamp_always_on)
        log.info("model %s: dpt = %.4f + %.2f/(d + %.4f), fitted to %.0f mm, "
                 "%d corrections applied", model_path, self.model.a, self.model.b,
                 self.model.c, self.model.fit_max, len(self.model.corr_d))

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._park()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30.0)

    # -- lamp --------------------------------------------------------------

    # Seconds the lamp is lit before the first AF cycle when it is not held
    # on. Lamp.acquire() already waits for the LEDs to come up; this is for the
    # frames already in flight, which were exposed dark.
    LAMP_LEAD_S = 2.0

    def set_lamp_mode(self, always: bool) -> None:
        """Hold the lamp on continuously, or light it only to measure.

        Continuous matches the calibration nights. Measure-only is the lighter
        option, and whether the lamp's heat in the lid moves the reading is
        what the switch exists to find out (lamptest.sh). A viewer lights it
        either way through the page's own reference count.
        """
        if always and not self.lamp_always_on:
            self._lamp.acquire()
        elif not always and self.lamp_always_on:
            self._lamp.release()
        if always != self.lamp_always_on:
            log.info("IR lamp: %s", "held on continuously, as during calibration"
                     if always else "lit only to measure and for viewers")
        self.lamp_always_on = always

    # -- zero --------------------------------------------------------------

    def _load_zero(self) -> dict | None:
        try:
            with open(self._zero_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def set_zero(self) -> dict | None:
        """Store the last good distance as the fill level. Returns it."""
        if not self.last or self.last.get("status") not in ("ok", "uppvarmning"):
            return None
        z = {"d_mm": self.last["d_mm"], "dpt": self.last["dpt"],
             "tid": self.last["tid"], "lock_C": self.last["lock_C"]}
        with open(self._zero_path, "w") as f:
            json.dump(z, f)
        self.zero = z
        self.last["krausen_mm"] = 0.0
        log.info("zero set: %.2f mm (%.4f dpt) from the reading at %s",
                 z["d_mm"], z["dpt"], z["tid"])
        self._notify()
        return z

    def _notify(self) -> None:
        for f in self.listeners:
            try:
                f(self.last, None if not self.zero else self.zero["d_mm"])
            except Exception:
                log.exception("listener failed")

    # -- viewers -----------------------------------------------------------

    def on_viewers(self, n: int) -> None:
        """Focus for a watcher, park when nobody is. Never mid-measurement."""
        with self._cam:
            if n > 0 and self.last and self.last.get("dpt"):
                self._picam2.set_controls({"AfMode": 0, "LensPosition": float(self.last["dpt"])})
                log.info("viewer present: lens held at %.2f dpt (holding current "
                         "on -- the module warms while watched)", self.last["dpt"])
            elif n == 0:
                self._park()

    def _park(self) -> None:
        self._picam2.set_controls({"AfMode": 0, "LensPosition": self._args.park_after})

    # -- measurement -------------------------------------------------------

    def state(self) -> dict:
        s = dict(self.last or {})
        s["busy"] = self.busy
        s["lamp_always_on"] = self.lamp_always_on
        s["age_s"] = None if not self.last else round(time.time() - self.last["t"])
        s["zero_mm"] = None if not self.zero else self.zero["d_mm"]
        # names the page already knows
        s["distance_mm"] = s.get("d_mm")
        s["lens_position"] = s.get("dpt") or 0.0
        return s

    def measure(self) -> dict:
        afc, args, picam2 = self._afc, self._args, self._picam2
        quiet = io.StringIO()
        with self._cam:
            self.busy = True
            self._lamp.acquire()
            try:
                if not self.lamp_always_on:
                    time.sleep(self.LAMP_LEAD_S)
                dark = not self._lamp.is_lit
                # The live view runs auto exposure; pick_exposure only sets the
                # time, and with AE still on the request would be ignored.
                picam2.set_controls({"AeEnable": False, "AnalogueGain": 1.0})
                with contextlib.redirect_stdout(quiet):
                    exp_us, level = afc.pick_exposure(picam2, args)
                    lo, hi, seq, t0, t1 = afc.take_point(picam2, self._controls, args)
                if self._viewers() > 0 and seq:
                    picam2.set_controls({"AfMode": 0,
                                         "LensPosition": float(np.mean(lo + hi))})
            finally:
                picam2.set_controls(dict(self._restore))
                self._lamp.release()
                self.busy = False

        v = lo + hi
        now = time.time()
        lid = read_ds18b20(self._lid_sensor)
        r = {"t": now, "tid": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
             "n_ok": len(v), "n": args.runs, "sensor_C": t1, "exp_us": exp_us,
             "niva": round(level, 1) if level == level else None,
             "lock_C": None if lid != lid else round(lid, 3),
             "dpt": None, "sd": None, "d_mm": None, "krausen_mm": None}
        if len(v) >= 2:
            dpt = float(np.mean(v))
            d = self.model.distance(dpt)
            r.update(dpt=round(dpt, 5), sd=round(float(np.std(v, ddof=1)), 5),
                     d_mm=round(d, 2))
            if self.zero:
                r["krausen_mm"] = round(self.zero["d_mm"] - d, 2)
            if now - self._t_start < self._settle_s:
                r["status"] = "uppvarmning"
            elif d > self.model.fit_max:
                r["status"] = "utanfor_kalibrering"
            else:
                r["status"] = "ok"
        else:
            # take_point drops a railed cycle rather than returning it, so a
            # rail looks like a failure from here. Ask the lens where it went.
            # A viewer can force the lamp off from the page, and AF in the
            # dark converges on nothing -- the trap this project has fallen
            # into three times. Say so rather than calling it a failure.
            if dark:
                r["status"] = "morkt"
            else:
                r["status"] = "i_halsen" if self._railed() else "misslyckad"
        return r

    def _railed(self) -> bool:
        """One more AF cycle, only to ask whether the lens is at its stop."""
        c, picam2 = self._controls, self._picam2
        with self._cam, self._lamp.held():
            picam2.set_controls(self._afc.af_controls(c, self._args))
            picam2.set_controls({"AfTrigger": c.AfTriggerEnum.Start})
            t0, lp = time.time(), None
            while time.time() - t0 < 9.0:
                md = picam2.capture_metadata()
                lp = md.get("LensPosition")
                if md.get("AfState") in (2, 3):
                    break
            self._park()
        return lp is not None and abs(lp - RAIL_DPT) < 0.001

    def _write(self, r: dict) -> None:
        path = os.path.join(self._log_dir, f"matning-{r['tid'][:10].replace('-', '')}.csv")
        new = not os.path.exists(path)
        cols = ["tid", "status", "dpt", "sd", "n_ok", "n", "d_mm", "krausen_mm",
                "sensor_C", "lock_C", "exp_us", "niva"]
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                f.write(f"# modell {self.model.path}: dpt = {self.model.a} + "
                        f"{self.model.b}/(d + {self.model.c})\n")
                w.writeheader()
            w.writerow(r)

    def _snapshot(self, dpt: float | None) -> None:
        """Frame A: lamp lit, exposure locked, focused on the surface just
        measured -- then parked again unless someone is watching."""
        from PIL import Image
        picam2 = self._picam2
        with self._cam:
            self._lamp.acquire()
            try:
                ctl = {"AeEnable": False, "ExposureTime": self._snap_exposure,
                       "AnalogueGain": 1.0}
                if dpt:
                    ctl.update(AfMode=0, LensPosition=float(dpt))
                picam2.set_controls(ctl)
                time.sleep(1.6 if self.lamp_always_on else max(1.6, self.LAMP_LEAD_S))
                for _ in range(4):
                    picam2.capture_array("main")
                a = picam2.capture_array("main")
            finally:
                self._lamp.release()
                picam2.set_controls(dict(self._restore))
                if self._viewers() == 0:
                    self._park()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self._snap_dir, f"A-{stamp}.jpg")
        Image.fromarray(a[:, :, :3][:, :, ::-1]).save(path, quality=self._snap_quality)
        log.info("frame A -> %s (%.0f mean, focus %s)", os.path.basename(path),
                 a[:, :, :3].mean(), f"{dpt:.2f} dpt" if dpt else "parked")

    def _run(self) -> None:
        log.info("pdaf meter: a point every %.0f s, frame A every %.0f s; "
                 "readings flagged as warming for %.0f min", self._interval,
                 self._snap_interval, self._settle_s / 60)
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                r = self.measure()
                self.last = r
                self._write(r)
                self._notify()
                self._fails = 0
                self.last_ok = time.time()
                log.info("%s  %s dpt  -> %s mm%s  (%d/%d, sensor %s C, lid %s C, %s us)",
                         r["status"], r["dpt"], r["d_mm"],
                         f", krausen {r['krausen_mm']} mm" if r["krausen_mm"] is not None else "",
                         r["n_ok"], r["n"], r["sensor_C"], r["lock_C"], r["exp_us"])
                if self._snap_dir and time.monotonic() - self._last_snap >= self._snap_interval:
                    self._last_snap = time.monotonic()
                    try:
                        self._snapshot(r["dpt"])
                    except Exception:
                        log.exception("frame A failed")
            except Exception:
                self._fails += 1
                log.exception("measurement failed (%d in a row)", self._fails)
                if self._fails >= self._max_fails:
                    log.critical("camera has failed %d times in a row -- exiting "
                                 "so systemd can restart it", self._fails)
                    os._exit(17)
            self._stop.wait(max(0.0, self._interval - (time.monotonic() - t0)))
