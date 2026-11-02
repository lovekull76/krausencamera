#!/bin/bash
# One line a minute of what the memory is doing, run by krausencamera-minne.service.
#
# The journal lives in RAM and goes with every reboot, so when the frontend
# timeouts came back on 2026-11-01 there was nothing to compare against: was
# the memory tighter than in the six clean days before, or not? This keeps
# the answer on the SD card, a day per file, ~100 kB a day.
#
#   ~/krausencamera/minne/minne-YYYYMMDD.csv
#
# A loop rather than a timer: a timer logs its start and stop to the journal
# every minute, and that journal has an ~8 MB cap -- it would push out the very
# hang logs this is meant to sit beside.
#
# Sizes in kB. pswpin/pswpout/pgmajfault/allocstall are counters since boot;
# the difference between two rows is what happened in that minute.
set -u
DIR=/home/pi/krausencamera/minne
COLS="tid,avail,free,cmafree,cached,anon,slab,sunreclaim,swapused,zram,pswpin,pswpout,pgmajfault,allocstall,tjanst_rss,tjanst_swap"
mkdir -p "$DIR"

m() { awk -v k="$1:" '$1 == k {print $2}' /proc/meminfo; }
v() { awk -v k="$1" '$1 == k {print $2}' /proc/vmstat; }

while :; do
  f="$DIR/minne-$(date +%Y%m%d).csv"
  [ -f "$f" ] || { echo "$COLS" > "$f"; find "$DIR" -name 'minne-*.csv' -mtime +14 -delete; }
  zram=$(awk '{print int($3 / 1024)}' /sys/block/zram0/mm_stat 2>/dev/null)
  pid=$(systemctl show -p MainPID --value krausencamera.service)
  rss=; swp=
  if [ -n "$pid" ] && [ "$pid" != 0 ]; then
    rss=$(awk '/^VmRSS:/ {print $2}' /proc/"$pid"/status 2>/dev/null)
    swp=$(awk '/^VmSwap:/ {print $2}' /proc/"$pid"/status 2>/dev/null)
  fi
  echo "$(date '+%F %T'),$(m MemAvailable),$(m MemFree),$(m CmaFree),$(m Cached),$(m AnonPages),$(m Slab),$(m SUnreclaim),$(( $(m SwapTotal) - $(m SwapFree) )),${zram},$(v pswpin),$(v pswpout),$(v pgmajfault),$(v allocstall_normal),${rss},${swp}" >> "$f"
  sleep 60
done
