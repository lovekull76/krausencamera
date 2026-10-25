#!/usr/bin/env python3
"""Small copies of frame A for the timelapse page to play.

    python3 forhandsbilder.py ~/arkiv [more roots...] [--pause 0.2]

Frame A is archived at 2304x1296, quality 95: about 1 MB a frame. The page
played those, and over Tailscale it stalled on the first frame and then hacked
along at whatever the tunnel managed -- ten frames a second wants 10 MB/s.
Playing needs nothing like that, so every `<batch>/bilder/A-*.jpg` gets a copy
at half size in `<batch>/sma/` with the same name, ~130 kB -- sensor noise
keeps JPEG from shrinking further. The page plays those and the film export
still reads the originals.

Half size is free with JPEG: `draft()` has the decoder scale by 1/2 in the
DCT, so the full frame is never decoded. Only missing copies are made, so a
run over an archive that is up to date only lists folders.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

from PIL import Image

SUB = "sma"


def make(src: str, dst: str) -> None:
    with Image.open(src) as im:
        im.draft("RGB", (im.width // 2, im.height // 2))
        im = im.convert("RGB")
        tmp = dst + ".tmp"
        im.save(tmp, "JPEG", quality=75, optimize=True)
    os.replace(tmp, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds between copies, to go easy on a share over WiFi")
    args = ap.parse_args()
    made = 0
    for root in args.roots:
        # A frame itself, as arkivsynk.sh passes the new ones; otherwise a
        # folder to search. Walking the whole archive every ten minutes kept
        # thousands of inodes in the kernel's caches (2026-10-25).
        if os.path.isfile(root):
            pairs = [(os.path.join(os.path.dirname(os.path.dirname(root)), SUB), [root])]
        else:
            pairs = [(os.path.join(os.path.dirname(b), SUB), sorted(glob.glob(os.path.join(b, "A-*.jpg"))))
                     for b in glob.glob(os.path.join(root, "**", "bilder"), recursive=True)]
        for out, frames in pairs:
            for p in frames:
                q = os.path.join(out, os.path.basename(p))
                if os.path.exists(q):
                    continue
                os.makedirs(out, exist_ok=True)
                try:
                    make(p, q)
                    made += 1
                except Exception as e:          # a half-written frame: next run
                    print(f"{p}: {e}", file=sys.stderr)
                if args.pause:
                    time.sleep(args.pause)
    if made:
        print(f"forhandsbilder: {made} nya")
    return 0


if __name__ == "__main__":
    sys.exit(main())
