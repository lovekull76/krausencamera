#!/bin/bash
# Find where the lens rails, then start the night with the heights that work.
#
# Runs against an already warm af_calibrate session waiting on its request
# file, so nothing is restarted and no thermal state is lost. Adaptive: starts
# at the nearest height in the schedule and walks outward only as far as it
# has to.
set -u
cd ~/krausencamera
SESSION=af12.csv
REQ=GO
D0=27.4

wait_warm() {
  for i in $(seq 1 240); do
    grep -q "vantar pa GO" af12.log && return 0
    sleep 30
  done
  return 1
}

point() {                       # point <distance mm>  ->  echoes dpt or RAIL
  local d="$1" z n0 n1
  z=$(python3 -c "print(f'{$d-$D0:.2f}')")
  python3 stage.py --to "$z" --feed 400 --hold >/dev/null 2>&1 || { echo ERR; return; }
  sleep 20
  n0=$(grep -c "^20" "$SESSION" 2>/dev/null || echo 0)
  echo "$d" > "$REQ"
  for i in $(seq 1 60); do
    sleep 5
    n1=$(grep -c "^20" "$SESSION" 2>/dev/null || echo 0)
    [ "$n1" -gt "$n0" ] && break
  done
  tail -1 "$SESSION" | awk -F, '{print ($4=="" ? "RAIL" : $4)}'
}

echo "$(date +%H:%M:%S) vantar pa uppvarmningen" | tee -a railjakt.log
wait_warm || { echo "uppvarmningen blev aldrig klar" | tee -a railjakt.log; exit 1; }
echo "$(date +%H:%M:%S) uppvarmning klar, borjar railjakt" | tee -a railjakt.log

# Search both ways. The first version only walked outward, which is fine when
# the rail has moved out -- but on 2026-09-22 a rebuild moved it *in*, and a
# hunt that stops at the first height that works would have reported 46.40 and
# left real range on the table. Probe 46.40, then walk whichever way the answer
# points.
OK=""
r=$(point 46.40)
echo "$(date +%H:%M:%S)  46.40 mm -> $r" | tee -a railjakt.log
if [ "$r" = "RAIL" ] || [ "$r" = "ERR" ]; then
  for d in 52.40 60.40 70.40 82.40 99.40; do
    r=$(point "$d")
    echo "$(date +%H:%M:%S)  $d mm -> $r  (utat)" | tee -a railjakt.log
    if [ "$r" != "RAIL" ] && [ "$r" != "ERR" ]; then OK="$d"; break; fi
  done
else
  OK=46.40
  for d in 41.40 38.40 35.40 32.40; do
    r=$(point "$d")
    echo "$(date +%H:%M:%S)  $d mm -> $r  (inat)" | tee -a railjakt.log
    if [ "$r" = "RAIL" ] || [ "$r" = "ERR" ]; then break; fi
    OK="$d"
  done
fi

if [ -z "$OK" ]; then
  echo "railar anda till 99.40 mm -- nagot ar fel som inte ar en toleransfraga." | tee -a railjakt.log
  echo "startar INGEN natt. Hojderna 123.40 och utat kan fortfarande matas." | tee -a railjakt.log
  exit 2
fi

# build the height list from the first height that converged and outward
HEIGHTS=""
for d in 32.40 35.40 38.40 41.40 46.40 52.40 60.40 70.40 82.40 99.40 123.40 158.40 218.40; do
  if [ "$(python3 -c "print(1 if $d >= $OK else 0)")" = "1" ]; then
    HEIGHTS="$HEIGHTS $(python3 -c "print(f'{$d-$D0:.2f}')")"
  fi
done
echo "$(date +%H:%M:%S) narmaste anvandbara hojd: $OK mm" | tee -a railjakt.log
echo "  Z-hojder:$HEIGHTS" | tee -a railjakt.log

CAL="python3 autocal.py --d0 $D0 --session $SESSION --request $REQ --interval 300 \
--visits 200 --zmax 200 --ref 96.00 --ref-every 3 --heights$HEIGHTS"
setsid nohup $CAL </dev/null >>af12.out 2>&1 &
sleep 20
echo "$(date +%H:%M:%S) autocal startad" | tee -a railjakt.log

# The watchdog is not optional and was left out here on 2026-09-22: this script
# started autocal directly and skipped it, so the run went nine hours with
# nothing to restart a stalled camera. Anything that has to survive the night
# belongs on the Pi, not in a watch on the laptop -- the laptop sleeps.
AF="python3 af_calibrate.py --session $SESSION --request $REQ --preview 8081 \
--interval 300 --runs 2 --auto-exposure --park-after 0.0 \
--warmup-interval 300 --warmup-min 30 --warmup-max 100"
setsid nohup python3 afwatch.py --session "$SESSION" --stale 25 \
  --af "$AF" --cal "$CAL" --af-log af12.log --cal-log af12.out \
  --log "${SESSION%.csv}.watch" </dev/null >>"${SESSION%.csv}.watchout" 2>&1 &
sleep 8
pgrep -f "python3 afwatch\.py" >/dev/null \
  && echo "$(date +%H:%M:%S) vakthund startad" | tee -a railjakt.log \
  || echo "$(date +%H:%M:%S) ** vakthunden startade inte **" | tee -a railjakt.log
