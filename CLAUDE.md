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

> **Viewer IPs are not what they seem over VPN.** A Tailscale subnet router
> source-NATs by default, so every viewer arriving over the tunnel is logged as
> the router's LAN address rather than its own. In this setup the router runs on
> the Home Assistant host, which made ordinary phone-from-the-bedroom viewing
> look like Home Assistant connecting to the stream — contradicting the explicit
> decision to keep HASS out of the image path. It had not. Confirmed by checking
> `$SSH_CLIENT` from the same tunnel: also the router's address.
> `--snat-subnet-routes=false` preserves the real source, at the cost of needing
> a route back to `100.64/10` on the Pi. Note it is the *subnet routing*, not the
> exit-node function, that does this.

> **The stream endpoint is unauthenticated and actuates hardware.** Anything on
> the LAN or the tailnet can open the page and switch the IR lamp on. Harmless
> while the LED is unwired, but once it is fitted an unnoticed viewer changes the
> lamp's thermal state — which is exactly the drift that contaminates frame A.
> `forced_off()` and the logged `was_lit_for` keep the measurement *correct*;
> preventing unexpected actuation in the first place still wants a token in the
> URL or binding to the Tailscale interface.

Status 2026-09-03: live view verified at 30 fps on the lores stream. Reference
counting tested with two overlapping viewers — the lamp stayed lit until the
last one left. GPIO17 is driven for real via gpiozero 2.0.1.

## ⚠️ YUV420 Y is limited range 16-235

This has produced two wrong conclusions in this project, so it is worth stating
plainly: `capture_array("main")` on a YUV420 configuration returns a Y plane in
**video range, 16-235** — not 0-255. Black is 16 and white is 235.

- A saturation test for `>= 250` on that plane **can never fire**. It once
  reported 0 % saturation on a scene that was in fact clipping 8.8 %.
- A dark frame reads ~15.5, not ~0. That was briefly mistaken for a light leak,
  and a ceiling light was switched off to chase it. Measured 2026-09-04: the
  residual was flat to within 0.18 counts across a 3x3 grid — a pedestal, not
  light. Real leakage would be spatially structured, brightest near its entry.

**Consequence for the laser centroid.** Frame B's background sits at 16. A
centroid computed as `sum(I*x)/sum(I)` over an image with a uniform pedestal is
pulled towards the frame centre, and the weaker the dot the worse the pull. The
pedestal must be subtracted, or a threshold applied, **before** computing the
centroid.

This error is invisible after the fact: the calibration table absorbs the bias
and everything looks consistent until the geometry changes and the table no
longer applies. Convert to full range, or work in RGB888, when photometry or
centroids matter.

## Laser: first calibration measurement (2026-09-04)

Laser mounted, GPIO27, enable active high. Measured with `laser_probe.py` and
`laser_repeatability.py`, against a flat matte target in the cardboard dummy.

| | measured | expected |
|---|---|---|
| Dot radius from image centre | 194.3 px | — |
| In object space at 12.71 px/mm | **15.29 mm** | 15.0 mm baseline (CAD) |
| Deviation | **+1.9 %** | — |
| Sensitivity dr/dd at 130 mm | 1.50 px/mm | — |
| ...extrapolated to 150 mm rest level | 1.12 px/mm | brief says ~1 px/mm |
| Short-term repeatability of r | 0.070 px std | — |
| ...in height | **47 µm** | brief says 300–500 µm |

The derived sensitivity matches the brief's optical analysis at rest level, and
the dot lands within a couple of percent of where the CAD baseline predicts.

> **What this check can and cannot establish.** It agrees to ~2 %, but it cannot
> discriminate 15.0 mm from the 15.5 mm the brief quotes — against 15.5 the same
> measurement reads −1.4 %. The scale of 12.71 px/mm comes from an FFT of a
> folding rule, assuming exactly 1 mm graduations lying square in the focal
> plane, and a couple of percent of error there passes straight through.
>
> Nor can it be inverted to calibrate the scale from the known baseline, because
> the laser's mounting angle is unknown — one of the three reasons the brief
> gives for building a lookup table instead of computing the triangulation.
>
> So: a consistency check at the few-percent level, and no more. Which is
> exactly why the table is measured against known liquid levels.

### The dot saturates hard

Peak stayed pinned at the limited-range ceiling from 12 ms all the way down to
800 µs, and only came free at **200 µs** — sixty times shorter than frame A's
exposure. A clipped dot has a flat top, so the centroid is computed over a
plateau instead of a profile and the sub-pixel precision is gone.

**Frame A and frame B therefore need different exposures**, set per frame.
`ExposureTime` is a runtime control, so this needs no reconfiguration.

### What 47 µm does and does not mean

It is short-term repeatability on a **static matte surface** over 25 frames in
a few seconds. It measures noise, not accuracy, and says nothing about drift or
systematic error.

It says nothing at all about **foam**, which is the real target: krausen is a
live, irregular, translucent bubble surface where the beam scatters subsurface
rather than reflecting off a defined plane, and where bursting bubbles move the
spot. The honest conclusion is not a resolution figure but that **the optics and
electronics are no longer the limiting factor** — whatever precision the
instrument ends up with will be set by the foam.

> **Observation:** the y centroid is ~8× noisier than x (0.180 vs 0.023 px),
> consistent across 25 frames. Most likely temporal row noise in the sensor,
> which biases a y centroid but averages out in x. Of no practical consequence
> here — the measured quantity is the radius, which inherits mostly from x since
> the dot sits 186 px sideways against 56 px up.

## Aperture: 1.5 mm printed stop (2026-09-05)

A printed ABS-GF sleeve over the lens, hole printed rather than drilled.

**It stops down exactly as intended.** Signal above the pedestal fell from
148.76 to 47.89 at identical exposure, a ratio of **0.322** against 0.32
predicted for a 1.5 mm hole. Working back, `N = 1.8/sqrt(0.322) = 3.17`, so
`D = 4.74/3.17 = 1.50 mm`. No drilling needed.

Depth of field measured from the sweep curve, illumination on, settle corrected:

| criterion | dioptres | distance | depth |
|---|---|---|---|
| 90 % | 6.00–8.00 | 125–167 mm | 42 mm |
| 80 % | 5.50–8.50 | 118–182 mm | **64 mm** |
| 70 % | 5.00–9.00 | 111–200 mm | 89 mm |

The normal krausen band of 10–30 mm fits with wide margin. Exposure for frame A
becomes 37 ms, which needs the frame-duration cap lifted (below).

> **The 23 mm figure from 2026-09-03 is not a valid comparison.** It was derived
> from the sweep's width in dioptres rather than measured by moving the target,
> and it was taken with a settle time now known to be too short. Re-measure
> without the sleeve, with the corrected tool, before quoting any ratio.

### Frame duration caps exposure

The default video configuration pins `FrameDurationLimits` at `(33333, 33333)`,
so exposure cannot exceed 33 ms — a frame cannot be shorter than its own
exposure. The brief calls for 50–100 ms as the first thing to reach for when
light is short, and stopping down makes that necessary. `frame_duration_for()`
now derives the limits from the requested exposure. Verified: a request for
37000 µs yields `ExposureTime 36982`, `FrameDuration 37997`.

### Two faults found in the sweep tool

**It never switched the illumination on.** The tool worked while the LEDs were
driven externally and always lit. Once they moved to GPIO17 it silently swept a
dark scene and returned a flat curve at the noise floor — no error, just a
plausible-looking result that meant nothing. It now holds the lamp for the
duration and warns if the region of interest is dark.

**The settle time was too short.** Measured directly by commanding a 7.35
dioptre jump and sampling every 0.24 s: nothing moves for ~0.7 s, the transition
takes ~0.3 s, and the reading is stable from ~1.2 s, the same from both
directions. Most of that is pipeline latency, not the actuator. The old
`0.35 + 0.04/dioptre` sampled inside the transition.

## Focus sweep

`src/focus_sweep.py` sweeps `LensPosition` and reports the sharpest setting from
two independent metrics (Laplacian variance and mean gradient magnitude). It
locks exposure, gain and white balance first — with auto-exposure running, a
sharpness metric partly measures brightness drift between steps instead of focus.

```bash
ssh krausencamera 'cd ~/krausencamera && python3 focus_sweep.py --save /tmp/sharp.jpg'
```

The sweep doubles as a **distance measurement**: LensPosition is in dioptres, so
the peak gives the object distance as 1000/position mm — useful for checking a
mechanical setup without measuring it mechanically. The reference plane inside
the lens is not known exactly, so treat the figure as repeatable rather than
absolute.

**First result, 2026-09-03, visible room light, provisional distance:**

| | Run 1 | Run 2 |
|---|---|---|
| peak, Laplacian | 7.80 dpt | 7.70 dpt |
| peak, gradient | 7.80 dpt | 7.40 dpt |
| implied distance | 128 mm | 130 mm |

The optimum is a **plateau, not a point**: 7.4–7.8 dpt all sit within 3 % of peak
sharpness. Useful precision is therefore about ±0.2 dpt, and quoting two decimals
would be false confidence. Peak sharpness is ~14× the defocused floor, so the
target had ample contrast.

Scale measured from a steel rule in frame: **~15.5 px/mm** at 2304×1296, so
roughly 150 mm of horizontal field. Half-millimetre graduations are resolved.

⚠️ Provisional on two counts: the working distance is not yet the final one, and
the brief requires the sweep to be repeated under **850 nm IR**, whose focal
plane differs from that of visible light.

> **Settle time must scale with travel.** A fixed settle is fine for steps within
> a sweep but not for the jump between sweeps. Measured: the coarse sweep ended
> at 15.0 dpt and the fine sweep began at 6.50, and that first point read
> lap=13.5 where its neighbours implied ~45 — the lens was still moving when the
> frame was taken. Now `base + 40 ms per dioptre`; the same point then read 60.6
> and fitted its neighbours.

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
2. **Reference counting with a timeout.** Lamp on if ≥1 viewer — but "connection
   open" is not the same as "somebody is watching". Measured 2026-09-03: a client
   that stops reading while holding the socket open (a backgrounded tab, a
   minimised phone app) leaves the server blocked in `wfile.write()` once the
   kernel send buffer fills. The lamp then stays lit until TCP keepalive
   notices — **two hours** by default on Linux.
   Fixed with `connection.settimeout(--stream-timeout)`, default 10 s. Verified:
   the viewer is dropped ~9 s after it stops reading, without the client ever
   closing the socket. A normally reading viewer is unaffected.
3. **⚠️ Thermal drift of the LED.** Light output falls as the package warms. A
   viewer watching for ten minutes leaves the lamp hot, and the next frame A
   comes out dimmer than one taken from cold. That is **exactly the brightness
   change the brief wants to measure** as the krausen builds. Locking the
   exposure does not help — the error is in the light source, not the camera.
   Remedy: always take frame A after a **fixed warm-up from a known state**, and
   log the lamp's prior state so the analysis can flag affected frames.

   **Measured 2026-09-04**, three 850 nm LEDs at 114 mA potted in a PE/PTFE rod,
   locked exposure, cold start after 19 minutes off:

   | | |
   |---|---|
   | cold start | 170.19 mean level |
   | settled | 165.37 |
   | **total droop** | **−2.83 %** |
   | half the change | 1.7 min |
   | 90 % | 8.5 min |
   | 99 % | 19.1 min |

   Two time constants stacked: the junction heats in under two minutes, the
   surrounding plastic mass over roughly twenty. At ~1 % output per 10 °C that
   is around 28 °C of package rise — the potting really is a thermos.

   So `was_lit_for` spans about **2.8 %**, which is small next to the ~130 % the
   scene brightens as the krausen rises toward the lamp. Worth flagging in
   metadata, not worth correcting for. Ten minutes of warm-up puts you within
   0.2 % of settled.

   ⚠️ Beware measuring this on the tail: an earlier reading over 13 minutes of
   an already-warm lamp showed only −0.3 % and led to the wrong conclusion that
   the LEDs barely heat at all.

### Stream rate is chosen per viewer

The live view serves two different jobs, and they want different rates:

- **checking whether anything is happening** — a couple of frames per second is
  plenty, and cheap
- **watching a dry hop** — hops being drawn under by the agitator is real motion
  at real speed, and needs the full sensor rate to be worth looking at

So the rate is per connection (`?fps=N`, presets on the page) rather than fixed.
Frames above the requested rate are simply dropped; the encoder runs at sensor
rate regardless. Measured 2026-09-03:

| Requested | Measured | Bandwidth |
|---|---|---|
| 2 fps | 2.2 fps | 33 kB/s |
| 10 fps (default) | 10.0 fps | 148 kB/s |
| 30 fps | 30.0 fps | 443 kB/s |

> The interval test compares against `min_interval * 0.9`. At the sensor rate the
> target interval equals the frame period, so a strict comparison loses every
> other frame to jitter and delivers about two thirds of what was asked for
> (measured: 20.3 fps for a requested 30). The tolerance costs at most ~10 %
> overshoot at low rates, which is why 2 fps measures 2.2.

### Thermal: much less of a problem than feared

Measured during a sustained 30 fps stream: **51.5 °C, nothing active in
`throttled`** — nine degrees below the 60 °C soft limit. MJPEG encoding of the
768×432 lores stream is hardware-accelerated and close to free.

The earlier concern that the live view would be the system's problematic
sustained load does not survive measurement. Watching a whole dry hop at full
rate is fine. The enclosure still has to be thought through, but the margin is
comfortable rather than tight.
