#!/bin/bash
# Is the drift the lens moving, or the camera running? Two days at one height.
#
# The new module drifts ~0.12 mm/h at 123.40 mm while the camera runs, and at
# most a third of that over seven hours switched off (2026-09-23). Operating
# time and AF cycles were locked together at one visit per five minutes, so
# that result cannot say which of them it follows. This alternates four-hour
# blocks of one visit per ten minutes and one per two minutes -- five times the
# lens motion for the same time. Drift per hour that scales with the visit rate
# is the lens; drift per hour that does not is time.
#
#   ./intervalltest.sh              # kor
#   ./intervalltest.sh --dry        # bara visa schemat
#
# Same camera settings as the calibration nights, so the result applies to
# them. See autocal.py run_blocks() for why the stage moves only once.
set -u
cd ~/krausencamera

D0=27.4
REF=123.40
SESSION=af14.csv
BLOCKS=600x4,120x4
HOURS=48
DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --session) SESSION="$2"; shift 2;;
    --hours)   HOURS="$2"; shift 2;;
    --dry)     DRY=1; shift;;
    *) echo "okant argument: $1"; exit 2;;
  esac
done
ZREF=$(python3 -c "print(f'{$REF-$D0:.2f}')")

AF="python3 af_calibrate.py --session $SESSION --request GO --preview 8081 \
--interval 300 --runs 2 --auto-exposure --park-after 0.0 \
--warmup-interval 300 --warmup-min 30 --warmup-max 100"
cal() {
  echo "python3 autocal.py --d0 $D0 --session $SESSION --request GO \
--heights $ZREF --ref $ZREF --blocks $BLOCKS --hours $HOURS --t0 $1 --zmax 200"
}

echo "referens $REF mm = Z$ZREF, block $BLOCKS, $HOURS h"
if [ -n "$DRY" ]; then $(cal "$(date +%s)") --dry-run; exit $?; fi

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

if ! pgrep -f "python3 dslog\.py" >/dev/null; then
  TLOG="temps-$(date +%Y%m%d).csv"
  echo "startar temperaturloggen -> $TLOG"
  setsid nohup python3 dslog.py --out "$TLOG" --interval 30 \
    </dev/null >>dslog.log 2>&1 &
  sleep 3
  pgrep -f "python3 dslog\.py" >/dev/null \
    && echo "  igang" || echo "  ** dslog startade inte -- kolla 1-Wire **"
else
  echo "temperaturloggen kor redan"
fi

# Warm up at the height the test runs at. On 2026-09-23 the night started with
# the stage wherever the previous run had left it, 60 mm from the reference,
# and was only moved by hand five minutes into the warm-up.
echo "flyttar bordet till Z$ZREF"
python3 stage.py --hold --to "$ZREF" --feed 150 --approach 5 --zmax 200 \
  | grep -q framme || { echo "** bordet kom aldrig fram -- avbryter **"; exit 1; }

echo "startar kameran, uppvarmning 30-100 min"
setsid nohup $AF </dev/null >"${SESSION%.csv}.log" 2>&1 &
sleep 8
for i in $(seq 1 300); do
  grep -q "vantar pa GO" "${SESSION%.csv}.log" && break
  sleep 30
done
grep -q "vantar pa GO" "${SESSION%.csv}.log" || { echo "uppvarmningen blev aldrig klar"; exit 1; }

# t0 is fixed here and carried in the command afwatch restarts, so a restart
# resumes the block schedule rather than starting it over.
CAL=$(cal "$(date +%s)")
echo "$(date +%H:%M:%S) uppvarmning klar, startar blockschemat"
setsid nohup $CAL </dev/null >>"${SESSION%.csv}.out" 2>&1 &
sleep 20
# --warmup-wait 110: the aluminium plate warms up in ~70 min, and afwatch's
# default of 45 would start the schedule against a camera still warming.
setsid nohup python3 afwatch.py --session "$SESSION" --stale 25 --warmup-wait 110 \
  --af "$AF" --cal "$CAL" --af-log "${SESSION%.csv}.log" \
  --cal-log "${SESSION%.csv}.out" --log "${SESSION%.csv}.watch" \
  </dev/null >>"${SESSION%.csv}.watchout" 2>&1 &
echo "$(date +%H:%M:%S) vakthund startad"
