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
automated analysis. Use --auto when aiming the housing, never when measuring.
"""

from __future__ import annotations

import argparse
import io
import logging
import socketserver
import sys
import threading
import time
from http import server
from urllib.parse import parse_qs, urlparse

from illumination import Lamp

log = logging.getLogger("liveview")

MAIN_SIZE = (2304, 1296)
LORES_SIZE = (1024, 576)   # default, overridden by --lores

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
  .hw button.laser.on { background: #c62828; border-color: #c62828; color: #fff; }
  .meta { opacity: .6; font-variant-numeric: tabular-nums; text-align: center; }
</style>
</head>
<body>
  <img src="" alt="Live view from the krausen camera">
  <div class="row rates">{buttons}</div>
  <div class="row hw">
    <button id="led">IR</button>
    <button id="laser" class="laser">Laser</button>
  </div>
  <div class="meta"></div>
<script>
  const img = document.querySelector("img");
  const meta = document.querySelector(".meta");
  // scoped to .rates -- the hardware toggles are buttons too
  const rateButtons = [...document.querySelectorAll(".rates button")];
  const led = document.getElementById("led");
  const laser = document.getElementById("laser");

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
    meta.textContent = "{w}\u00d7{h} \u00b7 " + n + " fps \u00b7 "
      + "~" + Math.round(n * 15) + " kB/s \u00b7 "
      + "IR illumination follows the viewer count unless overridden below";
    try { localStorage.setItem("fps", n); } catch (e) {}
  }
  rateButtons.forEach(b => b.onclick = () => setFps(+b.dataset.fps));

  function paint(st) {
    led.classList.toggle("on", st.led);
    laser.classList.toggle("on", st.laser);
    led.textContent = st.led ? "IR on" : "IR forced off";
    laser.textContent = st.laser ? "LASER ON" : "Laser off";
  }
  async function toggle(path, want) {
    const r = await fetch(path + "?on=" + (want ? 1 : 0), { method: "POST" });
    paint(await r.json());
  }
  led.onclick = () => toggle("/api/led", led.textContent !== "IR on");
  laser.onclick = () => toggle("/api/laser", laser.textContent !== "LASER ON");
  fetch("/api/state").then(r => r.json()).then(paint);

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

    def write(self, buf: bytes) -> int:
        with self._ready:
            self.frame = buf
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
    stream_timeout: float
    default_fps: float
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
            self._send_json(self.controls.state())
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
        if parsed.path == "/api/led":
            self.controls.set_led(on)
        elif parsed.path == "/api/laser":
            self.controls.set_laser(on)
        else:
            self.send_error(404)
            return
        self._send_json(self.controls.state())

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
                    .replace("{h}", str(self.lores[1]))).encode()
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
            log.info("viewer gone: %s%s", peer, " (last -- manual controls reset)" if last else "")


class Server(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


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

    controls = {"AfMode": 0, "LensPosition": args.lens_position}
    if args.auto:
        # Give the auto exposure room to go past 33 ms. Frame duration bounds
        # exposure, so leaving it at the default caps AEC exactly where a
        # stopped-down lens starts needing more light. The frame rate drops on
        # its own when a long exposure is actually chosen.
        # Bounded by the top preset's period rather than left open: given room,
        # the auto exposure spends it on exposure time and the rate collapses.
        # Measured with a 100 ms ceiling, a request for 24 fps delivered 15.2.
        controls["FrameDurationLimits"] = (33333, args.max_frame_duration_us)
        log.warning("--auto: exposure and white balance UNLOCKED. Aiming only.")
    else:
        controls.update(
            FrameDurationLimits=frame_duration_for(args.exposure_us),
            AeEnable=False,
            ExposureTime=args.exposure_us,
            AnalogueGain=args.gain,
            AwbEnable=False,
            ColourGains=(args.red_gain, args.blue_gain),
        )
    picam2.set_controls(controls)

    broker = FrameBroker()
    picam2.start_recording(
        MJPEGEncoder(bitrate=args.bitrate), FileOutput(broker), name="lores"
    )
    return picam2, broker


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--lens-position", type=float, default=7.1,
                   help="dioptres (1/distance in metres); 7.1 ~ 140 mm. "
                        "Calibrate with a focus sweep.")
    p.add_argument("--exposure-us", type=int, default=60000,
                   help="exposure time in microseconds; nothing moves, so time is free")
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--red-gain", type=float, default=1.5)
    p.add_argument("--blue-gain", type=float, default=1.5)
    p.add_argument("--bitrate", type=int, default=12_000_000)
    p.add_argument("--lores", default="1024x576",
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
    p.add_argument("--led-pin", type=int, default=17, help="GPIO pin for the IR illumination")
    p.add_argument("--laser-pin", type=int, default=27, help="GPIO pin for the laser enable")
    p.add_argument("--fps", type=float, default=10.0,
                   help="default stream rate; viewers can override per connection "
                        "with ?fps=N up to the sensor rate")
    p.add_argument("--stream-timeout", type=float, default=10.0,
                   help="drop a viewer that has not accepted data for this many "
                        "seconds, so a backgrounded tab cannot hold the lamp on")
    p.add_argument("--auto", action="store_true",
                   help="unlock exposure/white balance -- for aiming only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    lamp = Lamp("IR illumination", args.led_pin)
    laser = Lamp("laser", args.laser_pin, settle_s=0.1)
    picam2, broker = build_camera(args)
    Handler.broker = broker
    Handler.lamp = lamp
    Handler.controls = Controls(lamp, laser)
    Handler.stream_timeout = args.stream_timeout
    Handler.default_fps = min(max(args.fps, 0.1), FPS_MAX)
    Handler.lores = lores_size(args)

    httpd = Server(("", args.port), Handler)
    log.info("live view on http://0.0.0.0:%d/  (main %dx%d, lores %dx%d)",
             args.port, *MAIN_SIZE, *lores_size(args))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        httpd.shutdown()
        picam2.stop_recording()
        laser.shutdown()
        lamp.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
