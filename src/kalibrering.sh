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
# Exposures the auto choice picks from. Empty = af_calibrate's default, which
# since 2026-09-28 stops at 32 ms so every height runs at 30 fps; it used to
# reach 50 ms. Anything over ~32 ms lengthens the frame past 33.3 ms, so the
# sensor reads out less often and runs cooler: at 218 mm the 50 ms choice put it
# at 43 C against 46 everywhere else, and the reference read 24 mdpt low after
# every such visit (2026-09-23). Capping at 32000 keeps every height at 30 fps.
EXPOSURES=""
# Visits and how often the reference comes round. 200 at every third fills
# 16.7 h; a night that has to fit between the garage door at 17 and at 07
# wants fewer, and with the drift gone (2026-10-11) a reference every fourth
# visit still brackets it.
VISITS=200
REF_EVERY=3
while [ $# -gt 0 ]; do
  case "$1" in
    --d0)      D0="$2"; shift 2;;
    --session) SESSION="$2"; shift 2;;
    --dry)     DRY="--dry-run"; shift;;
    --exposures) EXPOSURES="$2"; shift 2;;
    --visits)  VISITS="$2"; shift 2;;
    --ref-every) REF_EVERY="$2"; shift 2;;
    *) echo "okant argument: $1"; exit 2;;
  esac
done

# The ten heights of the 2026-09-14 table, so the new one is directly
# comparable. 41.40 is back in: the 5 mm raise puts the rail near 36.7 mm.
# 41.40 dropped 2026-09-19: the rail sits at 43.5 mm with this housing, so it
# fails 0/2 every visit and wastes one visit in ten. Put it back only after a
# rebuild that measurably moves the rail inside it.
# 2026-09-23: that rebuild happened -- the new module glued with no preload
# rails near 25 mm, and 32.40 converges. These are the thirteen heights of its
# first night (af12, via railjakt.sh), so the second night is comparable.
# 2026-10-11, final housing: 110.40, 117.40, 130.40 and 140.40 added. A 75 L
# fill puts the zero at 117-125 mm, and the old table had a gap from 123.40 to
# 158.40 -- leave-one-height-out missed 123.40 by 1.9 mm, and the zero is a
# constant in every height that follows.
# 2026-10-12: 127.40, 135.40 and 145.40 added. The fill level is uncertain by
# a few litres -- fittings under the cone, the 2" sight glass, the valve bend,
# sensors reaching in -- and a litre is 5 mm in an F80, so the zero can land
# anywhere in ~105-145 mm. Night 1 missed 130.40 by -1.4 mm and 140.40 by -0.9,
# on one height each; a height every 5-7 mm there shows whether that repeats.
AVSTAND="32.40 35.40 38.40 41.40 46.40 52.40 60.40 70.40 82.40 99.40 110.40 117.40 123.40 127.40 130.40 135.40 140.40 145.40 158.40 218.40"
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
--warmup-interval 300 --warmup-min 30 --warmup-max 100\
${EXPOSURES:+ --exposures $EXPOSURES}"
CAL="python3 autocal.py --d0 $D0 --session $SESSION --request GO \
--interval 300 --visits $VISITS --zmax 200 --ref $ZREF --ref-every $REF_EVERY --heights $Z"

echo "d0 = $D0 mm"
echo "exponeringar: ${EXPOSURES:-af_calibrates standard}"
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

# The temperature log is not optional and was twice left out by hand: the
# afternoon run of 2026-09-19 has no temperatures at all because it was started
# without it. Every thermal conclusion in this project came from these three
# sensors against the reading, so a session without them cannot answer the
# question it was started to answer.
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

# Warm up at the reference height. On 2026-09-23 the night started with the
# stage wherever the previous run had left it, 60 mm from the reference, and
# was only moved by hand five minutes into the warm-up.
echo "flyttar bordet till referensen Z$ZREF"
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
echo "$(date +%H:%M:%S) uppvarmning klar, startar autocal"
setsid nohup $CAL </dev/null >>"${SESSION%.csv}.out" 2>&1 &
sleep 20
# --warmup-wait 110: the aluminium plate warms up in ~70 min, and afwatch's
# default of 45 would restart autocal against a camera still warming.
setsid nohup python3 afwatch.py --session "$SESSION" --stale 25 --warmup-wait 110 \
  --af "$AF" --cal "$CAL" --af-log "${SESSION%.csv}.log" \
  --cal-log "${SESSION%.csv}.out" --log "${SESSION%.csv}.watch" \
  </dev/null >>"${SESSION%.csv}.watchout" 2>&1 &
echo "$(date +%H:%M:%S) vakthund startad"
