# Krausencamera

Camera monitoring of the krausen (the yeast foam) on the fermenter.
Part of Gammabrewery. See `README.md` for the purpose and `BRIEFING.md` for the
optical geometry and calibration method.

## Hardware

- **Raspberry Pi Zero 2 W** Rev 1.0 — hostname `krausencamera`
- **Camera Module 3 NoIR** (imx708_noir), 4608×2592, 10-bit RGGB
  - Modes: 1536×864 @120fps · 2304×1296 @56fps · 4608×2592 @14fps
  - NoIR makes IR illumination possible without disturbing fermentation with
    visible light
- 425 MB usable RAM (512 physical, less firmware reserve) of which **256 MB is
  CMA** for the camera · zram swap ~415 MB · 28 GB SD card
  - Measured 2026-09-18 under a running calibration: 268 MB used, 147
    available, 52 MB already swapped. It works, but there is not much room.
  - **Leave the CMA alone.** Measured 2026-10-01 with the full service running
    (main 2304×1296, lores 1280×720, MJPEG): **~195 MB of the 256 in use, ~200
    during a recording** (H.264 as well). The processes themselves are small --
    the service 72 MB -- and ~100 MB stays available. Cutting CMA would win at
    most ~30 MB and spend the camera's margin; on 2026-09-22 it ran out once
    (`vc_sm_cma_import_dmabuf ... failed -12`). An earlier note here called CMA
    "the obvious place to find some"; measured, it is not.

> ⚠️ **The power and thermal characterisation below was done on a 3B+**, which
> this machine no longer is. The giveaway is `arm=1400MHz` in those tables: a
> Zero 2 W tops out at 1000. Treat the temperatures, the heatsink comparison
> and the current figures as history for a different board. What carries over
> is the *diagnosis* — that every fault was in the supply path, and that a
> current limit kills silently where a resistive drop warns first. The Zero 2 W
> draws roughly a third of the 3B+ and has correspondingly smaller transients,
> so the margins are wider, not tighter. Verified 2026-09-18: `throttled=0x0`
> after 18 hours and no voltage lines in `dmesg`.
- **WiFi only**, no cable
- **GPIO** (from 2026-10-03): IR lamp **GPIO10** (pin 19), 1-Wire DS18B20 bus
  **GPIO24** (pin 18), with 3V3 on pin 17 and GND on pin 20. Power through a
  Pimoroni Wide Input SHIM on pins 1-12. GPIO10 is SPI0 MOSI, so SPI stays
  off. Before the SHIM: lamp GPIO17, bus GPIO18, laser GPIO27 (removed).

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

> **In service this is the systemd unit** (`systemd/krausencamera.service`): the
> live view on ports 80 and 8080 (`CAP_NET_BIND_SERVICE`, not root), PDAF
> measurement, MQTT, batches and recording. The section below is how it was run
> by hand during development.

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

## PDAF calibration, nine points (2026-09-10)

Measured from **the lid's underside**, which is the reference that matters: zero
there means foam against the lid. The model's offset absorbs a constant, so only
the spacing between heights has to be accurate.

```
dpt = 1.0669 + 770.3/(d + 17.21)          nine points, 43.9 to 181 mm
                                          fit rms 0.0284 dpt, LOO 1.08 mm
```

**The model form depends on the range.** Over 109-181 mm a two-parameter
`b/(d+c)` predicted better than three, so the additive term looked like
overfitting. Adding points at 53.44 and then 43.91 mm settled it the other way —
one hyperbola cannot carry the curvature from 44 to 181 mm. The near point was
measured to test exactly that, and it failed the seven-point model's prediction
by 3.77 mm before it improved anything.

> **A check was lost in the trade.** The two-parameter fit put the lens plane
> 40.58 mm above the lid, and the housing face sits at 41 — a number nobody
> supplied, landing within a millimetre of where the optics are. With three
> parameters it becomes 17.21 mm plus a 1.07 dpt additive term, which may be a
> real VCM zero offset but corresponds to nothing measurable. More parameters
> fit better and mean less.

| from the lid | dpt | mm/dpt | within-run precision |
|---|---|---|---|
| 43.91 mm | 13.69 | 4.9 | 0.11 mm |
| 71.57 mm | 9.71 | 10.2 | 0.15 mm |
| 108.32 mm | 7.25 | 20.5 | 0.28 mm |
| 144.55 mm | 5.84 | 34.0 | 0.24 mm |
| 181 mm | 4.93 | 51.0 | 0.29 mm |

Data in `calib/af-pdaf-20260910.csv`. Every point is eight AF cycles parked
low/high/high/low, taken with the camera warm.

### The folding rule read 0.5 mm high, and it was not the explanation

The residual against the seven-point fit was a **bump**: zero at 44-90, then
-2.3, -2.8, -1.7 mm at 109-145, then zero again at 162-181. Nothing optical has
that shape, and the suspect region was exactly the folding-rule measurements, so
109, 127 and 145 were re-measured with the caliper (which reaches 155 mm).

They came back **108.32, 126.37, 144.55** — the rule read 0.45-0.68 mm high,
consistently, but nothing like the 1.7-2.8 mm the model demanded. The
prediction failed.

It still changed the character of the residual, from a localised bump to a
smooth wave, and dropped the fit rms 30 %. Which sent me chasing the model form
instead — also wrong, see below.

> `89.9 -> 90.21` on re-measurement, same instrument both times. **The rig
> re-creates itself to about 0.3 mm** as the caliper sees it. That is the floor
> on what any re-measurement of a dismantled height can achieve.

### ⚠️ The camera was cold, and that is the whole story

Measured 2026-09-10, 21:00-22:01, a 60-minute session at a fixed 126.39 mm with
the camera held open and the rig untouched. Twenty-one points, all 8/8.

```
        deviation from the final plateau
    0s      -10.94 mm
  360s       -3.07
  900s       -0.77
 1800s       -0.50
 2160s       +0.00
 3600s       -0.01
```

**From cold the reading is 10.9 mm out, and it takes 36 minutes to arrive.**
Once there it is flat: the scatter of the nine point-means over the last 24
minutes was 0.00247 dpt against 0.00257 predicted by counting noise alone. There
is no drift left to measure — the settled camera is a noise-limited instrument
at **0.066 mm** here.

`af_calibrate.py` was run once per height, so every calibration point was taken
on its own cold start, at whatever phase of that curve the preceding faff
happened to land on.

### The warm-up check never worked, and it failed twice over

It asked the sensor temperature to rise less than 0.6 C between samples 30 s
apart. Over this session the temperature went 53 to 58 C in eighteen minutes —
**0.14 C per half-minute, always under the threshold.** So it fired after two
minutes every single time, regardless of how cold the camera was, and printed
`jamvikt vid 51 C` while the true equilibrium was 58.

Two separate mistakes, and the second is the more instructive:

- **The wrong quantity.** Temperature is a proxy; what matters is whether the
  reading has stopped moving. Judge that directly.
- **The wrong shape.** A difference between two neighbouring samples drowns in
  the noise long before the underlying trend does. I repeated this error live
  the same evening: I called the plateau at t=1080 s because the step from the
  previous point was -0.0009 dpt, and the curve still had 0.79 mm to go. The
  test has to be a **fitted trend over several readings**, not one step.

`warm_up()` now runs AF cycles — the same duty cycle the measurement itself
draws — and fits a slope over the last six readings, declaring equilibrium below
0.03 dpt/h. The warm-up tail runs at +0.088 dpt/h, so the two separate cleanly.
`--warmup-max` is 50 minutes; the old 25 would now time out.

### Retracted: "it is the rig, not the camera"

Written earlier the same evening, from three repeats: 109 mm re-run on an
untouched rig agreed to 0.01 mm, while 126 mm rebuilt to the same caliper height
differed by 1.46 mm. I concluded the scatter belonged to the fixture.

**That does not survive.** All three runs were separate invocations, so each sat
at a different point on a 10.9 mm warm-up curve, and the temperatures were
printed as whole numbers — a "54 versus 55 C" could be anything from 0.1 to 1.9
degrees. The two repeats differ in how warm the camera was at least as much as
in whether the rig was rebuilt, and nothing in that data separates them.

The rig may still contribute. It is simply not measured, and the 1.46 mm was not
evidence for it.

> What does survive from that round: the folding rule reads 0.45-0.68 mm high
> against the caliper, the rig re-creates to 0.3 mm as the caliper sees it, and
> extra model parameters do not absorb the residual. None of those depend on the
> camera's thermal state.

### Consequences for the table

The nine points run 54 C at 181 mm to 57 C at 44 mm — **the thermal state
correlates with distance**, because the series worked from far to near over one
day. A confound that is monotonic in the fitted variable does not show up as a
bad fit. It is absorbed into the parameters, and the calibration comes out wrong
at every temperature except the one it was measured at.

That is the likeliest source of the residual wave, and it means **the table
should be re-taken on one thermal state**. `--request` does that: the session
sleeps until a file appears, takes a point, deletes it, and never closes the
camera. Write the distance in mm into the file, or `stop` to finish. One 36
minute warm-up buys the whole table.

| | |
|---|---|
| cold start error | **10.9 mm** at 126 mm |
| time to equilibrium | **36 min** |
| settled, 8-cycle mean | **0.066 mm** — counting noise, no drift |
| settled, single AF cycle | 0.16 mm |

### Re-taking the table: one thermal state, one live view

`--request FILE` makes the session sleep until that file appears, take a point,
and delete it -- so a whole table is measured without the camera ever closing.
Write the distance in mm into the file, or `stop` to finish.

`--preview PORT` serves the lores stream while it runs. The service has to be
stopped for a calibration, so without this there is no way to see what the
camera is looking at while a height is being built, which matters most at the
far end where the target is small in frame.

**The preview also buys configuration parity, which is the better reason.**
`af_calibrate` configured a single main stream while `liveview` runs main plus
lores. If the AF statistics depend on the stream configuration at all, the table
would carry a configuration-dependent offset with nothing in the data to reveal
it. Both now use the same two streams.

> **The warm-up ran AF in the dark**, because `lamp.acquire()` sat after
> `warm_up()` in `main()` -- harmless while the check only read a temperature,
> wrong the moment it started driving AF. It read 2.99 dioptres against the
> 6.7 the target sits at, and reported equilibrium. Caught by a smoke test.
>
> This is the third time in this project that a tool has been handed a dark
> scene and returned a plausible number: the focus sweep did it when the LEDs
> moved to GPIO17, the exposure work did it once, and now this. The lamp is now
> lit before the warm-up, and `warm_up()` refuses to run with it dark.

**Build the heights near to far this time.** The old series ran far to near over
one day, which is exactly how the thermal state came to correlate with distance.
On one thermal state the order should not matter -- so running it in the
opposite order and getting the same model is a free test that it does not.

Above 155 mm the caliper does not reach. Rather than fall back on the folding
rule, which reads 0.45-0.68 mm high, stand a measured block on the target and
measure to its top: at 181 mm a 40 mm block puts the reading at 141 mm, well
inside range, and two caliper readings beat one rule reading comfortably.
Remove the block before taking the AF point.

### Three confounds, each worth a millimetre or two

The first attempt at re-taking the table on one thermal state (2026-09-10,
23:00-00:15) got four heights in and found two more confounds. Held together
they explain the old table's residual wave without needing any model deficiency.

| | worth | fixed by |
|---|---|---|
| camera not thermally settled | 10.9 mm from cold | holding the camera open, 32 min once |
| rebuild settling | 0.2-0.35 mm | a short wait; it is not the problem |
| **camera drift, hours-long tail** | **~4 mm over 8 h** | not solved -- see the retraction below |
| **ambient cooling** | ~1 mm per degree | randomise the height order |

**Rebuild settling is real but small.** Two repeats looked like fast settling --
1.79 mm over eight minutes at 90.15, 1.01 mm over 110 seconds at 108.16 -- and
were recorded as such. The photometric check says otherwise: the illumination
level moved only a fraction of what those distances demand.

```
              apparent (focus)   actual (photometric)
  90.15 mm         +1.79 mm            +0.21 mm
 108.16 mm         +1.01 mm            +0.35 mm
```

So a rebuilt stack moves **0.2-0.35 mm**, which agrees with the 0.3 mm the
caliper sees, and the remaining 65-88 % is the camera drifting. The fixture is
sound; a threaded column or preloaded spacers would solve nothing.

**Ambient is the third one, and holding the camera open does not touch it.** The
sensor read 63, 62, 62, 61, 61, 61, 60 C across the session as the garage cooled
after midnight. At 0.07 dpt/C that is over a millimetre a degree, and it
accumulates in measurement order -- which is distance order if the heights are
built in sequence. Randomising the order turns it from a bias into scatter.

> `SensorTemperature` is reported in whole degrees, so a "62 versus 61" hides
> anything from 0.1 to 1.9 C, which is 0.1 to 2 mm. The quantisation is in the
> sensor, not the logging, so it cannot be fixed -- only averaged down over many
> readings.

### The tape is a thermal barrier, and that is why temperature leads the reading

Love's observation, and it explains something that had been nagging: the sensor
temperature plateaus after about eighteen minutes while the reading keeps moving
for another quarter of an hour.

The module is held to its PCB by thick double-sided tape (the same tape that
lets it creep off in vertical mounting). Heat from the ISP and the board has to
cross that tape to reach the module. `SensorTemperature` is measured in the
sensor die, inside the module; the lens and VCM sit in the same module but
further from the heat path still. So the sensor temperature is a **leading
indicator** of the lens's temperature, not a measure of it -- it arrives first
and levels off first, while the part that actually sets focus is still warming.

Which is the real reason the trend criterion has to be on the reading. The old
temperature criterion was not merely implemented wrongly; it watched a quantity
that by construction settles before the one that matters. A half-hour time
constant also argues the tape is not thermally conductive.

### The garage door, measured properly: 0.61 mm per degree of air

2026-09-11. The overnight session was still running at a fixed 108.16 mm, rig
untouched, when the door was opened to take the car out -- 72 seconds, from
07:54:24 to 07:55:36, onto 6 C outside. The FTX extract-air sensor sits directly
above the rig and logs at far higher resolution than anything used before.

```
garage air   22.2 -> 20.9 C at 07:57, back to 21.9 by 08:09

before the door    6 pts   -0.19 mm
trough 07:57-08:07 4 pts   -0.98 mm
recovered 08:15+  10 pts   -0.44 mm

dip        -0.79 mm +- 0.06    12.6 sigma
recovery   +0.54 mm +- 0.02    27.2 sigma
```

**It dipped and came back.** That is the reversal test: settling can fall but
cannot rise again, and no trend reverses on cue from a door. What remains
against the starting point is -0.24 mm, of which -0.09 is the known creep of
0.134 mm/h over the forty minutes.

**0.61 mm per degree of garage air** at this distance.

> **The lag is the tape, measured.** The air bottomed at 07:57 and the reading
> at 07:58-08:03; the air was back by 08:09 and the reading by 08:16. The optics
> trail the air by three to seven minutes and recover more slowly than it does
> -- a thermal mass behind an insulating layer. Over the whole excursion
> `SensorTemperature` moved **one count**, 58 -> 57 -> 58. It could never have
> revealed this.

**So `SensorTemperature` is the wrong covariate.** It is quantised to whole
degrees by the sensor itself, and a degree is worth over a millimetre, so it
cannot even see an event that moves the measurement 0.8 mm. The FTX extract
temperature can: high resolution, sited above the rig, and measuring the
quantity that actually drives the error.

Consequences for taking a table: **the garage has to be thermally quiet**, with
no door, and twenty minutes of grace after any disturbance, because the optics
lag. A 15-second door opening at 08:33 left no visible trace, so the threshold
is somewhere between that and a 72-second one.

### ⚠️ Retracted: "the stack was still creeping". The rig never moved.

87 points at a fixed 108.16 mm overnight showed the reading fall 3.85 mm over
8.3 hours, and I attributed it to the rebuilt stack settling, with a fitted
2.08 hour time constant. Love said a decimetre of particle board cannot settle
three millimetres -- 3 % compression -- and asked which way the drift went.

It is away from the camera, and there is a free test for that. **Illumination
falls as the inverse square**, so a target receding 3.85 mm at 108 mm must go
6.8 % darker. The exposure sat at 8000 us all night, so the level logged with
every point is directly comparable across all 87:

```
if the target really moved to 112.01 mm
  level should have fallen  -6.8 %   ->  87.5
  level actually moved      +0.5 %   ->  93.3

scatter in the level, all night   0.11 %  =  0.06 mm of distance
```

**The target held still to a tenth of a millimetre. The entire drift is in the
camera.** With f = 4.74 mm and an image distance near 4.95 mm, 0.164 dioptres is
about **4 micrometres** of change between lens and sensor -- invisible, and
equally plausible as thermal expansion or as creep in the module's tape.

> The number was already in the file. `niva` was added so the automatic exposure
> could be audited afterwards; it is also an independent, photometric distance
> measurement, calibrated by the inverse square. The data to refute the
> conclusion was sitting in the column next to it.

**This is far worse than a settling fixture.** A jig gets dismantled; this
follows the instrument into service, and a fermentation runs for days.

**And the equilibrium test cannot see it.** The overnight drift is
**-0.0197 dpt/h**, below the 0.03 dpt/h threshold `warm_up()` uses to declare the
camera settled. A criterion tuned against a thirty-minute warm-up is blind to a
tail measured in hours. The test is not wrong for what it was built for -- it
stops the 10.9 mm cold-start error -- but it must not be read as proof that the
camera has stopped moving.

What separates the two mechanisms is that **temperature is reversible and creep
is not**. The garage warms through the day; if the reading comes back up, it is
thermal. The session was left running to find out.

## The final housing (2026-10-10 to 10-19)

The Pi, the buck and the camera in one printed housing: halves bolted with
M2.5 inserts, a tighter thermal barrier between the Pi cavity and the camera
cavity, a chimney ducting the heatsink, a service hatch for USB and external
sensors, the camera turned 180 degrees so the vents face away from splashes,
an 80 mm camera ribbon looped over the camera board. No weight on top: the
800 g tried on 10-08 bore on the printed housing and was dropped. Lamp
resistors 33+33+18 ohm (see the lamp section; ~88 mA expected, not measured).

### Settled, and the plate sensor carries temperature

The first 17 h showed **no settling at all**: plate-corrected trend +0.002 mm/h
against 0.02-0.06 mm/h in the previous housing. The DS18B20 in the aluminium
plate follows the reading **with no lag** at **0.048 dpt/C**, door dips
included -- seven openings on 10-11 moved the raw reading up to 1.3 mm and the
corrected one by the noise. The service corrects against it since 10-11
(`--lid-sensor 28-713ecb356461 --temp-coeff 0.048`).

Under two busy cores the SoC reached 79.9 C against 82.0 in the previous
housing, in air 0.8 C warmer: the chimney is worth ~3 K. The plate sits ~5.5 K
above the garage air, ~0.4 K less than before.

### Hangs cluster after rebuilds

Three `frontend timed out` in 22 h after the 10-04/05 rebuilds, then none for
five days with nothing touched. One more at 10-10 22:38, within a second of a
USB cable being replugged at the hatch -- so **do not touch USB while the
service runs**. None since, through 10-19, with the new ribbon. Likely
connectors seating through the first thermal cycle; not proven.

### The calibration: two nights, and a step past 124 mm

`af17` (17 heights, 200 visits) and `af18` (20 heights, 170 visits),
`calib/af-model-20261013.csv`: `dpt = -0.1623 + 731.78/(d + 24.14)`, rms
0.27 mm to 130 mm, leave-one-height-out 0.33. Drift inside a night
+0.2 and +1.5 mdpt/h -- the housing has settled.

**Beyond ~124 mm the reading steps 1-2 mm farther than the hyperbola**, both
nights (130.4: -1.43/-1.02, 140.4: -0.86/-1.57, 158.4: -2.15/-1.98 mm
correction). It sits exactly where the automatic exposure steps from 15 to
25 ms, and **that is not the cause**: at a fixed 123.40 mm, 15 against 25 ms
moved the reading 0.1 mm (`calib/exptest-20261013.csv`, `exptest.sh`). So it
belongs to the optics or the VCM. The table carries it: corrections applied to
158.4 mm, and the service now flags `utanfor_kalibrering` only beyond the last
applied correction (`Model.valid_max`), because a fill a few litres off 75 L
puts the zero anywhere in ~105-145 mm -- a litre is 5 mm in an F80.

### ⚠️ Never calibrate against a halftone print

Prints of an AI-generated krausen image, at the reference heights:

| target | error at 82-145 mm | in dpt |
|---|---|---|
| halftone, paper wavy | -5.5 to -10 mm | ~0.35 |
| halftone, **flat on steel** | **-5.3 to -10.9 mm** | 0.21-0.36, jumps with height |
| random 0.3 mm solid dots, wavy | -2.8 to -3.9 | |
| random 0.3 mm solid dots, flat | -0.6 to -1.8 | **~0.045, constant** |
| speckle, 0.6-1.2 mm solid dots | 0 by definition | |

A printer's halftone screen aliases on the sparse PDAF pixels and biases the
phase by a fraction of a dioptre; flat or not, it reads 5-11 mm wrong. Colour
inks are nearly invisible at 850 nm besides, so a colour print shows only its
black. Laser-printed paper waves by 3 mm -- glue anything used as a target to a
plate. The residual 0.045 dpt between two random-dot targets is a hint that
**texture scale moves PDAF slightly**, which a foam of changing bubble size
may show as ~1 mm at the fill level.

A 12 h krausen simulation on the dot print (10-14) gave 1.6 mm rms and an
80 mm peak read as 77.7: heights ~3 % low, most likely that target's bias.
The September run on the speckle gave 0.5 mm rms. The same run shrugged off a
5.8 K fall of the plate with the door open.

### Five days at a fixed target: humidity, ~0.07 mm per % RH

10-14 to 10-19, 1444 points, krausen should read 0: **0.15-0.25 mm within each
day**, against -1.8..+3.4 mm uncorrected. Across the days it slid ~1 mm and
**follows the garage humidity** (`sensor.ftx_garage_ftx_garage_extract_air_humidity`,
r = +0.93 with ~6 h lag, 0.06-0.08 mm per % RH); air temperature and time
explain it less well. **Drier reads farther.** The MDF top under the lid would
do the opposite (drier, thinner, nearer), and the XPS under the target takes
up almost no water. Candidates: the plastics in the module -- lens barrel, VCM,
glue -- where 1 mm here is ~1 um; or something else in the rig. The lamp level
fell 0.6 % with it, so at least part is a real change of distance. The tank has
no MDF, so it will tell. Over a 48 h fermentation it is worth ~0.5 mm.

### Beer in a tray: the surface, foam and the end of it (2026-10-23/24)

0.44 L of flat NEIPA, 25 mm deep in a clear 13x17 cm box on the stage, the
surface ~115 mm below the lid by geometry. The empty box read 144.0 mm -- the
speckle seen through its clear bottom -- so a reading through the beer would
land there.

- **Still beer with a few bubbles reads its surface**: 115.3 mm, two points
  0.005 dpt apart once the ripples from placing it died. Never near 144.
- **Milk-frothed foam, ~10 mm**, read 8.6 mm at the first point and fell
  smoothly to the zero in three minutes. No jump when the last foam went.
  `niva` follows the foam: 148 under foam, ~50-70 on the bare surface.
- **Overnight a bubble skin read +2-3 mm, and as it broke up into sparse
  islands the reading humped to +5-7.7 mm** (03:35-06:00) -- more than any
  bubble stands proud. Sparse, small, high-contrast features read near, the
  same direction as the halftone print. Expect a small false hump as real
  krausen collapses, on a curve that has already fallen tens of millimetres.
- **A fully clear surface fails, visibly** (`misslyckad` from 09:31): no
  texture, no value -- not the bottom, not a guess. So the zero needs some
  bubbles or foam on the wort to be set; a glassy fill has to wait for them.

Two frontend hangs that night (02:23, 05:00) and one the morning before
(08:13), after twelve days with none; each back in half a minute. They are
why the warm-up now scales with downtime.

> **Then ten in two days, and the likely cause was mine.** Temperature fitted
> for a day and then failed: hangs came at 22.2 C too. What fitted was memory.
> An OOM kill on 2026-10-24 17:01, the camera service swapped out to 2.4 MB
> resident, and 70 MB of slab -- 13 MB of `cifs_inode_cache`, 11 MB of
> `ext4_inode_cache` -- in the ~170 MB that CMA leaves. Every ten minutes the
> archive sync walked every frame locally and on the NAS, built every batch's
> page check and re-read every batch for the start page, and the half-size
> copies of 2026-10-22 doubled the file count the day before the hangs began.
> A camera thread waiting on swap cannot dequeue a frame within a second,
> which is what a frontend timeout is. Since 2026-10-25 the sync is
> incremental (a mark file; only the open batch is searched; pages only for
> batches with something new; the start page caches its summaries; pruning
> once a day): 3 s against ~70 s, and a few dozen inodes against ~25 000.
>
> **They stopped.** None in the 21 h after the change, none in 3.6 days after
> a reboot on 2026-10-26 -- against one every five hours before, so ~20
> expected. Slab 50 MB after those days (`cifs_inode_cache` 3 MB against 13),
> 122 MB available, no OOM. The lesson: on this Pi the camera needs memory
> headroom more than anything else, and a background job that walks the
> archive can take it away silently.
>
> **Back on 2026-11-01**: five in 30 h, after six clean days, one only 11 min
> after a watchdog restart. Slab was normal this time (53 MB), and so was
> `MemAvailable` (111 MB) -- but only ~24 MB of it lay outside CMA, the
> service sat two thirds in swap, and every point swapped ~20 MB back in.
> **Three of the five came within the second frame A was written**, a ~3 s
> window in 300; the other two as `man-db` and `apt-daily` started. Frame A
> copied five 12 MB frames and a 9 MB RGB image out of the camera at the
> moment the stream restarts after a point. Since 2026-11-02 09:24 it waits
> out the settling frames with `capture_metadata()` and JPEG-encodes straight
> from the CMA buffer with simplejpeg (same channel order, same 4:2:0, ~830 kB
> as before); `man-db.timer` is masked. `krausencamera-minne.service` logs
> memory, swap and the service's resident size every minute to
> `~/krausencamera/minne/`, because the journal lives in RAM and the clean
> days had left nothing to compare against. No reboot alongside, so the
> result is attributable.
>
> **It held.** Two restarts in 13 days (11-06 15:24, 11-12 08:13), each back
> within a minute and not one point lost -- 3811 points, no gap over seven
> minutes. Neither came under memory pressure: 125-136 MB available, no
> swap-in in the minutes before. About the October background rate, then,
> and not the memory mechanism; the cause is unknown because the journal had
> already gone. It is kept on the SD card since 2026-11-15
> (`systemd/journald-50-persistent.conf`, 200 MB), which also frees the up to
> 8 MB it held in tmpfs. Still to watch: slab creeps ~1 MB a day (60 -> 73 MB,
> `cifs_inode_cache` back at 9 MB), and `apt-daily-upgrade` swaps the service
> out every morning at ~06:00 -- harmless so far, the first to mask if hangs
> return.
>
> **Not a hang: 29 h off the WiFi** from 2026-11-16 15:28. One failed
> handshake after a roam, and NetworkManager gave up for good (no-secrets);
> the camera measured on locally throughout. `krausencamera-wifivakt.service`
> reconnects it now -- see `systemd/README.md`. A frontend timeout 4 min after
> the power cycle that ended it, recovered in 20 s.

### Next

A zero on a liquid surface has now been tried, see above.
Before that: a mirror may give no reading,
or focus on the lid's reflection at twice the distance with nothing to flag
it. Test with flat, hazy beer in a tray on the stage, a floating scrap of
speckle as the truth, then with foam. Then a real fermentation: the humidity
question, bubble size, and whether the sight glass fogs from inside.

## The instrument in service (2026-09-27 to 10-01)

The service now measures krausen height with PDAF, publishes it to Home
Assistant, archives frames and recordings to the NAS, and builds a timelapse
page per batch. Site-specific names and addresses are in `LOCAL.md`.

### Measuring in service: the calibration's conditions, kept

`pdaf_meter.py` replaces the laser ranging (`focus_tracker.py`, void
constants). Every 300 s it takes one point with `af_calibrate`'s own
`pick_exposure` and `take_point`, not a reimplementation, and holds the
conditions the table was measured under:

| | why |
|---|---|
| **30 fps throughout** | exposures capped at 32 ms, and the live view's frame capped at 33.3 ms (`--max-frame-duration-us 33333`); a slower frame cools the sensor |
| **lamp lit continuously** | measured below: it moves the reading 0.7 mm |
| **lens parked at 0 dpt** between points | the VCM's holding current heats the module |
| **lores 1280×720** in both | `af_calibrate` takes `LORES_SIZE` from `liveview`; the current model was taken at 1024×576 -- AF statistics come from the sensor before scaling, but it is a difference to know about |

The exception is a viewer: while someone watches, the lens holds the last
focus, and it parks when the last one leaves -- never during a recording.

States: `uppvarmning` after a start, for 1.5x the time the service was down and at most 75 min (a `heartbeat` file beside `zero.json`, touched every 30 s, says when it last lived -- so a 30 s watchdog restart costs no points), `i_halsen` at the rail
(surface nearer than ~25 mm), `utanfor_kalibrering` beyond 130 mm,
`misslyckad`, `morkt` if the lamp was forced off. Each point goes to
`matningar/matning-YYYYMMDD.csv` with the lid temperature.

### The lamp moves the reading 0.7 mm, so it stays on

`lamptest.sh`, 2026-09-28/29: four rounds of two hours, lamp held on against lit
only to measure, target fixed at 123.40 mm.

```
d = a - 1.07 mm/C * lid - 0.447 +- 0.023 mm * (lamp always on)
lid +0.26 C with the lamp always on
```

About 0.28 mm through the lid temperature and 0.45 mm more that the ferrule
sensor does not see -- the lamp warms something nearer the camera. Far over the
0.1 mm threshold set before the test. The calibration was taken with it on, and
a lamp switched by viewers would be a varying heat source in the middle of a
fermentation.

### Temperature compensation: 0.053 dpt/C of the lid

`--temp-coeff 0.053` with `--lid-sensor` on the TC ferrule. The raw dpt is
corrected by the coefficient times the lid's change **since the zero was set**;
the zero stores the uncorrected distance and its lid temperature, so a re-zero
is exact. Without a zero nothing is corrected. The log keeps the raw `dpt`;
`d_mm` and `krausen_mm` are corrected.

Checked after the fact on the simulation below with the coefficient from the
independent interval test: rms over 249 points **1.24 -> ~0.36 mm**, the tail
after the run -1.78 -> ~-0.35 mm. Live, the first night after zeroing, target
still: **-0.06 +- 0.10 mm** corrected against +0.22 +- 0.13 uncorrected.

> Swap the sensor for the one in the new housing's aluminium plate, and
> **re-measure the coefficient** -- it belongs to the build.

### Fit the working range, not the whole table

`afmodell.py` fits `dpt = a_s + b/(d + c)` with one offset per night and a
shared shape, **over heights up to 130 mm only**. Including 158 mm misses it
by 2.6 mm and takes the rms inside the range from 0.22 to 0.78 mm: the curve
leaves the hyperbola beyond ~125 mm. Heights beyond are tabulated.

It matters at the zero. A 75 L fill puts the surface 117-125 mm below the lid,
and the zero is a constant in every height that follows. Leave-one-height-out
gives 0.1-0.5 mm inside the range but **1.9 mm at 123.40**, the last height
before a gap to 158. The stage check confirmed it: krausen within 1.2 mm of
the truth everywhere, the error being the model reading +1 mm at the zero
height. **The next table wants heights at ~110, 117, 130 and 140 mm**, so the
fill level sits inside the data instead of on its edge.

### A fermentation played on the stage

`krausensim.py`, 2026-09-29: batch and zero from Home Assistant, then the stage
walked a curve `h = H (t/tp)^k exp(k(1 - t/tp))` -- 80 mm at 4 h, 12 h long.

```
143 points against the truth    mean -0.20 mm   rms 0.50   extremes -1.27 / +1.03
peak                            truth 80.0      measured 80.2
rising +0.10 mm, falling -0.35 -- the night cooled
```

Afterwards, stage back at the fill level, the reading sat at -1.8 mm: the lid
was 0.8 C cooler than at the zero. That is what the compensation above
removes.

### Home Assistant over MQTT

`ha_mqtt.py`, device discovery (HA 2024.11+), names in English because HA runs
in English -- the internal Swedish states are translated on the way out.

- **One availability for the device**: LWT `offline` retained; the service says
  `offline` itself on a clean stop (SIGTERM is turned into a shutdown); an
  unclean death fires the will.
- **Nothing stale shown as fresh**: state is **not retained** (HA cannot tell a
  retained message's age), every sensor has `expire_after` 900 s, heights are
  null unless the point is valid, and *Last measurement* is the heartbeat --
  unchanged values do not update HA's "last changed", so watch that one.
- **HA restarting** (`homeassistant/status online`): discovery and the last
  point re-sent after 5 s.
- **Measurement stalled**: a binary sensor set by the watchdog thread, not the
  meter, after 11 min without a point. On 2026-09-29 the camera hung with the
  process and its MQTT link alive, and HA saw nothing until expiry.
- Buttons *Start new batch*, *Set zero at fill level*, switch *Recording*.
  **Retained commands are refused** -- they would re-run on every reconnect.
- Number *Measurement interval*, 2-60 min (from 2026-11-02): points **and
  frame A** at that interval, so the timelapse thins out with them -- for
  measuring sparser once the krausen has fallen. Kept in `intervall.json`
  beside `zero.json`, so a restart keeps it; without the file the service
  runs at `--measure-interval`. `expire_after`, *Measurement stalled* and the
  watchdog all follow it. Not yet used: it waits until the frame A fix of the
  same day has shown whether it stopped the hangs, since fewer frame A would
  muddle that.

### The archive: batches, NAS, timelapse

- **A batch is a folder** `~/arkiv/<YYYY-MM-DD_HHMM>/` with `bilder/`,
  `matningar.csv`, `nollningar.csv`, `video/`. **Batch and zero are separate**:
  a batch may be zeroed several times (before and after pitching, or once a
  skin of foam gives focus something to hold), every zero is logged and every
  row carries the zero it was computed against. A new batch clears the zero.
- **The service writes only locally.** `krausencamera-arkiv.timer` rsyncs to the
  NAS every 10 min (automount, `nofail`, `soft`), and prunes local files older
  than 14 days only when the NAS holds a copy of the same size. Nothing is ever
  deleted on the NAS. **Never `rsync --delete` into `~/krausencamera`** -- see
  Workflow.
- **`timelapse.html` per batch**, built against the NAS copy: playback, scrub,
  the curve with a cursor, a start/end range, and **film export** (canvas +
  MediaRecorder, MP4 where the browser can, time, height and curve burned in,
  the curve zoomed to the range).
  > A page opened from `file://` taints the canvas with its own images
  > (SecurityError) and the film comes out empty. The first test missed it
  > because headless Chrome ran with `--allow-file-access-from-files`. Now the
  > export asks for the batch folder once (Chrome/Edge) and checks it is the
  > right batch; served over http it just works.
- **The page plays half-size copies** (`sma/`, 1152x648, ~130 kB, made by
  `forhandsbilder.py` in each sync) and the film export reads the originals.
  The originals are ~1 MB each; over Tailscale the page stalled on them
  (2026-10-22), since ten frames a second wants 10 MB/s. The sync is capped at
  `--bwlimit=1500` so a backlog never floods the WiFi.
- **`index.html` at the share's root**, served by the NAS's own web server
  (Synology Web Station, a name-based virtual host), so a phone reaches it
  without SMB and the Pi carries none of the traffic.

### Recording

`recorder.py`: hardware H.264 on the lores stream beside the live MJPEG, PyAV
writing MP4 -- no ffmpeg on the Pi. 30 fps, ~2 Mbit/s measured, 5 min cap,
`live_recording_<time>.mp4` into the batch's `video/`. The meter pauses for it
(taking the camera lock, so a measurement in progress finishes first), the lens
holds focus, and the first point afterwards is marked.

> **A camera hang, once.** 2026-09-29 13:22, 25 s after the first test
> recording stopped: `Camera frontend has timed out`, no measurements, the page's
> state call blocked. Not reproduced in six start/stop cycles the next day, and
> the same error occurred on 09-10 and 09-12 before recording existed. Unknown.
> *Measurement stalled* and the watchdog cover it.
>
> **Again 2026-10-01 12:05:26**, no recording, no viewer -- but in the middle
> of an archive sync that was re-sending the whole 716 MB archive over WiFi
> every ten minutes (rsync's mtimes did not stick on the NAS; fixed with
> `--size-only`, a sync is now seconds). Not proven to be the trigger. The
> recovery took 17 min, the measurement watchdog's period; the watchdog now
> also watches the MJPEG encoder, which runs at 30 fps whether anyone watches
> or not, and exits for a restart after `--frame-timeout` 15 s without a frame.

## The new module: settled, and what is left is the lid's temperature (2026-09-15 to 09-27)

Two weeks from the dummy to the real sight glass, through four housings and a
second camera module. The short version: **every rebuild lost near range until
a new module was mounted with no preload, and once it had run in, the only
drift left is the lid's temperature** -- which is measurable and compensable.

> **How build E is actually put together** (Love, 2026-10-01). A thick printed
> ABS-GF shim carries the camera PCB on one side; the module is **glued into
> the shim**, its metal face flush with the shim's surface. PCB, shim and
> aluminium plate are bolted together, which brings the module's metal against
> the plate through thermal paste -- flush, so nominally no interference, but
> the module is held by glue in printed plastic, not by the aluminium. The
> plate is turned to a tight guide fit 4 mm into the sight glass housing, its
> flange resting flush on the housing's rim.
>
> Earlier text here said the module was "glued to the plate". It was not, and
> the difference matters for what the drift was -- see below.

### The sight glass does what glass does

The dummy was replaced by the real sight glass, **8 mm of glass** in the beam.
A slab moves the apparent object nearer by `t(1 - 1/n)`: 2.67 mm predicted for
ordinary glass, **2.75 mm measured**, which is n = 1.52. Nothing unexpected; the
calibration absorbs it. The housing was redesigned around it with the camera
5 mm higher, and the board became a Zero 2 W (see Hardware).

### Every rebuild moved the rail out, and preload was why

All fitted with `b` locked at the old module's 846.29, so `a` carries the change:

| build | `a`, dpt | rail, from the lid |
|---|---|---|
| A: the 2026-09-14 module, open back | 0.56 | 36.9 mm |
| B: new housing, lid over the PCB | 1.08 | 42.1 mm |
| C: camera 5 mm higher (09-20) | 2.14 | 43.2 mm |
| D: aluminium plate, pad compressed 0.5 mm | 4.86 | **62.3 mm** |
| E: **new module, glued in the shim, flush against the plate** | 0.15 | **24.8 mm** |

The raise in C shows up in the geometry -- `c` moved +3.96 mm of the 5.00 -- but
the remount moved `a` by 1.14 dpt and ate the gain. Only range was ever lost,
three rebuilds running, and the build with by far the highest force on the
module lost the most. Dose and response point the same way.

**Why D was pressed so hard: the pad relaxes over a day.** The stack the shims
were drawn against was measured straight after disassembly, and the thermal pad
had not yet recovered -- it reads 0.3 mm thin for about a day. So the pad was
compressed 0.5 mm against a designed 0.1.

> **What E cannot separate.** The module and the preload changed together, the
> confound this file warns against repeatedly. The old module got worse with
> every handling and never recovered, which suggests pressure can damage a
> module permanently, but that is not a measurement.
>
> Mechanisms tried and dropped along the way: the shim's preload bending the
> lens against the sensor, the PCB screws, a decentred aperture (there is none),
> and eddy currents in the aluminium (the larger hysteresis near the rail is
> explained by working closer to it).

**`b` is per module.** The new module fits 685.73 against the old 846. Locking
`b` across modules produced an 11.6 mm residual that was entirely the lock. Each
module has its own VCM gain, and nothing in a calibration transfers between them.

The rail at 24.8 mm sits **10 mm inside the tank's 35 mm shoulder**, the first
time focus has reached into the neck. 32.40 mm is measured and converges.

### The aluminium plate: 56 C to 40 C

A turned plate between the module and the sight glass steel, with thermal paste,
so the camera's heat goes into the lid instead of being shut in by the housing.

| | before | with the plate |
|---|---|---|
| camera at equilibrium | 56.0 C | **40.0 C** |
| optical wander during warm-up | ~0.44 dpt | **0.177 dpt** |
| warm-up time | 43-65 min | 71 min |

The warm-up got longer because the plate is mass: `tau = C/G`, and C grew more
than G. The excursion is what puts error into a measurement, and it more than
halved. `--warmup-max` is now 100 and afwatch's `--warmup-wait` 110; the
default 45 would have restarted a session against a camera still warming.

### AfWindows works and does not matter

Metering left against right half of the frame differs by 0.054 dpt, 3.6 sigma.
Real, and too small to explain anything. Not used.

### The new module's table, two nights

```
night 1   dpt = 0.1499 + 686.15/(d + 21.360)    rail 24.8 mm
night 2   dpt = 0.1134 + 684.27/(d + 21.210)    rail 24.8 mm
          drift-corrected, visits after 218 mm left out (see below)
```

Thirteen heights, 32.40-218.40 mm, 205 and 200 points, **zero failures**. The
shape holds between nights to a fraction of a percent; only `a` moved, and that
is the drift.

**Inside 125 mm the model alone is good to 0.24 mm rms, and a correction table
does not help.** Night 1's residuals applied to night 2 give 0.26. The pattern
repeats at r = +0.67 between nights, against +0.887 for the old module. So
something still varies from night to night at the few-tenths level, and it is
not known what.

**Beyond it the model misses by +0.9 to +1.8 mm at 158 mm and +3.7 to +5.3 at
218, the same sign both nights.** Part of it is probably the exposure effect
below; 158 mm cannot be, since it already runs at 30 fps.

### The drift was settling in operating time, and it has run out

At the reference height the reading moved farther by about 0.12 mm/h over the
first night. It is **the same in dioptres at every height**, -4 mdpt/h from
32 to 218 mm, so it is a shift of the zero and not of the shape -- which means
one known point would correct every height, and that the rail moves with it by
only ~0.01 mm/h, since a dioptre is ~3 mm there.

```
                                         drift at 123.40 mm
night 1, first 10 h                         0.139 mm/h
night 2, first 10 h                         0.105
interval test, lid temperature removed      0.013
```

It **follows operating time, not clock time**. Over a 7.9 h pause with the
camera closed for 6.6 h of it, the reference moved at most a third of what
continuous drift predicts. And it is not new: the old module drifted as much,
with the sign changing between nights (+0.17, -0.07 mm/h). Integrated over
every hour of running it comes to ~0.02 dpt, **a hundred times too small to
have caused the rail creep** above -- which moved in steps at rebuilds.

> **What was settling is not settled.** "Follows operating time" was read as
> something in the module. It fits a printed shim equally well: ABS-GF creeps
> much faster at 40-46 C than at room temperature, and it is only that warm
> while the camera runs. With the module glued in the shim, both are in the
> path. The next housing glues the module to aluminium with no printed part
> holding it, so its run-in decides: the same ~0.1 mm/h decaying over days
> means the module; much less from the start means the shim.

So a fresh module wants a few days of running before its table is taken. After
four days this one is at a tenth of where it started.

### What is left is the lid's temperature: -1.6 mm per degree at 123 mm

48 hours at one height (`intervalltest.sh`), 864 points. On the Friday evening
Love worked at the bench the rig stands on; the air outside the box rose 1.2 C
and the reading moved 1.2 mm nearer. Reversals both ways, the target still
throughout (`niva` 115.5-116.3).

| covariate | lag | coefficient | residual rms |
|---|---|---|---|
| TC ferrule on the lid | **~10 min** | -1.6 mm/C | **0.15 mm** |
| box air | 50 min | -1.4 mm/C | 0.16 mm |
| air outside the box | 60 min | -0.9 mm/C | 0.24 mm |
| time only | | | 0.38 mm |

**The camera follows the lid, not the air.** Through the plate it is bolted to
the sight glass steel, and the ferrule leads the air by an hour. That is what
the plate was built to do, seen from the other side.

-1.6 mm/C at 123 mm is **0.053 dpt/C**. If it is uniform in dioptres like the
drift, it is ~0.4 mm/C at 50 mm, where krausen lives. A 4 C ramp at the end of
a fermentation is then ~1.5 mm. Compensable: **a DS18B20 in a pocket in the
aluminium plate**, and the coefficient becomes one more constant measured per
build. A calibration night's natural 1-2 C swing turned out to be enough to fit
it.

> **This does not contradict "it is not ambient" of 2026-09-12.** Then the
> lens's holding current swung the camera twelve degrees and ambient was lost
> underneath it. Parking removed the swing, the plate removed most of the
> self-heating, and what is left is what was always there.

With the lid's temperature removed the point-to-point noise at a fixed height
is **~0.1 mm** at 123 mm, when the stage and the exposure never change.

### The AF rate: small, reversible, and not wear

The interval test alternated four-hour blocks of one visit per ten minutes and
one per two minutes -- five times the lens motion for the same time.
Temperature-corrected: **+0.053 +- 0.017 mm/h in the fast blocks, -0.029 +-
0.018 in the slow**, five of six fast blocks the same sign. A sawtooth of
0.1-0.2 mm that comes back, so not wear. The mechanism is unknown. In service
the rate is constant, so it has nothing to act on.

### Long exposures cool the sensor

After every visit to 218 mm the reference read **24 mdpt low, 6 of 6 on both
nights** (-13 to -30), against -2 to +6 after any other height. Leaving those
points out halves the reference's scatter, 0.31 to 0.13-0.16 mm.

`af_calibrate` sets the frame duration to `max(33333, exposure + 1000)`, so
every exposure up to ~32 ms runs at 30 fps and only the 50 ms chosen at 218 mm
lengthens the frame. The sensor reads out less often and runs at 43 C against
46 everywhere else, and has not recovered five minutes later.

Since auto exposure makes exposure a function of distance, this is a
distance-correlated confound of exactly the kind that hides in the fit. Night
af15 (started 2026-09-27) caps exposures at 32000 us, `kalibrering.sh
--exposures`, so every height runs at 30 fps. The predictions: the dip after
218 mm disappears, and 218's residual shrinks by up to ~2 mm. 158's cannot.

### Tooling from these two weeks

- `kalibrering.sh` is one command per night: distances in, stage Z computed,
  service stopped, temperature log and watchdog started, stage moved to the
  reference **before** the warm-up. On 2026-09-23 the warm-up started 60 mm
  from the reference because the script left the stage where the last run did.
- `railjakt.sh` searches inward as well as outward. It only walked outward, and
  would have reported 46.40 mm for a module that converges at 32.40.
- `autocal.py --blocks 600x4,120x4` alternates the visit rate at one height,
  moving the stage once. The schedule is anchored to `--t0`, carried in the
  command afwatch restarts, so a restart resumes the right block.
- afwatch: the two bugs that ate the night of 2026-09-18 are fixed and covered
  by seven unit tests.

## The calibration, finished (2026-09-14)

267 measurements across two nights, both with the lens parked, ten heights in
randomised order with one revisited every third visit.

```
dpt = 0.5712 + 845.01/(d + 21.5860)
plus a tabulated correction, in calib/af-model-20260914.csv

      d      dpt        std err   correction   n   apply
  41.40   14.00913      0.042 mm    +0.103     20   yes
  46.40   12.99363      0.046       -0.037     19   yes
  52.40   11.95486      0.054       -0.244     19   yes
  60.40   10.87385      0.032       -0.033     21   yes
  70.40    9.79313      0.067       +0.356     19   yes
  82.40    8.68375      0.065       -0.176     19   yes
  99.40    7.55628      0.091       +0.011     20   yes
 123.40    6.41469      0.075       +0.378     90   yes
 158.40    5.26045      0.185       -0.218     20   no
 218.40    4.08697      0.273       -0.366     20   no
```

**The correction is real inside 125 mm and noise beyond it.** Between the two
nights the residuals correlate **+0.887** there, and differ by 0.117 mm against
0.099 expected from the measurements' own noise -- so the difference is noise
and the pattern is fully reproducible. Past 125 mm the two nights differ by
0.581 mm against 0.302 expected, on two points; nothing can be concluded.

Cross-validated the only honest way, deriving the correction from night 2 and
applying it to night 3:

```
                                   residual    LOO
night 3, as measured                0.210 mm   0.279 mm
night 3, minus night 2's pattern    0.277      0.679     worse overall
   but inside 125 mm                0.117      0.147     clearly better
```

Applying it beyond 125 mm makes things worse, because subtracting noise adds
noise. The file carries an `apply` column for exactly that reason.

| | LOO |
|---|---|
| the nine-point table, 2026-09-10 | 1.08 mm |
| night 1, temperature-corrected | 0.39 |
| night 3, parked, no correction | 0.279 |
| **night 3, parked + correction, inside 125 mm** | **0.147** |

**Seven times better than three days ago**, and the mechanism behind every step
is understood rather than fitted away.

### What limits it now, in order

**Beyond 125 mm: counting statistics.** The standard error is 0.185 mm at
158 mm and 0.273 at 218, on twenty visits each, because one dioptre is 43 and
73 mm there. Nothing is wrong with the model or the method -- that end simply
wants more visits. Four times as many would halve it.

**Inside 125 mm: the correction's own uncertainty**, 0.06 mm, and the
measurement's 0.059. Both are now below a tenth of a millimetre, which is
where the AF's single-cycle scatter sits. There is little left to win without
averaging more.

> **And none of it transfers to a different camera or a different housing.**
> The correction is this module's VCM, this build's geometry. Rebuilding the
> housing -- which is planned -- invalidates the table and the whole two nights
> have to be repeated. That is now a nine-hour unattended job rather than a
> week, which is the real return on the stage and `autocal.py`.

## We out-measured the model (2026-09-13)

With the lens parked, each height's mean is known to **0.075 mm**. The
hyperbola's residuals against those means are **0.338 mm** -- four to ten times
the measurement's own uncertainty. They are no longer noise.

```
              std err   residual rms   LOO
night 1, corrected    0.240 mm   0.167 mm   0.39 mm
night 2, parked       0.075      0.338      0.76
```

Night 1's apparently better figures are partly an illusion: its residuals were
*smaller* than its standard errors, which means the fit was absorbing noise --
three parameters against ten points will. Night 2 measures better and fits
worse, which is what happens when the instrument passes the model.

**The residuals repeat.** Across two nights with different thermal handling:

```
      d     night 1   night 2
  41.40      +0.037    +0.118
  52.40      -0.105    -0.246
  70.40      +0.058    +0.406
 123.40      +0.243    +0.469
 218.40      -0.412    -0.792

correlation +0.844
```

A fourth parameter `e/(d+c)^2` changes nothing at all -- same rms to five
decimals, as on 2026-09-11. So it is not curvature the model is missing. It is
something height-dependent and reproducible, most likely the VCM's own
position-to-power relation not being perfectly smooth.

> **This updates "focus can be set from a formula and triangulation cannot"**
> from 2026-09-07. That rested on a fit good to 0.27 mm, which was then the
> measurement noise. At 0.075 mm the model's inadequacy is visible, and focus
> wants a table too -- at the 0.3 mm level rather than the 1.5 mm level where
> triangulation needed one.

### A table alone is worse, a table on top of the model is better

Straight interpolation between the measured heights fails badly: leave-one-out
gives 4.9 mm against the model's 0.31 on the same points. That is not a fair
test of a table in use -- removing a point forces interpolation across a doubled
gap -- but it does show the real problem. The heights are spaced uniformly in
dioptres, so in millimetres they run 5 to 60 mm apart, and the curvature across
one interval at the far end is about 30 mm per dioptre squared. Linear
interpolation there is worth 4.5 mm.

**So: the hyperbola carries the curvature and a tabulated correction carries the
repeatable residual.** Deriving the correction from night 1 and applying it to
night 2 -- independent data -- takes the residual from 0.338 to 0.216 mm.

It stops there for a measurable reason: night 1's residuals carry their own
0.24 mm of noise, and a correction is never better than what it was derived
from. **Derive it from parked runs.** Two nights at 0.075 mm would pin the
pattern to about 0.05, and the corrected model should then land near 0.1 mm.

## Parking the lens: the controlled comparison (2026-09-12)

Two runs, identical in every respect -- same ten heights, same randomised order,
same reference every third visit, same box, same cadence -- differing only in
whether the lens is parked at 0 dioptres after each measurement. The first
controlled single-variable comparison in this project; twice before, several
things were changed at once and a conclusion had to be retracted for it.

```
                        night 1 (left)      night 2 (parked)
camera temperature        57-69 C              56-58 C
                       std 2.92              std 0.50

reference height d=123.40
  scatter between visits   4.70 mm             0.43 mm
```

**The twelve-degree swing collapsed to two, and the scatter fell elevenfold.**
Every height improved:

```
      d     night 1   night 2    factor
  41.40      0.93      0.17       5.4x
  70.40      1.97      0.12      16.1x
  82.40      2.85      0.07      39.5x
 123.40      4.53      0.42      10.9x
 158.40      8.26      0.04     202.7x
 218.40      4.25      0.66       6.5x
```

0.43 mm now sits 2.3x above the scatter *within* a visit, against 25x before.
The feedback is broken at the source, and the mechanism is confirmed: it was
the VCM's holding current all along.

> **Two comparisons, only one of which is settled.** Scatter is measured per
> height and directly, so four visits each is plenty and the result stands.
> Model quality is not: night 1 has 117 measurements and nine per height,
> night 2 forty and four, and leave-one-out punishes that. Night 2's own
> temperature coefficient appears to give LOO 0.41 mm, but it is estimated
> across two degrees and fitted to the data it then corrects -- with night 1's
> independent coefficient the gain is a modest 0.96 to 0.79 mm. **Once parking
> has removed the swing there is little left for the correction to do**, which
> is the point of doing it at the source.

### Consequences for the product

`focus_tracker` leaves the lens wherever AF put it between cycles, exactly as
the session did, so the same feedback runs in service: a krausen rising drives
the lens nearer, the module warms, and the reading moves nearer still.

**The live view has it too**, and Love spotted that: a viewer holding the page
open holds the lens in position for as long as they watch. It is the same fault
in a third disguise, and it may be part of why the service drifted on days when
a browser tab had been left open. Park when the last viewer leaves, restore
when the first arrives.

> **Air cooling was considered and deferred.** Love proposed a 40 mm fan drawing
> air axially past the module and the Pi. Two objections: the module is on
> double-sided tape, so air over the PCB barely reaches the lens where the heat
> is actually made -- and air drawn past the lens is dust and humidity on the
> one surface in the instrument that has to stay clean. Cooling the Pi and the
> buck is fine and unrelated. But the heat source is being removed rather than
> managed, which is cheaper than any fan.

## The calibration, temperature-corrected (2026-09-12)

117 measurements, ten heights in randomised order, one thermal state, in the
box, at the service's own cadence. The temperature coefficient is estimated
from the reference height alone -- where the distance is constant by
construction, so it cannot absorb any distance dependence -- and then applied
to every reading.

```
dpt = 0.9039 + 851.3/(d + 21.74)          rms 0.0077 dpt
correction: -0.0664 dpt per C of SensorTemperature, referred to 63.7 C

      d      n     mean dpt    std err   residual
  41.40      9     14.3945     0.07 mm    +0.04 mm
  46.40      9     13.3953     0.10       -0.01
  52.40      9     12.3698     0.11       -0.11
  60.40      9     11.2733     0.19       +0.04
  70.40      8     10.1487     0.15       +0.06
  82.40      8      9.0768     0.19       -0.02
  99.40      9      7.9245     0.11       -0.12
 123.40     39      6.7790     0.10       +0.24
 158.40      8      5.6330     0.43       +0.13
 218.40      9      4.4428     0.95       -0.41

leave-one-out   max 1.15 mm   rms 0.39 mm
```

| | LOO rms |
|---|---|
| uncorrected, same data | 4.82 mm |
| the nine-point table of 2026-09-10 | 1.08 mm |
| **this** | **0.39 mm** |

**The residuals now sit at the level of the standard errors** -- 0.04 against
0.07, 0.11 against 0.11, 0.13 against 0.43. The model fits to within the
measurement's own noise, which it has never done before on this project;
previously the residuals ran ten times over.

> **The model is valid at one temperature.** Its constants belong to the camera
> at 63.7 C, the mean of the run. In service every reading must be corrected the
> same way before the model is applied -- or, better, the lens parked so the
> temperature stops moving in the first place. Applying these constants to a raw
> reading at 57 C would be 0.44 dioptres out, which at 123 mm is 11 mm.

**What still limits it is the far end.** At 218 mm one dioptre is 73 mm, so the
standard error is 0.95 mm on nine visits and the residual 0.41. Everything
inside 125 mm is better than 0.25 mm. If the far end matters it wants more
visits, not a better model -- the error there is counting statistics, not fit.

## ⚠️ The lens heats the camera, and that is the drift (2026-09-12)

Five hours, 61 points, ten heights in randomised order with one revisited every
third visit. The first table taken on one thermal state, in the box, at the
service's own cadence. And the reference height answers the question the whole
rig was built to ask.

```
d = 123.40 mm, 21 visits
  scatter between visits   0.190 dpt = 4.9 mm
  scatter within a visit   0.0074 dpt = 0.19 mm
```

**Twenty-five times more scatter between visits than inside them.** Nothing
moved during a measurement; everything moved between them.

### It is not ambient, not the lid, not time

```
                  change over 5 h    r against the reading    slope
TC ferrule            +0.250 C              +0.628          48 mm/C
box air               +0.125 C              +0.676          78 mm/C
outside               -0.063 C              -0.233         -12 mm/C
camera sensor         +6.000 C              +0.996         1.7 mm/C
time                                        +0.232        0.73 mm/h
```

**The camera's own die temperature correlates at 0.996** while the DS18B20s
barely move a quarter of a degree. The slope is 0.066 dpt/C -- the same
coefficient measured on 2026-09-11 from completely different data.

> And it reverses a judgement of my own. I dismissed `SensorTemperature` as
> useless because it is quantised to whole degrees, and a degree is 0.63 mm.
> That was right for the garage door, which moved the reading 0.8 mm while the
> sensor moved one count. It is wrong here: the swing is **twelve degrees**, and
> against that a one-degree step is eight per cent. A coarse instrument is only
> useless relative to what it has to measure.

### The lens's holding current is the source

The camera temperature is set by the *previous* visit, not the current one:

```
temp against the previous lens position   r = +0.965      +0.96 C per dioptre
temp against the previous height          r = -0.921
temp against this visit's exposure        r = +0.051
residual after the lens-position model     0.79 C  (from 3.01)
```

The VCM holds the lens wherever AF left it, for the whole interval between
visits. A near target means fourteen dioptres, far from rest, drawing current
continuously; a far one means four dioptres and almost nothing. Across the
table's range that is **9.6 C**, which accounts for nearly all of the twelve
degrees observed.

**So it is a feedback loop**: lens position sets temperature, temperature sets
the reading, the reading sets the lens position. The gain is
`0.066 x 0.96 = 0.063`, well under unity, so it converges rather than runs away
-- the same shape of answer as the autofocus/breathing loop. But it biases, and
it biases **in the same direction as the quantity being measured**: a krausen
rising drives the lens nearer, the camera warms, and the reading moves nearer
still. The instrument exaggerates itself by a few per cent.

**This is in the product, not just the calibration rig.** `focus_tracker` leaves
the lens wherever AF put it between cycles, exactly like the session did.

### The fix, and what the uncorrected data is still worth

Park the lens at a low dioptre after every measurement, so the holding current
between visits is the same whatever was just measured. `--park-after` (default
2.5 dpt) does that; a negative value disables it.

Until then the temperature is a covariate, and a good one. Correcting each
reading by 0.066 dpt/C, with the coefficient estimated from the reference height
alone where distance is constant by construction:

```
                scatter before    after
  41.40 mm         0.94 mm       0.23 mm      4.2x
 123.40 mm         4.89          0.46        10.6x
 158.40 mm        10.00          1.45         6.9x
 218.40 mm         3.84          3.72         1.0x
 overall           4.74          1.07         4.4x
```

The far end does not improve: at 218 mm one dioptre is 73 mm, so whatever
dioptre error remains is amplified beyond rescue. That is an argument for
parking the lens rather than correcting afterwards.

> **None of this would have been visible without the reference height.** With
> loose blocks a height could never be revisited, so a 4.9 mm swing at a fixed
> distance was indistinguishable from the rig settling, the room cooling, or the
> model being wrong -- which is exactly the three-way confusion that consumed
> 2026-09-10 and 11. One repeated height separated them in a single night.

## The warm near limit is 37 mm, not 43 (2026-09-12)

Measured in the light-tight box, camera warm, under the conditions the night
and then service will actually have. Six AF cycles at each height:

```
d = 31.4 mm    0/6    rails every time
d = 35.4 mm    0/6    rails every time
d = 39.4 mm    5/6    converges nearly always
d = 43.4 mm    6/6    always
d = 219.4 mm   6/6    the far end is fine, the sheet fills the frame
```

So the limit sits between 35.4 and 39.4 mm from the lid -- **better than the
43-44 mm extrapolated from cold readings the day before**, and the table's near
end moves in accordingly. The tank's shoulder is at 35 mm, so focus now reaches
to within a couple of millimetres of the neck.

> The rail is not only a limitation. `AfRange` is Full, so the stop is exactly
> 15.0000 dioptres and `af_calibrate` rejects that value outright rather than
> trusting `AfState`, which reports success against the stop. A railed reading
> therefore means "the surface is nearer than 37 mm" with no calibration
> involved at all -- a threshold detector for free, sitting almost exactly at
> the height where blow-off becomes the question.

**What sets the table's near end is scatter, not railing.** Just outside the
limit the lens converges legitimately at 14.8 or 14.9 with less and less to work
with, and the scatter climbs before `n_ok` falls. A height that gives 6/6 with
0.05 dpt of scatter instead of 0.01 is formally fine and practically useless.
Love raised this before the measurement: `AfState` lies, so what does 0/2 even
mean? It means the lens value, not the state -- but his question pointed at the
softer failure one level down.

### The box changes the thermal state considerably

Everything is now enclosed: lid, housing, stage and target in one light-tight
box, with three DS18B20s -- one taped to the TC ferrule under insulation, one in
the box air, one outside.

```
TC ferrule      24.375 C
box air         23.937 C     -0.44 against the ferrule
outside         23.124 C     -0.81 against the box
```

The gradient is the one predicted and never before measured: the lid assembly
warmest, the box air between, the room coolest. The ferrule and the box air hold
still while the outside sensor falls -- the box buffers, measurably.

**But the camera runs far hotter inside it.** `SensorTemperature` reached 69 C
during the rail hunt against 54 at the end of the warm-up, because the hunt ran
AF every two minutes in a sealed box. That is a duty-cycle difference, not a
box effect alone -- and it is exactly the inconsistency this project keeps
paying for: the warm-up established equilibrium at one duty cycle and the
measurement then ran at another. The warm-up now samples at the night's own
interval so the equilibrium it finds is the equilibrium the table is measured
in.

`d0 = 27.4 mm`: the target sits that far below the lid at stage Z0. Z0 is
therefore a homing reference and not a measurement height -- it is inside the
rail.

## The target stage: an Ultimaker 2 Z axis on a TinyG (2026-09-11)

Loose blocks are gone. The stage is the UM2's Z mechanism -- trapezoidal screw,
nut fixed to the platform, motor and screw in the chassis -- driven by a TinyG
v8 over USB from the Pi.

```
$3tr = 8.0      T8x8, measured 8.008 over 40 mm -- nominal kept, see below
$3pm = 3        coil dead the moment a move ends
$st  = 0        NO switch (the one to hand was already terminated NO)
$zsn = 3        min-end switch: limit + homing
$zsv/$zlv = 200 / 25 mm/min      search / latch
$zlb/$zzb = 3 / 5 mm             latch backoff / zero backoff
$ztn/$ztm = 0 / 150              up blocked, 150 mm down
-Z is up, +Z is down, away from the lid-mounted camera
```

| | |
|---|---|
| positioning **within** one session | **0.02 mm** |
| across a re-homing | ~0.1 mm |
| scale | 8.0 mm/rev, good to 0.1 % |
| round trip, 0 -> 200 -> 5 mm | **0.04 mm**, no steps lost |
| full travel verified | 200 mm down at 100, back up at 400 mm/min |
| the block stack it replaces | 0.2-0.35 mm |

**So home once per session and never again.** Within a session the stage is five
times better than the camera it exists to measure; across a homing it is merely
comparable, so re-homing mid-series would inject about as much error as the AF's
own noise. Every figure above is a single caliper reading against a rig, and the
caliper resolves perhaps 0.04 mm, so treat them as indicative.

The error does not look like scale: 0.06 mm over 40 mm but 0.14 over 20. That is
an offset -- backlash, or where the homing lands -- not a pitch error.

**The scale is left at the nominal 8.0.** Two measurements disagree about which
way to correct it: 40.04 against a commanded 40 with a caliper (+0.1 %), and
199.55 against a commanded 200 with a long scale rigged provisionally
(-0.22 %). Correcting on either would be chasing the instrument rather than the
screw. 0.2 % is 0.4 mm across the full range, and it is the one error that does
**not** cancel when height is taken as a difference -- but on a 30 mm krausen it
contributes 0.06 mm, below everything else in the chain.

### What the stage is for

Not convenience. **A height can be returned to**, which makes bracketing
possible: measure A, B, A, C, A, and the repeated A says what the camera did
while the table was taken. Drift that can be measured can be subtracted, and the
camera's multi-hour drift is the one thing still unexplained. With loose blocks a
height could never be revisited, so camera drift and rig error could not be
separated at all.

### Reach every height from below

These screws have backlash of a tenth of a millimetre, larger than everything
else left in the chain, so the approach direction has to be consistent:
overshoot past the target and finish moving up.

> I first argued that gravity preloads the nut against one flank so direction
> cannot matter, and that finishing upward would let the platform fall back when
> the coil releases. Love's answer was that friction here exceeds the platform's
> weight. Then the platform slid down the moment a measuring scale was rested on
> it -- so friction does **not** dominate, and neither of us had it right. It is
> a T8x8: four starts, 8 mm lead, far too steep to self-lock.

**Homing's own last move is downward** -- the `$zzb` retreat from the switch --
which is the opposite of every measurement approach. Love caught that. `home()`
now finishes by dropping 10 mm and coming back up to zero, so Z0 is defined the
same way as every other height.

### The evening's three crashes, and what they have in common

The platform hit the ceiling twice and crushed a few things, and a lost zero cost
an hour. None of them was a mechanical failure.

**The board reports success unconditionally.** It counts steps and has no idea
what the axis did. Twice the reality was ten millimetres in the wrong direction
while the status report read exactly as it does when everything works.

**A soft limit is only as good as the zero it is measured from.** Three times a
limit protected the wrong end -- twice because the sign convention was assumed
rather than tested, once because a reset had silently discarded the machine
position. So: **never assume the direction, prove it inside a window where a
wrong sign cannot do damage.** Zero where the table stands, clamp to +/-2 mm,
command 1 mm, ask which way it went, and only then open the limit -- in the safe
direction only.

**An alarm latches and refuses everything afterwards**, including `G21 G90`,
which makes a sulking board look like a dead one. Clearing it releases whatever
is still queued, so the order is feedhold, flush, *then* clear. Status 203 or 220
on a command that cannot fail is the signature.

**A reset keeps the `$` settings and discards the machine position.** Everything
in EEPROM survives; the zero does not. After any reset, re-zero before anything
moves, because the soft limits are now measured against a zero that no longer
exists.

> And `pkill -f` bit twice more. `[t]tyUSB0` protects the pattern from matching
> itself but not from matching the same text elsewhere on the command line --
> the ssh invocation carried `/dev/ttyUSB0` inside its own Python, so the kill
> took out its own session while a stage was moving. Match something that exists
> only in the target process.

### The door was a red herring, but only after dark

Love found the rig's side door had been open, probably for hours, letting
visible light in. The camera is NoIR and the focal plane for 850 nm is not where
it is for daylight, so a changing mixture moves the reading — a real mechanism,
and it predicted the right shape.

Tested inside the session: door opened 21:23:37, closed 21:32:35, with the slow
warm-up tail removed as a linear trend.

```
door step   -0.11 +- 0.11 mm    1.0 sigma    upper bound 0.32 mm
```

Nothing. Which also settles a contamination I had walked into: the door was
closed between the first two session points, so the +0.2166 dpt jump there had
two candidate causes. It was the temperature.

> **The test was run at half past nine in September, in the dark.** It shows
> that a door onto an unlit garage does nothing. It says very little about the
> same door at two in the afternoon, which is when several table points were
> taken. Repeating it in daylight costs ten minutes with the camera already
> warm, and until then daylight is not excluded as a table error.

## Focus has a near limit, and it is 3 mm short of the shoulder

The lens's travel ends at about **15.5 dioptres**. Driven by hand from 8 to 26
dpt the sharpness climbs steeply to 15.5 and then goes flat — 25.7 to 26.7 over
ten dioptres, four per cent. It is not a peak, it is the actuator running out,
and `LensPosition` accepting values up to 32 changes nothing.

**`AfRange` is worth setting.** The default Normal rails at 12.0 dpt; Macro and
Full reach 15.0. That is free range which was being left unused, and it is worth
about 20 mm of working distance at the near end.

From the nine-point model, measured from the lid's underside:

| | from the lid |
|---|---|
| 13.0 dpt | 47.4 mm |
| 14.0 dpt | 42.4 mm |
| **15.0 dpt — the rail** | **38.1 mm** |
| the tank's shoulder | 35 mm |

The nearest point actually measured is **43.91 mm at 13.69 dpt**, 8/8 converged,
0.11 mm precision, with 1.3 dioptres of margin left to the stop. So the model's
38 mm is an extrapolation of about 6 mm past real data, not a measured limit.

> **Retracted: "the last 35-60 mm before blow-off are blind to focus."** That
> came from a pair of railing tests at 76 and 101 mm *from the housing face*,
> taken before the lid became the reference and before the module was shimmed.
> It was recorded as the single most important limitation found so far. It is
> not: focus reaches to within about 3 mm of the shoulder, and the last
> measurement before the rail is one of the most precise in the table — 0.11 mm,
> because mm/dpt falls to 4.9 there.
>
> The argument for keeping the laser survives on its own terms, just not this
> one. Triangulation is best near and worst far; focus is the reverse, its
> precision decaying from 0.11 mm at 44 mm to 0.29 at 181. They fail at opposite
> ends, which is a good reason to keep both rather than choose.

**Railing near the shoulder is still a free threshold detector.** The rail sits
at 38.1 mm and the shoulder at 35, so a reading that rails means the surface has
essentially arrived at the neck — which is exactly the condition the alarm cares
about, reported by the sensor going blind rather than by a number.

### Railing reports success

`AfState` returns 2 (focused) while the lens sits against its stop, and every
reading comes back as exactly 12.0000 or 15.0000 with zero scatter. A tight
cluster at a round number is not precision, it is a mechanical end stop -- the
same shape of failure as the laser returning a tank bottom seen through clear
water at 0.06 px repeatability. Both tools now reject a railed reading rather
than recording it.

## ⚠️ RESOLVED: the camera module was coming off its own PCB (2026-09-10)

The Camera Module 3's sensor-and-lens package is held to its PCB by **thick
double-sided tape**, with a short flex acting as a hinge. In vertical mounting —
looking straight down, which is the whole point of this instrument — that tape
creeps under the package's own weight and the module slowly hinges away. Love
found it while changing housings: the module was visibly detached and hanging.
`evidence/module-detached-from-pcb-20260910.jpg` (gitignored, local only).

**A printed shim under the module, pressing it flat against the PCB, fixes it.**
Measured on the same target with the same method:

| | no shim | with shim |
|---|---|---|
| drift, first hours | −14.65 px/h | **−0.33 px/h** |
| drift, total | −43 px / 18 h | **−0.95 px / 7.7 h** |
| PDAF, best quarter | 0.0107 dpt | **0.0081 dpt** |
| PDAF convergence | 70/70 | 46/46 |

Forty times less movement. The remaining 0.06 px/h is a few times the 0.025 px
frame-to-frame noise.

### It explains every symptom, and kills two of my own conclusions

- **the drift** — tape creeping under gravity: viscoelastic, decaying, partly
  springing back, over days. Exactly the curve shape measured, `dx` overshooting
  and returning included.
- **the field-dependent residual** — 1.15 px left after the best rigid
  transform, 23x the noise and growing towards the field edges. That was read at
  the time as "the optics are moving inside the module", which was right.
- **the light loss** — the old camera passed half what its aperture predicted. A
  displaced module vignettes against the tube.
- **the 3.6 degree pointing error** — the whole module tilted, sensor and lens
  together, so lens-against-sensor stayed square and Scheimpflug stayed quiet.
  That is why the pointing showed up while the focal plane did not tilt.

> **Retracted: "the drift tracks the print's age."** Every new housing also meant
> a newly mounted camera, so "hours since printing" and "hours since the module
> was hung vertically" were the same variable in all of my data. Housing 1 did
> not drift because its tape had already settled, not because its plastic had.
> The annealing work followed from that confounded correlation.
>
> **This run cannot formally separate them** — the housing was annealed *and*
> shimmed at once, which is the confound I warned against two days earlier and
> then walked straight into. But the mechanism here was *seen*, not inferred,
> and a photograph of a detached module outweighs a correlation.

### Consequences for the build

- **Every housing needs the shim**, and it belongs in the printed part rather
  than as a separate piece. This is not a fault of one module; it is how they
  are all made.
- Any camera that has hung vertically for days without one should be assumed to
  have moved, and anything calibrated against it re-measured.

## The drift tracks the print's age, not the camera (2026-09-08)

Two independent faults appeared on the same day and were conflated for two days,
because on 2026-09-07 Love both printed a new housing *and* drilled into the
camera. Separating them took a timeline:

| part | printed | age when measured | drift |
|---|---|---|---|
| window dummy | 09-02 14:19 | weeks | — |
| **housing 1** | 09-02, afternoon | days | none noticed |
| **housing 2** | 09-07 ~14:00 | ~8 h | 1.5–9.9 px/h, never settled |
| **housing 3** | 09-08 16:32 | **3.5 h** | 14.7 -> 2.4 px/h |

The youngest print drifts fastest; the oldest does not drift at all. And housing
3 carries a **factory-fresh camera**, so the drift cannot be the camera.

- **A fresh print drifts.** Residual stress relaxing, over days to weeks at room
  temperature — exactly the scale separating housing 1 from housings 2 and 3.
- **The drill gave tilt, light loss, a field-dependent mapping and poor
  centring.** Only ever in the old camera.

Both are real; neither explains the other.

**This makes annealing the right fix**, which was Love's instinct before there
was evidence for it. Eight hours at 90 °C (ABS Tg ≈ 105) collapses that
relaxation into one cycle. It has to happen **before** final fitting, since the
stress coming out is a dimensional change.

Two predictions, both free to check: housing 3 should keep decelerating and stop
over *days*, and an annealed housing should drift far less from the start — the
number to beat is **14.7 px/h in its first hour**.

> The window dummy is exonerated by the same timeline: printed 09-02, clamped
> since, and in the same age class as housing 1, which never drifted. Stiffening
> it would address the one joint that has already settled.

## Temperature ruled out by a reversal, and the settling time measured

Housing 3 logged for 18.5 hours with a factory-fresh camera and locked focus.
The garage fell 22.3 -> 21.5 C overnight and then **rose** to 21.8 through the
afternoon, which is the reversal test the earlier data could not provide:

```
night        temp falling      dy falling
afternoon    temp RISING       dy still falling, -0.31 px/h
```

Had the drift been thermal it would have turned around. It did not. The
correlation within either window is high — both are monotonic there — but its
**sign flips between them**, and a causal relationship does not do that.

This closes a question that had been reopened twice: temperature is not the
driver. It was already implausible on magnitude, needing 0.22 deg/C where
expansion in a 30 mm ABS-GF body gives 0.002, and now it fails a direct test.

**The settling itself is well behaved.** Fitting two exponentials:

| | time constant | amplitude |
|---|---|---|
| the joint seating | 0.10 h | −29.0 px |
| the material relaxing | 9.5 h | −40.3 px |
| asymptote | | −50.6 px |

Rate falls from −15 px/h at the start to −0.31 now, and the fit puts it at
−0.027 px/h by 48 hours — settled by roughly two days after installation. The
fit's rms is 1.52 px, so treat it as indicative.

> **Which reframes annealing.** If an un-annealed housing settles in two days
> anyway, the oven buys *time*, not a different end state. Still worth it —
> two days per iteration is a lot when iterating — but the comparison to make
> is "does it reach its asymptote sooner", not "does it drift less".

## The rotation study: the camera sits 3.4 mm off the tube's axis

Rotating the housing in its dummy separates an error that belongs to the camera
from one that belongs to the dummy. In image coordinates the observed mouth
offset is `R(-theta)·m - a0`, so the part that **rotates** is the dummy's and the
part that stays **constant** is the camera's. Love rotates the camera clockwise,
which turns the image counter-clockwise.

**The tilt is the camera's**, decisively:

| housing | tilt direction | camera-fixed predicts | dummy-fixed predicts |
|---|---|---|---|
| 0 deg | 132 | 132 | 132 |
| 90 deg | 142 | 132 | 42 |
| 180 deg | 141 | 132 | 312 |
| 270 deg | 138 | 132 | 222 |

It holds inside a ten degree band while a dummy-fixed error would have swept the
whole circle.

**The off-centring is 88 % the camera's.** Four positions, eight equations
against four unknowns, residual 2.5 px rms:

| | | at the mouth |
|---|---|---|
| `a0`, camera off-axis in its housing | 142 px | **3.35 mm** |
| `m`, mouth off-axis in the dummy | 19 px | 0.45 mm |

Per position the model misses by 2.7, 4.0, 4.3 and 3.1 px, which is the circle
fit's own scatter — it is fitted to within the measurement's noise. The three
position solution gave 144 and 20 px, so adding the fourth barely moved it.

Predicting the 180 degree position from the 0 and 90 degree pair alone — a real
prediction rather than a fit to itself — landed within 11.2 px. And the mouth's
radius holds at 831.9 +/- 2.4 px, 0.29 %, so nothing moved axially across the
ninety minutes.

### It is 3.6 degrees of pointing, not 3.4 mm of offset

Love said 3+ mm of lateral offset was implausible, and asked whether an angular
error could be behind it. It can, and it is. **The mouth alone cannot tell them
apart** — a camera displaced sideways and one pointing off-axis shift its image
by the same amount. Parallax separates them, and the speckle target's blank
landing disc had been sitting in every frame as a world-fixed reference at the
target's distance while only the mouth was being used.

| | near/far ratio |
|---|---|
| measured | **1.24** |
| pure lateral offset predicts | 4.63 |
| pure angular error predicts | 1.00 |

Solving both terms: **3.60 degrees of pointing** and 0.84 mm of displacement.

**And that collapses the tilt into the same fault.** A camera pointing 3.6
degrees off-axis sees a perpendicular target as oblique: 64 mm of field radius
gives 4.0 mm of distance across the field, which is 0.118 dpt at 185 mm.
Decomposing the measured tilt over the four positions:

| | |
|---|---|
| constant, camera-fixed | 0.1247 dpt at 139 deg |
| rotating, world-fixed — **the target's own tilt** | 0.0116 dpt = **0.36 deg** |
| residual | 0.0059 dpt |

Predicted 0.1176 against measured 0.1247, six per cent apart from two
independent measurements. **Nothing is left for a lens-against-sensor tilt** —
at most 0.007 dpt, inside the residual.

Love also asked whether the bottom was assumed perpendicular. It was, and it is
not: 0.36 degrees, now measured. It does not affect the mouth, whose boundary is
the rim's own projection and so is independent of what lies behind it.

| quantity | value | where it lives |
|---|---|---|
| **camera points off-axis** | **3.60 deg** | the housing's board seat |
| camera displaced sideways | 0.84 mm | the housing's board seat |
| target tilt | 0.36 deg | the floor |
| mouth off-centre | 0.45 mm | the dummy, negligible |
| **lens against sensor** | **<= 0.007 dpt** | nothing measurable |

**So it is one CAD fix**, and the lopsided crop and the "tilt" are the same fault
seen twice.

> **⚠️ Superseded 2026-09-10, and again on 09-20.** The 3.60 degrees was not a
> property of the housing's board seat. It was the module hanging off its own
> PCB -- see the RESOLVED section above -- and **the shim fixed it**. The table
> below assigns it to the seat because that section was written before the
> detached module was found, and the attribution was never corrected.
>
> Do not cite these 3.6 degrees as evidence that a printed seat sets the
> pointing. Love has had to say so twice. If a future housing needs its
> pointing argued about, measure it again on that housing.

> **Retracted: "the drill doubled the tilt."** The 0.193 dpt on the damaged
> camera and 0.114 on the fresh one were measured in *different housings*, and
> the housing's pointing error dominates that figure. The drill's damage stands
> on its other evidence — the light loss and the field-dependent residual — but
> the tilt comparison was measuring the housings. Separating a pointing error
> from a lens tilt needs the same camera in two housings, or a target known to
> be square; the rotation test cannot do it, because both are camera-fixed.

> **The eight-wedge fit is what made this measurable.** Measuring the mouth from
> left and right alone gave +28 px in x and the conclusion that centring was
> fine. Love said it looked wrong. It was: the offset is almost entirely
> vertical, +144 px, and the mouth's radius exceeds half the frame height so the
> up and down wedges never reach it. Fitting a circle through the six directions
> that do reach recovers both axes. **The axis I could measure was the axis the
> error was not in.**

## ⚠️ The 2026-09-07 calibration is void

The camera module used for it had been damaged the day before — the drill caught
while its screw hole was being opened out and spun the module at 2000 rpm.
Inspection on 2026-09-08 found the optics pointing visibly wrong relative to the
housing's aperture.

**Everything below this line that depends on that camera is unreliable**, and
the sections that follow record the two days spent discovering it. They are kept
because the *methods* are sound and several were hard-won — the invariance
argument, dot-minus-target, texture-death for the mouth, the speckle target,
tilt by sector — but no constant fitted with that camera should be used.

Specifically void: the four-point series (180/130/108/80 mm), `f·b = 16782`,
`X_PP`, `C`, and every distance in millimetres quoted from them. The focus model
`dpt = 0.440 + 801/(d − 19.95)` is void as an absolute calibration too, though
its *form* held up well.

What survives: measurements from before the damage — the 1.5 mm aperture's
photometry, the depth of field figures, the liquid and turbidity work, the
illumination and thermal characterisation. And the negative results, which cost
nothing to keep and would otherwise be rediscovered.

## New housing, 10.5 mm baseline (2026-09-07)

Recalibrated after the rebuild. Distances are to the housing face; the fits
solve for the offset to the optical reference themselves.

| distance | focus | dx | dy |
|---|---|---|---|
| 180 mm | 5.45 dpt | 160.14 | 102.52 |
| 130 mm | 7.70 dpt | 201.50 | 104.13 |
| 108 mm | 9.55 dpt | 227.69 | 107.60 |
| 80 mm | 13.78 dpt | 292.20 | 108.47 |

```
FOCUS   dpt = 0.440 + 801/(d − 19.95)     residuals ±0.27 mm
LASER   dx  = 64.0  + 16782/(d − 6.38)    residuals −1.57 … +0.95 mm

f·b = 16782 px·mm at b = 10.5  ->  f ≈ 1600 px
laser height offset ≈ 0.3 mm
```

### The two models behave differently, and that is informative

Both were measured at the same target positions, so they share the distances. If
the heights were uncertain by a millimetre or two, **both** fits would show it.
The focus fit lands within 0.27 mm, so the heights are good to about a third of
a millimetre — and the laser model's 1.5 mm therefore cannot come from the rig.
`dx` was measured to 0.03–0.05 px, so it is not noise either. The model form is
slightly wrong, most likely lens distortion, since the dot travels 132 px of
radius across the range.

**So focus can be set from a formula and triangulation cannot.**
`dpt = 0.440 + 801/(d − 19.95)` is good to a third of a millimetre across
80–180 mm, which answers the autofocus-from-laser-distance question directly:
no table needed there.

> **Superseded, 2026-09-07.** The 1.5 mm was largely the target, not the model.
> See the two sections below: the laser positions were measured against the
> printed focus target, whose gratings bias the centroid, and the reading was
> never corrected for the focus it was taken at. Both were measured; both were
> worth about a pixel. The measured table is still the right call for
> production, but not for the reason recorded here.

### The patterned target biased the laser centroid

Love asked whether it mattered that the laser positions were measured against
the printed focus target rather than white paper. It did. Swapping to white
paper at the same 108 mm, nothing else touched:

| | dx | dy |
|---|---|---|
| pattern | 227.69 ± 0.03 | 107.60 |
| white paper | 228.77 ± 0.05 | 109.97 |

**1.08 px**, where the paper's own thickness accounts for 0.16. The dot spans
about 40 px and the gratings run 0.5–2 mm, so it covers several bars; black
absorbs, white returns, and the intensity-weighted centroid is pulled toward
whichever side carries more white. Against the four-point model the residual at
this position falls from −1.45 px to −0.37.

The focus fit was unaffected because its metric is contrast over the whole ROI,
which does not care *where* in the ROI the dot lands. That is why only one of
the two models looked bad.

**Operationally this does not go away.** Foam is not periodic like a grating,
but it is uneven on the same scale, and one pixel is 0.6 mm of height here. The
difference is that a grating gives a *systematic* error that varies with
position while foam gives a *random* one that averages down — so it sets the
noise floor, not a bias. That floor is well above the 47 µm measured on paper.

### Focus and triangulation are coupled by focus breathing

`laser_align.py` and `laser_spots.py` hardcode `LensPosition: 7.7`, so the whole
four-point calibration was taken at **one fixed focus** — correct for about
148 mm and nowhere else. Which is self-consistent, and fine, right up until
autofocus starts moving the very variable the model assumed was nailed down.

Measured at 108 mm with `breathing_probe.py`, sweeping the lens over 7.0–11.0
dioptres and reading the dot at each:

```
  7.00 dpt   dx = 227.61      11.00 dpt   dx = 233.91
  0.68 %/dioptre, repeatable to 0.04 px, linear across the range
```

The optical measurement of focus breathing made independently gave 0.72 %/dpt.
Two different routes, the same number.

Uncorrected, that is **3.8 mm of distance error across the focus range** — the
lens moving turns into the target appearing to move. It also validates the
1.08 px pattern result from the other direction: `laser_align` ran at 7.7 dpt,
and interpolating the sweep to 7.7 gives 228.71 against its measured 228.77.

The fix is not to range at a fixed focus — that would cost an extra lens move
and 1.6 s of settling every cycle. Breathing is a change of *magnification*, so
normalising `dx` back to the calibration focus is a multiplication:

```python
dx_ref = dx / (1 + 0.0068 * (lens_position - 7.7))
```

Across the same sweep that takes the spread from 2.83 mm to **0.06 mm**, and it
lands on 108.25 mm against a nominal 108. The multiplicative form is physics
rather than measurement — it is only verified at this one distance, and a
second distance would settle it.

Triangulation still wants the measured table the brief prescribes, but that is
now a judgement about distortion over a 132 px sweep of radius, not the 1.5 mm
recorded above.

### What the centroid does *not* depend on

Three things were suspected of moving it and measured instead. All three are
worth less than a fifth of a pixel, which is a useful licence to stop worrying
about them:

| | dx spread |
|---|---|
| pixel format: Y plane vs XBGR, Rec.601 weights vs an equal average | 0.03 px |
| colour gains (1.0, 1.0) against (1.5, 1.5) | 0.10 px |
| exposure 500–8000 µs, 0.3 % to 34 % of the blob clipped flat | 0.18 px |

At 850 nm all three Bayer filters pass about equally, so the channel weighting
has almost nothing to weight differently. And the dot is symmetric enough that
flattening a third of it against the ceiling does not pull the centroid — which
means **the ranging frame's exposure is not critical**, a good property to have
when the surface's reflectivity is about to become the unknown.

So of everything that changed between two sessions, only the lens position
mattered. A 4.2 px shift that survived all of the above turned out to be the rig
itself moving 2.5 mm between runs.

### Recalibrating after a rebuild costs one point, not four

If the camera and laser are remounted as a rigid pair — same baseline, same
angle — but the pair sits differently in the housing, then only the offset from
the housing face to the optical reference changes. Both models carry that offset
as an additive constant:

```
dx  = X_PP + K/(d + C)          C  -> C  − δ
dpt = F_OFF + F_K/(d + F_C)     F_C -> F_C − δ
```

Same δ in both. So **one measurement against a known distance recovers it**, and
the four-position series is only needed if `K` or `X_PP` moved too.

That also gives a free check on which happened. Solve δ from the focus model and
from the laser model separately: if they agree, the pair is intact and only the
mounting depth shifted. If they disagree, the geometry between camera and laser
really changed and the full series is required.

`src/recalibrate.py` does exactly that from one measured distance, and
`--append` / `--fit` accumulate and refit the full series when the verdict says
the pair itself moved. The fitter is nonlinear only in the offset, so it scans
that and solves the other two parameters linearly — no dependency beyond numpy.
Against the four points above it returns `0.446 + 799.5/(d − 20.05)` and
`64.04 + 16775/(d − 6.40)`, reproducing the constants recorded here.

### One target for both measurements

Focus wants contrast and the laser centroid wants a uniform surface, which
looks like it forces swapping the sheet at every position. It does not: the
sweep runs with the laser off, so a blank patch contributes no gradient either
way — it lowers the metric slightly and cannot move its peak.

Page 2 of `targets/focus-target-A4.pdf` is therefore a 1 mm grating field with a
44 mm blank disc in the middle. The beam is near enough parallel to the axis
that the dot lands about 10.5 mm off it whatever the distance, so 22 mm of
radius leaves better than 10 mm of margin, and does not care which side the
laser is on.

### Metrics agreeing is not evidence the target has contrast

Smoke-testing the tool against blank white paper produced a peak at 9.30 dpt
with the Laplacian and the gradient agreeing exactly — and the whole curve
spanning 5.1 to 6.1, a ratio of 1.2 where a real target gives 14. Both metrics
are computed from the same flat frames, so they agree *because* there is nothing
there. The existing disagreement check cannot see this, and neither can the
darkness check: the scene was well lit.

The guard that works is the sweep's own dynamic range. Both `recalibrate.py`
and `focus_sweep.py` now report it, and `recalibrate.py` aborts below 3x.

### The search window needed both axes

`|dx| ∈ (100, 450)` keeps the tube edge out — it is the brightest thing in the
frame, sits at dx = 871, and once captured `laser_align` completely. But there
was never anything in `y`, so a bright enough reflection directly above or below
the dot would have won on brightness alone.

Measured `dy` runs 102–115 px over 80–180 mm, which is small enough to confirm
the beam really is in the camera's plane. The window is now 110 ± 45 px, and the
tracker warns while there is still a quarter of the margin left — a window that
silently clips is worse than none, because the reading just stops with no clue
why.

### The live view was magenta because the gains were a visible-light guess

`ColourGains` shipped at (1.5, 1.5). Under the 850 nm lamp that gives
R=225 G=148 B=222 — the two boosted channels up, green down, which is exactly
magenta. At (1.0, 1.0) the same scene reads R=190.7 G=179.2 B=178.1, so an IR
scene is very nearly neutral to begin with and wants almost no correction at
all. The defaults are now the measured (0.94, 1.01); the delivered stream reads
(R+B)/2G = 1.009 against 1.5 before.

Worth separating from a nearby fact: the *main* stream's pixel format has
nothing to do with this. The live view encodes the lores stream, so changing
main between XBGR and YUV420 cannot alter what a viewer sees — a coincidence of
timing made it look as though it had.

### Predictions made before measuring, and how they fared

Fitted to three points, both models were tested against a fourth at 108 mm:
focus predicted 9.51 and measured 9.55, an error of 0.4 %; the laser predicted
dx = 231.4 and measured 227.69, which is 2.3 mm of distance. Three parameters
against three points is an exact fit that validates nothing, which is why the
fourth point exists.

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
rsync -avz --exclude '.git' --exclude '__pycache__' ./src/ krausencamera:~/krausencamera/
```

> **Never `--delete` here.** The Pi's `~/krausencamera` also holds what only
> exists there: `mqtt.json` (credentials), `zero.json` (the fill-level zero),
> `af-model.csv` (the model the service reads), `matningar/` (every
> measurement) and the calibration sessions. `--delete` would remove all of it,
> because none of it is in `src/`.

## Architecture (settled 2026-09-02)

Departs from the brief on one point: **no MJPEG camera in HASS.**

| Channel | Content | Consumer |
|---|---|---|
| **MQTT** (discovery) | krausen height in mm, values to log | HASS |
| **Web view on the Pi** | live image, opened from phone or browser | a human, on demand |
| **NAS (SMB)** | one frame per minute, archive | later analysis |

HASS is not in the image path at all — only the data path.

### Scope: height is the only measurement (settled 2026-09-07)

The brief is ambiguous here and it is worth resolving explicitly, because it
decides how much machinery the capture path needs. It describes frame A as
giving "krausen structure and relief", but justifies locking the exposure by
saying the automatics would "compensate away exactly the brightness change that
is to be measured as the krausen builds".

**Only one number is measured: height, from frame B's laser dot.** Frame A is an
image, archived for a timelapse and for whatever a human wants to look at later.
Nothing is computed from it.

| | | |
|---|---|---|
| **measured** | height, mm | frame B, every cycle, to MQTT |
| **archived** | frame A stills | variable interval, to the NAS |
| **on demand** | H.264, minutes at a time | dry hop, from the lores stream |

What this removes: the **fixed warm-up from a known state** before frame A. That
protocol existed to keep the −2.83 % LED droop out of a photometric time series.
With no photometry there is no series to protect, `was_lit_for` becomes purely
diagnostic, and the cycle does not have to wait for the lamp.

What it does *not* remove: **locking the exposure**. That survives on two
grounds that have nothing to do with measuring. A timelapse shot with auto
exposure pumps and flickers, which is unwatchable at speed. And a fermentation
cannot be re-shot — locking now keeps the option of analysing the archive later,
while leaving it automatic forecloses it permanently.

So the constraint on viewer adjustments stands: the live view may be tuned to
taste, and the measurement cycle sets its own known state before capturing.
Same discipline as `FocusTracker`, for a different reason than first recorded.

### Something in the camera-laser geometry drifts, and it has not stopped

`dy` should be constant. Over one evening it went 110 -> 118 px, and I predicted
from 34 minutes of data that it would settle near 128. **It did not.** After
7.5 hours it stood at 141, still moving at 1.5 px/h, with `dx` up 21.6 px. The
apparent distance fell 100.7 -> 93.0 mm.

**The target never moved.** Three independent checks:

| | measured | if it really came 7.7 mm closer |
|---|---|---|
| image scale, by correlation | **1.000** | 1.083 |
| scene shift, vertical | **0 px** | would track the dot |
| sharpness at fixed focus | 7.8 -> **7.9** | visibly softer |

**Nor did the camera rotate.** The scene correlates best at 0.0 degrees, and the
geometry rules it out independently: a rotation about the optical axis would
sweep the dot around the principal point on a radius of about 265 px, not the
47 px observed. **Nor is the beam changing shape** — the spot measures 27.2 px
against 27.3-29 the day before, so nothing is creeping inside the module.

So the laser's pointing relative to the camera is drifting, and Love confirms
the mount itself is rigid.

> **A wrong turn worth recording.** The path fits a circle at 0.105 px rms
> against 0.719 for a straight line, and I read that as the barrel rotating in
> its bore with the beam off its mechanical axis. Love said the mount makes that
> impossible, and he was right to push: the comparison was invalid. A circle's
> residual is measured perpendicular to the path, a polynomial's vertically.
> Measured the same way, a **parabola fits as well as the circle** — 0.176
> against 0.193. Thirty-seven degrees of arc cannot tell them apart, so all the
> data supports is that the path is curved.

What does survive, and is worth more than the shape: `dx` and `dy` track a tight
curve against *each other* (0.18 px) while neither follows a simple relaxation in
*time* (0.56 px). **One degree of freedom is moving, not two independent ones.**

**Consequences.** Do not recalibrate until it stops. And the four-point series
was taken in descending distance order with `dy` rising monotonically
102.5 -> 108.5, which was read as variation with distance — it may be variation
with time, in which case the `dx` values are contaminated too.

The free test is still running: if `dx` reverses, the motion is rotation-like;
if it merely flattens, it is settling. `spread` and `peak` are now logged on
every line rather than only when the lens moves.

### The dot minus the target isolates the laser alone

With the target fixed and angles small, writing the camera's translation as δ,
its rotation as φ and the laser's rotation as ψ:

```
dot in image     = f·ψ − f·δ/d − f·φ
target in image  =       − f·δ/d − f·φ
difference       = f·ψ
```

**Both camera terms cancel.** Whatever the camera did, the dot's position minus
the target's measures the laser's rotation in space and nothing else. This is
the same invariance that makes triangulation robust to how the housing points,
used as a diagnostic instead.

```
dot − target   (+32.6, +21.0) px = 38.8 px  ->  laser  1.39°
target alone                11   px         ->  camera 0.39°
```

The housing and the laser turned 1.39 degrees; the camera followed only 0.39.
The difference is the camera board moving in its mount — the one thing that
changed when it was screwed down for the first time in this housing.

**Checked against a prediction.** If the tube's mouth is rigid with the housing,
it should have moved 1.00 degree, or 12 px at lores. Measured on its left edge:
13 px. And the parallax is there — the near mouth moved 13.0 px while the
distant target moved 4.1.

> **Direction is not established.** Three methods give three answers: Love's eye
> says down-right, the border crossings say the disc left the top edge, and a
> patch correlation says up-left. The mouth's edge is an illumination falloff
> rather than a mechanical edge, and the two frames were taken at different
> exposures, so each method finds its own point on a soft gradient and that
> point moves with brightness. The magnitude survives because it is a difference
> between two patches within the same pair; the direction does not. The frame A
> series settles it, since every frame is now at the same locked 25 ms.

### Frame A must be captured after the focus is applied

Love saw the tube's mouth grow across the first frame A series and read it as
the movement we were hunting. It was mine. The snapshot was taken inside
`measure()`, which runs **before** `_apply()` sets the focus — so the first
frame of every series is at whatever focus the process started with and every
later one is at the corrected value. Here that was 7.10 against 11.53
dioptres, and at 0.68 %/dioptre of breathing the first frame is at a different
magnification from all the rest.

Measured with a patch displacement field, which needs no edges or thresholds:

| | scale change | residual |
|---|---|---|
| frame 1 (7.10 dpt) -> frame 7 (11.53) | +0.86 % | 7.1 px |
| frame 2 (11.53) -> frame 7 (11.53) | **−0.01 %** | **0.8 px** |

**Between correctly focused frames nothing moved at all.** The apparent growth
was entirely the focus, and the series is otherwise clean enough to measure on.

That the field came out as a pure radial scaling rather than a translation is
what gave it away — a mount slipping shifts things, it does not magnify them.

### The autofocus loop is damped, not self-reinforcing

Love asked whether focus and distance could spiral: focus is set from a distance
that is itself focus-dependent through breathing, so each reading changes the
conditions for the next. The loop is real. Its gain is not.

```
G = d(focus)/d(distance) · d(distance)/dx · dx · epsilon
  =    0.1543 dpt/mm     ·   0.4368 mm/px · 260 · epsilon
  = 17.5 · epsilon
```

The decisive point is that `epsilon` is the error **in the breathing
coefficient**, not the breathing itself. A perfect correction makes `dx_ref`
independent of focus, so the gain is zero and the loop settles in one step; only
the correction's error is fed back.

| | G | error shrinks per iteration |
|---|---|---|
| correction on (0.0068 against 0.0072 measured optically) | **0.007** | 99.3 % |
| no correction at all | 0.119 | 88 % |
| correction with the **wrong sign** | 0.238 | 76 % |

Instability needs `epsilon > 5.7 %/dioptre`, eight times the breathing itself.
Removing the correction entirely, or inverting it, still converges.

**And the loop runs this experiment at every startup**, measuring at 7.10 and
again at 11.53 after it corrects:

```
lens  7.10 dpt   dx 258.56 -> 259.62 normalised   d = 92.2 mm
lens 11.53 dpt   dx 266.10 -> 259.35 normalised   d = 92.3 mm
```

0.1 mm apart across the whole focus range. Uncorrected the same two readings
give 92.6 and 89.4 — 2.8 mm apart, and *then* the focus would step again.

So the correction does two things, and the second was not the reason it was
written: it removes the bias, and it divides the loop gain by seventeen.

The 1.2 dioptre deadband is a further guard. Even at a gain near unity the loop
would **stop** rather than oscillate, since small corrections are never applied
— a limit cycle at worst, never a spiral.

### Both the camera and the laser are moving, in a ratio of 1 to 4

The drift **accelerated**: 1.5 px/h overnight, then 3.95, 4.08, 7.67 and
9.93 px/h across four hours the next morning, with the SoC temperature flat
throughout. Mechanical settling decelerates by definition, so that hypothesis
goes too. Something is giving way, and faster as it goes.

Measuring the scene took three attempts, and the first two were worthless:

- **Patch correlation** has nothing to lock onto. The target is blank white
  paper, and patches with a standard deviation under 10 counts returned
  agreeing nonsense — three neighbours all reporting −25 px.
- **Threshold crossings on the mouth's edge** wander with local brightness
  rather than geometry: +22 px on one column and −6 on its neighbour.
- **The centroid of the whole illumination pattern** works, because it averages
  three million pixels instead of reading one contour, and because exposure and
  focus are both locked so nothing but geometry can move it.

```
dy of the illumination pattern   +5.88 px over 4 h, monotonic
noise between adjacent frames     0.23 px
laser dot over the same window   +24 px
```

Twenty-five times the noise, so the scene really is moving — which every earlier
measurement had missed. **It is not the laser alone.** Against the algebra, the
camera terms account for about 6 px and the remaining 18 is genuine
camera-to-laser motion. Both are non-zero; they were treated as either/or.

> The centroid moves toward larger y, which is *down* the image and therefore a
> camera moving *up*. Love read the mouth as creeping up, which is the opposite.
> The centroid is not purely the mouth — the bright patch to the right pulls it
> — so the direction is not settled, only the fact of the movement.

**And PDAF holds still through all of it**: 104.6, 104.5, 105.1 mm across two
hours while the laser sat 14 mm away. The reading with no baseline is the stable
one, which is the case Love made for it before any of this data existed.

### The same target position, 24 hours apart

The speckle sheet went back on the floor, which is where the four-point
calibration started — its 180 mm point. That makes yesterday and today directly
comparable at one physical position, with focus as an independent reference.

| | yesterday | today | change |
|---|---|---|---|
| focus | 5.45 dpt | 5.70 dpt | +0.25 |
| -> distance | 179.8 mm | 172.2 mm | −7.6 mm |
| laser `dx` | 160.14 px | 194.87 px | **+34.7 px** |
| -> distance | 180.9 mm | 134.6 mm | **−46.3 mm** |

The focus moved 8 mm, which is inside the difference between "about 183" and
"180" — tape-measure slop. The laser moved 45 mm on a target that did not move.

**Focus is stable; the laser is not.** This is the cleanest isolation of the
drift so far: one physical position, a 24 hour baseline, and a reference that
shares no mechanism with the thing being measured.

> **Retracted.** I read this at first as `f·b` being 30 % low, on the grounds
> that 183 mm was outside the fitted range. Love pointed out the calibration
> started at the floor, so 183 mm is the range's own top end. Working backwards
> from that point gives `f·b = 16692` against the fitted 16782 — **the constant
> was right when it was measured.** What has changed since is the geometry.
>
> That thread is now closed, and not in favour of either guess. See below.

### The bright disc's edge is illumination, not the mouth

Love's argument for it being the mouth is sound — the aperture sleeve sits at
the lens and cannot be imaged at all, so a vignette edge needs a stop some
distance away. But measuring the falloff properly settles it differently:

```
r =  700    76 % of plateau
r =  963    50 %
r = 1190    10 %
```

**The transition is 500 px wide.** A geometric vignette from a stop at 40 mm,
imaged through the 1.5 mm aperture, has a penumbra of `D·(d−m)/m` at the target,
which is 5 mm, or **46 px** in the image. Ten times sharper than what is there.

So the disc's edge is the light running out — the lamp's distribution, cos⁴, and
the tube's inner wall — not the mouth's shadow. The rim surely cuts somewhere
further out, but it is not what dominates.

**Two consequences.** The `f ≈ 2150` inferred from it was never a measurement:
it computed a half-angle for a pattern that has no geometric half-angle.
`f ≈ 1590` from `f·b` and the known baseline stands unopposed.

And it retroactively explains why the ring fitted nothing. It moved +52 px in x
where the paper and the dot barely moved in x at all, and no mechanical motion
would account for it. None had to: **an illumination pattern is not fixed to the
housing.** It moves when the lamp's geometry does, or the inner wall's lighting,
not when the mouth does.

Every conclusion drawn today from "the mouth has moved" is therefore void. It is
the same error as the fixed-mask centroid and the mis-placed annulus, in a third
disguise — measuring the light and calling it geometry.

### Measure the mouth by where the texture stops, not by brightness

Love pointed out that the illumination is strongly asymmetric — light enters
from the right, so the right of the tube is lit only by floor reflection while
the left gets direct light, with a bright crescent on the rim itself. That makes
an **angular average invalid**: a sharp edge sitting at different brightness
levels around the circumference averages into a smooth ramp. The 500 px was
mostly that.

Single radial lines do not fix it — they pick up the speckle dots, and the
"steepest fall" is just a black dot. What works is **texture energy averaged
over a wedge**: where the speckle stops being resolved, the target has stopped
being imaged. That is a geometric edge and it does not care how bright the
region is.

```
right    speckle dies at 936 px
left                     757 px
up                       664 px   (the frame's own edge, not the mouth)
down                     beyond the frame
```

Left and right give a mouth centred about **90 px right of the image centre**
with a radius near **846 px**. At `f = 1590` that is a half-angle of 28.0
degrees, so a 42.6 mm aperture at 40 mm against a nominal 38 — twelve per cent,
on an arbitrary 50 % criterion over a gradual transition. Fair agreement.

**This reverses "drop the ring".** The mouth *is* measurable; brightness was the
wrong observable. An illumination pattern is fixed to nothing, but the radius at
which texture dies is fixed to the housing.

So three quantities, each anchored to something mechanical:

| quantity | fixed to | measured as |
|---|---|---|
| speckle target | the world | correlation, sub-pixel |
| mouth | the housing | radius where texture dies |
| dot − target | the laser | centroid minus correlation |

The blank landing disc also shows up as low texture near the centre, offset to
the right — the target's disc is not centred on the optical axis. Harmless at
present margins, worth knowing when re-aiming.

### The target decides whether a focus sweep means anything

Same sweep, same tool, same lamp:

| target | peak-to-floor |
|---|---|
| blank white paper | **1.1x** |
| random speckle | **21.4x** |

On paper the sweep returned a confident peak that was noise, and both metrics
agreed on it because both were computed from the same flat frames. On speckle
the two metrics land 0.20 dioptres apart on a peak worth twenty times the floor.
The guard that rejects the first and passes the second is the curve's own
dynamic range, not the agreement between metrics.

### A grating is the wrong target for tracking motion

Page 2 was built for recalibration and is fine for that. For chasing the drift
it fails twice:

- **Vertical bars carry no vertical information.** The correlation can localise
  x well and y hardly at all — and the drift is currently almost purely
  vertical, so it would measure the one axis that is not moving.
- **A periodic pattern is ambiguous.** The correlation peaks repeat every
  period. At 1 mm and about 20 px/mm that is 20 px, and the drift is already
  24 px, so a displacement can be read a whole period wrong and look healthy.

Page 3 is a **random speckle**, the pattern digital image correlation uses for
exactly this problem: broad spatial frequency content, no repeat to confuse a
correlator, and equal in both axes. Dots are 0.6-1.2 mm, which is 12-24 px at
this working distance, at 42 % coverage, with a 60 mm blank disc for the laser
to land in — larger than page 2's 44 mm because the dot sits 16 mm off axis and
is currently moving several millimetres a day.

> **On darkening the target around the mouth**, which Love suggested for
> contrast against stray light in the tube: the edge's position is set by the
> tube's geometry and its softness by the illumination falloff, not by the
> target's reflectance. Darkening there removes light without sharpening
> anything. What actually helps is texture running right out to the edge, so the
> *target* is trackable at that radius — which is what makes the parallax
> between a housing-fixed edge and a world-fixed target measurable at all.

### Measure the target's own features, not the light falling on it

Two of my measurements of "the target" were worthless, and Love caught both by
looking at the picture.

The first was a centroid inside a fixed mask. On a near-featureless white paper
the centroid is dominated by the mask's own geometry, so it reported 2.3 px
while the paper's creases were visibly travelling with the ring. A fixed mask on
a moving pattern always under-reports, and with nothing else to weight it, it
under-reports almost completely.

The second placed the annulus at r = 500..1100 without checking where the mouth's
edge actually was. The radial profile puts the steepest falloff at **r = 1022**,
so the ring had been measured well inside the disc, on an interior illumination
gradient. It reported 9 px where the edge had moved 57.

What works is high-passing the frame to strip the lamp's smooth gradient and
correlating what remains — the paper's creases are real image structure, and
they are the only thing in the frame that is genuinely *on* the target.

```
                        dx        dy
paper (creases)       -1.3     -24.8
laser dot             +2.2     +24.0
mouth (the ring)     +52.4     +23.3
```

**Paper and dot move equally and oppositely in y**, which no earlier measurement
had shown.

### The geometry checks out, and the focal length does not

The mouth is 38 mm across at 40 mm, a half-angle of 25.4 degrees. For the edge
to land at r = 1022 needs **f ≈ 2150 px**, and a steel rule in frame gave ~2015.
Neither agrees with the 1600 implied by `f·b = 16782` at b = 10.5 mm — which
would put the baseline nearer 8 mm. The four-point fit was taken over hours
while this drift was running, so it is the suspect.

### Dot minus paper is the only figure that isolates the laser

```
dot − paper = +48.8 px = 1.33 degrees over four hours at f = 2100
```

Twice what was recorded an hour earlier, because that calculation assumed the
paper was stationary and it is not.

**And it rules out the TC joint on its own.** Love's own argument: if the clamp
moves, camera and laser travel together, so the dot's image position is
invariant while the paper and the ring shift — the same invariance that makes
triangulation indifferent to how the housing points. The dot is not invariant.

The ring is a third witness agreeing with neither: +52.4 px in x where the paper
and the dot barely moved in x at all. Three parts, three different motions, and
the printed structure holding them is the only thing common to all of it.

### Three degrees of freedom, separated at last (2026-09-08, evening)

With the speckle target on the floor and focus locked, all three motions are
measurable independently over 3.7 hours:

| quantity | measured as | result |
|---|---|---|
| camera vs the world | correlation of the speckle | −9.77 px = **0.31 deg** |
| laser vs the camera | dot minus speckle | +16.98 px = **0.55 deg** |
| lens vs the mouth | mouth radius, −1.38 % | **0.55 mm along the axis** |

The third is new. A radius that shrinks symmetrically on both sides — right
−13.4 px, left −10.0 — cannot be a rotation or a lateral shift; it means the
mouth has moved *away* from the lens. Nothing measured earlier could see an
axial degree of freedom at all. The parts are separating in depth as well as
tilting.

**The rate is decelerating**: 2.27 px/h in the first hour of the session, 1.38
in the last, against 9.93 measured that morning. The first hopeful sign in a
day of them getting worse.

> But across the day the rate runs 1.5 -> 9.9 -> 1.4, which is not monotonic and
> not what plain creep does. Either the rig was disturbed in between or there
> are two processes with different time constants. No explanation is offered
> here, because none is known.

**PDAF holds at 185.3 mm** over 40 readings, spread 7.7 mm, against a tape
measure of about 183 — while the laser reads 135. The independent witness agrees
with the tape and the laser is 50 mm out, an error accumulated before this
session and now roughly static, which fits the deceleration.

### The image motion is not rigid, and the camera had been dropped on a drill

Love mentioned, after two days of this, that he had drilled out the camera
PCB's screw hole before fitting it to the new housing — the bit caught, he lost
his grip, and the whole module spun with the drill at 2000 rpm with the ribbon
attached.

That reframes everything, because it predicts something a rigid-body model
cannot produce, and the data has been refusing a rigid-body model all along.

**Fit the best rigid transform to the whole frame and look at what is left.**
Fifty patches, first frame against last:

```
best rigid transform   translation (+1.45, −9.65) px, scale +0.83 %, rotation 0.003 deg
residual after it      1.15 px mean, 3.06 px max
correlation noise      ~0.05 px
```

**Twenty-three times the noise**, and structured: 0.2–0.8 px in the middle,
2.4–3.1 along the left and right edges. A camera that has moved leaves a
residual at the noise floor, by definition — there is nothing left to explain.
A residual that grows towards the field edges is the mapping itself changing.

**And a second sign that no rigid motion can give.** Over the same window the
mouth's angular size shrank 1.38 % while the speckle's scale grew 0.83 %.
Opposite signs. An axial move of the camera changes both by different amounts —
they sit at 40 mm and 185 mm — but in the *same* direction, and so does a change
in lens-to-sensor spacing.

### Measuring the tilt: sweep once, peak per sector

`src/tilt_probe.py` sweeps `LensPosition` and finds the sharpness peak in eight
sectors of an annulus, all from the same frames so nothing time-varying can
masquerade as a tilt. The annulus avoids the speckle target's blank landing disc
inside and the mouth's cut-off outside.

| sweep | amplitude | direction | residual |
|---|---|---|---|
| 4.0–7.6 dpt | 0.152 dpt | 118 deg | 0.066 |
| 2.0–11.0 dpt | **0.193 dpt** | **116 deg** | 0.047 |

Same direction within 2 degrees, and 4.1 sigma against its own residual. In
physical terms 0.193 dpt at 185 mm is 6.6 mm of focal plane displacement over a
63.7 mm field radius — 5.9 degrees object-side, so about **0.17 degrees of lens
against sensor**, or 19 µm across the sensor's width.

> **Two things this does not establish.** There is no "before" measurement, so
> 0.17 degrees could be factory tolerance rather than damage; the spare camera
> is the control, which is why it is worth measuring before it is fitted. And a
> tilt that is *static* does not drift — the evidence that the mapping is
> changing is the 1.15 px residual, which is a different observable. They point
> the same way without being the same measurement.

**The reassuring part**, given that a settling time measured in days is alarming
for the method: it is not a property of laser triangulation. The 0.03–0.07 px
repeatability measured earlier in the week came from this same camera *before*
the drill. A sound module does not do this.

### The spare camera measures 40 % less tilt, with a sharper instrument

The control the tilt figure needed. Same target, same lamp, same sectors:

| | old camera | spare |
|---|---|---|
| tilt amplitude | **0.193 dpt** @ 116 deg | **0.114 dpt** @ 136 deg |
| fit residual | 0.047 | **0.031** |
| contrast per sector | 6.6–9.2x | **16–27x** |
| lens against sensor | ~0.17 deg | ~0.10 deg |

The spare has no aperture sleeve, so its depth of field is narrower, its peaks
sharper and its contrast three times higher — it measures **less** tilt with a
**more** sensitive instrument, which makes the comparison stronger than the
numbers alone. The directions differ by 20 degrees, so these are two units with
their own tolerances rather than one shared defect.

**The spare is new out of its box**, which makes 0.114 dpt the *factory* figure
rather than a used one — so 0.193 on the damaged module sits clearly above
factory and the drill is worth the difference, roughly doubling it. That is the
control this measurement needed, and it turned out to already exist.

It also means some tilt is simply normal: a fresh module gives 0.10 degrees, so
there is no point chasing below that.

**Centring, and what cannot be measured.** By the same texture-death estimator:

| | mouth centre in x | radius |
|---|---|---|
| new camera | **+28 px** (0.66 mm at the mouth) | 831 px |
| old, *after* the damage | +87 px (2.0 mm) | 848 px |

Three times better centred — but against the *damaged* old module. Love's
impression is that it centres worse than the old one did *before* the drill, and
no measurement of that state exists, so it can be neither confirmed nor
contradicted.

> And only in x. The mouth's radius is 831 px where half the frame height is
> 648, so the texture never dies going up or down and vertical centring is
> unmeasurable at this working distance. If what Love sees is a vertical offset,
> none of these numbers speak to it. A caliper against the housing's aperture
> answers it faster than moving the target closer would.

> Absolute dioptres are **not** comparable between modules — the spare peaks at
> 4.4 dpt where the old one peaked at 5.5 on the same target, because the VCM's
> zero differs per unit. Only the spread between sectors carries over, and even
> that assumes similar VCM gain.

**A photometric hint in passing.** The spare needs 15 ms where the old camera
needed 90 for the same mean level, a factor of 6. Removing a 1.5 mm stop from
f/1.8 should give 3.1. The missing factor of 1.8 is consistent with the old
camera losing light — which is what a displaced lens does — but it is one
comparison across two units and two exposures, so it is a hint and not a
measurement.

### The module can focus itself, and it is a second opinion worth having

The Camera Module 3 has phase-detect pixels, so it does not need the laser at
all. Tested under the 850 nm lamp: it converges every time, in about 4 s, from
either end of its travel, repeatable to 0.25 dioptres.

It lands at 9.9 dpt where the laser says 11.53 — **1.6 dioptres apart**, which
is 12 mm of distance.

> **Two reasons that does not convict the laser, both Love's.** The aperture was
> fitted to widen the depth of field, and the measured 64 mm at the 80 %
> criterion is three dioptres wide — so a contrast sweep *cannot* localise focus
> better than about a dioptre, and the 1.1x peak-to-floor it returned here is
> exactly what that predicts. The sweep's apparent peak at 9.7 is not evidence.
> And an external stop can bias phase detection outright: PDAF compares light
> from opposite halves of the pupil, so a stop that is even slightly decentred
> vignettes the two halves unequally and puts the null somewhere other than true
> focus.

What survives is a pattern a constant bias cannot produce:

| | distance |
|---|---|
| yesterday: laser *and* contrast sweep on the patterned target | 108.6 mm |
| today: PDAF | 104.6 mm |
| today: laser | **92.2 mm** |

PDAF today lands where the laser and the sweep agreed yesterday. Today's laser
is the outlier.

**As the measurement it is useless.** 0.112 dpt/mm at 105 mm against a 0.25 dpt
repeatability is 2.2 mm, where the laser gives 0.031 — seventy times worse. And
the aperture makes that structural rather than incidental: it was fitted so that
focus need not be precise, which is the same property as focus being a poor
ranger. You cannot have both.

**As an independent witness it is exactly what was missing.** It shares no
failure mode with the laser — no baseline, no centroid, no beam — so it is blind
to everything that has gone wrong this week. `--pdaf-every N` runs it every N
cycles, logs the implied distance beside the laser's, flags a gap over 4 mm, and
puts the lens back where it was.

### Measure the creep at fixed focus

The breathing correction `dx / (1 + 0.0068·(lp − 7.7))` is a *model*, with one
coefficient measured at one distance. It belongs in the production path, where
autofocus has to move. It does not belong in a drift study, where the whole
point is to observe rather than to model — a slow focus change would enter the
reading through the correction's own error and be indistinguishable from the
thing being measured.

So the drift run holds `LensPosition` at 11.53 with the threshold set high
enough that the tracker never moves it. `dx` and `dy` are then raw.

It also buys a free diagnostic: **at fixed focus, sharpness tracks distance.**
If the target ever really moves, the frames soften — and that is an independent
check on the reading, using no laser at all.

### Ranging and archiving need separate clocks

Frame A was captured inside the ranging cycle, so adding the archive at five
minute intervals silently slowed ranging from 60 s to 300 s. A height is a few
bytes and wants to be frequent; a frame is 200 kB and does not. They now have
`--af-interval` and `--snapshot-interval` independently, which is what the
architecture called for in the first place: constant fast height, variable image
rate.

### Ambient temperature is a live variable, and was not being logged

The garage door opened twice during the test window, onto cold air. The Pi is
outside the housing and the lamp is in the stainless lid, so nothing inside
heats the body appreciably — **it follows the room**. That makes a door opening
a real disturbance, and overnight cooling a continuous one, which would explain
a drift that decelerates but never asymptotes.

The SoC temperature now goes into every log line as a stand-in for ambient. It
is a poor thermometer in absolute terms but it moves with the room, which is all
the correlation needs.

**And the room's own log rules the hypothesis out.** Over the drift window the
garage moved 22.2 -> 21.8 C, four tenths of a degree, while `dy` moved 21 px —
0.75 degrees of relative rotation at f = 1600.

| | |
|---|---|
| implied sensitivity | **1.9 deg/C** |
| what expansion can give | 0.0021 deg |
| short by | a factor of **365** |

And that 0.0021 already assumes the *entire* length change of a 30 mm ABS-GF
body appears as a pure differential across a 10 mm arm, with no symmetry
anywhere. The real figure is far smaller. Thermal expansion is not off by a
little; it is off by two and a half orders of magnitude.

So the garage door was a good lead and a dead end, and the graph is worth having
for a second reason: **the room holds ±0.4 C overnight and about 2.5 C over a
day.** The measurement environment will not be the limitation.

What survives every elimination — target, camera, beam shape, tube mouth,
temperature — is mechanical creep, which is also the only candidate that fits
the deceleration measured at 0.36 -> 0.13 -> 0.025 px/min. That is Love's own
first suggestion: preload relaxing in a mount screwed down for the first time.

The temperature logging stays anyway. It costs nothing, it makes the null result
quantitative rather than argued, and if `dy` ever steps when the door opens the
conclusion is wrong and it will show immediately.

### Auto exposure for the live view, locked for the archive

These are different jobs and they were conflated in one flag. The live view is
watched by a human across a scene that spans about 2.3x from an empty tank to
high krausen, so it wants auto exposure. Frame A is archived and wants a locked
one — not because anything is measured from it, but because a timelapse shot
with auto exposure pumps, and because a fermentation cannot be re-shot to
recover the option later.

So `liveview.py` now runs AEC by default; `--exposure-us N` locks it when you
want that, and the measurement cycle sets its own state before capturing
either frame regardless.

**White balance stays locked either way.** Under 850 nm the channels sit within
6 % of each other, so AWB has nothing real to correct and would only chase
noise. The old `--auto` unlocked both at once and is now `--auto-wb`, which is
useful only for aiming in visible light.

The chosen exposure and gain are on the page, because otherwise there is no way
to tell AEC from a locked value without changing the scene and squinting.
Measured on the bench: 15.8 ms at gain 1.12 with the lamp lit, opening to
40.3 ms at gain 15.5 when the ranging cycle takes the lamp away.

> **Known wart:** that swing happens once a cycle, so a viewer sees a bright
> noisy moment while AEC re-converges after each ranging. The `ranging...`
> label explains it, but damping it would mean holding the last good frame for
> the few seconds the lamp is off.

### Choosing the locked exposure

Against the brightest scene it will ever see, not the one in front of you. The
scene brightens about 130 % as the krausen rises toward the lamp, so an exposure
set at rest level clips at high krausen -- and a clipped frame cannot be
un-clipped, while a dark one can be stretched.

`src/exposure_probe.py` sweeps exposure and reports the percentiles. Measured
2026-09-07 against white paper at 104 mm, which is conservative twice over:
brighter than foam, and closer than high krausen is expected to come.

| exp | mean | p99.9 | clipped |
|---|---|---|---|
| 8 ms | 67.6 | 132 | 0 % |
| 25 ms | 145.9 | 225 | 0 % |
| 37 ms | 177.6 | 247 | 0.002 % |
| 50 ms | 200.4 | 255 | **8.2 %** |
| 75 ms | 225.0 | 255 | 25.6 % |

**25 ms** is the longest exposure that keeps the 99.9th percentile under 230.
Extrapolating to rest level by the inverse square gives (104/150)² = 0.48, so a
mean near 70 there — well clear of the noise, and the far end is not the
constraint.

Two notes on the criterion. It is the 99.9th percentile rather than the maximum
because foam glints: bursting bubbles will always clip a few pixels, and chasing
zero would force a needlessly dark image. And it reads the **max across R, G
and B**, since whichever channel clips first is the one that matters.

> **The live view's 60 ms default is clipping about 15 % on this scene.** It was
> chosen for a working distance the rebuild has since halved. Which is the
> argument for making the live exposure adjustable rather than picking a new
> constant: the same 2.3x spread that forces frame A to be set for the bright
> end leaves a single live exposure wrong at one end or the other.

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

   **Measured 2026-09-04**, three 850 nm LEDs (Vishay TSHG5410) at 114 mA, in
   an open cavity in a thin-walled PTFE cup with a retaining plug above them --
   not potted, but with little room for air to circulate. Locked exposure, cold
   start after 19 minutes off:

   | | |
   |---|---|
   | cold start | 170.19 mean level |
   | settled | 165.37 |
   | **total droop** | **−2.83 %** |
   | half the change | 1.7 min |
   | 90 % | 8.5 min |
   | 99 % | 19.1 min |

   Two time constants stacked: the junction heats in under two minutes, the
   cup and its surroundings over roughly twenty. The datasheet gives
   **-0.27 %/K** for radiant power, so the droop is about **10 K** of rise after
   the first frame -- a lower bound, since whatever the junction gained in the
   first second is already in the "cold" reading. An earlier version of this
   note assumed ~1 %/10 K and called it 28 K and "a thermos"; neither holds.

   > **The drive, measured 2026-10-08:** 12 V switched supply, 2 x 33 ohm in
   > series on the housing side, 4.67 V across the three LEDs (1.56 V each),
   > **110 mA**. The datasheet's maximum is 100 mA continuous and 180 mW; each
   > LED takes ~0.17 W. Within power, 10 % over current. ~80 ohm (~92 mA) at
   > the next rebuild, before a calibration, not during one -- the lamp's heat
   > moves the reading. A first meter read 0.17 A; a second gave 110 mA, which
   > is what 12 V and 66 ohm predict.

   So `was_lit_for` spans about **2.8 %**, which is small next to the ~130 % the
   scene brightens as the krausen rises toward the lamp. Worth flagging in
   metadata, not worth correcting for. Ten minutes of warm-up puts you within
   0.2 % of settled.

   ⚠️ Beware measuring this on the tail: an earlier reading over 13 minutes of
   an already-warm lamp showed only −0.3 % and led to the wrong conclusion that
   the LEDs barely heat at all.

### ⚠️ A clear liquid surface returns nothing — the beam reads the bottom

Measured 2026-09-06. The concern was that triangulation needs the surface to
**scatter**, and that a liquid surface is largely specular. It is worse than
that: with clear water there was no surface return at all.

Reference, dry bottom at 182 mm: one spot, `r = 166.2 ± 0.11 px` at **21.9°**,
peak 168. That calibrates `f·b = 30248 px·mm` for this installation.

Then 28 mm of clear water over the same bottom:

| | radius | angle | peak | movement | implies |
|---|---|---|---|---|---|
| outer | 171.3 px | **22.0°** | 44 | 0.06 px | 176.6 mm |
| inner | 84.3 px | 29.4° | 10 | 0.59 px | — |

The outer spot shares the laser's angle, so it is a direct return — but its
radius corresponds to **the bottom seen through the water** (predicted 175.1 mm,
measured 176.6, a 1.5 mm match). The surface would have sat at r = 196.4 px and
there was nothing there.

The inner spot is 7.5° off the laser's line, so it cannot be a direct return. It
is the lid reflected in the water surface — dim, and mobile because the surface
is a moving mirror.

**The failure mode is the dangerous one.** The measurement does not fail; it
succeeds with the wrong answer. A clear spot, on the correct angle, at a
plausible radius, with a standard deviation of 0.06 px — among the steadiest
readings taken. Nothing in the signal says it is the wrong surface.

**An angular region of interest does not catch it.** Restricting the search to a
band along the laser's radial line rejects the specular ghost, which is off
angle. It cannot reject the bottom return, which is the same beam further away.

### What that means for the vessel

There is no bottom 28 mm down in an F80 — the liquid is half a metre deep, so
the beam scatters in the **volume** instead. The return then comes from a
penetration depth set by turbidity: cloudy wort returns near the surface, clear
beer returns further down. The zero reading therefore carries a
turbidity-dependent bias of some millimetres, and it differs between a cloudy
ale wort and a clearer lager one. Krausen height is measured relative to that
zero, so a constant bias cancels — but it is worth knowing it exists.

During active fermentation the surface is foam, which scatters well, so this
does not touch the main measurement. It touches the **zero reading at fill** and
the **packing phase**, and at packing there is usually foam as well.

### The spot is an image of the beam's path, not a point

Adding milk to the water bracketed the turbidity, and the result changed what to
measure. Water column 175 mm across, 25 mm deep, 601 ml:

| milk | radius | centroid depth | peak | spot px |
|---|---|---|---|---|
| 0 % | 171.7 | 25.5 mm | 64 | 144 |
| 0.17 % | 172.6 | 24.3 mm | 25 | 250 |
| 0.83 % | 181.9 | 12.4 mm | 47 | 677 |
| 1.50 % | 182.5 | 11.6 mm | 51 | 939 |
| 2.33 % | 182.5 | 11.6 mm | 54 | 1403 |

The centroid stopped moving at 182.5 while the spot kept growing, which is the
signature of something other than a point return. A spot of 1403 px is a disc of
radius 21 px, and the whole surface-to-bottom range spans 20.6 px. The spot **is**
the beam's illuminated path through the liquid, imaged.

Its radial profile confirms it. At 30 % of peak the spot runs from r = 170.3 to
193.9, against 172.1 for the bottom and 192.7 for the surface — the full column.

### So read the outer edge for liquid, the centroid for foam

| threshold | outer edge | implied depth |
|---|---|---|
| 0.50 | 189.7 | +3.2 mm |
| **0.30** | **193.9** | **−1.3 mm** |
| 0.20 | 198.6 | −6.2 mm |

The edge at a 30 % threshold finds the surface within about a millimetre, where
the centroid is 11.6 mm deep. The edge is threshold-dependent, so the threshold
must be fixed and calibrated rather than chosen per reading.

**And the spot's radial extent is a free diagnostic.** A compact spot means the
beam stops at the surface — foam, or liquid turbid enough — and the centroid is
right, with the 0.07 px precision measured on paper. A radially drawn-out spot
means the beam is penetrating, the centroid is systematically deep, and the edge
is the reading to take.

The algorithm therefore does not need to be told whether it is looking at foam
or liquid. It can measure that, and the same number becomes a quality flag worth
logging with every reading.

### The principal point is not the image centre

The dot's vertical offset had drifted between sessions -- +56, +37, +63, +71 px
-- and computing the laser's height from it as `v = b·dy/dx` gave 5.9 mm, which
the mechanics rule out: camera and laser sit in the same plane by construction.

The error was assuming the optical axis meets the sensor at its centre. It does
not, and the two explanations predict opposite things: a principal point offset
is a **constant** in the image, while a real height offset on the laser is imaged
like the sideways one and therefore **grows** as distance shrinks.

White paper at two measured distances settles it:

| | dx | dy |
|---|---|---|
| 182 mm | 162.46 ± 0.06 | 70.36 ± 0.24 |
| 84 mm | 342.54 ± 0.12 | 71.72 ± 0.25 |
| predicted, offset principal point | — | 70.4 |
| predicted, high laser | — | 152.4 |

`dx` more than doubled while `dy` moved 1.4 px. Solving both axes:

```
principal point      (1160, 717)      +8.1, +69.2 px from the image centre
laser height offset  0.113 mm         zero, as built
f·b                  28092 px·mm  ->  f = 5.24 mm

distance             d = 28092 / (x − 1160)
```

The principal point sits 0.19 mm from the sensor centre, an ordinary tolerance.
It also explains an earlier contradiction: measuring radius from the image
centre put the far end of a target at 209 mm inside a box 182 mm deep.

**Consequences.** The measurement variable is `x − 1160`, a horizontal distance
from the principal point, not a radius from the image centre — which is both
more sensitive and free of a needless nonlinearity. The region of interest is a
horizontal band centred on y = 717.

**Tested, and it held.** Two points against two parameters is an exact fit that
validates nothing — the `LensPosition` model failed exactly this way, predicting
11.45 for its third point where the measurement gave 13.16. This one predicted
`dx = 220.9` at 132 mm and measured 218.79, an error of 1.3 mm.

Refitted against all three points:

```
x = 6.77 + 28167/d          principal point (1159, 717)
                            f = 5.26 mm, laser height offset 0.114 mm

     d   measured   model   residual
   182     162.46  161.54    −1.08 mm
   132     218.79  220.16    +0.85 mm
    84     342.54  342.10    −0.11 mm
```

Within ±1.1 mm across the range, and the parameters barely moved from the
two-point solution. The residuals alternate in sign, which is the signature of a
small systematic curvature — lens distortion, most likely — but at a millimetre
it cannot be separated from the by-eye accuracy of the target heights.

That is close to the brief's 0.3–0.5 mm target but not inside it, which is
another reason the calibration table is measured rather than computed: it
absorbs the curvature along with everything else.

### Two cheap guards

- **Flag more than one spot.** A second return means the situation is not what
  the model assumes.
- **Flag a radius outside the plausible range.** In the vessel the bottom is
  half a metre beyond any possible liquid surface, so a through-liquid reading
  lands far outside and is caught — which it would not have been in this
  28 mm test rig.

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
