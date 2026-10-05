#!/bin/bash
# Pi heat without the lens: 10 min quiet, 20 min with two cores busy, 20 min
# to recover. No viewer, so the lens stays parked between measurements -- the
# load test held it in focus for a viewer, and that mixed the VCM holding
# current in with the Pi heat. Plate and lid come from dslog.
cd ~/krausencamera
OUT=soclast.csv
echo "tid,fas,soc_C,throttled,load1" > $OUT
log() { echo "$(date +%H:%M:%S),$1,$(vcgencmd measure_temp | tr -dc 0-9.),$(vcgencmd get_throttled | cut -d= -f2),$(cut -d" " -f1 /proc/loadavg)" >> $OUT; }
t0=$(date +%s); pids=""
while [ $(( $(date +%s) - t0 )) -lt 3000 ]; do
  e=$(( $(date +%s) - t0 ))
  if [ $e -ge 600 ] && [ $e -lt 1800 ] && [ -z "$pids" ]; then
    for i in 1 2; do nice -n 10 sh -c "while :; do :; done" & pids="$pids $!"; done
  fi
  if [ $e -ge 1800 ] && [ -n "$pids" ]; then kill $pids; pids=""; fi
  f=fore; [ $e -ge 600 ] && f=last; [ $e -ge 1800 ] && f=efter
  log $f; sleep 10
done
[ -n "$pids" ] && kill $pids
echo klart >> $OUT
