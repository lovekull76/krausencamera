#!/usr/bin/env python3
"""HTTP live view for the krausen camera.

Open http://krausencamera:8080/ in any browser. The IR illumination switches
on when the first viewer connects and off when the last one disappears.

The camera is configured once and never reconfigured -- switching modes forces
a sensor reconfiguration and is the only genuinely slow operation. A single
video configuration carries two streams out of the same sensor mode:

    main   2304x1296  -- measurement frames (2x2 binned, 4x signal per pixel)
    lores   768x432   -- the web view, a fraction of the encoding work

Exposure, white balance and focus are locked. This is not cosmetic: the
automatics would otherwise compensate away exactly the brightness change that
is to be measured as the krausen builds, leaving the time series useless for
automated analysis. Exposure is automatic here; the measurement cycle sets
its own locked state before it captures. --auto-wb additionally unlocks the
white balance, which is only useful when aiming in visible light.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import socketserver
import sys
import threading
import time
from http import server
from urllib.parse import parse_qs, urlparse

from illumination import Lamp
from focus_tracker import FocusTracker

log = logging.getLogger("liveview")

MAIN_SIZE = (2304, 1296)
# 1280x720 so a dry-hop recording is 720p. Both dimensions are multiples of 16
# (see --lores). af_calibrate uses the same, so a calibration is taken under
# the configuration the service runs.
LORES_SIZE = (1280, 720)

# The sensor delivers 30 fps. Watching whether anything is happening at all
# needs a small fraction of that; watching hops being drawn under by the
# agitator during a dry hop needs the lot. So the rate is chosen per viewer
# rather than fixed, and the frames not sent are simply dropped -- the encoder
# runs at sensor rate regardless.
# 24 rather than 30 as the top preset: at the ~37 ms exposure a stopped-down
# lens needs, a frame cannot be shorter than 37 ms, so the sensor tops out near
# 26 fps. A 30 preset would quietly deliver 26. 24 is the highest round number
# the camera can actually honour, so the number chosen is the number delivered.
FPS_PRESETS = [(2, "Low"), (10, "Mid"), (24, "High")]
FPS_MAX = 30

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Krausen camera</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; background: #111; color: #ddd;
         font: 14px system-ui, sans-serif; display: flex;
         flex-direction: column; align-items: center; gap: .75rem; padding: 1rem; }
  img { max-width: 100%; height: auto; border-radius: 4px; background: #000; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; justify-content: center; }
  button { font: inherit; padding: .5rem .9rem; border-radius: 999px; cursor: pointer;
           border: 1px solid #444; background: #1c1c1c; color: #ccc; }
  .rates button.on { background: #ddd; color: #111; border-color: #ddd; }
  .hw button.on { background: #2e7d32; border-color: #2e7d32; color: #fff; }
  .nav { position: absolute; top: 1rem; right: 1rem; font-size: 13px; }
  .nav a { color: #e0a33a; text-decoration: none; border: 1px solid #444;
           border-radius: 999px; padding: .35rem .8rem; background: #1c1c1c; }
  body { position: relative; }
  .hw button.rec { color: #e57373; }
  .hw button.rec.on { background: #c62828; border-color: #c62828; color: #fff; }
  .focus { margin-left: 0.8em; opacity: 0.75; font-variant-numeric: tabular-nums; }
  .meta { opacity: .6; font-variant-numeric: tabular-nums; text-align: center; }
</style>
</head>
<body>
  <nav class="nav"><a href="{archive}">Archive &rarr;</a></nav>
  <img src="" alt="Live view from the krausen camera">
  <div class="row rates">{buttons}</div>
  <div class="row hw">
    <button id="led">IR</button>
    <span id="focus" class="focus"></span>
    <span id="exp" class="focus"></span>
  </div>
  <div class="row hw" id="zerorow" hidden>
    <button id="rec" class="rec">&#9679; REC</button>
    <button id="batch">Start new batch</button>
    <button id="zero">Set zero at fill level</button>
    <span id="zeroinfo" class="focus"></span>
  </div>
  <div class="meta"></div>
<script>
  const img = document.querySelector("img");
  const meta = document.querySelector(".meta");
  // scoped to .rates -- the hardware toggles are buttons too
  const rateButtons = [...document.querySelectorAll(".rates button")];
  const led = document.getElementById("led");
  const focus = document.getElementById("focus");
  const exp = document.getElementById("exp");

  let currentFps = 0;
  function setFps(n) {
    currentFps = n;
    // Abort the previous stream before starting the next one. Changing img.src
    // on a multipart stream leaves the old connection open but unread: the
    // server fills its send buffer, blocks, and only drops it after
    // --stream-timeout. A few quick changes exhaust the browser's six
    // connections per host and the image freezes on its last painted frame.
    img.removeAttribute("src");
    // A token as well, so re-selecting a rate is never a no-op assignment.
    img.src = "/stream.mjpg?fps=" + n + "&t=" + Date.now();
    rateButtons.forEach(b => b.classList.toggle("on", +b.dataset.fps === n));
    // No bandwidth estimate: it was a constant calibrated for one resolution
    // and silently became wrong by 3x when the stream grew. A stale number
    // reads as information.
    meta.textContent = "{w}\u00d7{h} \u00b7 " + n + " fps \u00b7 "
      + "IR illumination follows the viewer count unless overridden below";
    lastFps = n;
    try { localStorage.setItem("fps", n); } catch (e) {}
  }
  rateButtons.forEach(b => b.onclick = () => setFps(+b.dataset.fps));

  let lastFps = 0;
  function paint(st) {
    if (st.exposure_us) {
      exp.textContent = (st.exposure_us / 1000).toFixed(1) + " ms"
        + (st.gain > 1.05 ? " \u00b7 gain " + st.gain.toFixed(1) : "");
    }
    led.classList.toggle("on", st.led);
    led.textContent = st.led ? "IR on" : "IR forced off";
    if (st.focus && "zero_mm" in st.focus) {   // the PDAF meter
      const f = st.focus;
      document.getElementById("zerorow").hidden = false;
      const words = {ok: "", uppvarmning: "warming up \u00b7 ",
        utanfor_kalibrering: "beyond calibration \u00b7 ",
        i_halsen: "IN THE NECK", misslyckad: "no focus", morkt: "lamp off \u00b7 no reading"};
      focus.textContent = f.busy ? "measuring\u2026"
        : !f.tid ? "no measurement yet"
        : f.d_mm === null ? words[f.status] + " \u00b7 " + f.age_s + " s ago"
        : words[f.status] + "surface " + f.d_mm.toFixed(1) + " mm"
          + (f.krausen_mm !== null ? " \u00b7 krausen " + f.krausen_mm.toFixed(1) + " mm" : "")
          + " \u00b7 " + f.dpt.toFixed(3) + " dpt \u00b7 " + f.age_s + " s ago";
      const rec = document.getElementById("rec"), rs = st.recording || {};
      rec.classList.toggle("on", !!rs.recording);
      const mmss = s => Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
      rec.innerHTML = rs.recording
        ? "&#9679; REC " + mmss(rs.elapsed_s) + " / " + mmss(rs.max_s) + " \u00b7 stop"
        : "&#9679; REC";
      document.getElementById("zeroinfo").textContent =
        (f.batch ? "batch " + f.batch : "no batch") + " \u00b7 "
        + (f.zero_mm === null ? "no zero set" : "zero at " + f.zero_mm.toFixed(1) + " mm");
    } else if (st.focus) {
      const f = st.focus;
      // "busy" is why the picture just went black: the lamp is off and the
      // exposure is down at 8 ms for the laser frame.
      focus.textContent = f.busy ? "ranging\u2026 (lamp off for the laser frame)"
        : f.distance_mm === null ? "no range yet"
        : f.distance_mm + " mm \u00b7 focus " + f.lens_position.toFixed(2)
          + " dpt \u00b7 ranged " + f.age_s + " s ago";
    }
  }
  async function toggle(path, want) {
    const r = await fetch(path + "?on=" + (want ? 1 : 0), { method: "POST" });
    paint(await r.json());
  }
  led.onclick = () => toggle("/api/led", led.textContent !== "IR on");
  document.getElementById("rec").onclick = async () => {
    const on = !document.getElementById("rec").classList.contains("on");
    const r = await fetch("/api/record?on=" + (on ? 1 : 0), { method: "POST" });
    if (!r.ok) { alert("Recording is not available on this service."); return; }
    paint(await r.json());
  };
  document.getElementById("batch").onclick = async () => {
    if (!confirm("Start a new batch? Frames and logs go to a new folder, "
                 + "and the zero is cleared until the tank is zeroed again.")) return;
    const r = await fetch("/api/batch", { method: "POST" });
    if (!r.ok) { alert("No archive configured on the service."); return; }
    paint(await r.json());
  };
  document.getElementById("zero").onclick = async () => {
    if (!confirm("Store the latest surface distance as the fill-level zero? "
                 + "Every krausen height is measured from it.")) return;
    const r = await fetch("/api/zero", { method: "POST" });
    if (!r.ok) { alert("No usable measurement to zero on yet."); return; }
    paint(await r.json());
  };
  // Poll rather than fetch once: the reading has an age, and an age that never
  // changes is worse than none -- it looks like a live number and is not.
  function refresh() {
    if (document.hidden) return;
    fetch("/api/state").then(r => r.json()).then(paint).catch(() => {});
  }
  refresh();
  setInterval(refresh, 2000);

  // Close the stream deterministically on navigation, so the viewer count
  // reaches zero and the manual overrides -- the laser above all -- are reset.
  addEventListener("pagehide", () => img.removeAttribute("src"));

  // A backgrounded tab keeps draining the socket, so the server still counts it
  // as a healthy viewer and holds the illumination on for nobody. The reference
  // count should follow attention, not merely an open connection -- an LED
  // potted in a rod with no heat path should not sit warming because a tab was
  // left open. Hiding the tab drops the stream; showing it picks it up again.
  addEventListener("visibilitychange", () => {
    if (document.hidden) img.removeAttribute("src");
    else setFps(currentFps);
  });

  let start = {default_fps};
  try { start = +localStorage.getItem("fps") || start; } catch (e) {}
  setFps(start);
</script>
</body>
</html>
"""


def frame_duration_for(exposure_us: int) -> tuple[int, int]:
    """Frame duration limits that allow the requested exposure.

    The default video configuration pins FrameDurationLimits at (33333, 33333),
    which caps exposure at 33 ms -- a frame cannot be shorter than its own
    exposure. The brief calls for 50-100 ms as the first thing to reach for when
    light is short, and stopping down makes that necessary rather than optional,
    so the limits are derived from the exposure instead of left at the default.

    The frame rate drops accordingly. That costs nothing for a measurement of
    two frames per minute, and the live view only slows when a long exposure is
    actually asked for.
    """
    d = max(33333, exposure_us + 1000)
    return (d, d)


class Controls:
    """Manual overrides from the web UI, on top of the viewer reference count.

    Everything here is cleared when the last viewer disconnects: a closed tab
    must not leave the laser on, and it must not leave the illumination forced
    dark for whoever connects next.
    """

    def __init__(self, led: Lamp, laser: Lamp) -> None:
        self._lock = threading.Lock()
        self._led = led
        self._laser = laser
        self.led_forced_off = False
        self.laser_on = False

    def set_led(self, on: bool) -> None:
        with self._lock:
            want_forced = not on
            if want_forced == self.led_forced_off:
                return
            if want_forced:
                self._led.force_off()
            else:
                self._led.unforce_off()
            self.led_forced_off = want_forced
            log.info("web: illumination %s", "forced off" if want_forced else "released")

    def set_laser(self, on: bool) -> None:
        with self._lock:
            if on == self.laser_on:
                return
            if on:
                self._laser.acquire()
            else:
                self._laser.release()
            self.laser_on = on
            log.info("web: laser %s", "ON" if on else "off")

    def reset(self) -> None:
        self.set_led(True)
        self.set_laser(False)

    def state(self) -> dict:
        with self._lock:
            return {"led": not self.led_forced_off, "laser": self.laser_on}


class FrameBroker(io.BufferedIOBase):
    """Receives JPEG frames from the encoder and hands the latest to readers."""

    def __init__(self) -> None:
        self.frame: bytes | None = None
        self._ready = threading.Condition()
        # When the last frame arrived. The encoder runs at the sensor's 30 fps
        # whether anyone watches or not, so silence here is the camera itself
        # stopping -- the quickest sign of a CSI frontend timeout there is.
        self.last: float | None = None

    def write(self, buf: bytes) -> int:
        with self._ready:
            self.frame = buf
            self.last = time.monotonic()
            self._ready.notify_all()
        return len(buf)

    def next_frame(self, timeout: float = 5.0) -> bytes | None:
        with self._ready:
            if not self._ready.wait(timeout):
                return None
            return self.frame


class Handler(server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # injected by main()
    broker: FrameBroker
    lamp: Lamp
    controls: Controls
    tracker = None
    recorder = None
    picam2 = None
    stream_timeout: float
    default_fps: float
    archive_url = "http://krausen/"
    lores: tuple

    _viewers = 0
    _viewers_lock = threading.Lock()

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_page()
        elif parsed.path == "/stream.mjpg":
            self._send_stream(self._wanted_fps(parsed.query))
        elif parsed.path == "/api/state":
            self._send_json(self._state())
        elif parsed.path == "/healthz":
            self._send_bytes(b"ok\n", "text/plain")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        on = parse_qs(parsed.query).get("on", ["1"])[0] not in ("0", "false", "off")
        # Log the request itself, with the client, not only the resulting state
        # change. A no-op request leaves no other trace, and when hardware that
        # emits a laser beam is involved it should be clear who asked for it.
        log.info("web request from %s: %s on=%s", self.address_string(), parsed.path, on)
        if parsed.path == "/api/record":
            if self.recorder is None:
                self.send_error(404)
                return
            self.recorder.start() if on else self.recorder.stop()
        elif parsed.path == "/api/lampmode":
            if self.tracker is None or not hasattr(self.tracker, "set_lamp_mode"):
                self.send_error(404)
                return
            self.tracker.set_lamp_mode(on)
        elif parsed.path == "/api/batch":
            if self.tracker is None or not hasattr(self.tracker, "new_batch") \
                    or self.tracker.new_batch() is None:
                self.send_error(409, "no archive configured")
                return
        elif parsed.path == "/api/zero":
            if self.tracker is None or not hasattr(self.tracker, "set_zero") \
                    or self.tracker.set_zero() is None:
                self.send_error(409, "no usable measurement to zero on")
                return
        elif parsed.path == "/api/led":
            self.controls.set_led(on)
        elif parsed.path == "/api/laser":
            self.controls.set_laser(on)
        else:
            self.send_error(404)
            return
        self._send_json(self._state())

    def _tell_tracker(self, n: int) -> None:
        """Let the PDAF meter focus for a watcher or park when none is left.

        On its own thread: the meter holds the camera for ~20 s while it
        measures, and the stream must not wait for that to start.
        """
        t = self.tracker
        if t is not None and hasattr(t, "on_viewers"):
            threading.Thread(target=t.on_viewers, args=(n,), daemon=True).start()

    def _state(self) -> dict:
        st = self.controls.state()
        # What the auto exposure actually settled on. Without this the only way
        # to tell AEC from a locked exposure is to change the scene and squint.
        if self.picam2 is not None:
            try:
                md = self.picam2.capture_metadata()
                st["exposure_us"] = md.get("ExposureTime")
                st["gain"] = round(md.get("AnalogueGain", 0.0), 2)
            except Exception:
                pass
        if self.tracker is not None:
            st["focus"] = self.tracker.state()
        if self.recorder is not None:
            st["recording"] = self.recorder.state()
        return st

    def _send_json(self, obj: dict) -> None:
        import json
        self._send_bytes(json.dumps(obj).encode(), "application/json")

    def _send_bytes(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _wanted_fps(self, query: str) -> float:
        """Requested rate, clamped. Falls back to the server default."""
        try:
            fps = float(parse_qs(query).get("fps", [self.default_fps])[0])
        except ValueError:
            return self.default_fps
        return min(max(fps, 0.1), FPS_MAX)

    def _send_page(self) -> None:
        # str.replace rather than %-formatting or .format(): the CSS contains
        # both "100%" and curly braces, each of which collides with one of
        # those template languages.
        buttons = "".join(
            f'<button data-fps="{n}">{label} &middot; {n} fps</button>'
            for n, label in FPS_PRESETS
        )
        body = (PAGE.replace("{buttons}", buttons)
                    .replace("{default_fps}", str(int(self.default_fps)))
                    .replace("{w}", str(self.lores[0]))
                    .replace("{h}", str(self.lores[1]))
                    .replace("{archive}", self.archive_url)).encode()
        self._send_bytes(body, "text/html; charset=utf-8")

    def _send_stream(self, fps: float) -> None:
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()

        # A backgrounded tab or a minimised app stops reading but leaves the
        # socket open. Without a timeout the kernel send buffer fills, write()
        # blocks forever, and the lamp stays lit until TCP keepalive notices --
        # two hours by default on Linux. The timeout turns that into a
        # TimeoutError we can act on.
        self.connection.settimeout(self.stream_timeout)

        # The viewer holds the lamp on for as long as the stream lives.
        # release() in the finally is what stops a crashed tab from leaving
        # it lit indefinitely.
        self.lamp.acquire()
        with Handler._viewers_lock:
            Handler._viewers += 1
            n = Handler._viewers
        self._tell_tracker(n)
        peer = self.address_string()
        log.info("viewer connected: %s at %g fps", peer, fps)
        min_interval = 1.0 / fps
        next_due = 0.0
        try:
            while True:
                frame = self.broker.next_frame()
                if frame is None:
                    log.warning("no frame for 5 s -- closing stream to %s", peer)
                    break
                now = time.monotonic()
                # Advance a fixed schedule rather than restarting the interval
                # at each frame sent. Resetting to "now" can only ever deliver
                # whole divisions of the source rate: against a 30 fps sensor a
                # request for 24 asks for 41.7 ms, which falls between one and
                # two source frames, so it waits for the second one and yields
                # 15. Accumulating the due time instead alternates one- and
                # two-frame gaps and averages out at the rate asked for.
                if next_due == 0.0:
                    next_due = now
                if now < next_due - 0.002:
                    continue  # drop this frame to hold the requested rate
                next_due += min_interval
                if next_due < now:
                    next_due = now + min_interval   # source slower than asked
                self.wfile.write(b"--FRAME\r\n")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except TimeoutError:
            log.info("viewer %s stopped reading for %.0f s (backgrounded?) -- closing",
                     peer, self.stream_timeout)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.lamp.release()
            with Handler._viewers_lock:
                Handler._viewers -= 1
                last = Handler._viewers == 0
            if last:
                self.controls.reset()
                self._tell_tracker(0)
            log.info("viewer gone: %s%s", peer, " (last -- manual controls reset)" if last else "")


class Server(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A browser closing a stream is not an error worth a traceback.

        The default prints the whole stack for every tab that goes away, which
        buries the measurement lines in a log that gets read closely.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            log.debug("viewer disconnected: %s (%s)", client_address,
                      type(exc).__name__)
            return
        super().handle_error(request, client_address)


def lores_size(args) -> tuple[int, int]:
    w, h = (int(v) for v in args.lores.lower().split("x"))
    return (w, h)


def build_camera(args):
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput

    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": MAIN_SIZE},
        lores={"size": lores_size(args), "format": "YUV420"},
    )
    picam2.configure(config)

    # Auto exposure is the default for the live view. The scene spans about
    # 2.3x from an empty tank to high krausen, so no single locked value looks
    # right at both ends, and nothing is measured from what a viewer sees --
    # frame A is archived, not measured, and the cycle sets its own state
    # before capturing it. White balance stays locked regardless: under 850 nm
    # the channels sit within 6 % of each other, so AWB has nothing real to
    # correct and would only chase noise.
    # Continuous AF is for aiming and building, never for measuring: it moves
    # the lens whenever it likes, and every move changes the magnification by
    # 0.68 %/dioptre. Opt-in only, and it refuses to coexist with a snapshot
    # series for that reason.
    if args.continuous_af:
        from libcamera import controls as _lc
        controls = {"AfMode": _lc.AfModeEnum.Continuous,
                    "AfRange": _lc.AfRangeEnum.Full,
                    "AwbEnable": bool(args.auto_wb)}
        log.warning("continuous AF: the lens moves on its own. Aiming only -- "
                    "magnification changes with it, so nothing measured here "
                    "compares with anything else.")
    else:
        controls = {"AfMode": 0, "LensPosition": args.lens_position,
                    "AwbEnable": bool(args.auto_wb)}
    if not args.auto_wb:
        controls["ColourGains"] = (args.red_gain, args.blue_gain)

    if args.exposure_us:
        controls.update(FrameDurationLimits=frame_duration_for(args.exposure_us),
                        AeEnable=False, ExposureTime=args.exposure_us,
                        AnalogueGain=args.gain)
        log.info("exposure locked at %d us", args.exposure_us)
    else:
        # Bounded rather than left open: given room, the auto exposure spends it
        # on exposure time and the frame rate collapses. Measured with a 100 ms
        # ceiling, a request for 24 fps delivered 15.2.
        controls["AeEnable"] = True
        controls["FrameDurationLimits"] = (33333, args.max_frame_duration_us)
    if args.auto_wb:
        log.warning("--auto-wb: white balance UNLOCKED. Aiming in visible light only.")

    picam2.set_controls(controls)

    # What the focus tracker has to restore after each ranging cycle.
    restore = {k: controls[k] for k in
               ("FrameDurationLimits", "AeEnable", "AwbEnable") if k in controls}
    for k in ("ExposureTime", "AnalogueGain", "ColourGains"):
        if k in controls:
            restore[k] = controls[k]

    broker = FrameBroker()
    picam2.start_recording(
        MJPEGEncoder(bitrate=args.bitrate), FileOutput(broker), name="lores"
    )
    return picam2, broker, restore


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, action="append",
                   help="port to serve on; repeat for more (default 8080). The "
                        "service uses 80, for http://krausenlive/, and 8080 so "
                        "older links keep working. Port 80 needs "
                        "CAP_NET_BIND_SERVICE, granted in the unit.")
    p.add_argument("--lens-position", type=float, default=7.1,
                   help="dioptres (1/distance in metres); 7.1 ~ 140 mm. "
                        "Calibrate with a focus sweep.")
    p.add_argument("--exposure-us", type=int, default=0,
                   help="lock the exposure at this many microseconds; "
                        "0 (the default) runs auto exposure. Nothing moves, "
                        "so time is free when you do lock it.")
    p.add_argument("--gain", type=float, default=1.0)
    # Measured under the 850 nm lamp: at (1.0, 1.0) the channels come out
    # R=190.7 G=179.2 B=178.1, so the scene is very nearly neutral already
    # and these are what flatten the last few per cent. The old (1.5, 1.5)
    # was a visible-light guess and gave R=225 G=148 B=222 -- magenta.
    p.add_argument("--red-gain", type=float, default=0.94)
    p.add_argument("--blue-gain", type=float, default=1.01)
    # 25 Mbit/s since lores went to 1280x720: at the old 12 the same bits were
    # spread over 1.6x the pixels and smooth gradients -- the vignette above
    # all -- showed hard banding (2026-10-03).
    p.add_argument("--bitrate", type=int, default=25_000_000)
    p.add_argument("--lores", default="%dx%d" % LORES_SIZE,
                   help="size of the stream the web view encodes. Keep both "
                        "dimensions multiples of 16: JPEG codes in 16x16 blocks, "
                        "and 1152x648 -- exactly 16:9 but 648 is not -- produced "
                        "a green artefact row along the bottom edge")
    p.add_argument("--max-frame-duration-us", type=int, default=41_000,
                   help="longest frame the auto exposure may choose. Defaults to "
                        "the top preset's period, so the camera can always "
                        "deliver the rate printed on the button; a dark scene "
                        "then costs gain rather than frame rate. Raise it to let "
                        "the exposure grow instead")
    # GPIO10 (pin 19) since 2026-10-03: the Wide Input SHIM covers pins 1-12,
    # where the lamp (GPIO17, pin 11) used to be. Pins 17-20 give 3V3, GPIO24
    # (1-Wire), GPIO10 (lamp) and GND in one row. GPIO10 is SPI0 MOSI, so SPI
    # must stay off -- the lamp rather than the sensors goes if it is ever on.
    p.add_argument("--led-pin", type=int, default=10, help="GPIO pin for the IR illumination")
    p.add_argument("--laser-pin", type=int, default=None,
                   help="GPIO pin for the laser enable; none is fitted since PDAF "
                        "replaced triangulation, so no pin is claimed by default")
    p.add_argument("--fps", type=float, default=10.0,
                   help="default stream rate; viewers can override per connection "
                        "with ?fps=N up to the sensor rate")
    p.add_argument("--stream-timeout", type=float, default=10.0,
                   help="drop a viewer that has not accepted data for this many "
                        "seconds, so a backgrounded tab cannot hold the lamp on")
    p.add_argument("--autofocus", action="store_true",
                   help="range with the laser and hold the focus there")
    p.add_argument("--af-interval", type=float, default=60.0,
                   help="seconds between laser ranging cycles (default 60)")
    p.add_argument("--af-exposure-us", type=int, default=8000,
                   help="exposure for the laser frame; the dot saturates above this")
    p.add_argument("--af-threshold", type=float, default=1.2,
                   help="dioptres of drift before the lens is moved (default 1.2, "
                        "about half the measured depth of field)")
    p.add_argument("--snapshot-dir",
                   help="save frame A here after each ranging cycle")
    p.add_argument("--continuous-af", action="store_true",
                   help="keep the live view sharp while the scene moves. "
                        "Aiming only -- the lens moves on its own.")
    p.add_argument("--maintenance-flag",
                   default=os.path.join(os.path.dirname(
                       os.path.abspath(__file__)), "MAINTENANCE"),
                   help="while this file exists the service idles without "
                        "opening the camera, so scripts can use it")
    p.add_argument("--no-laser", action="store_true",
                   help="no laser fitted: take frame A on the snapshot "
                        "interval and skip ranging entirely")
    p.add_argument("--af-band-y", type=float, default=None,
                   help="centre of the vertical search window, px below the "
                        "image centre (default from focus_tracker)")
    p.add_argument("--af-band-halfwidth", type=float, default=None)
    p.add_argument("--pdaf-every", type=int, default=0,
                   help="run the module's own autofocus as a cross-check "
                        "every N ranging cycles (0 = never). Shares no "
                        "failure mode with the laser.")
    p.add_argument("--pdaf-model", metavar="FILE",
                   help="measure the surface with PDAF against this model file "
                        "(afmodell.py) instead of the laser. See pdaf_meter.py.")
    p.add_argument("--measure-interval", type=float, default=300.0,
                   help="seconds between PDAF measurements. The calibration "
                        "visited every 300 s; keep it there.")
    p.add_argument("--zero-file", default="/home/pi/krausencamera/zero.json",
                   help="where the fill-level zero is kept across restarts")
    p.add_argument("--log-dir", default="/home/pi/krausencamera/matningar",
                   help="daily CSV of every PDAF measurement")
    p.add_argument("--temp-coeff", type=float, default=0.0,
                   help="PDAF meter: dpt per degree C of lid temperature, applied "
                        "relative to the lid at the zero. 0 disables.")
    p.add_argument("--plate-sensor", default=None,
                   help="DS18B20 id in the housing's aluminium plate, logged and "
                        "published beside the lid sensor")
    p.add_argument("--lid-sensor", default=None,
                   help="DS18B20 id on the lid, logged with each measurement")
    p.add_argument("--lamp-mode", choices=("always", "measure"), default="always",
                   help="PDAF meter: hold the IR lamp on, or light it only to "
                        "measure and for viewers. Switchable at runtime with "
                        "POST /api/lampmode?on=0|1")
    p.add_argument("--mqtt-config", metavar="FILE",
                   help="publish to Home Assistant over MQTT; JSON with host, "
                        "port, username, password (mqtt.example.json). "
                        "Keep it out of the repository.")
    p.add_argument("--archive-dir", default=None,
                   help="batch folders for frame A and per-batch logs, synced "
                        "to the NAS by arkivsynk.sh. Overrides --snapshot-dir.")
    p.add_argument("--archive-url", default="http://krausen/",
                   help="where the page's Archive link goes: the NAS start page")
    p.add_argument("--frame-timeout", type=float, default=15.0,
                   help="exit for a restart when the camera has sent no frame "
                        "for this many seconds")
    p.add_argument("--record-max-s", type=float, default=300.0,
                   help="a dry-hop recording stops by itself after this long")
    p.add_argument("--snapshot-quality", type=int, default=95,
                   help="JPEG quality of frame A")
    p.add_argument("--settle-min", type=float, default=75.0,
                   help="minutes after start during which readings are "
                        "flagged as warming")
    p.add_argument("--snapshot-interval", type=float, default=300.0,
                   help="seconds between frame A captures, independent of "
                        "--af-interval (default 300)")
    p.add_argument("--snapshot-exposure-us", type=int, default=25000,
                   help="locked exposure for frame A; 25 ms was measured "
                        "as the longest that does not clip high krausen")
    p.add_argument("--auto-wb", action="store_true",
                   help="unlock exposure/white balance -- for aiming only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # Maintenance mode, checked before the camera is opened. Under systemd a
    # collision over the camera is not merely annoying: the service fails in a
    # couple of seconds, restarts every ten, and burns StartLimitBurst in about
    # a minute -- which reboots the Pi in the middle of whatever you were doing.
    # With the flag in place the service stays up holding nothing, and resumes
    # by itself when the flag goes away.
    if args.maintenance_flag and os.path.exists(args.maintenance_flag):
        log.warning("maintenance flag %s present: camera released, "
                    "waiting. Remove it to resume.", args.maintenance_flag)
        while os.path.exists(args.maintenance_flag):
            time.sleep(5.0)
        log.info("maintenance flag gone -- exiting so systemd restarts us")
        return 0

    lamp = Lamp("IR illumination", args.led_pin)
    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    picam2, broker, restore = build_camera(args)
    Handler.broker = broker
    Handler.lamp = lamp
    Handler.picam2 = picam2
    Handler.controls = Controls(lamp, laser)
    Handler.stream_timeout = args.stream_timeout
    Handler.default_fps = min(max(args.fps, 0.1), FPS_MAX)
    Handler.lores = lores_size(args)
    Handler.archive_url = args.archive_url

    if args.continuous_af and args.snapshot_dir:
        log.error("--continuous-af and --snapshot-dir together would archive frames at a magnification that changes between them. Refusing.")
        return 2

    tracker = None
    ha = None
    recorder = None
    if args.pdaf_model:
        from pdaf_meter import PdafMeter
        batches = None
        if args.archive_dir:
            from batch import Batches
            batches = Batches(args.archive_dir,
                              os.path.join(os.path.dirname(args.zero_file), "batch.json"))
        tracker = PdafMeter(
            picam2, lamp, model_path=args.pdaf_model,
            interval_s=args.measure_interval, restore_controls=restore,
            snapshot_dir=args.snapshot_dir,
            snapshot_interval_s=args.snapshot_interval,
            snapshot_exposure_us=args.snapshot_exposure_us,
            zero_path=args.zero_file, log_dir=args.log_dir,
            lid_sensor=args.lid_sensor, plate_sensor=args.plate_sensor,
            temp_coeff=args.temp_coeff,
            settle_min=args.settle_min,
            lamp_always_on=args.lamp_mode == "always",
            snapshot_quality=args.snapshot_quality, batches=batches,
            viewers=lambda: Handler._viewers)
        Handler.tracker = tracker
        from recorder import Recorder
        recorder = Recorder(
            picam2, lamp, tracker, max_s=args.record_max_s,
            video_dir=(lambda: batches.dir("video")) if batches
            else (lambda: "/home/pi/video"))
        Handler.recorder = recorder
        if args.mqtt_config:
            import json as _json
            from ha_mqtt import HaMqtt
            with open(args.mqtt_config) as f:
                mqtt_cfg = _json.load(f)
            ha = HaMqtt(mqtt_cfg, on_zero=tracker.set_zero,
                        on_batch=tracker.new_batch,
                        on_record=lambda on: recorder.start() if on else recorder.stop(),
                        interval_s=args.measure_interval)
            tracker.listeners.append(ha.publish)
            recorder.listeners.append(ha.publish_recording)
            ha.start()
        tracker.start()
    elif args.autofocus or (args.no_laser and args.snapshot_dir):
        tracker = FocusTracker(
            picam2, lamp, laser, size=MAIN_SIZE,
            interval_s=args.af_interval, laser_exposure_us=args.af_exposure_us,
            threshold_dpt=args.af_threshold, restore_controls=restore,
            **({"band_y": args.af_band_y} if args.af_band_y is not None else {}),
            **({"band_halfwidth": args.af_band_halfwidth}
               if args.af_band_halfwidth is not None else {}),
            initial_lens=args.lens_position,
            snapshot_dir=args.snapshot_dir,
            snapshot_exposure_us=args.snapshot_exposure_us,
            snapshot_interval_s=args.snapshot_interval,
            pdaf_every=args.pdaf_every,
            laser_fitted=not args.no_laser,
        )
        Handler.tracker = tracker
        tracker.start()

        if args.no_laser:
            log.info("no laser: frame A every %.0f s, no ranging",
                     args.snapshot_interval)
        else:
            log.info("autofocus on: ranging every %.0f s, moving past %.1f dpt",
                     args.af_interval, args.af_threshold)

    if tracker is not None:
        # Report a stall well before the watchdog acts on it: two missed
        # points and a minute of grace.
        stall_s = (2 * args.measure_interval + 60) if args.pdaf_model else None

        def watchdog(t, period):
            """Exit if the camera stops producing, even without raising.

            The tracker's own failure counter needs an exception. A wedged CSI
            link can instead hang inside capture_array, and then nothing raises,
            nothing counts, and the process serves an empty stream until someone
            notices -- which once took five hours.
            """
            import os as _os
            last = None
            n = 0
            while True:
                time.sleep(5.0)
                n += 1
                # The frames first. A frontend timeout stops them at once, and
                # waiting for the measurement to notice took seventeen minutes
                # on 2026-10-01; this restarts within about half a minute.
                fl = broker.last
                if fl is not None and time.monotonic() - fl > args.frame_timeout:
                    log.critical("watchdog: no frame from the camera for %.0f s -- "
                                 "frontend timeout? exiting for a restart",
                                 time.monotonic() - fl)
                    if ha is not None:
                        ha.publish_stalled(True)
                        time.sleep(1.0)
                    _os._exit(17)
                if n % 6:
                    continue
                idle = time.time() - t.last_ok
                if ha is not None and stall_s:
                    stalled = idle > stall_s
                    if stalled != last:
                        ha.publish_stalled(stalled)
                        last = stalled
                if idle > period:
                    log.critical("watchdog: no successful cycle for %.0f s "
                                 "(limit %.0f) -- exiting for a restart", idle, period)
                    _os._exit(17)

        period = (max(args.measure_interval, args.snapshot_interval) if args.pdaf_model
                  else max(args.af_interval, args.snapshot_interval)) * 3 + 120
        threading.Thread(target=watchdog, args=(tracker, period),
                         daemon=True).start()
        log.info("watchdog: exit if no cycle completes within %.0f s", period)

    ports = args.port or [8080]
    extra = [Server(("", p), Handler) for p in ports[1:]]
    for srv in extra:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    httpd = Server(("", ports[0]), Handler)
    # systemd stops us with SIGTERM, which by default kills the process
    # without running the finally below -- so MQTT would never say offline and
    # HA would wait for the broker's keepalive instead. Turn it into a shutdown.
    import signal
    signal.signal(signal.SIGTERM,
                  lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start())
    log.info("live view on port %s  (main %dx%d, lores %dx%d)",
             " and ".join(map(str, ports)), *MAIN_SIZE, *lores_size(args))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        httpd.shutdown()
        for srv in extra:
            srv.shutdown()
        if recorder and recorder.recording:
            recorder.stop()          # close the MP4 properly, or it is unplayable
        if ha:
            ha.stop()
        if tracker:
            tracker.stop()
        picam2.stop_recording()
        laser.shutdown()
        lamp.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
