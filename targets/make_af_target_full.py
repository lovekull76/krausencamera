#!/usr/bin/env python3
"""Speckle over the whole of a landscape A4, edge to edge.

`make_af_target.py` leaves a 250x175 mm field inside the page. This one runs to
the paper's edge and lets the printer clip whatever it cannot reach, because on
the stage the target has to stay large in frame at the *far* end of the travel.

The tube's mouth sets a fixed angular aperture -- about 846 px of radius in the
2304-wide frame -- so the visible circle grows with distance:

    d = 108 mm   ~110 mm across      ~15.4 px/mm
    d = 240 mm   ~244 mm across       ~6.9 px/mm

Phase detection meters a central fraction of the frame rather than all of it,
perhaps a third, which at 240 mm is around 80 mm. An A4 sheet covers that with
room to spare even unmargined -- but every millimetre of margin is texture that
is not there at the distance where the measurement is already worst.

**Square sizes 0.6-1.6 mm**, a little wider than the bordered target's
0.6-1.3. The range has to serve both ends of the travel at once:

    0.6 mm      21 px at 48 mm      4.1 px at 240 mm
    1.6 mm      56 px at 48 mm       11 px at 240 mm

Squares rather than discs: one PDF operator each instead of five Bezier
segments, and axis-aligned edges suit a left/right split phase sensor.

Measured on the rendered page: 34 % ink, uniform to half a per cent across
fifths of the sheet in both axes, and the outermost pixels match the middle --
squares are drawn from starting corners slightly off the page so that the edges
are not thinned by clipping.

**No label.** Any text is a contrast-free band, and with the printer choosing
the margins there is no corner that is reliably out of the way. The filename
carries the identity instead.

    python3 targets/make_af_target_full.py
"""

import random

MM = 72.0 / 25.4
PAGE_W_MM, PAGE_H_MM = 297.0, 210.0     # A4 landscape
SIZE_MM = (0.6, 1.6)
COVER = 0.42
SEED = 20260911


def field():
    rnd = random.Random(SEED)
    ops = ["0 0 0 rg"]
    area = PAGE_W_MM * PAGE_H_MM
    covered = n = 0
    # Squares may start just off the page as well as on it. Drawing them only
    # from corners inside the page thins the ink along the right and bottom
    # edges, because those are the ones that hang over and get clipped -- and
    # the printer then clips the same edges again. Starting from -w makes the
    # coverage uniform right out to the paper.
    while covered < COVER * area and n < 200000:
        w = rnd.uniform(*SIZE_MM)
        x = -w + rnd.random() * (PAGE_W_MM + w)
        y = -w + rnd.random() * (PAGE_H_MM + w)
        ops.append(f"{x*MM:.2f} {(PAGE_H_MM-y-w)*MM:.2f} "
                   f"{w*MM:.2f} {w*MM:.2f} re f")
        covered += w * w
        n += 1
    # covered sums the squares' areas, so overlaps are counted twice. Measured
    # on the rendered page the ink comes to about 34 % for a nominal 42, and it
    # is uniform to within half a per cent across fifths of the page in both
    # axes, edges included.
    print(f"  {n} kvadrater, {100*covered/area:.0f} % nominellt "
          f"(~{100*covered/area*0.81:.0f} % black efter overlapp)")
    return "\n".join(ops).encode("latin-1")


def main(path="targets/af-target-full-A4.pdf"):
    stream = field()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
         f"{PAGE_W_MM*MM:.2f} {PAGE_H_MM*MM:.2f}] /Resources << >> "
         f"/Contents 4 0 R >>").encode(),
        b"<< /Length " + str(len(stream)).encode()
        + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    open(path, "wb").write(out)
    print(f"{path}: {len(out)//1024} kB")
    print("Skriv ut i 100 % / 'faktisk storlek', INTE 'anpassa till sida' --")
    print("skalning andrar prickstorleken och darmed vad AF har att arbeta med.")


if __name__ == "__main__":
    main()
