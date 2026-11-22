#!/usr/bin/env python3
"""A local register of the files each batch has on the NAS, so its pages can
be built without listing the NAS.

    python3 arkivregister.py add < new-files    # paths relative to ~/arkiv

`arkivsynk.sh` feeds it the files it has just sent. timelapse.py and
arkivindex.py ask it for a batch's frames, copies and recordings, and read the
CSVs from the Pi's own copy, which is appended locally and only ever copied up.
A folder with no register -- another camera's, or any folder on a Mac -- is
listed as before.

Why: with the batch of 2026-10-24 a month old, every sync listed 8428 frames
and as many copies over CIFS, twice, and read and wrote 1.5 MB, to rebuild one
page. Five frontend timeouts in five days (2026-11-17 to 22), and all five
came within seconds of a sync starting -- a 13 s window in 600.

One file per batch under ~/krausencamera/register/, one `sub/name` per line;
outside ~/arkiv so it is neither synced nor pruned. A batch's register is
seeded from one listing of the NAS the first time it gets something new.
"""

from __future__ import annotations

import os
import socket
import sys

# The same paths as arkivsynk.sh.
DEST = "/mnt/krausen_cam/" + socket.gethostname()
LOCAL = "/home/pi/arkiv"
REGDIR = "/home/pi/krausencamera/register"
SUBS = ("bilder", "sma", "video")


def _rel(folder: str) -> str | None:
    folder = os.path.normpath(folder)
    if not folder.startswith(DEST + "/"):
        return None
    return os.path.relpath(folder, DEST)


def _file(rel: str) -> str:
    return os.path.join(REGDIR, rel + ".txt")


def names(folder: str, sub: str) -> list[str]:
    """The names in folder/sub, sorted: from the register when it has the
    folder, otherwise by listing it."""
    rel = _rel(folder)
    if rel and os.path.exists(_file(rel)):
        with open(_file(rel)) as f:
            return sorted({line[len(sub) + 1:].rstrip("\n") for line in f
                           if line.startswith(sub + "/")})
    try:
        return sorted(os.listdir(os.path.join(folder, sub)))
    except OSError:
        return []


def local_copy(folder: str, name: str) -> str:
    """folder/name on the Pi when it still has it, else on the NAS. The local
    CSV is never behind the NAS one: it is appended here and copied up."""
    rel = _rel(folder)
    if rel:
        p = os.path.join(LOCAL, rel, name)
        if os.path.exists(p):
            return p
    return os.path.join(folder, name)


def add(lines) -> None:
    new: dict[str, list[str]] = {}
    for line in lines:
        parts = line.strip().removeprefix("./").split("/")
        # <batch>/<sub>/<name> or utan-batch/<day>/<sub>/<name>
        if len(parts) >= 3 and parts[-2] in SUBS:
            new.setdefault("/".join(parts[:-2]), []).append("/".join(parts[-2:]))
    for rel, files in new.items():
        path = _file(rel)
        if os.path.exists(path):
            with open(path, "a") as f:
                f.writelines(p + "\n" for p in files)
            continue
        # First time: one listing of what the NAS holds, which already includes
        # what was just sent.
        os.makedirs(os.path.dirname(path), exist_ok=True)
        seed = []
        for sub in SUBS:
            try:
                seed += [f"{sub}/{n}" for n in sorted(os.listdir(os.path.join(DEST, rel, sub)))]
            except OSError:
                pass
        seed = seed or files
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(p + "\n" for p in seed)
        os.replace(tmp, path)


def main() -> int:
    if sys.argv[1:] != ["add"]:
        print(__doc__)
        return 2
    add(sys.stdin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
