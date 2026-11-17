#!/bin/bash
# Bring the WiFi back when NetworkManager has given up on it, run by
# krausencamera-wifivakt.service.
#
# 2026-11-16 15:28 the Pi roamed to another access point, the 4-way handshake
# there failed once ("pre-shared key may be incorrect"), and NetworkManager
# asked for a new key. With no one to ask on a headless Pi it marked the
# connection failed (no-secrets) and never tried again: 29 hours off the
# network while the camera went on measuring, until a power cycle. A failed
# handshake blocks autoconnect until the connection is activated by hand, so
# that is what this does.
#
# Two misses in a row before acting, so an ordinary roam -- a few seconds
# disconnected -- is left alone. Only acting is logged.
set -u
missed=0
while :; do
  state=$(nmcli -t -g GENERAL.STATE device show wlan0 2>/dev/null)
  if [ "${state%% *}" = 100 ]; then
    missed=0
  else
    missed=$((missed + 1))
    if [ "$missed" -ge 2 ]; then
      echo "wlan0: ${state:-unknown} -- reconnecting"
      # nmcli draws a progress spinner; strip it or the journal shows a blob.
      nmcli device connect wlan0 2>&1 | tr '\r' '\n' | tr -cd '[:print:]\n' | tail -1
      missed=0
    fi
  fi
  sleep 60
done
