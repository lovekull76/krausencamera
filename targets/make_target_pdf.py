#!/usr/bin/env python3
"""Write the focus target as a PDF, in points, at exact scale.

PDF rather than SVG because browsers commonly rescale SVG when printing, and
the whole value of the target is that a printed millimetre is a millimetre. A
PDF with a correct MediaBox prints true as long as scaling is set to 100 %.

Rectangles are emitted as `x y w h re f`; the origin is bottom left, so y is
flipped from the layout coordinates used here.
"""

MM = 72.0 / 25.4
PAGE_W_MM, PAGE_H_MM = 297.0, 210.0
LENGTH = 240.0
X0 = (PAGE_W_MM - LENGTH) / 2.0
BANDS = [(2.0, 12.0), (1.0, 12.0), (0.5, 12.0)]
GAP, TICK_H, LABEL = 2.0, 6.0, 9.0


def main(path="targets/focus-target-A4.pdf"):
    ops = ["0 0 0 rg"]
    def rect(x, y, w, h):                       # layout coords, mm, y down
        ops.append(f"{x*MM:.4f} {(PAGE_H_MM-y-h)*MM:.4f} "
                   f"{w*MM:.4f} {h*MM:.4f} re f")
    def text(x, y, s, size=LABEL, centre=True):
        w = size * 0.5 * len(s) if centre else 0.0
        ops.append(f"BT /F1 {size:.1f} Tf {x*MM - w/2:.3f} "
                   f"{(PAGE_H_MM-y)*MM:.3f} Td ({s}) Tj ET")

    y = 40.0
    for period, h in BANDS:
        for i in range(int(LENGTH / period)):
            rect(X0 + i*period, y, period/2.0, h)
        text(X0 - 12.0, y + h/2 + 1.2, f"{period:g} mm")
        y += h + GAP

    y += 2.0
    for mm in range(0, int(LENGTH) + 1, 10):
        tall = (mm % 50 == 0)
        rect(X0 + mm - (0.6 if tall else 0.3), y,
             1.2 if tall else 0.6, TICK_H * (1.6 if tall else 1.0))
    ylab = y + TICK_H*1.6 + 4.5
    for mm in range(0, int(LENGTH) + 1, 10):
        text(X0 + mm, ylab, str(mm))

    yv = ylab + 12.0
    rect(X0, yv, 200.0, 0.3)
    for x in (X0, X0 + 200.0):
        rect(x - 0.15, yv - 2.0, 0.3, 4.0)
    text(X0 + 100.0, yv - 4.0,
         "200.0 mm - measure before use. Print at 100 %, no fit to page.", 9.0)

    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
         f"{PAGE_W_MM*MM:.2f} {PAGE_H_MM*MM:.2f}] /Resources << /Font "
         f"<< /F1 5 0 R >> >> /Contents 4 0 R >>").encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
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
    print(f"{path}: {len(out)//1024} kB, {len(ops)} operationer")


if __name__ == "__main__":
    main()
