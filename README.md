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

3. The daemon starts automatically and survives reboots.

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

## License

MIT
