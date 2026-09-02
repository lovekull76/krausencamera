# Krausencamera

Camera monitoring of the krausen (the yeast foam) on the fermenter.
Part of Gammabrewery. See `README.md` for the purpose and `BRIEFING.md` for the
optical geometry and calibration method.

## Hardware

- **Raspberry Pi 3B+** Rev 1.3 — hostname `krausencamera`
- **Camera Module 3 NoIR** (imx708_noir), 4608×2592, 10-bit RGGB
  - Modes: 1536×864 @120fps · 2304×1296 @56fps · 4608×2592 @14fps
  - NoIR makes IR illumination possible without disturbing fermentation with
    visible light
- 905 MB RAM + zram swap (~905 MB) · 28 GB SD card
- **WiFi only**, no cable

## Access

Every command in this repository goes through the SSH alias `krausencamera`.
Put it in `~/.ssh/config` and they all work unchanged whatever address your Pi
happens to have:

```
Host krausencamera
    HostName <your-pi-ip>
    User pi
    IdentityFile ~/.ssh/id_ed25519
```

> Addresses, MAC and other devices on the local network live in `LOCAL.md`,
> which is gitignored. That file is site-specific and does not belong in the
> repository.

**Passwordless sudo** is needed to install packages and systemd services
non-interactively. Raspberry Pi OS usually ships it, but the file can be missing:

```bash
sudo sh -c 'echo "pi ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_pi-nopasswd \
  && chmod 440 /etc/sudoers.d/010_pi-nopasswd && visudo -c'
sudo -n true && echo WORKS
```

`visudo -c` is not optional: a broken sudoers file locks you out of root
entirely, and then it is the SD card in another machine.

## Software on the Pi

- Debian 13 **Trixie**, **64-bit** (aarch64), Python **3.13.5**
- `rpicam-apps-lite` + libcamera 0.7.2 — `rpicam-still` / `rpicam-vid` / `rpicam-hello`
- `python3-picamera2` **0.3.37**, numpy 2.2.4, `python3-gpiozero` 2.0.1 (installed)

```bash
sudo apt update && sudo apt install -y python3-picamera2
```

> Python 3.13 + Trixie: picamera2 must be installed as an **apt package**, not
> via pip — the bindings come from libcamera. PEP 668 applies, so a venv needs
> `--system-site-packages` to see them. `python3-gpiozero` was already in the
> image. The install pulls in Qt/PyQt5 as a dependency (~500 MB); that is the
> preview stack and is not needed for headless operation, but cannot be
> deselected.

## ✅ Power supply: solved

**Solution: MeanWell 5.1 V / 15 W directly on the GPIO pins.** No micro-USB.

Final verification 2026-09-02 22:53, booted with `throttled=0x0`:

```
Idle 40s                     under-voltage:  0/20
1 core, 20s                  under-voltage:  0/10   arm=1400MHz  49.4'C
2 cores, 20s                 under-voltage:  0/10   arm=1399MHz  55.8'C
3 cores, 20s                 under-voltage:  0/10   arm=1200MHz  60.1'C
4 cores, 30s                 under-voltage:  0/15   arm=1200MHz  65.5'C
Camera alone 2304x1296 60s   under-voltage:  0/30   arm=600MHz   48.3'C
Camera + 2 cores, 60s        under-voltage:  0/30   arm=1200MHz  60.1'C
4 cores + camera, 60s        under-voltage:  0/30   arm=1200MHz  68.8'C
```

Final state `0x80000` — bit 19 only (*soft temp limit has occurred*).
**No under-voltage bit set at all**, and 0 voltage lines in `dmesg`.

### What the fault actually was

| Setup | Idle | Under load |
|---|---|---|
| Original cable + PSU | **95.6 %** under-voltage, 600 MHz | — |
| New cable + same PSU | 0 % | under-voltage, one 53 s episode |
| Bench supply via bad micro-USB stub, 1 A limit | ~10 % | — |
| Bench supply on GPIO pins, **1 A limit** | 0 % | **died at 4 cores** |
| Bench supply on GPIO pins, 5.1 A limit | 0 % | under-voltage at 4 cores |
| **MeanWell 5.1 V/15 W on pins** | **0 %** | **clean throughout** |

Three independent faults, all in the supply path — never in the power supply's
rating:

1. **The original cable, ~1.5 Ω.** Computed from a 0.45 V drop at 0.3 A. The
   dominant fault.
2. **The bench supply's 1 A limit** (the default on the spare slot). A Pi 3B+
   draws ~300 mA on average but has WiFi transients of 1.5–2 A. At 1 A the
   supply entered constant-current mode.
3. **The bench leads, ~0.39 Ω.** Only visible once the limit was raised to 5.1 A.

**Diagnostic tip:** resistive drop *warns first* (`Undervoltage detected`, clock
reduction, recovery). A current limit collapses straight through brownout
**without a word in the log**. Silent death under load ⇒ suspect the current
limit, not the cable.

### Thermal: heatsink fitted 2026-09-02 23:19

Standard RPi heatsink. Same ramp, same MeanWell supply, directly comparable:

| Stage | Without heatsink | With heatsink |
|---|---|---|
| 1 core | 49.4 °C · 1400 MHz · 0/10 | 46.2 °C · 1400 MHz · 0/10 |
| 2 cores | 55.8 °C · 1399 MHz · 0/10 | 52.6 °C · 1400 MHz · 0/10 |
| 3 cores | 60.1 °C · 1200 MHz · **4/10** | 58.5 °C · **1399 MHz** · **0/10** |
| 4 cores | 65.5 °C · 1200 MHz · 14/15 | 62.8 °C · 1199 MHz · 12/15 |
| Camera alone | 48.3 °C · 0/30 | 49.4 °C · 0/30 |
| **Camera + 2 cores** | 60.1 °C · 1200 MHz · **7/30** | 59.1 °C · **1399 MHz** · **1/30** |
| 4 cores + camera | 68.8 °C · 1200 MHz · 30/30 | 67.1 °C · 1199 MHz · 29/30 |

**Result:** the realistic workload (camera + 2 cores) now runs at full clock
essentially all the time — 1/30 versus 7/30, and a minimum clock of 1399 rather
than 1200 MHz. Three cores became entirely throttle-free.

**But the gain is only 2–3 °C, and constant across every load step.** That means
the dominant thermal resistance is not chip→heatsink but **heatsink→air**. At
4 cores it is still limited 12/15 — the heatsink saturates without air movement.

⚠️ Consequence for the enclosure: 3 °C of margin is eaten by a sealed body.
**A bigger heatsink inside the box does not fix this** — it meets the same
saturated heatsink→air resistance. What actually helps is a **conduction path
out of the enclosure**: a thermal pad from the SoC/heatsink to the body wall,
preferably towards the sight glass or a metal part with contact to the outside.

**The cheapest fix, though, is software:** the live view is only needed on
demand. Serving it that way rather than running a continuous stream removes the
system's only sustained load — and then the operating case is camera alone,
49.4 °C, nowhere near the limit.

### Throttled bit reference

| Value | Bits | Meaning |
|---|---|---|
| `0x0` | — | healthy |
| `0x50005` | 0, 2, 16, 18 | under-voltage *now* + throttled *now* + has occurred |
| `0xd0008` | 3, 16, 18, 19 | soft temp limit *now*, voltage event has occurred |
| `0x80000` | 19 | temp limit only has occurred — voltage has been clean |

Sticky bits are cleared only by a reboot. Odd low hex digit ⟺ bit 0 set.

## Running the live view

```bash
rsync -avz --exclude '.git' ./src/ krausencamera:~/krausencamera/
ssh -f krausencamera 'cd ~/krausencamera && setsid nohup python3 liveview.py </dev/null >liveview.log 2>&1'
```

Then open **http://krausencamera:8080/** in any browser (or the Pi's IP directly
if the hostname does not resolve on your network).
`--auto` unlocks exposure and white balance for aiming — **never when measuring**.

Three traps that cost time, worth remembering:

- `pkill -f liveview.py` matches **its own ssh command line** and kills its own
  shell. Run the kill and the start as two separate `ssh` invocations, and use a
  pattern like `[l]iveview` that cannot match itself.
- `ssh host 'cmd &'` hangs until the channel closes. `ssh -f` with
  `setsid nohup … </dev/null` is what works reliably.
- `timeout` is not present on macOS by default; use `ssh -f` instead.

Status 2026-09-03: live view verified at 30 fps on the lores stream. Reference
counting tested with two overlapping viewers — the lamp stayed lit until the
last one left. GPIO17 is driven for real via gpiozero 2.0.1.

## Workflow

Develop locally in this folder → deploy with `rsync` over SSH → run as a systemd
service on the Pi. No sshfs/Samba mount: slow and fragile over WiFi.

```bash
rsync -avz --delete --exclude '.git' ./src/ krausencamera:~/krausencamera/
```

## Architecture (settled 2026-09-02)

Departs from the brief on one point: **no MJPEG camera in HASS.**

| Channel | Content | Consumer |
|---|---|---|
| **MQTT** (discovery) | krausen height in mm, values to log | HASS |
| **Web view on the Pi** | live image, opened from phone or browser | a human, on demand |
| **NAS (SMB)** | one frame per minute, archive | later analysis |

HASS is not in the image path at all — only the data path.

### The IR lamp lights when someone connects

Consequences to build in from the start:

1. **Two consumers of the lamp.** The measurement cycle needs it lit (frame A)
   *and* dark (frame B, where the laser dot must be the only bright thing in a
   near-black image). A connected viewer holding the lamp on **ruins frame B**.
   The measurement cycle must win: the live view drops a frame for the second it
   takes.
2. **Reference counting with a timeout.** Lamp on if ≥1 viewer. A browser tab
   that dies without closing cleanly would otherwise leave the lamp lit forever
   — this needs a heartbeat or an inactivity timeout, not just "connection open".
3. **⚠️ Thermal drift of the LED.** Light output falls as the package warms. A
   viewer watching for ten minutes leaves the lamp hot, and the next frame A
   comes out dimmer than one taken from cold. That is **exactly the brightness
   change the brief wants to measure** as the krausen builds. Locking the
   exposure does not help — the error is in the light source, not the camera.
   Remedy: always take frame A after a **fixed warm-up from a known state**, and
   log the lamp's prior state so the analysis can flag affected frames.

### Thermal: solved by the architecture

Without a sustained MJPEG stream the operating case is camera alone =
**49.4 °C, no throttling**, ten degrees below the limit. The web view is
sporadic. The enclosure therefore has a healthy margin to spend.
