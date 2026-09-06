# What the housing has to provide

Requirements derived from measurements on the test rig, for the redesign. Every
number here came out of a measurement rather than a specification, and each says
what it is protecting against.

## Laser baseline: 12 mm

The dot's image radius and the tube mouth's both scale as `offset / distance`,
so their ratio is fixed at `b/R`. With a 19 mm tube radius, a 15 mm baseline puts
the dot's maximum at 79 % of the ring — a 21 % gap that a tilted TC gasket eats
into, and that the spot's own width eats further at close range.

At 12 mm the gap is 37 %. The cost is precision, which scales directly with the
baseline: measured repeatability goes from 47 µm to about 59 µm against the
brief's 300–500 µm target. Six times the margin becomes five.

**Search window.** Set the upper bound at `r_max = f·b / L`, with L the tube
mouth's distance. It is a constant in the rigid camera-laser frame, computed
once, and it excludes the ring without any per-frame fitting. Tilt would have to
reach roughly 6° before the ring intruded.

## A defined seat for the camera board

The dot's vertical offset moved +56, +37, +63 px across three mountings. In the
image that is the principal point's apparent position; mechanically it is the
board landing differently in its play, 1.5–2 mm.

Vertical play is harmless — it is the cross axis, and the measurement uses the
horizontal position. **Play along the baseline is not**, because it changes `b`
and therefore the whole calibration. A seat, a pin, anything that makes the board
land the same way twice.

Worth logging the vertical offset anyway: it costs nothing and it is a free
indicator that the mounting has shifted, which warns that the horizontal may
have moved too.

## Contain the laser's stray light

The ghost — the laser's own aperture reflected in a liquid surface — measured as
bright as the real return, 51 against 51. Brightness is therefore useless as a
selection criterion, and the ghost's angle moves with the surface tilt so it
cannot be excluded geometrically either.

The present bore is 3 mm across and 10 mm long, which passes everything within
17° of the beam. A longer bore, a smaller exit aperture, and a second baffle
would cut it. Check first whether the beam is grazing the bore: if it is,
alignment fixes more than blackening will, since the beam must exit regardless.

## Frame B's exposure must scale with distance

The return grows as `1/d²`, so a fixed exposure is wrong somewhere in the range
by construction. The dot saturated from 12 ms all the way down to 800 µs, and at
the tube mouth it would be 19 times brighter still than at rest level.

A saturated spot blooms, and its apparent width is then set by the exposure
rather than the optics — which is exactly where it matters, because a wide spot
at close range is what closes the gap to the ring. Scale by `d²` from the
previous cycle's reading.

## Somewhere for the LED heat to go

Three 850 nm LEDs at 114 mA potted in a rod dropped 2.83 % in output between cold
and settled, half of it inside two minutes and the rest over twenty. That is
roughly 28 °C of package rise with no conduction path out.

It does not affect the height measurement, which is taken with the lamp off. It
does affect frame A's brightness, and it is the reason `was_lit_for` is logged
with every reading.

## The optical parts are part of the calibration

The 1.5 mm aperture, the laser, and the camera board together define `f·b`, the
principal point and the ring's radius. **Any of them moving invalidates the
calibration table**, so they need to be rigid with respect to each other, and the
aperture in particular has to be centred before the table is measured rather than
after.

## The numbers change, the procedures do not

A redesign invalidates every figure in this file. It does not invalidate the way
they were obtained: `laser_align` for the baseline geometry and the principal
point, `focus_sweep` for the focus table, `laser_spots` for the returns and the
artefacts. A full recalibration is an evening's work.
