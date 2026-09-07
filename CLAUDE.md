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
