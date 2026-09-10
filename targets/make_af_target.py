#!/usr/bin/env python3
"""Two AF calibration targets: the same speckle at two contrasts.

Page 3 of the focus target has a blank landing disc in the middle for the laser
dot. Phase detection meters the middle of the frame, so that disc sits exactly
where it looks -- it converges, but probably on the disc's edge rather than on
texture, which is fragile. With focus as the primary sensor there is no dot to
land, so these fill the field.

**Both pages share a random seed.** The geometry is identical and contrast is
the only variable. Foam has far less contrast than black on white, and phase
detection loses precision as contrast falls; measuring the two against a known
distance says how much, before ever meeting foam.

Squares rather than discs: one PDF operator each instead of five Bezier
segments, which is the difference between a file that prints and one that does
not. Their edges are axis-aligned, which suits a left/right split phase sensor.
"""

import random

MM = 72.0 / 25.4
PAGE_W_MM, PAGE_H_MM = 297.0, 210.0
FIELD_W, FIELD_H = 250.0, 175.0
SIZE_MM = (0.6, 1.3)          # 12-26 px at ~20 px/mm
COVER = 0.42
GREY = 0.38                   # second page: 62 % of full contrast
SEED = 20260910


def field(grey: float):
    rnd = random.Random(SEED)
    x0, y0 = (PAGE_W_MM - FIELD_W) / 2.0, 24.0
    ops = [f"{grey:.2f} {grey:.2f} {grey:.2f} rg"]
    area = FIELD_W * FIELD_H
    covered = n = 0
    while covered < COVER * area and n < 120000:
        w = rnd.uniform(*SIZE_MM)
        x = x0 + rnd.random() * (FIELD_W - w)
        y = y0 + rnd.random() * (FIELD_H - w)
        ops.append(f"{x*MM:.2f} {(PAGE_H_MM-y-w)*MM:.2f} {w*MM:.2f} {w*MM:.2f} re f")
        covered += w * w
        n += 1
    ops.append("0 0 0 rg")
    label = ("Autofocus target - full field, full contrast."
             if grey == 0 else
             f"Autofocus target - SAME pattern at {100*(1-grey):.0f} % contrast.")
    ops.append(f"BT /F1 9.0 Tf {(x0+FIELD_W/2)*MM - 115:.1f} "
               f"{(PAGE_H_MM-(y0-6))*MM:.1f} Td ({label} Print at 100 %.) Tj ET")
    print(f"  grey={grey:.2f}: {n} kvadrater, {100*covered/area:.0f} % tackning")
    return "\n".join(ops).encode("latin-1")


def main(path="targets/af-target-A4.pdf"):
    pages = [field(0.0), field(GREY)]
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    ]
    for i, stream in enumerate(pages):
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                     f"{PAGE_W_MM*MM:.2f} {PAGE_H_MM*MM:.2f}] /Resources << /Font "
                     f"<< /F1 7 0 R >> >> /Contents {4+2*i} 0 R >>").encode())
        objs.append(b"<< /Length " + str(len(stream)).encode()
                    + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

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


if __name__ == "__main__":
    main()
