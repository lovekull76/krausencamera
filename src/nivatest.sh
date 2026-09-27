#!/bin/bash
# Does image level bias the far end? Six levels at 218.40 mm, all at 30 fps.
#
# Night af15 (2026-09-27) capped exposure at 32 ms so every height ran at
# 30 fps. The sensor-cooling dip after 218 mm disappeared, as predicted, but
# 218's residual grew from +4-5 to +7.8 mm -- and that height had become
# darker (level 148 -> 114), while 158 mm became brighter (126 -> 146) and its
# residual shrank (+0.9-1.8 -> +0.6). Frame rate and level changed together.
#
# This holds the frame rate and steps the level: four exposures at unity gain,
# then 32 ms with gain for the brighter end, since a longer exposure would slow
# the frame again. Four rounds, each in shuffled order, two minutes apart, so a
# slow drift spreads over every condition instead of riding on one.
#
# Waits for af15 to finish, then takes over the camera. Run it in the
# background; it needs nothing from anyone.
set -u
cd ~/krausencamera

SESSION=af16.csv
D=218.40
Z=191.00
ROUNDS=4
INTERVAL=120
CONDS=("exp=8000 gain=1.0" "exp=15000 gain=1.0" "exp=25000 gain=1.0"
       "exp=32000 gain=1.0" "exp=32000 gain=1.3" "exp=32000 gain=1.45")

say() { echo "$(date +%H:%M:%S) $*"; }
# grep -c prints 0 *and* exits 1 on a file with no data rows, so "|| echo 0"
# would print two lines. Take its output, default only when there is none.
rows() { local n; n=$(grep -vc "^#" "$SESSION" 2>/dev/null); echo "${n:-0}"; }

say "vantar pa att af15 blir klar"
while pgrep -f "autocal\.py --d0" >/dev/null; do sleep 30; done
say "af15 klar, stanger den sessionen"
echo stop > GO
for i in $(seq 1 120); do
  pgrep -f "python3 af_calibrate\.py" >/dev/null || break
  sleep 2
done
if pgrep -f "python3 af_calibrate\.py" >/dev/null; then
  say "** af_calibrate lever an -- avbryter hellre an kor tva mot samma kamera **"
  exit 1
fi
rm -f GO

say "flyttar bordet till Z$Z ($D mm)"
python3 stage.py --hold --to "$Z" --feed 150 --approach 5 --zmax 200 \
  | grep -q framme || { say "** bordet kom aldrig fram -- avbryter **"; exit 1; }

# The warm-up runs at this height with exposure capped at 32 ms, so the camera
# settles at 30 fps -- the frame rate every point below is taken at.
setsid nohup python3 af_calibrate.py --session "$SESSION" --request GO \
  --preview 8081 --runs 2 --auto-exposure --park-after 0.0 \
  --warmup-interval 120 --warmup-min 12 --warmup-max 60 \
  --exposures 1000 2000 4000 8000 15000 25000 32000 \
  </dev/null >"${SESSION%.csv}.log" 2>&1 &
sleep 8
for i in $(seq 1 150); do
  grep -q "vantar pa GO" "${SESSION%.csv}.log" && break
  sleep 30
done
grep -q "vantar pa GO" "${SESSION%.csv}.log" || { say "uppvarmningen blev aldrig klar"; exit 1; }
say "uppvarmning klar, $ROUNDS varv x ${#CONDS[@]} nivaer"

n=0
for r in $(seq 1 "$ROUNDS"); do
  while IFS= read -r c; do
    t=$(date +%s)
    before=$(rows)
    n=$((n + 1))
    echo "$D $c" > GO
    for i in $(seq 1 150); do
      [ "$(rows)" -gt "$before" ] && break
      sleep 2
    done
    say "[$n] varv $r  $c  -> rader $(rows)"
    echo "$(date +%Y-%m-%dT%H:%M:%S),$n,$r,$c" >> nivatest.log
    left=$((INTERVAL - ($(date +%s) - t)))
    [ "$left" -gt 0 ] && sleep "$left"
  done < <(printf '%s\n' "${CONDS[@]}" | shuf)
done

echo stop > GO
say "klart, $n punkter i $SESSION"
