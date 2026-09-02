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
from http import server

from illumination import Lamp

log = logging.getLogger("liveview")

MAIN_SIZE = (2304, 1296)
LORES_SIZE = (768, 432)

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
  .meta { opacity: .6; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <img src="/stream.mjpg" alt="Live view from the krausen camera">
  <div class="meta">{w}&times;{h} &middot; IR illumination is on while this page is open</div>
</body>
</html>
"""


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
    stream_timeout: float

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_page()
        elif self.path == "/stream.mjpg":
            self._send_stream()
        elif self.path == "/healthz":
            self._send_bytes(b"ok\n", "text/plain")
        else:
            self.send_error(404)

    def _send_bytes(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self) -> None:
        # str.replace rather than %-formatting or .format(): the CSS contains
        # both "100%" and curly braces, each of which collides with one of
        # those template languages.
        body = (PAGE.replace("{w}", str(LORES_SIZE[0]))
                    .replace("{h}", str(LORES_SIZE[1]))).encode()
        self._send_bytes(body, "text/html; charset=utf-8")

    def _send_stream(self) -> None:
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
        peer = self.address_string()
        log.info("viewer connected: %s", peer)
        try:
            while True:
                frame = self.broker.next_frame()
                if frame is None:
                    log.warning("no frame for 5 s -- closing stream to %s", peer)
                    break
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
            log.info("viewer gone: %s", peer)


class Server(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def build_camera(args):
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput

    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": MAIN_SIZE},
        lores={"size": LORES_SIZE, "format": "YUV420"},
    )
    picam2.configure(config)

    controls = {"AfMode": 0, "LensPosition": args.lens_position}
    if args.auto:
        log.warning("--auto: exposure and white balance UNLOCKED. Aiming only.")
    else:
        controls.update(
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
    p.add_argument("--bitrate", type=int, default=4_000_000)
    p.add_argument("--led-pin", type=int, default=17, help="GPIO pin for the IR illumination")
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
    picam2, broker = build_camera(args)
    Handler.broker = broker
    Handler.lamp = lamp
    Handler.stream_timeout = args.stream_timeout

    httpd = Server(("", args.port), Handler)
    log.info("live view on http://0.0.0.0:%d/  (main %dx%d, lores %dx%d)",
             args.port, *MAIN_SIZE, *LORES_SIZE)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        httpd.shutdown()
        picam2.stop_recording()
        lamp.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
