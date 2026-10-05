#!/usr/bin/env python3
"""Batches: one folder per fermentation, started by a button.

    ~/arkiv/2026-10-02_1430/bilder/A-*.jpg     frame A
    ~/arkiv/2026-10-02_1430/matningar.csv      every point, with the zero in force
    ~/arkiv/2026-10-02_1430/nollningar.csv     every zero set during the batch
    ~/arkiv/2026-10-02_1430/video/             dry-hop recordings
    ~/arkiv/utan-batch/2026-10-01/...          anything taken with no batch open

`arkivsynk.sh` copies `~/arkiv` to the NAS; nothing here touches the network.

**Starting a batch and zeroing are separate on purpose** (Love, 2026-09-28).
A batch is a fermentation; a zero is where heights are measured from, and it
may be set more than once in one batch -- before pitching and again after, or
once the surface has a skin of foam to focus on. So every zero is appended to
`nollningar.csv`, and every measurement row carries the zero it was computed
against, so any height can be recomputed later against any of them.

A new batch clears the zero. The old one belongs to a different fill, and a
height computed against it would look valid and mean nothing -- so the height
is unknown until the new batch is zeroed.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time

log = logging.getLogger(__name__)

MEAS_COLS = ["tid", "status", "dpt", "sd", "n_ok", "n", "d_mm", "noll_mm",
             "krausen_mm", "sensor_C", "lock_C", "exp_us", "niva", "tittare"]
ZERO_COLS = ["tid", "d_mm", "dpt", "lock_C"]


class Batches:
    def __init__(self, root: str = "/home/pi/arkiv",
                 state_path: str = "/home/pi/krausencamera/batch.json") -> None:
        self.root = root
        self._state_path = state_path
        try:
            with open(state_path) as f:
                self.current = json.load(f)
        except (OSError, ValueError):
            self.current = None
        os.makedirs(root, exist_ok=True)

    @property
    def id(self) -> str | None:
        return self.current["id"] if self.current else None

    def dir(self, sub: str | None = None) -> str:
        """The folder to write into now, created if need be."""
        if self.current:
            d = os.path.join(self.root, self.current["id"])
        else:
            d = os.path.join(self.root, "utan-batch", time.strftime("%Y-%m-%d"))
        if sub:
            d = os.path.join(d, sub)
        os.makedirs(d, exist_ok=True)
        return d

    def new(self) -> dict:
        """Open a new batch named by its start, date and time to the minute."""
        base = time.strftime("%Y-%m-%d_%H%M")
        bid, n = base, 1
        while os.path.exists(os.path.join(self.root, bid)):
            n += 1
            bid = f"{base}-{n}"      # two presses within one minute
        self.current = {"id": bid, "start": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(self._state_path, "w") as f:
            json.dump(self.current, f)
        self.dir()
        log.info("new batch %s", bid)
        return self.current

    def _append(self, name: str, cols: list, row: dict) -> None:
        path = os.path.join(self.dir(), name)
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    def log_measurement(self, r: dict, zero_mm: float | None) -> None:
        self._append("matningar.csv", MEAS_COLS, {**r, "noll_mm": zero_mm})

    def log_zero(self, z: dict) -> None:
        self._append("nollningar.csv", ZERO_COLS, z)
