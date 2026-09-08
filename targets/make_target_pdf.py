#!/usr/bin/env python3
"""Write the focus targets as a PDF, in points, at exact scale.

Two pages. Page 1 is the original strip of gratings with a decade scale, for
focus sweeps and for measuring the image scale. Page 2 is for recalibration,
where focus and triangulation have to be measured against the *same* sheet:
focus needs contrast, the laser centroid needs a uniform surface, and a grating
under the dot was measured to shift it 1.08 px. So page 2 is a grating field
with a blank disc in the middle for the dot to land in. The sweep runs with the
laser off, so the blank disc contributes no gradient either way -- it lowers the
sharpness metric slightly and does not move its peak.

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

# Page 2. The disc has to hold the dot at every working distance. The beam is
# near enough parallel to the axis that the dot sits about 10.5 mm to one side
# whatever the distance -- that is what triangulation trades on -- so 22 mm of
# radius leaves better than 10 mm of margin for mounting error on either side,
# and does not care which side the laser ends up on.
FIELD_W, FIELD_H, FIELD_PERIOD = 200.0, 150.0, 1.0
DISC_R = 22.0

# Page 3. A grating is the wrong tool for tracking motion: vertical bars carry
# no vertical information, and a periodic pattern gives a correlation peak every
# period -- 1 mm is 20 px at this working distance, and the drift being chased is
# already 24 px, so a displacement can be read a whole period wrong and look
# perfectly healthy. A random pattern has broad spatial frequency content, no
# repeat to be confused by, and works equally in both axes. This is the speckle
# used in digital image correlation, for the same reason.
SPECKLE_W, SPECKLE_H = 240.0, 170.0
SPECKLE_R = (0.30, 0.60)      # dot radii, mm -> 12-24 px at 20 px/mm
SPECKLE_COVER = 0.42
SPECKLE_DISC_R = 30.0         # blank landing zone, larger than page 2's: the dot
                              # sits 16 mm off axis and is currently moving


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

    page1 = "\n".join(ops).encode("latin-1")

    # --- page 2: grating field with a blank landing disc ------------------
    ops = ["0 0 0 rg"]
    fx, fy = (PAGE_W_MM - FIELD_W) / 2.0, 26.0
    cx, cy = fx + FIELD_W / 2.0, fy + FIELD_H / 2.0
    n = int(FIELD_W / FIELD_PERIOD)
    for i in range(n):
        x = fx + i * FIELD_PERIOD
        w = FIELD_PERIOD / 2.0
        # A bar that misses the disc is one rectangle. One that crosses it is
        # two, split at the chord -- exact, and it keeps the file small enough
        # to print without a fight. Sampling the circle instead took 57000
        # operations and 2 MB.
        off = abs(x + w / 2.0 - cx)
        if off >= DISC_R:
            rect(x, fy, w, FIELD_H)
            continue
        half = (DISC_R ** 2 - off ** 2) ** 0.5
        rect(x, fy, w, (cy - half) - fy)
        rect(x, cy + half, w, (fy + FIELD_H) - (cy + half))
    for dx_, dy_ in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        rect(cx + dx_ * (DISC_R + 3.0) - 0.4, cy + dy_ * (DISC_R + 3.0) - 0.4, 0.8, 0.8)
    text(cx, fy - 6.0,
         f"Recalibration target - land the laser dot inside the {2*DISC_R:.0f} mm "
         f"blank disc. Print at 100 %, no fit to page.", 9.0)
    page2 = "\n".join(ops).encode("latin-1")

    # --- page 3: random speckle with a blank landing disc -----------------
    import random
    rnd = random.Random(20260908)
    ops = ["0 0 0 rg"]
    sx, sy = (PAGE_W_MM - SPECKLE_W) / 2.0, 22.0
    cx, cy = sx + SPECKLE_W / 2.0, sy + SPECKLE_H / 2.0
    area = SPECKLE_W * SPECKLE_H
    placed = covered = 0
    while covered < SPECKLE_COVER * area and placed < 60000:
        x = sx + rnd.random() * SPECKLE_W
        y = sy + rnd.random() * SPECKLE_H
        r = rnd.uniform(*SPECKLE_R)
        placed += 1
        if (x - cx) ** 2 + (y - cy) ** 2 < (SPECKLE_DISC_R + r) ** 2:
            continue          # keep the landing zone clean
        # A circle as four Bezier arcs; k is the standard 4/3*(sqrt(2)-1).
        k = r * 0.5523
        X, Y = x * MM, (PAGE_H_MM - y) * MM
        R, K = r * MM, k * MM
        ops.append(f"{X - R:.3f} {Y:.3f} m")
        ops.append(f"{X - R:.3f} {Y + K:.3f} {X - K:.3f} {Y + R:.3f} {X:.3f} {Y + R:.3f} c")
        ops.append(f"{X + K:.3f} {Y + R:.3f} {X + R:.3f} {Y + K:.3f} {X + R:.3f} {Y:.3f} c")
        ops.append(f"{X + R:.3f} {Y - K:.3f} {X + K:.3f} {Y - R:.3f} {X:.3f} {Y - R:.3f} c")
        ops.append(f"{X - K:.3f} {Y - R:.3f} {X - R:.3f} {Y - K:.3f} {X - R:.3f} {Y:.3f} c f")
        covered += 3.14159 * r * r
    for dx_, dy_ in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        rect(cx + dx_ * (SPECKLE_DISC_R + 4.0) - 0.5,
             cy + dy_ * (SPECKLE_DISC_R + 4.0) - 0.5, 1.0, 1.0)
    text(cx, sy - 6.0,
         f"Drift target - random speckle for image correlation. Land the laser "
         f"dot inside the {2*SPECKLE_DISC_R:.0f} mm blank disc. Print at 100 %.", 9.0)
    page3 = "\n".join(ops).encode("latin-1")
    print(f"  sida 3: {placed} forsok, {covered/area*100:.0f} % tackning")

    def page(contents_obj):
        return (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                f"{PAGE_W_MM*MM:.2f} {PAGE_H_MM*MM:.2f}] /Resources << /Font "
                f"<< /F1 9 0 R >> >> /Contents {contents_obj} 0 R >>").encode()

    def content(stream):
        return (b"<< /Length " + str(len(stream)).encode()
                + b" >>\nstream\n" + stream + b"\nendstream")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>",
        page(4), content(page1),
        page(6), content(page2),
        page(8), content(page3),
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
