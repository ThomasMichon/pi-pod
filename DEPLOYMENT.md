# Deployment Guide

## Fresh Install (New Pi)

If you're starting from a fresh Raspberry Pi OS Lite image, `setup.sh` automates the entire configuration — Bluetooth audio, HiFiBerry DAC, UART serial, and pi-pod installation.

### 1. Image the SD card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write **Raspberry Pi OS Lite (32-bit)** to your SD card. In the imager settings, configure:
- WiFi credentials
- SSH enabled
- Username and password (e.g. `piuser`)

### 2. Copy the project to the Pi

```bash
ssh <user>@<hostname> "mkdir -p ~/pi-pod"
scp -r pipod/ requirements.txt install.sh setup.sh systemd/ <user>@<hostname>:~/pi-pod/
```

### 3. Run the setup script

```bash
ssh <user>@<hostname>
cd ~/pi-pod
chmod +x setup.sh
sudo ./setup.sh --hostname yourpi --btuser-password <password>
```

The script will:
- Update the system and install all packages
- Create `btuser` with PulseAudio and Bluetooth agent
- Configure the HiFiBerry DAC and UART serial
- Install the pi-pod iPod emulator service
- Reboot automatically

After reboot, Bluetooth is finalized by a one-shot service that then removes itself.

### 4. Pair your phone

After reboot, pair your phone via Bluetooth. The Pi appears as the hostname you chose (e.g. "yourpi"). No PIN required.

### 5. (Optional) Enable read-only filesystem

See the [Read-Only Filesystem](#read-only-filesystem) section below. Only do this after verifying audio works.

## Redeploying pi-pod (Already Configured Pi)

If the Pi is already set up and you just need to update pi-pod code:

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

> **If the Pi is in read-only mode**, you must disable overlay first.
> See [Read-Only Filesystem](#read-only-filesystem) below.

## Re-running Full Setup (install.sh)

If `btuser` and Bluetooth are already configured but you need to reinstall the
pi-pod service (e.g. after reimaging), use `install.sh` instead of `setup.sh`:

```bash
cd ~/pi-pod
chmod +x install.sh
sudo ./install.sh
sudo systemctl restart user@1001.service  # needed once for dialout group
```

## Read-Only Filesystem

Enabling a read-only root filesystem protects the SD card from corruption
caused by sudden power loss (e.g. when the car ignition turns off).

### How it works

`raspi-config` enables OverlayFS, which mounts the root partition read-only
with a tmpfs (RAM) upper layer. All runtime writes go to RAM and are discarded
on reboot. The SD card is never written to during normal operation.

### When to enable

**After all setup AND phone pairing are complete.** Bluetooth pairing data
lives in `/var/lib/bluetooth/` on the root filesystem. With overlay enabled,
new pairings are lost on reboot.

### Enabling read-only mode

```bash
# Option A: During initial setup
sudo ./setup.sh --hostname yourpi --btuser-password <pw> --enable-readonly

# Option B: After setup, manually
sudo raspi-config nonint enable_overlayfs
sudo reboot
```

### What works in read-only mode

| Feature | Status | Why |
|---------|--------|-----|
| Bluetooth audio from paired devices | ✅ | Pairing data already on disk |
| pi-pod iPod emulator | ✅ | No disk writes |
| PulseAudio | ✅ | Runtime state in /run (tmpfs) |
| WiFi / SSH | ✅ | DHCP lease in tmpfs |
| systemd journal | ✅ | Writes to /run/log/journal (tmpfs) |
| Pairing NEW Bluetooth devices | ❌ | Lost on reboot |
| apt install / system updates | ❌ | Lost on reboot |
| Config file changes | ❌ | Lost on reboot |

### Disabling read-only mode (to make changes)

```bash
sudo raspi-config nonint disable_overlayfs
sudo reboot

# Make changes (pair new phone, update pi-pod, apt upgrade, etc.)

# Re-enable when done
sudo raspi-config nonint enable_overlayfs
sudo reboot
```

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
