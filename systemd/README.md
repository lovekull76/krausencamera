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
