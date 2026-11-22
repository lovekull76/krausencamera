#!/bin/bash
# Copy the local archive to the NAS, then prune what is safely there.
#
# Run by krausencamera-arkiv.timer every ten minutes. The service only ever
# writes locally -- it must never wait on the network, and a NAS that hangs
# would otherwise stall a measurement -- so this is the one place the NAS is
# touched. A run that finds the NAS away does nothing, and the next one
# catches up.
#
#   ~/arkiv/<batch>/...        ->  NAS/<host>/<batch>/...
#   ~/krausencamera/matningar/ ->  NAS/<host>/matningar/   (daily service logs)
#
# Local files older than KEEP_DAYS are deleted, but only when the NAS holds a
# copy of the same size. Nothing is deleted on the NAS, ever.
set -u
NAS=/mnt/krausen_cam
DEST="$NAS/$(hostname)"
SRC=/home/pi/arkiv
LOGS=/home/pi/krausencamera/matningar
KEEP_DAYS=14

# Touching the automount mounts it; a NAS that is down fails here within the
# mount timeout instead of hanging rsync.
if ! timeout 45 ls "$NAS" >/dev/null 2>&1; then
  echo "NAS inte tillganglig -- forsoker igen nasta gang"
  exit 0
fi
mkdir -p "$DEST" || exit 1

# CIFS has no Unix owners or modes, so copy content and times only. --partial
# lets an interrupted large file (a video) resume rather than restart.
#
# --size-only, because the times do not stick. rsync sets a file's mtime and
# the NAS then overwrites it when the file is closed, so every run saw every
# file as changed and re-sent the whole archive -- 716 MB, four minutes of
# saturated WiFi out of every ten. A camera hang (2026-10-01 12:05) landed in
# one of those. Frames and recordings never change once written and the logs
# only grow, so size is enough to tell what is new.
# --bwlimit: the first run after forhandsbilder.py arrived had ~500 MB of
# copies to send, and a whole-archive resend over WiFi coincided with a camera
# hang once (2026-10-01). 1.5 MB/s still sends a normal ten minutes in seconds.
opts=(-rt --size-only --no-perms --no-owner --no-group --partial --timeout=60 --bwlimit=1500)

# Only what is new since the last run. Walking the whole archive -- the local
# frames, the NAS copy, every batch's page check and the start page -- every
# ten minutes kept ~15k CIFS and ~10k ext4 inodes in the kernel's caches: 70 MB
# of slab on a Pi with ~170 MB outside CMA. On 2026-10-24 that ended in an OOM
# kill, the camera service was swapped out to 2.4 MB resident, and frontend
# timeouts went from none in twelve days to one every five hours, starting the
# day the half-size copies doubled the file count. A frame that cannot be
# dequeued within a second because its thread is waiting on swap is exactly a
# frontend timeout.
MARK=/home/pi/krausencamera/.arkivsynk-senast
STAMP=$(mktemp); NEW=$(mktemp); trap 'rm -f "$STAMP" "$NEW"' EXIT
since=(); [ -f "$MARK" ] && since=(-newer "$MARK")

# New files only ever appear in the open batch, or in today's utan-batch when
# none is open, so after the first run only those are searched. The first run
# (no mark) takes everything.
scope=(.)
if [ -f "$MARK" ]; then
  bid=$(python3 -c 'import json; print(json.load(open("/home/pi/krausencamera/batch.json"))["id"])' 2>/dev/null)
  scope=()
  for d in "$bid" "utan-batch/$(date +%F)"; do [ -n "$d" ] && [ -d "$SRC/$d" ] && scope+=("./$d"); done
fi
if [ -d "$SRC" ] && [ ${#scope[@]} -gt 0 ]; then
  # Half-size copies of the new frames, so they travel with them.
  (cd "$SRC" && find "${scope[@]}" -type f -path '*/bilder/A-*.jpg' "${since[@]}" -print0) \
    | (cd "$SRC" && xargs -0 -r nice -n 19 python3 /home/pi/krausencamera/forhandsbilder.py)
  (cd "$SRC" && find "${scope[@]}" -type f "${since[@]}" -print) > "$NEW"
  # The register of what the NAS holds, so the pages below never list it.
  [ -s "$NEW" ] && rsync "${opts[@]}" --files-from="$NEW" "$SRC/" "$DEST/" \
    && python3 /home/pi/krausencamera/arkivregister.py add < "$NEW"
fi
[ -d "$LOGS" ] && rsync "${opts[@]}" "$LOGS/" "$DEST/matningar/"

# Pages only for the batches that got something new -- or every one, when the
# page builder itself is newer than the last run.
if [ ! -f "$MARK" ] || [ /home/pi/krausencamera/timelapse.py -nt "$MARK" ]; then
  find "$DEST" -maxdepth 3 -type d -name bilder -printf '%h\n'
else
  sed -E 's#^\./##; /\/(bilder|sma|video)\//{s#/(bilder|sma|video)/.*##;b}; s#/[^/]*$##' "$NEW" | sort -u \
    | while read -r b; do [ -d "$DEST/$b/bilder" ] && echo "$DEST/$b"; done
fi | sort -u | while read -r d; do
  python3 /home/pi/krausencamera/timelapse.py "$d" && echo "timelapse: $d"
done

# The start page; it re-reads only batches whose page changed (arkivindex.py).
python3 /home/pi/krausencamera/arkivindex.py "$NAS" || echo "startsidan kunde inte skrivas"
mv "$STAMP" "$MARK"; STAMP=

# Prune the local copy once a day rather than every run, for the same reason.
# Today's files are still being appended to, and a file is only removed once
# the NAS has one of the same size.
PRUNED=/home/pi/krausencamera/.arkivsynk-rensat
if [ -d "$SRC" ] && [ -z "$(find "$PRUNED" -mmin -1440 2>/dev/null)" ]; then
  n=0
  while IFS= read -r -d '' f; do
    rel=${f#"$SRC"/}
    remote="$DEST/$rel"
    if [ -f "$remote" ] && [ "$(stat -c %s "$f")" = "$(stat -c %s "$remote")" ]; then
      rm -f "$f" && n=$((n + 1))
    fi
  done < <(find "$SRC" -type f -mtime +"$KEEP_DAYS" -print0)
  find "$SRC" -mindepth 1 -type d -empty -delete
  [ "$n" -gt 0 ] && echo "rensade $n lokala filer aldre an $KEEP_DAYS dagar"
  touch "$PRUNED"
fi
echo "synkat till $DEST"
