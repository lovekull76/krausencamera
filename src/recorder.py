#!/usr/bin/env python3
"""Record the live stream to an MP4. Start, stop, a time cap.

Written for dry hops, but named for what it is -- `live_recording_<time>.mp4`
-- since anything worth watching in the tank can be filmed the same way.

The lores stream already feeds the live view through the MJPEG encoder. A
second encoder -- hardware H.264 -- is attached to the same stream for the
length of a recording, so the live view carries on untouched, and PyAV writes
the MP4 directly: no ffmpeg on the Pi, and nothing to remux afterwards.

**Written locally, never straight to the NAS.** A recording is minutes of
video arriving at 30 fps; a WiFi hiccup mid-file would lose it. It goes into
the batch's `video/` folder and `arkivsynk.sh` moves it on within ten minutes.

**The measurement is paused while it runs.** A measurement would show in the
film as focus hunting and an exposure jump, so the meter holds off -- at most
one point is missed at the five-minute cap -- the lens stays at the last
measured focus and the lamp stays lit. The first point afterwards is marked in
the log, since the lens has been powered for the length of the recording.

30 fps, the sensor's own rate: hops being drawn under by the agitator are
motion, and 10 fps films it as a stutter. About 4 Mbit/s, so 150 MB a
five-minute clip.
"""

from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, picam2, lamp, meter=None, *, video_dir, max_s=300.0,
                 bitrate=4_000_000) -> None:
        self._picam2 = picam2
        self._lamp = lamp
        self._meter = meter
        self._video_dir = video_dir          # callable -> folder to write into
        self.max_s = max_s
        self._bitrate = bitrate
        self._lock = threading.Lock()
        self._enc = None
        self._timer = None
        self.started: float | None = None
        self.path: str | None = None
        self.listeners: list = []            # called with the state dict

    @property
    def recording(self) -> bool:
        return self._enc is not None

    def state(self) -> dict:
        return {"recording": self.recording, "max_s": self.max_s,
                "elapsed_s": round(time.time() - self.started) if self.started else None,
                "file": os.path.basename(self.path) if self.path else None}

    def _notify(self) -> None:
        st = self.state()
        for f in self.listeners:
            try:
                f(st)
            except Exception:
                log.exception("recorder listener failed")

    def start(self) -> bool:
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import PyavOutput
        with self._lock:
            if self._enc is not None:
                return False
            if self._meter:
                self._meter.pause()           # waits for a measurement in progress
            self._lamp.acquire()
            folder = self._video_dir()
            os.makedirs(folder, exist_ok=True)
            self.path = os.path.join(folder, time.strftime("live_recording_%Y%m%d-%H%M%S.mp4"))
            enc = H264Encoder(bitrate=self._bitrate)
            try:
                self._picam2.start_encoder(enc, PyavOutput(self.path, format="mp4"), name="lores")
            except Exception:
                log.exception("recording failed to start")
                self._lamp.release()
                if self._meter:
                    self._meter.resume()
                return False
            self._enc = enc
            self.started = time.time()
            self._timer = threading.Timer(self.max_s, self._cap)
            self._timer.daemon = True
            self._timer.start()
        log.info("recording -> %s (stops by itself after %.0f s)", self.path, self.max_s)
        self._notify()
        return True

    def _cap(self) -> None:
        log.info("recording reached its %.0f s cap", self.max_s)
        self.stop()

    def stop(self) -> bool:
        with self._lock:
            if self._enc is None:
                return False
            if self._timer:
                self._timer.cancel()
            try:
                self._picam2.stop_encoder(self._enc)
            except Exception:
                log.exception("stopping the encoder failed")
            took = time.time() - self.started
            self._enc = None
            self.started = None
            self._lamp.release()
            if self._meter:
                self._meter.resume()
        size = os.path.getsize(self.path) / 1e6 if os.path.exists(self.path) else 0
        log.info("recording stopped: %s, %.0f s, %.0f MB", os.path.basename(self.path), took, size)
        self._notify()
        return True
