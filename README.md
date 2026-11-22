# Krausencamera

A camera in a fermenter lid that measures **krausen height** — how high the
yeast foam stands above the beer — and publishes it to Home Assistant every
few minutes, with a live view, recordings and a timelapse of every batch.

It exists to qualify new yeast strains. How high and how fast does a strain
build foam, and when does it fall? That decides the risk of blow-off into
equipment that must not see foam, and it lets an unknown yeast be run at low
starting pressure on the strength of a measurement, rather than at a
defensively high pressure that suppresses the yeast's expression.

A qualification instrument rather than a permanent process sensor: it runs for
a few batches per new strain and then comes off. Part of Gammabrewery.

## How it measures

A Raspberry Pi Zero 2 W and a **Camera Module 3 NoIR** sit in one printed
housing on the sight glass in the fermenter lid, looking straight down. Nothing
enters the tank. An 850 nm lamp lights the surface, so fermentation never sees
visible light.

**The distance comes from the camera's own autofocus.** The IMX708 has
phase-detect pixels. Every five minutes the service runs one autofocus cycle
and reads where the lens settled, in dioptres. A calibration taken on a
motorised stage turns dioptres into millimetres: a hyperbola,
`dpt = a + b/(d + c)`, plus a tabulated correction for what the hyperbola
misses.

**The krausen height is a difference.** At fill, *Set zero at fill level*
stores the distance to the beer surface. Every later reading is subtracted from
it, so foam rising towards the lid reads as a positive height.

Most of the work went into keeping the reading still. Every item below was
measured, and each was worth a millimetre or more before it was dealt with:

| what moves the reading | what is done about it |
|---|---|
| the camera warming from cold, 10.9 mm over half an hour | no heights during a warm-up after each start, scaled to how long the service was down, up to 75 min |
| the lens's holding current heating the module | the lens is parked at 0 dpt between measurements |
| the lid's temperature, ~0.05 dpt/°C | a DS18B20 in the aluminium plate the module sits against; every reading is corrected to the temperature at the zero |
| the lamp's own heat, 0.7 mm | the lamp stays lit all the time, as during calibration |
| a slower frame cooling the sensor | 30 fps held throughout, exposures capped at 32 ms |

With all of that held, a fixed target reads **~0.1–0.25 mm** from point to
point, and the calibration fits to **0.27 mm rms** out to 130 mm. A 12-hour
fermentation curve played on the stage, peaking at 80 mm, was measured to
**0.5 mm rms**.

What a reading cannot do is just as much part of the design:

- **A glassy surface gives no reading.** With nothing to focus on, the
  autofocus reports a failure instead of a number: no value, not a guess and
  not the tank bottom. A zero needs a few bubbles on the wort.
- **Foam closer than ~25 mm to the lid runs the lens into its end stop.** That
  is reported as *In the neck*, a blow-off warning that needs no calibration.
- **Every calibration belongs to one module in one housing.** Rebuild either
  and the calibration has to be taken again. On the stage that is one
  unattended night.

### Why not the laser

The first design ranged by laser triangulation: a dot beside the camera, its
position in the image giving the distance. It was precise on paper and wrong
in practice:

- **The geometry crept** by tens of pixels over days.
- **Clear liquid returned the bottom** of the vessel at 0.06 px repeatability,
  with nothing in the signal to say it was the wrong surface.

The autofocus held still throughout. The laser came out on 2026-10-03.
[`CLAUDE.md`](CLAUDE.md) keeps the whole story, because the negative results
are worth as much as the positive ones.

## What it produces

| where | what |
|---|---|
| **Home Assistant**, MQTT discovery | *Krausen height*, *Distance to surface*, *Status*, *Last measurement*, *In the neck*, *Measurement stalled*; diagnostics such as lens position and temperatures. Buttons *Start new batch* and *Set zero at fill level*, switch *Recording*, number *Measurement interval* (2–60 min). |
| **Live view** on the Pi, port 80 | the camera in a browser, 2–30 fps per viewer, and recording |
| **Recordings** | hardware H.264 from the live stream, up to 5 min, for watching a dry hop back |
| **Archive** on a NAS | one folder per batch: frames, every measurement and every zero, recordings |
| **Timelapse page** per batch | the frames as a flip-book above the krausen curve, with scrubbing, a range and film export; plus a start page listing every batch |

Home Assistant is only in the data path, never the image path. The service
writes only to the Pi's own SD card. A separate timer copies the archive to the
NAS, so a NAS or network problem can never stall a measurement.

Nothing stale is shown as fresh. State is not retained, every sensor expires
after three missed intervals, and heights are empty unless the point is valid.

## Keeping itself running

- **A camera that stops delivering frames** makes the service exit for a
  restart within 15 s. Five restarts in ten minutes reboots the Pi.
- **A measurement that stops** for 11 minutes sets *Measurement stalled* in
  Home Assistant. The service also says *offline* when it stops, and its MQTT
  will says it if it dies.
- **WiFi that NetworkManager has given up on** is reconnected by
  `krausencamera-wifivakt` within two minutes.
- **The journal and a per-minute memory log** are kept on the SD card, so a
  fault found the next morning can still be read.

## Hardware

| part | detail |
|---|---|
| Computer | Raspberry Pi Zero 2 W, Debian 13 Trixie 64-bit |
| Camera | Camera Module 3 **NoIR**, IMX708, against an aluminium plate through thermal paste; the plate seats in the sight glass and carries the camera's heat into the lid |
| Illumination | 3 × 850 nm LED (Vishay TSHG5410) from 12 V, switched by a MOSFET on GPIO10 |
| Temperature | DS18B20 on 1-Wire, GPIO24, in a pocket in the aluminium plate |
| Power | Pimoroni Wide Input SHIM on pins 1–12 |
| Housing | one printed housing for the Pi and the camera, with a thermal barrier between them and a chimney over the Pi's heatsink |
| Calibration stage | an Ultimaker 2 Z axis on a TinyG, driven from the Pi over USB |

## Setting one up

Everything goes through an SSH alias, `krausencamera`, so the commands work
whatever address the Pi has. Site-specific addresses belong in a gitignored
`LOCAL.md`, never in the repository.

```bash
sudo apt update && sudo apt install -y python3-picamera2   # on the Pi; apt, not pip
rsync -avz --exclude '.git' --exclude '__pycache__' ./src/ krausencamera:~/krausencamera/
```

Never use `rsync --delete` here. The Pi's folder also holds files that exist
only there: credentials, the zero, the calibration in use and every
measurement.

The service, the archive timer, the WiFi watchdog and the persistent journal
are all installed from [`systemd/`](systemd/README.md). Two files have to be
supplied per unit:

- **`mqtt.json`**, the broker and its credentials, from
  [`src/mqtt.example.json`](src/mqtt.example.json). It stays on the Pi.
- **`af-model.csv`**, the calibration for this module in this housing, made on
  the stage with `kalibrering.sh`, `autocal.py` and `afmodell.py`.

## Status, November 2026

In service on the test rig since late September, against a fixed target and a
simulated fermentation on the stage. A tray of flat beer showed that it reads a
liquid surface, follows foam down and fails visibly on a clear surface. Not yet
run on a real fermentation.

Open:

- **Occasional camera frontend timeouts.** Each recovers in about 30 s without
  losing a point. The current suspect is the archive sync's work against the
  NAS; a fix is under test since 2026-11-22.
- **A slow ~1 mm drift that follows the garage humidity.** A real tank, with no
  wooden rig around it, will show whether it belongs to the camera.

## Documents

- [`CLAUDE.md`](CLAUDE.md): the measurement log. Every result, every
  retraction, and the reasoning behind each design decision.
- [`BRIEFING.md`](BRIEFING.md): the original brief, with its optical geometry
  and calibration method (written for the laser design).
- [`OPTICS.md`](OPTICS.md): depth of field, and why it is not the constraint.
- [`HOUSING.md`](HOUSING.md): housing requirements from the laser era, kept
  for the measurements behind them.
- [`systemd/README.md`](systemd/README.md): installing and running the
  services.
