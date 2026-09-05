#!/usr/bin/env python3
"""Generate a printable focus/depth target.

A ruler has three tick scales at once, which defeats automatic detection: a
period finder latches onto 1 mm marks where they resolve and 5 or 10 mm marks
where they do not, and the two are indistinguishable in the result. This target
carries bands of a single spatial frequency each instead, so a measurement of
one band is unambiguous.

Three periods so the useful range is bracketed. Over a working distance of
82-182 mm the image scale runs about 10-22 px/mm, giving:

    2.0 mm period -> 20-44 px   comfortably resolved everywhere
    1.0 mm period -> 10-22 px   the working measurement
    0.5 mm period ->  5-11 px   near the limit, most sensitive to blur

Print on a laser printer. Carbon toner is opaque at 850 nm; dye-based inkjet
black is often nearly transparent there, which would leave the target invisible
under IR illumination.
"""

LENGTH   = 240.0   # mm of patterned length
PAGE_W   = 297.0   # A4 landscape
PAGE_H   = 210.0
X0       = (PAGE_W - LENGTH) / 2.0
BANDS    = [(2.0, 12.0), (1.0, 12.0), (0.5, 12.0)]
GAP      = 2.0
TICK_H   = 6.0
LABEL_H  = 4.0


def main() -> None:
    out = []
    add = out.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}mm" '
        f'height="{PAGE_H}mm" viewBox="0 0 {PAGE_W} {PAGE_H}">')
    add('<rect width="100%" height="100%" fill="#fff"/>')
    add('<g fill="#000" stroke="none">')

    y = 40.0
    for period, height in BANDS:
        bar = period / 2.0
        n = int(LENGTH / period)
        for i in range(n):
            add(f'<rect x="{X0 + i*period:.4f}" y="{y:.3f}" '
                f'width="{bar:.4f}" height="{height:.3f}"/>')
        add(f'</g><text x="{X0 - 4:.2f}" y="{y + height/2 + 1.5:.2f}" '
            f'font-family="Helvetica" font-size="4" text-anchor="end">'
            f'{period:g} mm</text><g fill="#000" stroke="none">')
        y += height + GAP

    # Decade marks and numbers, for mapping image position to distance.
    y += 2.0
    for mm in range(0, int(LENGTH) + 1, 10):
        tall = (mm % 50 == 0)
        h = TICK_H * (1.6 if tall else 1.0)
        w = 1.2 if tall else 0.6
        add(f'<rect x="{X0 + mm - w/2:.3f}" y="{y:.3f}" '
            f'width="{w:.3f}" height="{h:.3f}"/>')
    add('</g>')
    for mm in range(0, int(LENGTH) + 1, 10):
        add(f'<text x="{X0 + mm:.3f}" y="{y + TICK_H*1.6 + LABEL_H + 1:.3f}" '
            f'font-family="Helvetica" font-size="{LABEL_H}" '
            f'text-anchor="middle">{mm}</text>')

    # Print-scale check: measure this span with calipers before trusting anything.
    yv = y + TICK_H*1.6 + LABEL_H + 10
    add(f'<g stroke="#000" stroke-width="0.3" fill="none">')
    add(f'<line x1="{X0:.2f}" y1="{yv:.2f}" x2="{X0+200:.2f}" y2="{yv:.2f}"/>')
    for x in (X0, X0 + 200):
        add(f'<line x1="{x:.2f}" y1="{yv-2:.2f}" x2="{x:.2f}" y2="{yv+2:.2f}"/>')
    add('</g>')
    add(f'<text x="{X0+100:.2f}" y="{yv-3:.2f}" font-family="Helvetica" '
        f'font-size="4" text-anchor="middle">'
        f'200.0 mm — measure this before use; print at 100 %, no fit to page</text>')
    add('</svg>')
    print("\n".join(out))


if __name__ == "__main__":
    main()
