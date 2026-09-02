"""Referensräknad styrning av IR-belysning och laser.

Två konsumenter delar IR-lampan: mätcykeln och livevyn. Det ställer tre krav
som är billiga att bygga in nu och besvärliga att lägga till efteråt:

1. Mätcykelns bildruta B tas i mörker med bara lasern tänd. En ansluten
   tittare får inte hålla lampan tänd då -- därav `forced_off()`.
2. En webbläsarflik som dör utan att stänga snyggt får inte lämna lampan
   tänd för alltid -- därav referensräkning med `release()` i finally.
3. LED:ens ljusutbyte sjunker när kapseln blir varm. Bildruta A måste därför
   tas efter en *fast* tändtid från känt läge, annars läcker den termiska
   driften in i just den ljusstyrkemätning som ska säga något om krausen.
   `settled()` sköter det, och `was_lit_for` loggas med varje mätning så
   analysen kan flagga rutor tagna med varm lampa.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


class _NullPin:
    """Fallback tills GPIO är inkopplat -- loggar i stället för att lysa."""

    def __init__(self, name: str, pin: int) -> None:
        self._name = name
        self._pin = pin
        self.value = 0

    def on(self) -> None:
        self.value = 1

    def off(self) -> None:
        self.value = 0


def _make_pin(name: str, pin: int):
    """Riktig GPIO om den går att ta, annars en stub.

    Både importen och själva anspråket kan fallera -- gpiozero kastar t.ex.
    lgpio.error('GPIO busy') om en annan process redan håller stiftet, och
    BadPinFactory när inget backend finns. Ingen av dem är ImportError, och
    ingen av dem ska hindra servern från att starta utan hårdvara.
    """
    try:
        from gpiozero import DigitalOutputDevice
    except ImportError:
        log.warning("gpiozero saknas -- %s körs som STUB, ingen GPIO", name)
        return _NullPin(name, pin)
    try:
        return DigitalOutputDevice(pin, active_high=True, initial_value=False)
    except Exception as exc:
        log.warning("GPIO%d gick inte att ta (%s) -- %s körs som STUB", pin, exc, name)
        return _NullPin(name, pin)


class Lamp:
    """En MOSFET-driven last med referensräkning och känd tändhistorik."""

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

    # -- tillstånd ---------------------------------------------------------

    @property
    def is_lit(self) -> bool:
        return self._lit_since is not None

    @property
    def was_lit_for(self) -> float:
        """Sekunder lampan varit tänd, eller hur länge den var tänd senast.

        Loggas med varje mätning: ett högt värde betyder varm kapsel och
        därmed lägre ljusutbyte i bildruta A.
        """
        with self._lock:
            if self._lit_since is not None:
                return time.monotonic() - self._lit_since
            return self._last_lit_duration

    # -- intern växling ----------------------------------------------------

    def _apply(self) -> None:
        """Lampan lyser om någon håller den och ingen tvingat ner den."""
        want = self._holders > 0 and self._forced_off == 0
        if want and self._lit_since is None:
            self._pin.on()
            self._lit_since = time.monotonic()
            log.info("%s TÄND%s (hållare=%d)", self.name, self._stub_tag, self._holders)
        elif not want and self._lit_since is not None:
            self._pin.off()
            self._last_lit_duration = time.monotonic() - self._lit_since
            self._lit_since = None
            log.info("%s SLÄCKT%s (var tänd %.1f s)",
                     self.name, self._stub_tag, self._last_lit_duration)

    # -- publikt API -------------------------------------------------------

    def acquire(self) -> None:
        with self._lock:
            self._holders += 1
            self._apply()

    def release(self) -> None:
        with self._lock:
            if self._holders == 0:
                log.warning("%s: release() utan matchande acquire()", self.name)
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

    @contextmanager
    def forced_off(self):
        """Tvinga ner lampan oavsett tittare -- för bildruta B."""
        with self._lock:
            self._forced_off += 1
            self._apply()
        try:
            yield self
        finally:
            with self._lock:
                self._forced_off -= 1
                self._apply()

    @contextmanager
    def settled(self):
        """Tänd och vänta ut en *fast* tändtid innan exponering.

        Ger bildruta A samma termiska utgångsläge varje gång, oberoende av
        om en tittare nyss haft lampan tänd.
        """
        with self.held():
            time.sleep(self.settle_s)
            yield self

    def shutdown(self) -> None:
        with self._lock:
            self._holders = 0
            self._forced_off = 0
            self._apply()
