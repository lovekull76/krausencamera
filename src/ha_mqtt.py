#!/usr/bin/env python3
"""Publish the measurement to Home Assistant over MQTT, with discovery.

    krausencamera/<id>/status   online | offline     retained, the LWT
    krausencamera/<id>/state    one JSON per point   NOT retained
    krausencamera/<id>/cmd/zero PRESS                never retained
    krausencamera/<id>/cmd/batch PRESS               never retained
    krausencamera/<id>/cmd/record ON | OFF           never retained
    krausencamera/<id>/recording  ON | OFF           the switch's state, on change
    krausencamera/<id>/stalled    ON | OFF           from the watchdog, not the meter
    homeassistant/device/<id>/config                 retained, device discovery

**One availability for the whole device.** Device discovery puts every entity
under one config with the availability topic at its root, so they all go
offline together. The broker publishes the will when the Pi drops off the
network (1.5 x keepalive, ~45 s); the service publishes `offline` itself on a
clean stop, since a will is not sent for a clean disconnect; and when the
watchdog kills a hung camera process, the unclean exit fires the will.

**Nothing stale is ever shown as fresh.** State is not retained: HA cannot tell
how old a retained message is, so after an HA restart it would show the last
reading as current. Every sensor carries `expire_after`, so a process that is
alive but no longer measuring -- which the will cannot see -- turns the
entities unavailable after three missed points. A timestamp sensor says when
the reading was taken. Heights are published only when the reading is valid
(status `ok`); otherwise they are null, HA shows them as unknown, and the
status sensor says why.

**HA restarting** announces itself with `online` on `homeassistant/status`.
The discovery config is re-sent and so is the last point, a few seconds later,
so the entities do not sit unknown for up to five minutes. The point is at most
one interval old and the timestamp sensor says exactly how old.

Credentials live in a JSON file on the Pi, never in the repository:
`mqtt.example.json` shows the shape.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time

log = logging.getLogger(__name__)

# Home Assistant here runs in English, and an MQTT enum shows its raw values,
# so the service's internal (Swedish) states are translated on the way out.
# The CSV and the page keep the internal names.
STATUS_EN = {"ok": "ok", "uppvarmning": "warming up", "i_halsen": "in the neck",
             "utanfor_kalibrering": "beyond calibration",
             "misslyckad": "no focus", "morkt": "lamp off"}
STATUSES = list(STATUS_EN.values())


class HaMqtt:
    def __init__(self, cfg: dict, *, device_id: str | None = None,
                 on_zero=None, on_batch=None, on_record=None,
                 interval_s: float = 300.0) -> None:
        import paho.mqtt.client as mqtt

        self.id = device_id or cfg.get("device_id") or socket.gethostname()
        self.base = f"{cfg.get('base', 'krausencamera')}/{self.id}"
        self.prefix = cfg.get("discovery_prefix", "homeassistant")
        self.t_status = f"{self.base}/status"
        self.t_state = f"{self.base}/state"
        self.t_cmd = f"{self.base}/cmd"
        self.t_birth = f"{self.prefix}/status"
        self._host = cfg["host"]
        self._port = int(cfg.get("port", 1883))
        self._keepalive = int(cfg.get("keepalive", 30))
        # three missed points before HA calls a value stale
        self._expire = int(cfg.get("expire_after", 3 * interval_s))
        self._on_zero = on_zero
        self._on_batch = on_batch
        self._on_record = on_record
        self._recording = "OFF"
        self.t_rec = f"{self.base}/recording"
        self._stalled = "OFF"
        self.t_stall = f"{self.base}/stalled"
        self._last: str | None = None
        self._lock = threading.Lock()

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"{self.id}-service", clean_session=True)
        if cfg.get("username"):
            c.username_pw_set(cfg["username"], cfg.get("password"))
        c.will_set(self.t_status, "offline", qos=1, retain=True)
        c.reconnect_delay_set(min_delay=2, max_delay=60)
        c.on_connect = self._connected
        c.on_disconnect = self._disconnected
        c.on_message = self._message
        self._c = c

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._c.connect_async(self._host, self._port, keepalive=self._keepalive)
        self._c.loop_start()
        log.info("mqtt: %s:%d as %s, availability %s", self._host, self._port,
                 self.id, self.t_status)

    def stop(self) -> None:
        """Clean stop: say offline ourselves -- no will is sent for this."""
        try:
            self._c.publish(self.t_status, "offline", qos=1, retain=True).wait_for_publish(3)
        except Exception:
            pass
        self._c.disconnect()
        self._c.loop_stop()
        log.info("mqtt: offline")

    # -- callbacks ---------------------------------------------------------

    def _connected(self, c, userdata, flags, reason, properties) -> None:
        if reason.is_failure:
            log.warning("mqtt: connect refused: %s", reason)
            return
        log.info("mqtt: connected")
        c.subscribe([(f"{self.t_cmd}/#", 1), (self.t_birth, 1)])
        self._discovery()
        c.publish(self.t_status, "online", qos=1, retain=True)
        self._resend()

    def _disconnected(self, c, userdata, flags, reason, properties) -> None:
        log.warning("mqtt: disconnected (%s), reconnecting", reason)

    def _message(self, c, userdata, msg) -> None:
        payload = msg.payload.decode(errors="replace").strip()
        if msg.topic == self.t_birth:
            if payload == "online":
                # Give HA a moment to subscribe before it is told anything.
                log.info("mqtt: Home Assistant came online -- resending")
                threading.Timer(5.0, lambda: (self._discovery(), self._resend())).start()
            return
        if msg.retain:
            # A retained command would re-run on every reconnect. Refuse it.
            log.warning("mqtt: ignoring RETAINED command on %s", msg.topic)
            return
        if msg.topic == f"{self.t_cmd}/zero":
            log.info("mqtt: zero requested")
            if self._on_zero:
                self._on_zero()
        elif msg.topic == f"{self.t_cmd}/record":
            log.info("mqtt: recording %s requested", payload)
            if self._on_record:
                threading.Thread(target=self._on_record, args=(payload == "ON",),
                                 daemon=True).start()
        elif msg.topic == f"{self.t_cmd}/batch":
            log.info("mqtt: new batch requested")
            if self._on_batch:
                self._on_batch()

    # -- publishing --------------------------------------------------------

    def _resend(self) -> None:
        with self._lock:
            last = self._last
        if last is not None:
            self._c.publish(self.t_state, last, qos=1, retain=False)
        self._c.publish(self.t_rec, self._recording, qos=1, retain=False)
        self._c.publish(self.t_stall, self._stalled, qos=1, retain=False)

    def publish_stalled(self, stalled: bool) -> None:
        """Set by the service's watchdog thread, not by the measurement.

        On 2026-09-29 the camera hung while the process and its MQTT link
        stayed up: HA saw nothing wrong until the values expired fifteen
        minutes later. A thread that is not the one that hung can say so
        sooner. Published on change; re-sent on reconnect and HA restart.
        """
        v = "ON" if stalled else "OFF"
        if v != self._stalled:
            log.warning("mqtt: measurement stalled -> %s", v)
        self._stalled = v
        self._c.publish(self.t_stall, v, qos=1, retain=False)

    def publish_recording(self, st: dict) -> None:
        """The recording switch's state, the moment it changes -- not on the
        five-minute measurement clock."""
        self._recording = "ON" if st.get("recording") else "OFF"
        self._c.publish(self.t_rec, self._recording, qos=1, retain=False)

    def publish(self, r: dict, zero_mm: float | None, batch: str | None = None) -> None:
        """One measurement from PdafMeter, as the state JSON."""
        ok = r.get("status") == "ok"
        tid = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["t"]))
        tz = time.strftime("%z", time.localtime(r["t"]))
        body = {
            "status": STATUS_EN.get(r.get("status"), r.get("status")),
            "krausen_mm": r.get("krausen_mm") if ok else None,
            "avstand_mm": r.get("d_mm") if ok else None,
            "i_halsen": r.get("status") == "i_halsen",
            "tid": f"{tid}{tz[:3]}:{tz[3:]}",
            "noll_mm": zero_mm,
            "batch": batch,
            "dpt": r.get("dpt"),
            "lock_C": r.get("lock_C"),
            "platta_C": r.get("platta_C"),
            "soc_C": r.get("soc_C"),
            "sensor_C": r.get("sensor_C"),
            "exp_us": r.get("exp_us"),
            "n_ok": r.get("n_ok"),
        }
        text = json.dumps(body)
        with self._lock:
            self._last = text
        self._c.publish(self.t_state, text, qos=1, retain=False)

    def _discovery(self) -> None:
        i, exp = self.id, self._expire

        def sensor(key, name, tpl, **kw):
            return {"p": "sensor", "unique_id": f"{i}_{key}", "name": name,
                    "stat_t": self.t_state, "val_tpl": tpl, "exp_aft": exp, **kw}

        cmps = {
            "krausen": sensor("krausen", "Krausen height", "{{ value_json.krausen_mm }}",
                              dev_cla="distance", unit_of_meas="mm",
                              stat_cla="measurement", sug_dsp_prc=1),
            "avstand": sensor("avstand", "Distance to surface", "{{ value_json.avstand_mm }}",
                              dev_cla="distance", unit_of_meas="mm",
                              stat_cla="measurement", sug_dsp_prc=1),
            "status": sensor("status", "Status", "{{ value_json.status }}",
                             dev_cla="enum", ops=STATUSES),
            "senast": sensor("senast", "Last measurement", "{{ value_json.tid }}",
                             dev_cla="timestamp"),
            "noll": sensor("noll", "Zero level", "{{ value_json.noll_mm }}",
                           dev_cla="distance", unit_of_meas="mm", sug_dsp_prc=1,
                           ent_cat="diagnostic"),
            "lock": sensor("lock", "Lid temperature", "{{ value_json.lock_C }}",
                           dev_cla="temperature", unit_of_meas="°C",
                           stat_cla="measurement", sug_dsp_prc=2,
                           ent_cat="diagnostic"),
            "platta": sensor("platta", "Plate temperature", "{{ value_json.platta_C }}",
                             dev_cla="temperature", unit_of_meas="°C",
                             stat_cla="measurement", sug_dsp_prc=2,
                             ent_cat="diagnostic"),
            "soc": sensor("soc", "Pi temperature", "{{ value_json.soc_C }}",
                          dev_cla="temperature", unit_of_meas="°C",
                          stat_cla="measurement", sug_dsp_prc=1,
                          ent_cat="diagnostic"),
            "kamera": sensor("kamera", "Camera temperature", "{{ value_json.sensor_C }}",
                             dev_cla="temperature", unit_of_meas="°C",
                             stat_cla="measurement", ent_cat="diagnostic"),
            "dpt": sensor("dpt", "Lens position", "{{ value_json.dpt }}",
                          unit_of_meas="dpt", stat_cla="measurement",
                          sug_dsp_prc=3, ent_cat="diagnostic"),
            "exp": sensor("exp", "Exposure", "{{ value_json.exp_us }}",
                          unit_of_meas="µs", ent_cat="diagnostic"),
            "stalled": {"p": "binary_sensor", "unique_id": f"{i}_stalled",
                        "name": "Measurement stalled", "dev_cla": "problem",
                        "stat_t": self.t_stall, "pl_on": "ON", "pl_off": "OFF"},
            "halsen": {"p": "binary_sensor", "unique_id": f"{i}_halsen",
                       "name": "In the neck", "dev_cla": "problem",
                       "stat_t": self.t_state,
                       "val_tpl": "{{ 'ON' if value_json.i_halsen else 'OFF' }}",
                       "exp_aft": exp},
            "batch": sensor("batch", "Batch", "{{ value_json.batch }}",
                            icon="mdi:beer"),
            "rec": {"p": "switch", "unique_id": f"{i}_rec", "name": "Recording",
                    "icon": "mdi:record-rec",
                    "cmd_t": f"{self.t_cmd}/record", "stat_t": self.t_rec,
                    "pl_on": "ON", "pl_off": "OFF", "ret": False},
            "nybatch": {"p": "button", "unique_id": f"{i}_nybatch",
                        "name": "Start new batch",
                        "cmd_t": f"{self.t_cmd}/batch", "pl_prs": "PRESS",
                        "ent_cat": "config", "ret": False},
            "nolla": {"p": "button", "unique_id": f"{i}_nolla",
                      "name": "Set zero at fill level",
                      "cmd_t": f"{self.t_cmd}/zero", "pl_prs": "PRESS",
                      "ent_cat": "config", "ret": False},
        }
        cfg = {
            "dev": {"ids": [i], "name": i.capitalize(), "mf": "Gammabrewery",
                    "mdl": "Raspberry Pi Zero 2 W + Camera Module 3 NoIR"},
            "o": {"name": "krausencamera",
                  "url": "https://github.com/lovekull/krausencamera"},
            # Availability at the root is shared by every component -- the one
            # switch that takes the whole device offline. The state topic is
            # set per component instead: a button has none.
            "avty_t": self.t_status,
            "qos": 1,
            "cmps": cmps,
        }
        self._c.publish(f"{self.prefix}/device/{i}/config", json.dumps(cfg),
                        qos=1, retain=True)
