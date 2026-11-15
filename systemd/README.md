# Running as a service

```bash
rsync -avz --exclude '.git' ./src/ krausencamera:~/krausencamera/
scp systemd/krausencamera.service krausencamera:/tmp/
ssh krausencamera 'sudo mv /tmp/krausencamera.service /etc/systemd/system/ \
  && sudo systemctl daemon-reload \
  && sudo systemctl enable --now krausencamera'
```

Then:

```bash
ssh krausencamera 'systemctl status krausencamera'
ssh krausencamera 'journalctl -u krausencamera -f'
ssh krausencamera 'journalctl -u krausencamera --since -12h | grep "frame A"'
```

## Keep the journal

Raspberry Pi OS keeps the journal in RAM (`Storage=volatile`), where avahi's
noise pushed it past its ~8 MB cap in about a day -- so a hang found the next
morning had no log left. `journald-50-persistent.conf` keeps it on the SD card,
200 MB.

The noise itself was the UniFi gateway's device identification: once a minute
it multicasts one query for every service type it has seen, from port 38055
rather than 5353, so avahi treats it as a legacy unicast query -- and the
answer for `_workstation._tcp` does not fit one packet. Five warnings a
minute, ~8 MB of journal a day. It has nothing to do with UniFi's mDNS
forwarding, which was switched off without effect. `publish-workstation=no`
in `/etc/avahi/avahi-daemon.conf` (2026-11-15) silenced it; `krausencamera.local`
still resolves.

```bash
scp systemd/journald-50-persistent.conf krausencamera:/tmp/
ssh krausencamera 'sudo mkdir -p /etc/systemd/journald.conf.d \
  && sudo mv /tmp/journald-50-persistent.conf /etc/systemd/journald.conf.d/50-persistent.conf \
  && sudo systemctl restart systemd-journald && sudo journalctl --flush'
```

## What restarts what

Two watchdogs, because they catch different failures:

- **The tracker's failure counter** fires when a capture *raises*. Three in a
  row and the process exits 17.
- **The watchdog thread** fires when a capture *hangs* without raising, which is
  what a wedged CSI link does. It exits 17 if no cycle has completed in three
  intervals plus two minutes.

systemd then restarts the process after 10 s. If that happens five times inside
ten minutes the fault is below the process — a CSI receiver stuck in the kernel
is not cleared by reopening the device — and `StartLimitAction=reboot` reboots
the Pi.

Measured on 2026-09-10: a frontend timeout stopped the camera at 06:26 and went
unnoticed until 11:30, because the process stayed up and served an empty stream.

## Working on it while the service runs

The service holds the camera. Anything else that wants it -- `tilt_probe.py`,
`focus_sweep.py`, `exposure_probe.py` -- will fail while it is up.

**Do not `pkill` it.** systemd restarts it within ten seconds, it fails to get
the camera in about two, and five of those inside ten minutes trips
`StartLimitAction=reboot`. The Pi reboots roughly a minute later.

Use the flag instead:

```bash
ssh krausencamera 'touch ~/krausencamera/MAINTENANCE'
ssh krausencamera 'sudo systemctl restart krausencamera'   # releases the camera
# ... run whatever you like ...
ssh krausencamera 'rm ~/krausencamera/MAINTENANCE'          # resumes by itself
```

With the flag in place the service stays `active` but never opens the camera, so
there is no restart loop and nothing to remember to undo. Removing the flag
makes it exit cleanly, and systemd starts it again in normal operation.

`systemctl stop krausencamera` works too and is fine for a quick job -- the flag
is for when you might forget, or when the Pi could reboot in between.
