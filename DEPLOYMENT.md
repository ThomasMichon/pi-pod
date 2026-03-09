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

### USB iPod Gadget Setup

If your car stereo uses USB (not serial) to communicate with iPods, you can configure the Pi as a USB iPod gadget. This requires the adapter board to route 30-pin USB pins to the Pi's USB test pads — see [USB Connectivity](README.md#usb-connectivity) in the README.

#### Prerequisites

- Kernel headers installed: `sudo apt install raspberrypi-kernel-headers`
- Build tools: `gcc`, `make`, `git`
- Go compiler (for cross-compiling the client on your dev machine)

#### Build and install kernel modules

```bash
# On the Pi:
git clone https://github.com/oandrew/ipod-gadget.git
cd ipod-gadget/gadget
make
sudo mkdir -p /lib/modules/$(uname -r)/extra
sudo cp g_ipod_hid.ko g_ipod_audio.ko g_ipod_gadget.ko /lib/modules/$(uname -r)/extra/
sudo depmod -a
```

#### Cross-compile the Go client

```bash
# On your dev machine (requires Go):
git clone https://github.com/oandrew/ipod.git ipod-client
cd ipod-client
GOOS=linux GOARCH=arm GOARM=6 go build -o ipod-arm6 github.com/oandrew/ipod/cmd/ipod

# Copy to Pi:
scp ipod-arm6 <user>@<hostname>:/home/<user>/
ssh <user>@<hostname> "sudo cp ~/ipod-arm6 /usr/local/bin/ipod-usb && sudo chmod +x /usr/local/bin/ipod-usb"
```

#### Configure dwc2 peripheral mode

Edit `/boot/firmware/config.txt`:
```
# Under the [all] section:
dtoverlay=dwc2,dr_mode=peripheral
```

Remove or comment out `otg_mode=1` if present (usually under `[cm4]`).

Add module auto-loading:
```bash
echo -e "libcomposite\ng_ipod_hid\ng_ipod_audio\ng_ipod_gadget" | sudo tee /etc/modules-load.d/ipod-gadget.conf
```

#### Create the systemd service

```bash
sudo tee /etc/systemd/system/ipod-gadget.service > /dev/null << 'EOF'
[Unit]
Description=iPod USB Gadget
After=multi-user.target
Wants=bluetooth.service

[Service]
Type=simple
ExecStartPre=/sbin/modprobe libcomposite
ExecStartPre=/sbin/insmod /lib/modules/%v/extra/g_ipod_hid.ko
ExecStartPre=/sbin/insmod /lib/modules/%v/extra/g_ipod_audio.ko
ExecStartPre=/sbin/insmod /lib/modules/%v/extra/g_ipod_gadget.ko
ExecStart=/usr/local/bin/ipod-usb -d serve /dev/iap0
ExecStopPost=-/sbin/rmmod g_ipod_gadget g_ipod_audio g_ipod_hid
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ipod-gadget
sudo reboot
```

#### Verify after reboot

```bash
# Check USB device controller
ls /sys/class/udc/          # Should show 20980000.usb
# Check iAP device
ls -la /dev/iap0            # Should exist
# Check ALSA card
aplay -l | grep iPodUSB     # Should show iPod PCM card
# Check service
systemctl status ipod-gadget
```

#### Bridge Bluetooth audio to iPodUSB

Once the iPodUSB ALSA card is available, route Bluetooth audio to it via PulseAudio:

```bash
# As btuser:
pactl load-module module-alsa-sink device=plughw:CARD=iPodUSB,DEV=0 sink_name=ipod_usb
pactl set-default-sink ipod_usb
```

> **Note:** The kernel modules must be rebuilt whenever the kernel is updated (`sudo apt upgrade`). Re-run the build steps in the `ipod-gadget/gadget` directory after a kernel update.

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
