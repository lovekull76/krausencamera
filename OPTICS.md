# Depth of field, and why it is not the constraint

Written for a photographer who reasonably expected depth of field to be the
problem here. It is not, and the reason is worth stating precisely.

## The optical regime

| | |
|---|---|
| Sensor | IMX708, 1.4 µm pixels, used 2×2 binned → **2.8 µm** effective |
| Lens | Camera Module 3 standard, f = 4.74 mm, native **f/1.8** |
| Added stop | 1.50 mm printed aperture → **f/3.16** |
| Illumination | 850 nm IR |
| Working distance | 100–180 mm |
| Magnification | 1:44 at 180 mm to 1:20 at 82 mm |

Photographically this looks like macro, but at 1:20 to 1:44 it is nowhere near
it. Depth of field at those magnifications is generous, not razor thin.

## The aperture, verified rather than assumed

The stop is a hole in a printed sleeve over the lens. Its effect was measured
photometrically rather than trusted: signal above the black pedestal fell from
148.76 to 47.89 at identical exposure, a ratio of **0.322** against 0.32
predicted for 1.5 mm. Working back, `N = 1.8/√0.322 = 3.17`, so
`D = 4.74/3.17 = 1.50 mm`. The printed hole is 1.50 mm without drilling.

Cost: **1.63 stops**. Paid entirely in exposure time, which is free here — the
krausen rises millimetres per hour and the measurement takes two frames a
minute. Photon count is unchanged, so signal-to-noise is unchanged; only the
shutter gets longer.

## Diffraction: already at the limit wide open

This is the part that surprises people coming from full-frame.

With 2.8 µm pixels and 850 nm light, the f-number at which the Airy disc equals
one pixel is

    N = pitch / (2.44 λ) = 2.8 / (2.44 × 0.85) = **f/1.35**

The lens is **f/1.8 wide open**. It is diffraction-limited before any stop is
added:

| | Airy diameter | in binned pixels |
|---|---|---|
| f/1.8 native | 3.73 µm | 1.33 |
| f/3.16 with the stop | 6.55 µm | 2.34 |

There is no sweet spot to hunt for. From the first stop down, every bit of depth
of field is bought directly with resolution. Long wavelength is half the reason:
850 nm is 1.6× the diffraction of green light for the same aperture.

## Measured depth of field

Not calculated. A printed target with single-frequency gratings at 2, 1 and
0.5 mm was placed flat at three measured distances, and focus was swept at each.
The criterion is 80 % of peak contrast on the 1 mm grating.

| focused at | depth of field | span |
|---|---|---|
| 182 mm | **63 mm** | 150–214 mm |
| 132 mm | **50 mm** | 119–169 mm |
| 82 mm | ≥32 mm | 65–97 mm |

Shrinking with distance roughly as expected. The 82 mm figure is a lower bound —
the sweep hit the lens's 15-dioptre limit before contrast fell to the criterion.

The working range of 100–170 mm spans about 4 dioptres of focus while the depth
of field is 2.4–2.8, so **one fixed focus nearly covers it but not quite**. Two
or three discrete positions cover it comfortably, switched when the measured
distance moves more than half the depth of field.

## Why the worry does not apply to the measurement

Krausen height is measured from a laser dot's **centroid**, not from a sharp
image. Defocus blur is symmetric, so it spreads the spot without moving its
centre of mass — and a spot spread over more pixels averages sensor noise better,
not worse.

That was measured, not assumed. Sweeping focus across four dioptres with the
target stationary, the spot grew from 678 to 808 pixels while the centroid moved
smoothly and monotonically, with no lateral wander. Short-term repeatability of
the radius is **0.070 px**, which is 47 µm of height.

What focus *does* change is magnification — 0.72 % per dioptre, measured. That
produces a gain error on height rather than an offset, because height is a
difference of two distances and both scale together: 0.2 mm on a 30 mm krausen
across the realistic focus range. The relation is linear and measured, so it can
be divided out exactly if the focus value is logged with each frame.

So depth of field governs how good the *picture* looks. It does not govern the
number.

## What we could not establish

`LensPosition` is documented in dioptres but is not. Three measured points give
5.80, 7.70 and 13.16 at 182, 132 and 82 mm, and `1/LensPosition` is not linear in
distance — the two 50 mm steps give slopes differing by 27 %. A two-parameter fit
to the first two points predicted 11.45 for the third and the measurement gave
13.16, so the model was rejected.

Three points cannot determine which better form is right, and none is needed: a
small interpolation table serves, which is what the brief already prescribes for
the triangulation and for the same reason — it absorbs every systematic error at
once without requiring any of them to be understood.

Note also that 82 mm needs 13.2 of the lens's 15.0 available, and Camera Module 3
is specified to focus no closer than 100 mm. We are operating below spec. It
works, and the image is usable, but performance there is not guaranteed and the
departure from a linear dioptre scale is probably part of the same story.
