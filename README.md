# pi-pod 🎵

An iPod Accessory Protocol (iAP) emulator for Raspberry Pi Zero W that lets it masquerade as an iPod over a 30-pin dock connector.

Built to work with the [Poolside Factory 30-Pin Dock Adapter](https://poolsidefactory.com/products/airplay-audio-streaming-adapter-for-apple-30pin-dock-connector), which passively bridges the Pi's UART and I2S audio to the 30-pin connector. This project provides the missing protocol layer so that car stereos and other iPod accessories that require iAP communication will recognize the Pi as an iPod.

## What It Does

- **Speaks iAP** over serial (`/dev/serial0` at 19200 baud) to convince a car stereo (or other 30-pin dock accessory) that an iPod is connected
- **Bridges playback controls** — play/pause, skip, etc. from the car stereo are forwarded to a Bluetooth-connected phone via MPRIS D-Bus → AVRCP
- **Provides track metadata** — title, artist, album from the Bluetooth source are reported to the car stereo
- **Handles polling** — responds to elapsed-time polling requests

## Prerequisites

- Raspberry Pi Zero W or Zero 2 W
- [Poolside Factory 30-Pin Dock Adapter](https://poolsidefactory.com/products/airplay-audio-streaming-adapter-for-apple-30pin-dock-connector)
- Bluetooth audio configured per the [Poolside Factory Bluetooth tutorial](https://poolsidefactory.com/blogs/how-tos/how-to-setup-bluetooth-streaming-for-a-raspberry-pi-with-the-30-pin-dock-adapter-from-poolside-factory)
- UART serial enabled per the [Poolside Factory UART tutorial](https://poolsidefactory.com/blogs/how-tos/raspberry-pi-zero-w-to-apple-30-pin-dock-uart-connection)

## Installation

See [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment instructions, including prerequisites, troubleshooting, and redeployment procedures.

Quick start:

1. Copy this project to the Pi (e.g. via `scp`):
   ```bash
   scp -r pi-pod/ piuser@yourpi:~/pi-pod/
   ```

2. SSH into the Pi and run the installer:
   ```bash
   ssh piuser@yourpi
   cd ~/pi-pod
   chmod +x install.sh
   ./install.sh
   ```

3. Restart the btuser session (needed once for serial port permissions):
   ```bash
   sudo systemctl restart user@1001.service
   ```

4. The daemon starts automatically and survives reboots.

## Usage

The daemon runs automatically as a systemd user service for `btuser`. Manual usage:

```bash
# Run directly (for testing/debugging)
python3 -m pipod --port /dev/serial0 --baud 19200 --name iPod --verbose

# Check service status
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user status pipod

# View live logs
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 journalctl --user -u pipod -f
```

### Command-Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `-p`, `--port` | `/dev/serial0` | Serial port device |
| `-b`, `--baud` | `19200` | Baud rate |
| `-n`, `--name` | `iPod` | iPod name reported to accessory |
| `-v`, `--verbose` | off | Enable debug logging |

## How It Works

```
Phone (Pixel 7a)
  │ Bluetooth A2DP (audio) + AVRCP (controls)
  ▼
Raspberry Pi Zero W
  ├── PulseAudio ← Bluetooth audio → HiFiBerry DAC → 30-pin audio pins
  └── pi-pod daemon
        ├── MPRIS D-Bus ← mpris-proxy ← AVRCP (playback control)
        └── UART serial → 30-pin serial pins → Car Stereo
                          (iAP protocol)
```

1. The car stereo sends iAP commands over the 30-pin serial connection
2. `pi-pod` parses them and responds as if it were an iPod
3. Playback commands (play/pause/skip) are forwarded to the phone via MPRIS → AVRCP
4. Track metadata (title/artist/album) is read from the phone via MPRIS and sent back to the car

## Protocol Reference

The Apple Accessory Protocol (iAP) uses 19200 baud 8N1 serial with this packet format:

```
0xFF 0x55 [length] [mode] [cmd1] [cmd2] [params...] [checksum]
```

- **Mode 0**: Mode switching (handshake)
- **Mode 4**: Advanced Remote (playback control, metadata)
- **Checksum**: `(0x100 - (sum of length + all payload bytes)) & 0xFF`

See [ipodlinux.org AAP docs](http://ipodlinux.org/wiki/Apple_Accessory_Protocol) for the full protocol specification.

## Compatibility

### Works with (passive 30-pin docks)

The Poolside Factory adapter routes analog line-out audio and UART serial to the 30-pin connector. pi-pod speaks iAP over serial to satisfy accessories that require iPod identification before accepting audio. This works with **passive dock accessories** that take analog audio directly from the 30-pin line-out pins:

- Apple iPod Hi-Fi
- Bose SoundDock
- Speaker docks, clock radios, etc.

See the [Poolside Factory product page](https://poolsidefactory.com/products/airplay-audio-streaming-adapter-for-apple-30pin-dock-connector) for a full list of tested devices.

### Does NOT work with (active car iPod adapters)

Many car stereo iPod integrations use an **active adapter box** (CD changer emulator) that sits between the 30-pin connector and the head unit. These adapters typically communicate with the iPod over **USB** (30-pin pins 23/25/27), not serial, and re-encode audio for the car's CD changer bus. The Poolside Factory adapter does not connect USB pins, so these adapters cannot detect the Pi as an iPod.

**Known incompatible:**

| Adapter | Vehicle | Why |
|---------|---------|-----|
| Mitsubishi MZ360138EX | 2006-2012 Eclipse (Rockford Fosgate) | CD changer emulator; uses USB to detect/control iPod, no serial communication observed. Shows "E" (Error) on head unit. |

**Symptoms of an incompatible setup:**
- Car shows "E" or "Error" on the iPod/CD2 input
- No serial data received by pi-pod (check logs with `--verbose`)
- Audio pipeline on the Pi is healthy (PulseAudio sink RUNNING, loopback active) but no sound from speakers

**How to tell if your car adapter is compatible:**
1. Run pi-pod with `--verbose` and check if any serial data arrives from the car
2. If you see iAP packets, the adapter uses serial and pi-pod can work
3. If no data arrives, the adapter likely uses USB — pi-pod cannot help

**Alternatives for incompatible cars:**
- Bypass the iPod adapter entirely with an AUX input adapter or FM transmitter
- Use a Bluetooth-to-AUX adapter connected to the head unit's AUX input (if available)
- Replace the head unit with one that has Bluetooth built in

## License

MIT
