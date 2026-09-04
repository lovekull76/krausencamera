"""Reference-counted control of the IR illumination and the laser.

Two consumers share the IR lamp: the measurement cycle and the live view.
That imposes three requirements which are cheap to build in now and awkward
to retrofit:

1. **Two consumers.** The measurement cycle needs the lamp both lit (frame A)
   and dark (frame B, where the laser dot must be the only bright thing in an
   almost black image). A connected viewer holding the lamp on would ruin
   frame B -- hence `forced_off()`.
2. **Reference counting with a release guarantee.** A browser tab that dies
   without closing cleanly must not leave the lamp lit forever -- hence
   `release()` in a `finally`.
3. **Thermal drift.** LED output falls as the package heats up. A viewer
   watching for ten minutes leaves the lamp hot, so the next frame A comes out
   dimmer than one taken from cold -- and that is exactly the brightness change
   the measurement is supposed to attribute to the krausen. Locking the camera
   exposure does not help, because the error is in the light source, not the
   sensor. `settled()` enforces a fixed warm-up from a known state, and
   `was_lit_for` is logged with each measurement so the analysis can flag
   frames taken with a hot lamp.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


class _NullPin:
    """Stand-in until the GPIO hardware is wired up.

    Deliberately silent: `Lamp` logs every transition itself, so that the log
    reads the same whether or not real hardware is present.
    """

    def __init__(self, name: str, pin: int) -> None:
        self._name = name
        self._pin = pin
        self.value = 0

    def on(self) -> None:
        self.value = 1

    def off(self) -> None:
        self.value = 0


def _make_pin(name: str, pin: int):
    """Real GPIO if it can be claimed, otherwise a stub.

    Both the import and the claim itself can fail: gpiozero raises
    lgpio.error('GPIO busy') when another process already holds the pin, and
    BadPinFactory when no backend is available. Neither is an ImportError, and
    neither should stop the server from starting without hardware attached.
    """
    try:
        from gpiozero import DigitalOutputDevice
    except ImportError:
        log.warning("gpiozero not available -- %s running as STUB, no GPIO", name)
        return _NullPin(name, pin)
    try:
        return DigitalOutputDevice(pin, active_high=True, initial_value=False)
    except Exception as exc:
        log.warning("could not claim GPIO%d (%s) -- %s running as STUB", pin, exc, name)
        return _NullPin(name, pin)


class Lamp:
    """A MOSFET-driven load with reference counting and known lit history."""

    def __init__(self, name: str, pin: int, settle_s: float = 0.25) -> None:
        self.name = name
        self.settle_s = settle_s
        self._pin = _make_pin(name, pin)
        self._stub_tag = " [stub]" if isinstance(self._pin, _NullPin) else ""
        self._lock = threading.RLock()
        self._holders = 0
        self._forced_off = 0
        self._lit_since: float | None = None
        self._last_lit_duration = 0.0

    # -- state -------------------------------------------------------------

    @property
    def is_lit(self) -> bool:
        return self._lit_since is not None

    @property
    def was_lit_for(self) -> float:
        """Seconds the lamp has been lit, or how long it was lit last time.

        Logged with every measurement: a high value means a warm package and
        therefore reduced light output in frame A.
        """
        with self._lock:
            if self._lit_since is not None:
                return time.monotonic() - self._lit_since
            return self._last_lit_duration

    # -- internal switching ------------------------------------------------

    def _apply(self) -> None:
        """Lit if somebody holds it and nobody has forced it off."""
        want = self._holders > 0 and self._forced_off == 0
        if want and self._lit_since is None:
            self._pin.on()
            self._lit_since = time.monotonic()
            log.info("%s ON%s (holders=%d)", self.name, self._stub_tag, self._holders)
        elif not want and self._lit_since is not None:
            self._pin.off()
            self._last_lit_duration = time.monotonic() - self._lit_since
            self._lit_since = None
            log.info("%s OFF%s (was lit for %.1f s)",
                     self.name, self._stub_tag, self._last_lit_duration)

    # -- public API --------------------------------------------------------

    def acquire(self) -> None:
        with self._lock:
            self._holders += 1
            self._apply()

    def release(self) -> None:
        with self._lock:
            if self._holders == 0:
                log.warning("%s: release() without matching acquire()", self.name)
                return
            self._holders -= 1
            self._apply()

    @contextmanager
    def held(self):
        self.acquire()
        try:
            yield self
        finally:
            self.release()

    def force_off(self) -> None:
        """Hold the lamp off regardless of who else wants it lit."""
        with self._lock:
            self._forced_off += 1
            self._apply()

    def unforce_off(self) -> None:
        with self._lock:
            if self._forced_off == 0:
                log.warning("%s: unforce_off() without matching force_off()", self.name)
                return
            self._forced_off -= 1
            self._apply()

    @contextmanager
    def forced_off(self):
        """Force the lamp off regardless of viewers -- for frame B."""
        self.force_off()
        try:
            yield self
        finally:
            self.unforce_off()

    @contextmanager
    def settled(self):
        """Light up and wait out a *fixed* warm-up before exposing.

        Gives frame A the same thermal starting point every time, regardless
        of whether a viewer has just been holding the lamp on.
        """
        with self.held():
            time.sleep(self.settle_s)
            yield self

    def shutdown(self) -> None:
        with self._lock:
            self._holders = 0
            self._forced_off = 0
            self._apply()
