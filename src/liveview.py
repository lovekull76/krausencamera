#!/usr/bin/env python3
"""Livevy över HTTP för krausenkameran.

Öppna http://krausencamera:8080/ i valfri webbläsare. IR-lampan tänds när
första tittaren ansluter och släcks när den sista försvinner.

Kameran konfigureras en gång och konfigureras aldrig om -- lägesbyten kräver
omkonfigurering av sensorn och är det enda som faktiskt är långsamt. Samma
videokonfiguration bär två strömmar ur samma sensorläge:

    main   2304x1296  -- mätningens bildrutor (2x2-binnat, 4x signal/pixel)
    lores   768x432   -- webbvyn, bråkdelen av kodningsarbetet

Exponering, vitbalans och fokus är låsta. Det är inte kosmetika: automatiken
kompenserar annars bort exakt den ljusstyrkeförändring som ska mätas när
krausen bygger, och tidsserien blir värdelös för automatisk analys.
Kör med --auto vid inriktning av huset, aldrig vid mätning.
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
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Krausenkamera</title>
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
  <img src="/stream.mjpg" alt="Livebild från krausenkameran">
  <div class="meta">{w}&times;{h} &middot; IR-belysning tänd medan denna sida är öppen</div>
</body>
</html>
"""


class FrameBroker(io.BufferedIOBase):
    """Tar emot JPEG-rutor från encodern och delar ut senaste till alla läsare."""

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

    # sätts av main()
    broker: FrameBroker
    lamp: Lamp

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
        # str.replace, inte %-formatering eller .format(): CSS innehåller både
        # "100%" och klammerparenteser, som båda kolliderar med de mallspråken.
        body = (PAGE.replace("{w}", str(LORES_SIZE[0]))
                    .replace("{h}", str(LORES_SIZE[1]))).encode()
        self._send_bytes(body, "text/html; charset=utf-8")

    def _send_stream(self) -> None:
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()

        # Tittaren håller lampan tänd så länge strömmen lever. release() i
        # finally är det som hindrar en kraschad flik från att lämna den på.
        self.lamp.acquire()
        peer = self.address_string()
        log.info("tittare ansluten: %s", peer)
        try:
            while True:
                frame = self.broker.next_frame()
                if frame is None:
                    log.warning("ingen bildruta på 5 s -- stänger ström till %s", peer)
                    break
                self.wfile.write(b"--FRAME\r\n")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            self.lamp.release()
            log.info("tittare borta: %s", peer)


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
        log.warning("--auto: exponering och vitbalans OLÅSTA. Endast för inriktning.")
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
                   help="dioptrier (1/avstånd i meter); 7.1 ~ 140 mm. Kalibreras med fokussvep.")
    p.add_argument("--exposure-us", type=int, default=60000,
                   help="exponeringstid i mikrosekunder; inget rör sig, så tid är gratis")
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--red-gain", type=float, default=1.5)
    p.add_argument("--blue-gain", type=float, default=1.5)
    p.add_argument("--bitrate", type=int, default=4_000_000)
    p.add_argument("--led-pin", type=int, default=17, help="GPIO för IR-belysningen")
    p.add_argument("--auto", action="store_true",
                   help="lås upp exponering/vitbalans -- endast för inriktning")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    lamp = Lamp("IR-belysning", args.led_pin)
    picam2, broker = build_camera(args)
    Handler.broker = broker
    Handler.lamp = lamp

    httpd = Server(("", args.port), Handler)
    log.info("livevy på http://0.0.0.0:%d/  (main %dx%d, lores %dx%d)",
             args.port, *MAIN_SIZE, *LORES_SIZE)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("avslutar")
    finally:
        httpd.shutdown()
        picam2.stop_recording()
        lamp.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
