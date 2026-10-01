#!/bin/bash
# CPU cap vs SoC temperature under the real workload: three caps, each 25 min:
# 12 min idle, then a viewer (from outside, at 10 fps), then a 5 min recording.
set -u
cd ~/krausencamera
F=/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq
OUT=lasttest.csv
echo "tid,fas,tak_MHz,klocka_MHz,soc_C,load1,cpu_py" >> $OUT
log() {
  t=$(vcgencmd measure_temp | tr -dc "0-9."); c=$(( $(vcgencmd measure_clock arm | cut -d= -f2) / 1000000 ))
  l=$(cut -d" " -f1 /proc/loadavg); p=$(ps -C python3 -o %cpu= --sort=-%cpu | head -1 | tr -d " ")
  echo "$(date +%H:%M:%S),$1,$2,$c,$t,$l,$p" >> $OUT
}
for cap in 1000 800 600; do
  echo ${cap}000 | sudo tee $F >/dev/null
  t0=$(date +%s); rec=0
  while [ $(( $(date +%s) - t0 )) -lt 1500 ]; do
    e=$(( $(date +%s) - t0 ))
    if [ $e -ge 1080 ] && [ $rec -eq 0 ]; then curl -s -m 60 -X POST "localhost:8080/api/record?on=1" >/dev/null; rec=1; fi
    fas=tom; [ $e -ge 720 ] && fas=tittare; [ $rec -eq 1 ] && fas=rec+tittare
    log $fas $cap; sleep 15
  done
  curl -s -m 60 -X POST "localhost:8080/api/record?on=0" >/dev/null
done
echo 1000000 | sudo tee $F >/dev/null
echo klart >> $OUT
