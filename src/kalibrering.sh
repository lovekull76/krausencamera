#!/bin/bash
# One calibration night, start to finish. Run it on the Pi.
#
# Written because the night of 2026-09-17 was assembled by hand at one in the
# morning and carried three setup errors that no amount of care catches at that
# hour: --runs 8 where nights 2 and 3 used 2, no --auto-exposure so the near
# heights saturated and `niva` logged nan, and --heights given as distances
# when autocal wants stage Z. The last would have produced a complete,
# internally consistent table of entirely the wrong heights.
#
# So: heights are written here as DISTANCES FROM THE LID, which is how we think
# about them, and the script converts to stage Z. Nothing is retyped.
#
#   ./kalibrering.sh --d0 27.4 --session af9.csv          # kor
#   ./kalibrering.sh --d0 27.4 --session af9.csv --dry    # bara visa schemat
#
# ⚠️ --d0 must be re-measured after any change to the housing: it is the
# distance from the lid's underside to the target at stage zero.
set -u
cd ~/krausencamera

D0=27.4
SESSION=af9.csv
DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --d0)      D0="$2"; shift 2;;
    --session) SESSION="$2"; shift 2;;
    --dry)     DRY="--dry-run"; shift;;
    *) echo "okant argument: $1"; exit 2;;
  esac
done

# The ten heights of the 2026-09-14 table, so the new one is directly
# comparable. 41.40 is back in: the 5 mm raise puts the rail near 36.7 mm.
# 41.40 dropped 2026-09-19: the rail sits at 43.5 mm with this housing, so it
# fails 0/2 every visit and wastes one visit in ten. Put it back only after a
# rebuild that measurably moves the rail inside it.
AVSTAND="46.40 52.40 60.40 70.40 82.40 99.40 123.40 158.40 218.40"
REF=123.40

Z=$(python3 -c "
d0=$D0
print(' '.join(f'{float(a)-d0:.2f}' for a in '$AVSTAND'.split()))")
ZREF=$(python3 -c "print(f'{$REF-$D0:.2f}')")

# --runs 2 and --auto-exposure: exactly what nights 2 and 3 used. Do not raise
# runs -- it quadruples the AF duty cycle, warms the camera through the night,
# and breaks parity with the warm-up, which runs four cycles.
AF="python3 af_calibrate.py --session $SESSION --request GO --preview 8081 \
--interval 300 --runs 2 --auto-exposure --park-after 0.0 \
--warmup-interval 300 --warmup-min 30 --warmup-max 75"
CAL="python3 autocal.py --d0 $D0 --session $SESSION --request GO \
--interval 300 --visits 200 --zmax 200 --ref $ZREF --ref-every 3 --heights $Z"

echo "d0 = $D0 mm"
echo "avstand: $AVSTAND"
echo "stage Z: $Z   (referens Z$ZREF)"
echo
if [ -n "$DRY" ]; then $CAL --dry-run; exit $?; fi

# The service owns the camera, and a session started against it fails in a way
# that looks like a camera fault. Same for a session left over from an earlier
# attempt. Clear both before anything else -- by PID, never by pkill pattern,
# which has killed its own shell four times in this project.
if systemctl is-active --quiet krausencamera; then
  echo "stoppar tjansten (den haller kameran)"
  sudo systemctl stop krausencamera || { echo "kunde inte stoppa tjansten"; exit 1; }
  sleep 2
fi
for pid in $(pgrep -f "af_calibrate\.py --session" || true); do
  [ "$pid" = "$$" ] && continue
  echo "stoppar tidigare session, PID $pid"; kill "$pid" 2>/dev/null
done
for pid in $(pgrep -f "autocal\.py --d0" || true); do
  [ "$pid" = "$$" ] && continue
  kill "$pid" 2>/dev/null
done
sleep 6
if pgrep -f "af_calibrate\.py --session" | grep -qv "^$$\$"; then
  echo "** en session lever an -- avbryter hellre an kor tva mot samma kamera **"
  exit 1
fi

echo "startar kameran, uppvarmning 30-75 min"
setsid nohup $AF </dev/null >"${SESSION%.csv}.log" 2>&1 &
sleep 8
for i in $(seq 1 300); do
  grep -q "vantar pa GO" "${SESSION%.csv}.log" && break
  sleep 30
done
grep -q "vantar pa GO" "${SESSION%.csv}.log" || { echo "uppvarmningen blev aldrig klar"; exit 1; }
echo "$(date +%H:%M:%S) uppvarmning klar, startar autocal"
setsid nohup $CAL </dev/null >>"${SESSION%.csv}.out" 2>&1 &
sleep 20
setsid nohup python3 afwatch.py --session "$SESSION" --stale 25 \
  --af "$AF" --cal "$CAL" --af-log "${SESSION%.csv}.log" \
  --cal-log "${SESSION%.csv}.out" --log "${SESSION%.csv}.watch" \
  </dev/null >>"${SESSION%.csv}.watchout" 2>&1 &
echo "$(date +%H:%M:%S) vakthund startad"
