#!/bin/bash
# Check the running service against the stage: known heights in, its readings out.
#
# The service measures every 300 s on its own clock. This waits for each new
# row in its daily CSV, moves the stage straight after one -- never during a
# measurement -- and lets two more land at every height. The first of those
# is taken 20-300 s after the move; the second is the one to trust.
#
# Before the tour it sets the zero at the reference height through the page's
# own API, so the krausen column can be checked too: at every height it should
# read REF minus that height.
#
#   ./tjanstprov.sh          # waits for the service's warm-up flag to clear
set -u
cd ~/krausencamera

D0=27.4
REF=123.40
TOUR="99.40 70.40 46.40 123.40 60.40 35.40 82.40 123.40 41.40 110.40 123.40"
OUT=tjanstprov.csv

say() { echo "$(date +%H:%M:%S) $*"; }
today() { echo "matningar/matning-$(date +%Y%m%d).csv"; }
rows() { local n; n=$(grep -vc "^#" "$(today)" 2>/dev/null); echo "${n:-0}"; }
last_status() { tail -1 "$(today)" | cut -d, -f2; }
wait_rows() {    # wait until $1 more rows have landed
  local want=$(( $(rows) + $1 ))
  while [ "$(rows)" -lt "$want" ]; do sleep 10; done
}
move_to() {
  local z; z=$(python3 -c "print(f'{$1-$D0:.2f}')")
  python3 stage.py --hold --to "$z" --feed 150 --approach 5 --zmax 200 | grep -q framme \
    || { say "** bordet kom aldrig fram till $1 -- avbryter **"; exit 1; }
  echo "$(date +%Y-%m-%dT%H:%M:%S),$1,$z" >> "$OUT"
}

echo "# tjanstprov $(date +%Y-%m-%dT%H:%M:%S), bordet flyttat: tid,d_mm,Z" >> "$OUT"
say "vantar pa att uppvarmningen ska klinga av i tjansten"
until [ "$(last_status)" = "ok" ]; do sleep 30; done

say "ok -- satter bordet pa referensen $REF och tar nollan dar"
wait_rows 1
move_to "$REF"
wait_rows 2
curl -s -X POST localhost:8080/api/zero >/dev/null && say "nolla satt" \
  || say "** nollan gick inte att satta **"

for d in $TOUR; do
  wait_rows 1
  move_to "$d"
  say "bordet pa $d mm"
  wait_rows 2
done
say "klart"
