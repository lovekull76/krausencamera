# Krausencamera

A camera that measures **krausen height** — the height of the yeast foam — in a
fermenter, in order to qualify new yeast strains. How high and how fast does the
strain build foam, and is that foam dry and cracked or wet and climbing?

That determines the risk of blow-off into equipment that must not see foam, and
it makes it possible to run an unknown yeast at low starting pressure with
measurement as the basis for the decision, rather than defensively high pressure
which suppresses yeast expression.

This is a qualification instrument, not a permanent process sensor: it runs for a
couple of batches per new strain and is then removed. Part of Gammabrewery.

## Principle

A Raspberry Pi with a **Camera Module 3 NoIR** sits in a rigid body on top of a
sight glass in the fermenter lid, looking straight down at the beer surface.
Nothing enters the tube. Two frames per measurement cycle:

| Frame | Illumination | Laser | Yields |
|---|---|---|---|
| **A** | on | off | krausen structure and relief |
| **B** | off | on | laser dot in a near-black image, making the centroid trivial |

A red laser mounted 15.5 mm from the camera axis and parallel to it gives the
distance to the surface by **triangulation**: the radial position of the dot in
the image translates into height. 850 nm IR illumination means fermentation is
never disturbed by visible light.

The triangulation is deliberately **not** computed analytically — the lens has
distortion, the exact position of the entrance pupil is unknown, and the laser's
mounting angle has error. Instead the dot's pixel position is calibrated against
known liquid levels and interpolated in a table, which removes all three error
sources at once.

## Architecture

| Channel | Content | Consumer |
|---|---|---|
| MQTT (discovery) | krausen height in mm | Home Assistant |
| Web view on the Pi | live image in a browser | a human, on demand |
| NAS (SMB) | one frame per minute | later analysis |

Home Assistant is not in the image path — only the data path.

## ⚠️ Read this first: power supply

A Raspberry Pi 3B+ trips its under-voltage detector at ~4.63 V and is then
**clocked down from 1400 to 600 MHz**. In this build that was caused by three
independent faults in the supply path — none of them in the power supply's
rating:

1. A micro-USB cable with **~1.5 Ω** resistance. On its own it accounted for
   95.6 % of time spent in under-voltage at idle.
2. A bench supply with its current limit set to **1 A**. A Pi 3B+ draws ~300 mA
   on average but has WiFi transients of 1.5–2 A.
3. Bench leads with **~0.39 Ω**.

**Solution: a MeanWell 5.1 V / 15 W feeding the GPIO pins directly**, bypassing
the micro-USB connector and the input polyfuse. After that: zero under-voltage
under every load tested.

Always check this before building anything on top:

```bash
vcgencmd get_throttled     # should be 0x0
vcgencmd measure_clock arm # should be 1400000000
dmesg | grep -ci voltage   # should be 0
```

**Diagnostic tip:** resistive voltage drop *warns first* in the log
(`Undervoltage detected`, clock reduction, recovery). A current limit collapses
straight through brownout **without a word**. Silent death under load means
suspect the current limit, not the cable.

## Hardware

| Part | Detail |
|---|---|
| Computer | Raspberry Pi 3B+, Debian 13 Trixie 64-bit, 1 GB RAM |
| Camera | Camera Module 3 **NoIR**, 75°, IMX708 |
| Illumination | 850 nm IR LED cast into a PMMA rod, separate port |
| Laser | Red 650 nm module with driver board, logic input |
| Switching | MOSFET driver boards, 3.3 V compatible, one per load |
| Power | MeanWell 5.1 V / 15 W on GPIO pins 2/4 + 6 |
| Cooling | Standard RPi heatsink (see the thermal note in CLAUDE.md) |

## Quick start

```bash
sudo apt update && sudo apt install -y python3-picamera2
rsync -avz --exclude '.git' ./src/ krausencamera:~/krausencamera/
ssh -f krausencamera 'cd ~/krausencamera && \
  setsid nohup python3 liveview.py </dev/null >liveview.log 2>&1'
```

Open **http://krausencamera:8080/**. The IR illumination switches on when the
first viewer connects and off when the last one disappears.

Pick a stream rate on the page: 2 fps to check whether anything is happening
(33 kB/s), 30 fps to watch hops being drawn under during a dry hop (443 kB/s).
The choice is per viewer and is remembered in the browser.

Run with `--auto` to unlock exposure and white balance while aiming the housing.
**Never when measuring** — the automatics would then compensate away exactly the
brightness change that is to be measured as the krausen builds.

## Status

Working: live view at 30 fps, reference-counted IR control.
Remaining: measurement cycle, centroid computation, MQTT, NAS archiving.

Wanted: recording from the live view, for watching a dry hop back afterwards.
Worth doing on the Pi rather than as a screen capture on a phone — the Pi has
the full 2304×1296 main stream with known exposure and focus, hardware H.264
encoding, and no dependency on a browser staying open for the length of a dry
hop. Note that a recording has to hold its own reference on the illumination,
independent of viewers, or the lamp goes dark the moment the tab is hidden.

See [`CLAUDE.md`](CLAUDE.md) for measurement data and details, and
[`BRIEFING.md`](BRIEFING.md) for optical geometry and calibration method.
