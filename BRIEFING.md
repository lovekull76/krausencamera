# Krausen camera — handover brief

## What is to be built

A camera mounted in the lid of a Brewtools F80 fermenter, looking straight down
through a sight glass at the beer surface. It shall:

1. Take one frame per minute throughout fermentation and archive it on the NAS.
2. Measure krausen height in millimetres by laser triangulation and publish it
   over MQTT.
3. Offer a live view in Home Assistant on demand.

The purpose is to qualify new yeast strains: how high and how fast they build
foam, and whether that foam is dry and cracked or wet and climbing. That
determines the risk of blow-off into equipment that must not contain foam, and
makes it possible to run an unknown yeast at low starting pressure with
measurement as the basis for the decision, instead of defensively high pressure
which suppresses yeast expression.

This is a qualification instrument, not a permanent process sensor. It runs for a
couple of batches per new strain and is then removed.

## Hardware

| Part | Detail |
|---|---|
| Computer | Raspberry Pi 3B+, Debian 13 Trixie, 1 GB RAM |
| Camera | Raspberry Pi Camera Module 3 **NoIR**, standard 75° (IMX708) |
| Illumination | 850 nm IR LED cast into a PMMA rod, separate port |
| Laser | Red 650 nm module with driver board, logic input "S" |
| Switching | MOSFET driver boards, 3.3 V compatible, one per load |
| Network | WiFi |

The Pi and all optics sit in a rigid body on top of the sight glass. **Nothing
enters the tube** — it is only what clips the field of view.

## Optical geometry

- Sight glass in a DN40 port in the lid, 38 mm inner diameter
- Distance from lens to tube mouth (called **L**): roughly 40–45 mm, to be measured
- From tube mouth to maximum liquid level: 104 mm
- The tube mouth limits the field of view, not the lens — the camera sees 41°
  vertically, the tube gives about 46°
- The visible circle on the wort surface is therefore about 126–137 mm

The tube mouth appears as a ring in the image. It is a fixed reference for image
registration. The ring being clipped at top and bottom is intentional — the
sensor is 16:9 and you gain area laterally.

**The laser sits 15.5 mm from the camera axis, parallel to it.** The dot's radial
position in the image gives the distance to the surface. Sensitivity is about
1 px/mm at rest level and 6 px/mm as the krausen approaches the mouth, in binned
mode. Centroid computation gives sub-pixel resolution, so around 0.3–0.5 mm.

## Software requirements

**picamera2**, not the legacy stack. Installed with `apt`, not pip — the bindings
come from libcamera. On Debian 13, PEP 668 applies, so a venv needs
`--system-site-packages` to see picamera2.

**Fixed focus.** `AfMode` manual, `LensPosition` in dioptres (1 divided by the
distance in metres). For 140 mm that is 7.1. The exact value is found by sweeping
and picking the sharpest — lens calibration varies between units. The sweep must
be done **with the working illumination on**, since the focal plane for 850 nm
differs from that for visible light.

**Locked exposure.** `AeEnable=False` with explicit `ExposureTime` and
`AnalogueGain`. `AwbEnable=False` with fixed `ColourGains`. Without this the
automatics compensate away exactly the brightness change that is to be measured
as the krausen builds, and the time series becomes useless for automated analysis.

**A single video configuration at all times**, 2304×1296 (the sensor's 2×2 binned
mode). Frames are grabbed from the stream rather than switching to still mode —
mode changes require a sensor reconfiguration and are the only genuinely slow
operation. Binning also gives four times the signal per pixel.

**Two frames per measurement cycle:**
- **A** — illumination on, laser off. Gives krausen structure and relief.
- **B** — illumination off, laser on. The laser dot is then the only bright thing
  in a near-black image, which makes the centroid computation trivial.

**Exposure time is free.** Nothing moves — the krausen rises millimetres per
minute. 50–100 ms is entirely unproblematic and is the first knob to turn if
there is not enough light.

## Architecture

The Pi owns the whole measurement cycle: illuminate, expose, switch, expose,
extinguish, compute, publish, store.

Images are written to a mounted SMB share on the NAS. A local fallback directory
if the mount is down, but **prune it when the mount returns** — unbounded
buffering on an SD card kills it.

MJPEG stream for the live view, added to HASS as `camera: platform: mjpeg`.
HASS is not in the path for measurement data.

Krausen height out over MQTT, logged alongside gravity, temperature and pressure.

> **Note (2026-09-02):** this last point has since been revised. HASS receives no
> image stream at all; the live view is served directly from the Pi and opened in
> a browser, and the IR illumination is triggered by a viewer connecting. See the
> architecture section in `CLAUDE.md`.

## Working order

1. `rpicam-hello --list-cameras` shall show the imx708. If it does not, it is the
   cable, not the software.
2. `rpicam-still -o test.jpg --autofocus-mode manual --lens-position 7.1` — a
   sharp image before any Python is written.
3. Sweep LensPosition against a test target at the working distance, lock in the
   best value.
4. Lock exposure and white balance to fixed values.
5. Video configuration with frames grabbed from the stream, two frames with GPIO
   switching in between.
6. SMB mount and storage.
7. MJPEG stream to HASS.
8. Centroid computation and MQTT — last.

## What to know about the environment

The Pi 3B+ has 1 GB of RAM and **cannot run the VS Code Remote-SSH server**.
Development happens against a Samba share from another machine, execution over
SSH in a terminal.

Camera buffers are allocated from CMA. In binned mode they are about 4.5 MB and
that is sufficient, but at full resolution the ceiling can be reached — raise
`cma` in `/boot/firmware/config.txt` if so.

## Calibration

The triangulation shall **not** be computed analytically. The lens has
distortion, the exact position of the entrance pupil is unknown, and the laser's
mounting angle has error. Instead, calibrate the dot's pixel position against
known water levels and interpolate in a table. That removes all three error
sources at once.

The unit is removed and refitted between batches. At every fill the liquid stands
at a known level — read the laser dot then and compare against the calibration.
If it deviates, something has moved. Build that check into the startup routine
from the beginning.
