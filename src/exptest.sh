#!/bin/bash
# Does the exposure move the AF reading? Run inside a calibration session, after
# autocal has finished, with af_calibrate still waiting for requests.
#
# Both nights in the final housing show the curve stepping about 1 mm away
# from the hyperbola exactly where the automatic exposure steps from 15 to
# 25 ms (between 123.40 and 127.40). If the step is the exposure, a krausen
# brighter or darker than the paper target picks a different exposure at the
# same height and reads a millimetre differently. This separates exposure time
# from image level at one fixed height:
#   A  15 ms, gain 1.00    the reference's own choice
#   B  25 ms, gain 1.00    longer exposure, brighter image
#   C  15 ms, gain 1.67    same brightness as B, same exposure as A
# A vs B changes both; B vs C isolates exposure time; A vs C isolates level.
# One point per 300 s, as in the night, so the duty cycle does not change.
#
#   ./exptest.sh af18          # waits for af18.out to say "klart"
set -u
cd ~/krausencamera
S=${1:-af18}
D=123.40
ZREF=96.00
LOG=exptest-$S.log
until grep -q "^klart" "$S.out" 2>/dev/null; do sleep 30; done
echo "$(date +%T) autocal klar -- flyttar till Z$ZREF" | tee -a $LOG
python3 stage.py --hold --to $ZREF --feed 150 --approach 5 --zmax 200 | grep -q framme \
  || { echo "bordet kom inte fram" | tee -a $LOG; exit 1; }
sleep 60
rows() { grep -c "^20" "$S.csv"; }
for i in 1 2 3 4; do
  for req in "exp=15000 gain=1.0" "exp=25000 gain=1.0" "exp=15000 gain=1.667"; do
    t0=$(date +%s); n=$(rows)
    echo "$D $req" > GO
    for k in $(seq 1 120); do sleep 5; [ "$(rows)" -gt "$n" ] && break; done
    echo "$(date +%T) $req -> $(tail -1 $S.csv)" | tee -a $LOG
    w=$(( 300 - ($(date +%s) - t0) )); [ $w -gt 0 ] && sleep $w
  done
done
echo "$(date +%T) klart" | tee -a $LOG
