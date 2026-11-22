# What the housing has to provide

Requirements for building the housing of a PDAF unit: the Pi, the buck and the
camera in one printed body on the sight glass. Every item came out of a
measurement, not a specification, and each says what it protects against. The
dates point into [`CLAUDE.md`](CLAUDE.md), where the data is.

The housing is part of the instrument. Focus is read in dioptres, and at the
fill level one dioptre is ~30 mm, so the module moving by a few micrometres
against its lens or warming by a degree shows up in the reading. Almost every
requirement below is about keeping the module still and its temperature
predictable.

## Hold the module flat, without force

**Support the module so it cannot hang on its own tape.** The Camera Module 3's
sensor-and-lens package is held to its PCB by thick double-sided tape. Looking
straight down, it creeps off under its own weight and hinges away on its flex.
It was found visibly detached on 2026-09-10, after days of drift that had been
blamed on everything else. A printed shim under the package cut the drift
forty-fold. Every housing needs one, built into the printed part.

**But do not press on it.** Over four rebuilds the near end of the focus range
moved outwards with every remount, from 37 to 62 mm from the lid. The build
with by far the most force on the module lost the most range. A new module
mounted with no preload reached 24.8 mm, inside the tank's 35 mm shoulder
(2026-09-15 to 27). Pressure may damage a module permanently; that is
suggested, not measured.

**A thermal pad is 0.3 mm thin for about a day after it was compressed.** Draw
the stack against a relaxed pad, or a shim designed for 0.1 mm of compression
ends up at 0.5.

## Give the camera's heat a way out, through metal

**An aluminium plate between the module and the sight glass steel**, with
thermal paste on both faces, carries the camera's heat into the lid instead of
shutting it into the housing:

| | before | with the plate |
|---|---|---|
| camera at equilibrium | 56.0 °C | **40.0 °C** |
| optical wander while warming up | ~0.44 dpt | **0.177 dpt** |
| warm-up | 43–65 min | 71 min |

The warm-up gets longer because the plate is mass. What matters is that the
excursion more than halves. A plate turned to a tight guide fit in the sight
glass housing, its flange resting on the rim, also locates the camera.

**A DS18B20 in a pocket in the plate, beside the module.** In the final housing
it follows the reading with no lag, door openings included, and the service
corrects every reading against it. A sensor on the lid's TC ferrule was ten
minutes out of step with the reading; one in the air around it, nearly an
hour. See
[`hardware/ds18b20-sensors.md`](hardware/ds18b20-sensors.md).

## Keep the Pi's heat away from the camera

**A thermal barrier between the Pi's cavity and the camera's**, and a
**chimney ducting the Pi's heatsink** to the outside. The chimney is worth
~3 K at the SoC under load.

## The lamp: limit its current, keep it lit

Three 850 nm LEDs (Vishay TSHG5410) from 12 V. The datasheet allows 100 mA
continuous. 2 × 33 Ω measured 110 mA, so the final housing has 33 + 33 + 18 Ω,
~88 mA expected but not yet measured.

**The lamp's heat moves the reading 0.7 mm.** It stays lit all the time, as it
was during calibration, so it is a constant heat source rather than one that
switches with viewers. The housing has to be designed around that constant
load. Output droops 2.8 % from cold, over ~20 min.

## Mechanical

- **Nothing heavy on top.** An 800 g weight tried on 2026-10-08 bore on the
  printed housing and was dropped.
- **Vents facing away from splashes.** The final housing turns the camera
  180° to get there.
- **A service hatch for USB and external sensors**, but do not touch USB while
  the service runs. A replugged cable coincided to the second with a camera
  hang on 2026-10-10.
- **Ribbon and connectors seem to seat through the first thermal cycle.**
  Three camera hangs came in the 22 h after the rebuilds of 2026-10-04/05, then
  none for five days. Do not read anything into hangs in the first days of a
  new build.

## Printed parts creep, so let a new build run in

ABS-GF creeps much faster at 40–46 °C than at room temperature, and it is only
that warm while the camera runs. The build that held the module glued in a
printed shim settled at ~0.1 mm/h, decaying over days of *operating* time, not
clock time. The final housing showed no settling from its first 17 hours. Give
a new build a few days of running before its calibration is taken. A fresh
print also relaxes over its first days; annealing it before final fitting
shortens that.

## Every rebuild costs a calibration

The calibration belongs to one module in one housing. The sight glass alone
moves the apparent surface 2.75 mm nearer (8 mm of glass, n = 1.52), and the
remount itself moves the rail. After any rebuild, take all three:

- **The table:** one unattended night on the stage (`kalibrering.sh`,
  `autocal.py`, `afmodell.py`).
- **The temperature coefficient:** a night's natural swing is enough to fit it.
- **The rail:** find it with `railjakt.sh`, to confirm the near range still
  reaches the neck.

---

The previous version of this file listed requirements for the laser design:
baseline, stray light from the laser bore, frame B's exposure and a seat for
the camera board. The laser came out on 2026-10-03. That version is in the git
history, `git log -- HOUSING.md`.
