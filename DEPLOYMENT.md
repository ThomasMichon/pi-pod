# Deployment Guide

## Prerequisites

Before deploying pi-pod, your Raspberry Pi Zero W must have:

1. **Bluetooth audio streaming configured** per the [Poolside Factory Bluetooth tutorial](https://poolsidefactory.com/blogs/how-tos/how-to-setup-bluetooth-streaming-for-a-raspberry-pi-with-the-30-pin-dock-adapter-from-poolside-factory)
2. **UART serial enabled** (console disabled) per the [Poolside Factory UART tutorial](https://poolsidefactory.com/blogs/how-tos/raspberry-pi-zero-w-to-apple-30-pin-dock-uart-connection)
3. A `btuser` account (UID 1001) already running PulseAudio and `mpris-proxy`

### Verify Prerequisites

```bash
# UART available and not used by console
ls -la /dev/serial0          # should point to ttyS0
grep 'console=serial' /boot/firmware/cmdline.txt  # should return nothing

# HiFiBerry DAC overlay active
grep 'dtoverlay=hifiberry-dac' /boot/firmware/config.txt

# btuser session running with PulseAudio
sudo systemctl status user@1001.service
```

## Deploying from a Development Machine

### 1. Copy files to the Pi

```bash
scp -r pipod/ requirements.txt install.sh systemd/ piuser@yourpi:~/pi-pod/
```

> **Note:** You must create `~/pi-pod/` on the Pi first if it doesn't exist:
> ```bash
> ssh piuser@yourpi "mkdir -p ~/pi-pod"
> ```

### 2. Run the installer

```bash
ssh piuser@yourpi
cd ~/pi-pod
chmod +x install.sh
sudo ./install.sh
```

The installer will:
- Install `python3-serial` and `python3-dbus` via apt
- Add `btuser` to the `dialout` group (required for `/dev/serial0` access)
- Copy the project to `/home/btuser/pi-pod/`
- Install and enable a systemd user service for `btuser`

### 3. Restart the btuser session

The `dialout` group membership requires a session restart to take effect. This is **not** handled automatically by the installer because it would kill the running PulseAudio and Bluetooth audio.

```bash
sudo systemctl restart user@1001.service
```

> **⚠️ This will briefly interrupt Bluetooth audio.** Any connected phone will need to reconnect or will reconnect automatically after a few seconds.

After restarting, the pipod service starts automatically:

```bash
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user status pipod
```

You should see:
```
● pipod.service - pi-pod iPod Emulator
     Active: active (running)
...
pipod INFO Serial port /dev/serial0 opened at 19200 baud
pipod INFO Emulator running — waiting for commands from car stereo
```

## Redeploying After Code Changes

```bash
# From your development machine:
scp -r pipod/ piuser@yourpi:~/pi-pod/

# On the Pi:
ssh piuser@yourpi
sudo cp -r ~/pi-pod/pipod/ /home/btuser/pi-pod/
sudo chown -R btuser:btuser /home/btuser/pi-pod
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user restart pipod
```

No session restart needed for code-only changes — just restart the service.

## Troubleshooting

### Viewing logs

```bash
# Live log stream
sudo journalctl --no-pager -f | grep pipod

# Last 50 lines
sudo journalctl --no-pager -n 50 | grep pipod
```

> **Note:** `journalctl --user -u pipod` requires the `btuser` session, but log permissions may prevent access. Using `sudo journalctl | grep pipod` is more reliable.

### Running manually for debugging

```bash
# Stop the service first
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user stop pipod

# Run manually with verbose output
sudo -u btuser DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus \
  python3 -m pipod --port /dev/serial0 --baud 19200 --name iPod --verbose
```

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Permission denied: '/dev/serial0'` | `btuser` not in `dialout` group, or group change not yet active | `sudo usermod -aG dialout btuser` then `sudo systemctl restart user@1001.service` |
| `No module named serial` | `python3-serial` not installed | `sudo apt install python3-serial` |
| `Failed to connect to D-Bus` | `btuser` session not running, or `DBUS_SESSION_BUS_ADDRESS` not set | Ensure `user@1001.service` is active; the systemd unit sets the env var |
| Service in `activating (auto-restart)` loop | Repeated crash — check journal for the actual error | See "Viewing logs" above |

### Boot time

The Pi Zero W takes approximately 2–2.5 minutes to fully boot with all services (Bluetooth, PulseAudio, pipod). This is normal for the single-core ARM11 CPU. The pipod service has `RestartSec=5` so it will retry automatically if it starts before the serial port is ready.
