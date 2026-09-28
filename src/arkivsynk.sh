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
opts=(-rt --no-perms --no-owner --no-group --partial --timeout=60)
[ -d "$SRC" ] && rsync "${opts[@]}" "$SRC/" "$DEST/"
[ -d "$LOGS" ] && rsync "${opts[@]}" "$LOGS/" "$DEST/matningar/"

# A timelapse page in every folder on the NAS that has frames newer than its
# page. Built against the NAS copy, so it lists frames already pruned here.
while IFS= read -r -d '' bilder; do
  d=$(dirname "$bilder")
  page="$d/timelapse.html"
  if [ ! -f "$page" ] || [ -n "$(find "$bilder" -newer "$page" -name 'A-*.jpg' -print -quit)" ] \
     || [ "$d/matningar.csv" -nt "$page" ]; then
    python3 /home/pi/krausencamera/timelapse.py "$d" && echo "timelapse: $d"
  fi
done < <(find "$DEST" -maxdepth 3 -type d -name bilder -print0)

# Prune the local copy. Today's files are still being appended to, and a file
# is only removed once the NAS has one of the same size.
if [ -d "$SRC" ]; then
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
fi
echo "synkat till $DEST"
