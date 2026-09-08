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

What survives is mechanically anchored: the **speckle target**, fixed to the
world and correlatable to sub-pixel anywhere in frame, and **dot minus target**,
which isolates the laser whatever the camera does. The ring is dropped.

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
