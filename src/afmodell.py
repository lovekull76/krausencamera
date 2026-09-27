#!/usr/bin/env python3
"""Fit the focus model from calibration nights, over the working range only.

    python3 afmodell.py calib/af-natt3-30fps-20260927.csv \\
        --out calib/af-model-20260928.csv --note "ny modul, 30 fps"

Until now every model file was produced by analysis code written in a
conversation and thrown away. This is that code, kept, so a table can be
re-fitted from its raw nights and the choices below are written down.

**Fit the working range, tabulate the rest.** The hyperbola cannot carry the
far end on the new module: across three nights 218 mm sits +3.7 to +7.8 mm off
it, and fitting through that pulls the curve so the reference height at 123.40
misses by -0.4 to -0.8 mm. That is exactly where a 75 L fill puts the liquid
surface, 117-125 mm below the lid, and the zero taken at fill is a constant
error in every krausen height that follows. So the fit uses heights up to
`--fit-max` (130 mm), and heights beyond it get their residual reported as a
correction instead.

**One shape, one zero per night.** The camera's zero drifts between nights --
settling, then the lid's temperature -- while b and c stay put to a fraction
of a percent. So several nights share b and c and each gets its own offset.
Krausen height is a difference from a zero taken at fill, so the absolute
offset matters least of the three.

**Drift inside a night** is removed with a straight line through the reference
height, the height revisited every third visit. Temperature is not used yet:
the lid sensor that will carry it goes into the aluminium plate in the next
housing.

**`--skip-after 218.40`** drops the visit following that height. Nights run
with exposures above ~32 ms slowed the frame there and the sensor cooled, and
the next reading came out 24 mdpt low (2026-09-23). Not needed from night 3 on.

The `tillampa_korrektion` column defaults to `nej` everywhere. Whether a
correction reproduces between nights is a judgement on data, not something a
fit can decide -- on the old module it did inside 125 mm, on the new one it did
not (r = +0.67). `--apply-within MM` sets it to `ja` up to that distance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import numpy as np


def load(path, skip_after=None):
    """Rows with a measurement, as (t, d, dpt). Failed and drift-flagged rows,
    and the visit after `skip_after`, are dropped."""
    out, prev = [], None
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        f = line.strip().split(",")
        d = f[2]
        skip = skip_after is not None and prev == skip_after
        prev = d
        if skip or not d or not f[3] or f[3] == "nan" or f[10] == "1":
            continue
        out.append((dt.datetime.fromisoformat(f[0]).timestamp(), float(d), float(f[3])))
    return np.array(out)


def detrend(rows, ref):
    """Remove a straight line in time fitted through the reference height."""
    t, d, p = rows.T
    h = (t - t.mean()) / 3600.0
    m = np.isclose(d, ref)
    if m.sum() < 4:
        raise SystemExit(f"for fa besok pa referenshojden {ref} for att skatta driften")
    slope = np.polyfit(h[m], p[m], 1)[0]
    return p - slope * h, slope


def fit(sessions, fit_max):
    """dpt = a_s + b/(d + c): scan c, solve the offsets and b linearly."""
    d = np.concatenate([s["d"] for s in sessions])
    p = np.concatenate([s["p"] for s in sessions])
    sid = np.concatenate([np.full(len(s["d"]), i) for i, s in enumerate(sessions)])
    m = d <= fit_max
    best = None
    # numpy on Apple's Accelerate warns spuriously inside matmul here; the
    # results are finite and checked by the residuals printed below.
    np.seterr(divide="ignore", over="ignore", invalid="ignore")
    for c in np.arange(0.0, 60.0, 0.005):
        A = np.column_stack([(sid[m] == i).astype(float) for i in range(len(sessions))]
                            + [1.0 / (d[m] + c)])
        coef, *_ = np.linalg.lstsq(A, p[m], rcond=None)
        r = float(((A @ coef - p[m]) ** 2).sum())
        if best is None or r < best[0]:
            best = (r, c, coef)
    _, c, coef = best
    return list(coef[:-1]), float(coef[-1]), float(c)


def to_mm(p, a, b, c):
    return b / (p - a) - c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", help="session CSVs from af_calibrate")
    ap.add_argument("--ref", type=float, default=123.40)
    ap.add_argument("--fit-max", type=float, default=130.0,
                    help="heights up to this are fitted; beyond it, tabulated")
    ap.add_argument("--skip-after", default=None, metavar="D",
                    help="drop the visit following this height, as written in the CSV")
    ap.add_argument("--apply-within", type=float, default=None, metavar="MM",
                    help="mark the correction to be applied up to this distance")
    ap.add_argument("--out", help="model CSV to write")
    ap.add_argument("--note", default="", help="one line describing the build")
    args = ap.parse_args()

    sessions = []
    for path in args.sessions:
        rows = load(path, args.skip_after)
        pc, slope = detrend(rows, args.ref)
        sessions.append({"path": path, "t": rows[:, 0], "d": rows[:, 1], "p": pc,
                         "slope": slope})
    offs, b, c = fit(sessions, args.fit_max)

    # per-height means in mm, each night through its own offset
    heights = sorted({round(float(x), 2) for s in sessions for x in s["d"]})
    table = []
    for h in heights:
        mm, dp = [], []
        for s, a in zip(sessions, offs):
            k = np.isclose(s["d"], h)
            mm.extend(to_mm(s["p"][k], a, b, c) - h)
            dp.extend(s["p"][k] - a + offs[-1])     # referred to the last night's zero
        mm = np.array(mm)
        n = len(mm)
        se = float(mm.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
        table.append((h, float(np.mean(dp)), se, float(mm.mean()), n))

    # leave-one-height-out inside the fit range: refit without it, predict it
    loo = []
    for h, *_ in table:
        if h > args.fit_max:
            continue
        sub = [{**s, "d": s["d"][~np.isclose(s["d"], h)], "p": s["p"][~np.isclose(s["d"], h)]}
               for s in sessions]
        o2, b2, c2 = fit(sub, args.fit_max)
        err = []
        for s, a in zip(sessions, o2):
            k = np.isclose(s["d"], h)
            err.extend(to_mm(s["p"][k], a, b2, c2) - h)
        loo.append(float(np.mean(err)))
    inside = [r for r in table if r[0] <= args.fit_max]
    rms = float(np.sqrt(np.mean([r[3] ** 2 for r in inside])))
    loo_rms = float(np.sqrt(np.mean(np.square(loo))))
    a = offs[-1]
    rail = b / (15.0 - a) - c

    lines = [
        f"# Krausencamera, AF-kalibrering {dt.date.today().isoformat()}",
        *( [f"# {args.note}"] if args.note else [] ),
        f"# natter: " + ", ".join(s["path"].split("/")[-1] for s in sessions),
        f"# modell:  dpt = {a:.4f} + {b:.2f}/(d + {c:.4f})",
        f"#   anpassad till hojder <= {args.fit_max:g} mm, en nollpunkt per natt",
        f"#   (" + ", ".join(f"{o:.4f}" for o in offs) + "), den sista ovan",
        f"#   drift inom natten borttagen via referensen {args.ref:g} mm: "
        + ", ".join(f"{s['slope']*1000:+.2f}" for s in sessions) + " mdpt/h",
        f"# inom anpassningen: rms {rms:.3f} mm, utelamna-en-hojd {loo_rms:.3f} mm",
        f"# railar vid {rail:.1f} mm (15.0 dpt)",
        "# Galler DENNA modul och DETTA bygge. Ett ingrepp i kamerastapeln",
        "# ogiltigforklarar bade modellen och tabellen.",
        "d_mm,dpt,medelfel_mm,korrektion_mm,n,tillampa_korrektion",
    ]
    for h, dp, se, res, n in table:
        apply = "ja" if args.apply_within is not None and h <= args.apply_within else "nej"
        lines.append(f"{h:.2f},{dp:.5f},{se:.3f},{-res:+.3f},{n},{apply}")
    text = "\n".join(lines) + "\n"
    print(text)
    print(f"utelamna-en-hojd, mm: " + "  ".join(
        f"{r[0]:g}:{e:+.2f}" for r, e in zip(inside, loo)))
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
