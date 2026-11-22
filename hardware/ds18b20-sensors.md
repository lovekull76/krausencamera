# DS18B20, 1-Wire on GPIO24

```
dtoverlay=w1-gpio,gpiopin=24        in /boot/firmware/config.txt
VDD 3.3 V (pin 17)  ·  DQ GPIO24 (pin 18)  ·  GND (pin 20)
4.7 kΩ between DQ and 3.3 V
read /sys/bus/w1/devices/28-*/temperature, in thousandths of a degree
```

⚠️ **3.3 V, never 5.** The DS18B20 takes either, but fed from 5 V it pulls the
data line to 5 V, and the Pi's GPIO tolerates 3.3. A pull-up to 5 V through
4.7 kΩ limits the current through the clamp diode to 0.30 mA and is survived --
it happened here on 2026-09-11 and GPIO18 came through -- but that is luck, not
design.

Since 2026-10-03 a Pimoroni Wide Input SHIM sits on pins 1–12, where both the
lamp (GPIO17) and the bus (GPIO18) used to be. Everything moved to the cluster
at pins 17–20: 3.3 V, GPIO24 (the bus), GPIO10 (the lamp) and GND. The laser on
GPIO27 is gone. Before the move: GPIO17 the lamp, GPIO27 the laser, GPIO18 the
bus.

## Offsets between the sensors, measured 2026-09-12

All three bundled together for ten minutes, until none had moved more than
0.05 °C in two minutes. The last six readings:

| id | reading | offset | placement |
|---|---|---|---|
| `28-ef39cb356461` | 23.3120 °C | reference | the TC ferrule of the camera housing |
| `28-f161ca356461` | 23.1870 °C | −0.1250 | the experiment board on the lid |
| `28-fe3ecb356461` | 23.2500 °C | −0.0620 | ambient, outside the box |
| `28-713ecb356461` | — | not measured | **the aluminium plate in housing v2**, in the pocket beside the module (2026-10-03) |

> The plate sensor arrived with housing v2 and has no measured offset against
> the others. Since 2026-10-11 it is the service's `--lid-sensor`: in the final
> housing it follows the reading with no lag, door dips included, at
> 0.048 dpt/°C (see `CLAUDE.md`, "The final housing").

**Largest difference 0.125 °C**, i.e. two quantisation steps -- at 0.63 mm/°C
that is 0.08 mm if two sensors are compared directly.

Absolute accuracy is ±0.5 °C and does not matter: we measure changes. The
offset matters only when two sensors are compared with each other, for example
the lid against the air in the box, and then the figures above must be
subtracted first.

> The placements above are the planned ones. **The ids are random and cannot be
> derived from a position** -- if a sensor is moved without this table being
> updated, there is no way to discover it afterwards.

## Why the TC ferrule

It is welded into the 8-inch lid and the camera housing is clamped onto it, so
it *is* the joint between the large stainless mass and the ABS housing. Metal
also gives good contact and a fast response.

But it sits on the lid's side of the plastic, and ABS conducts poorly -- so the
ferrule is a **leading indicator** of the module's temperature, not a measure
of it. The same relationship as `SensorTemperature`, but from the other side,
so together they bracket the optics between them.

Tape it on and put a piece of foam over it. A sensor against metal with air at
its back reads somewhere between the metal and the air.
