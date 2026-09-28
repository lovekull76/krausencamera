#!/bin/bash
# Does the IR lamp's heat in the lid move the reading?
#
# The service holds the lamp on because the calibration nights did, and the
# lid's temperature moves the reading about 1.1-1.6 mm/C. Whether the lamp
# itself warms the lid enough to matter was never measured. This alternates
# two-hour blocks of lamp held on and lamp lit only to measure, four of each,
# at one stage height, and logs when each block began. The lid sensor and the
# reading are in the service's own daily CSV.
#
# A step at each switch that reverses at the next is the lamp. Two hours
# because the lid is steel with a time constant of tens of minutes.
set -u
cd ~/krausencamera
BLOCK_S=7200
CYCLES=4
OUT=lamptest.csv
today() { echo "matningar/matning-$(date +%Y%m%d).csv"; }

say() { echo "$(date +%H:%M:%S) $*"; }
echo "# lamptest $(date +%Y-%m-%dT%H:%M:%S): tid,lampa (1 = alltid, 0 = bara vid matning)" >> "$OUT"
say "vantar pa att uppvarmningen ska klinga av"
until [ "$(tail -1 "$(today)" 2>/dev/null | cut -d, -f2)" = "ok" ]; do sleep 30; done
for c in $(seq 1 "$CYCLES"); do
  for mode in 0 1; do
    curl -s -X POST "localhost:8080/api/lampmode?on=$mode" >/dev/null \
      || { say "** tjansten svarar inte -- avbryter **"; exit 1; }
    echo "$(date +%Y-%m-%dT%H:%M:%S),$mode" >> "$OUT"
    say "varv $c: lampa $([ $mode = 1 ] && echo 'alltid tand' || echo 'bara vid matning')"
    sleep "$BLOCK_S"
  done
done
curl -s -X POST "localhost:8080/api/lampmode?on=1" >/dev/null
say "klart, lampan tillbaka till alltid tand"
