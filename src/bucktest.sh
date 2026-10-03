#!/bin/bash
# The Wide Input SHIM under the real load: 10 min idle, then a viewer (from
# outside), then a 5 min recording with the viewer still on. Logs the
# throttled flags -- bit 0/16 is under-voltage now/since boot -- every 10 s.
cd ~/krausencamera
OUT=bucktest.csv
echo "tid,fas,throttled,core_V,soc_C,load1" >> $OUT
t0=$(date +%s); rec=0
while [ $(( $(date +%s) - t0 )) -lt 1800 ]; do
  e=$(( $(date +%s) - t0 ))
  if [ $e -ge 1500 ] && [ $rec -eq 0 ]; then curl -s -m 60 -X POST "localhost:8080/api/record?on=1" >/dev/null; rec=1; fi
  fas=tom; [ $e -ge 600 ] && fas=tittare; [ $rec -eq 1 ] && fas=rec+tittare
  echo "$(date +%H:%M:%S),$fas,$(vcgencmd get_throttled | cut -d= -f2),$(vcgencmd measure_volts core | tr -dc 0-9.),$(vcgencmd measure_temp | tr -dc 0-9.),$(cut -d" " -f1 /proc/loadavg)" >> $OUT
  sleep 10
done
curl -s -m 60 -X POST "localhost:8080/api/record?on=0" >/dev/null
echo klart >> $OUT
