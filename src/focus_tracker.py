#!/usr/bin/env python3
"""Measure distance with the laser and hold the focus there.

Runs inside whichever process owns the camera, because only one can. It takes
the controls for a moment, does its measurement, and hands them back:

    force the illumination off      the dot must be the only bright thing
    laser on, short exposure        it saturates at anything longer
    grab, find the dot, compute d
    laser off, restore              exposure and illumination as they were
    refocus if d has moved enough

**Why the focus can come from a formula.** Measured over four target positions
from 80 to 180 mm, `dpt = 0.440 + 801/(d − 19.95)` holds to ±0.27 mm. The
triangulation could not be modelled that well — 1.5 mm — which is why distance
still wants the measured table, but focus does not.

**Why there is a threshold.** Depth of field is about 2.4 dioptres wide at the
80 % criterion, so refocusing on every reading would work the actuator forty
thousand times a fortnight for no gain. Moving when the target has drifted half
the depth of field costs a handful of moves per batch.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

REC601 = np.array([0.299, 0.587, 0.114], dtype=np.float32)

# Laser geometry for this build, from four target positions 2026-09-07.
# dx = X_PP + K / (d + C), distances to the housing face.
X_PP, K_LASER, C_LASER = 64.0, 16782.0, -6.38
# Focus, same positions: dpt = F_OFF + F_K / (d + F_C)
F_OFF, F_K, F_C = 0.440, 801.0, -19.95

# Focus breathing couples the two. The calibration above was taken with
# LensPosition hardcoded to 7.7 for every position, so the model is only
# valid at that focus -- and autofocus, by construction, leaves it. Measured
# at 108 mm over 7.0-11.0 dpt: the dot moves 0.68 %/dioptre, repeatable to
# 0.04 px, which independently reproduces the 0.72 %/dpt measured optically.
# Uncorrected that is 3.8 mm of distance error across the focus range, far
# more than the measurement is trying to resolve. Multiplicative rather than
# a fixed pixel offset because breathing is a change of magnification: the
# shift has to scale with dx, which is only verified at this one distance.
LENS_REF = 7.7
BREATHING_PER_DPT = 0.0068


def normalise_dx(dx: float, lens_position: float) -> float:
    """dx as it would have been seen at the focus the model was fitted at."""
    return dx / (1.0 + BREATHING_PER_DPT * (lens_position - LENS_REF))


def distance_for(dx: float, lens_position: float = LENS_REF) -> float | None:
    """Object distance from the dot's horizontal offset, or None if impossible."""
    dx = normalise_dx(dx, lens_position)
    if dx <= X_PP:
        return None
    return K_LASER / (dx - X_PP) - C_LASER


def focus_for(distance_mm: float) -> float:
    return F_OFF + F_K / (distance_mm + F_C)


class FocusTracker:
    """Periodic laser ranging, with the focus following at a threshold."""

    def __init__(self, picam2, illumination, laser, *, size,
                 interval_s=60.0, laser_exposure_us=8000,
                 threshold_dpt=1.2, band_y=None, band_halfwidth=60.0,
                 min_dx=100.0, max_dx=450.0, min_peak=20.0,
                 restore_controls=None, settle_s=1.4, initial_lens=7.1):
        self._picam2 = picam2
        self._ir = illumination
        self._laser = laser
        self._w, self._h = size
        self._interval = interval_s
        self._exposure = laser_exposure_us
        self._threshold = threshold_dpt
        # The dot rides a horizontal line whose height is set by where the
        # camera sits in its mount, not by the optics -- measured to move 50-70
        # um between mountings. Established at startup rather than hardcoded.
        self._band_y = band_y
        self._halfwidth = band_halfwidth
        self._min_dx, self._max_dx = min_dx, max_dx
        self._min_peak = min_peak
        # Everything measure() perturbs has to be put back, not just the
        # exposure: FrameDurationLimits bounds exposure, so restoring one
        # without the other silently caps the live view's next frame.
        self._restore = dict(restore_controls or {"AeEnable": True})
        self._settle = settle_s

        self.distance_mm: float | None = None
        # Not None: the very first reading is taken at whatever focus the
        # camera was started with, and needs correcting for it like any other.
        self.lens_position: float = initial_lens
        self.last_dx: float | None = None
        self.last_peak: float | None = None
        self.spread_px: float | None = None
        self.updated_at: float | None = None

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def state(self) -> dict:
        return {
            "distance_mm": None if self.distance_mm is None else round(self.distance_mm, 1),
            "lens_position": self.lens_position,
            "dx": None if self.last_dx is None else round(self.last_dx, 2),
            "peak": self.last_peak,
            "spread_px": self.spread_px,
            "age_s": None if self.updated_at is None else round(time.time() - self.updated_at),
        }

    # -- measurement -------------------------------------------------------

    def _grab(self, discard: int = 4) -> np.ndarray:
        """A 2D brightness plane, whatever the stream format happens to be.

        The main stream is XBGR8888 here, so it arrives with four channels;
        a YUV420 stream would arrive as one plane with chroma stacked below.
        Rec.601 weights reproduce the Y plane the model was fitted on to
        0.002 px -- measured, along with an equal average at 0.014 and the
        channels reversed at 0.027. At 850 nm all three Bayer filters pass
        about equally, so the weighting barely matters; it costs nothing to
        match anyway, and reading XBGR leaves the live view its own colour.
        """
        for _ in range(discard):
            self._picam2.capture_array("main")
        a = self._picam2.capture_array("main")
        if a.ndim == 3:
            return a[:, :, :3].astype(np.float32) @ REC601
        return a[:self._h].astype(np.float32)

    def _find_dot(self, diff: np.ndarray):
        """Brightest spot inside the band, ignoring the ghost and the tube edge.

        Both of those have been measured brighter than the real return, so the
        search is bounded rather than won on brightness.
        """
        yy, xx = np.mgrid[0:self._h, 0:self._w]
        adx = np.abs(xx - self._w / 2.0)
        mask = (adx > self._min_dx) & (adx < self._max_dx)
        if self._band_y is not None:
            mask &= np.abs(yy - self._h / 2.0 - self._band_y) < self._halfwidth
        work = np.where(mask, diff, 0.0)
        peak = float(work.max())
        if peak < self._min_peak:
            return None
        y0, x0 = np.unravel_index(int(np.argmax(work)), work.shape)
        near = (xx - x0) ** 2 + (yy - y0) ** 2 <= 70 * 70
        blob = near & (diff >= 0.25 * peak)
        w = diff[blob]
        cx = float((xx[blob] * w).sum() / w.sum())
        cy = float((yy[blob] * w).sum() / w.sum())
        r = np.hypot(xx[blob] - cx, yy[blob] - cy)
        return {"cx": cx, "cy": cy, "peak": peak,
                "dx": cx - self._w / 2.0, "dy": cy - self._h / 2.0,
                "spread": float(r.max()) if r.size else 0.0}

    def measure(self):
        """One ranging cycle. Returns the spot dict, or None."""
        picam2 = self._picam2
        # Frame B's conditions: illumination held off so the dot is alone, and
        # an exposure sixty times shorter than frame A's -- the dot saturated
        # from 12 ms down to 800 us when it was measured.
        with self._ir.forced_off():
            picam2.set_controls({"AeEnable": False,
                                 "ExposureTime": self._exposure,
                                 "AnalogueGain": 1.0})
            time.sleep(self._settle)
            # force_off, not shutdown: a viewer may be holding the laser on
            # from the web UI, and the reference count has to survive this.
            with self._laser.forced_off():
                time.sleep(0.3)
                dark = self._grab()
            self._laser.acquire()
            try:
                time.sleep(0.3)
                lit = self._grab()
            finally:
                self._laser.release()
            spot = self._find_dot(lit - dark)

        picam2.set_controls(dict(self._restore))
        return spot

    def _apply(self, spot) -> None:
        d = distance_for(spot["dx"], self.lens_position)
        if d is None or not (30.0 < d < 2000.0):
            log.warning("laser range: dx=%.1f gives an implausible %s -- ignored",
                        spot["dx"], "None" if d is None else f"{d:.0f} mm")
            return
        self.distance_mm = d
        self.last_dx = spot["dx"]
        self.last_peak = round(spot["peak"])
        self.spread_px = round(spot["spread"], 1)
        self.updated_at = time.time()

        want = focus_for(d)
        if abs(want - self.lens_position) > self._threshold:
            self._picam2.set_controls({"AfMode": 0, "LensPosition": float(want)})
            log.info("range %.1f mm (dx=%.2f at %.2f dpt -> %.2f normalised, "
                     "spread %.0f px) -> focus %.2f dpt, moved %+.2f",
                     d, spot["dx"], self.lens_position,
                     normalise_dx(spot["dx"], self.lens_position),
                     spot["spread"], want, want - self.lens_position)
            self.lens_position = want
        else:
            log.info("range %.1f mm (dx=%.2f at %.2f dpt -> %.2f normalised) -> "
                     "focus %.2f dpt, within %.1f, holding",
                     d, spot["dx"], self.lens_position,
                     normalise_dx(spot["dx"], self.lens_position),
                     want, self._threshold)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                spot = self.measure()
                if spot is None:
                    log.warning("laser range: no spot in the band")
                else:
                    self._apply(spot)
            except Exception:
                log.exception("laser range failed")
            self._stop.wait(self._interval)
