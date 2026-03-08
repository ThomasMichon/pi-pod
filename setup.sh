#!/usr/bin/env bash
# setup.sh — Full pre-configuration of a fresh Raspberry Pi for Bluetooth
# audio streaming via the Poolside Factory 30-pin dock adapter, with UART
# serial enabled and the pi-pod iPod emulator installed.
#
# Based on:
#   https://poolsidefactory.com/blogs/how-tos/how-to-setup-bluetooth-streaming-for-a-raspberry-pi-with-the-30-pin-dock-adapter-from-poolside-factory
#   https://poolsidefactory.com/blogs/how-tos/raspberry-pi-zero-w-to-apple-30-pin-dock-uart-connection
#
# Usage:
#   sudo ./setup.sh --hostname yourpi --btuser-password <password>
#
# Run this on a fresh Raspberry Pi OS Lite image after first SSH login.
# The script reboots at the end; a post-reboot phase finalizes Bluetooth.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOSTNAME=""
BTUSER_PASSWORD=""
BTUSER="btuser"
ENABLE_READONLY=false

# --- Argument parsing ---

usage() {
    echo "Usage: sudo $0 --hostname <name> --btuser-password <password> [--enable-readonly]"
    echo ""
    echo "  --hostname          Bluetooth device name / Pi hostname"
    echo "  --btuser-password   Password for the btuser account"
    echo "  --enable-readonly   Enable read-only overlay FS after setup (optional)"
    echo "                      NOTE: Pair your phone BEFORE enabling this."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hostname)        HOSTNAME="$2"; shift 2 ;;
        --btuser-password) BTUSER_PASSWORD="$2"; shift 2 ;;
        --enable-readonly) ENABLE_READONLY=true; shift ;;
        -h|--help)         usage ;;
        *)                 echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$HOSTNAME" || -z "$BTUSER_PASSWORD" ]]; then
    echo "Error: --hostname and --btuser-password are required."
    usage
fi

if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run as root (sudo)."
    exit 1
fi

echo "============================================="
echo " pi-pod Full Setup"
echo " Hostname:  $HOSTNAME"
echo " BT User:   $BTUSER"
echo " Read-only: $ENABLE_READONLY"
echo "============================================="
echo ""

# --- Phase 1: System update & packages ---

echo ">>> [1/8] Updating system and installing packages..."
apt-get update -y
apt-get -y dist-upgrade
apt-get install -y \
    pulseaudio pulseaudio-module-bluetooth bluez-tools \
    python3-serial python3-dbus

# --- Phase 2: Hostname ---

echo ">>> [2/8] Setting hostname to '$HOSTNAME'..."
raspi-config nonint do_hostname "$HOSTNAME"

# --- Phase 3: Create btuser ---

echo ">>> [3/8] Creating $BTUSER account..."
if id "$BTUSER" &>/dev/null; then
    echo "  $BTUSER already exists, skipping creation."
else
    useradd -m "$BTUSER"
    echo "$BTUSER:$BTUSER_PASSWORD" | chpasswd
    echo "  $BTUSER created."
fi

# Add to sudoers (idempotent)
SUDOERS_FILE="/etc/sudoers.d/010_pi-nopasswd"
if ! grep -q "^$BTUSER " "$SUDOERS_FILE" 2>/dev/null; then
    sed -i "1s/^/$BTUSER ALL=(ALL) NOPASSWD: ALL\n/" "$SUDOERS_FILE"
    echo "  Added $BTUSER to sudoers."
fi

# Add to dialout group for serial access
usermod -aG dialout "$BTUSER"
echo "  Added $BTUSER to dialout group."

# --- Phase 4: Bluetooth configuration ---

echo ">>> [4/8] Configuring Bluetooth..."

# Autologin btuser on tty1
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $BTUSER --noclear %I \$TERM
EOF
echo "  Configured tty1 autologin for $BTUSER."

# Set DiscoverableTimeout to 0 (always discoverable)
sed -i --follow-symlinks 's/#DiscoverableTimeout = 0/DiscoverableTimeout = 0/' \
    /etc/bluetooth/main.conf
echo "  Set DiscoverableTimeout = 0."

# Add --noplugin=avrcp to bluetoothd (idempotent)
BT_SERVICE="/etc/systemd/system/bluetooth.target.wants/bluetooth.service"
if [[ -f "$BT_SERVICE" ]] && ! grep -q -- '--noplugin=avrcp' "$BT_SERVICE"; then
    sed -i --follow-symlinks 's|bluetooth/bluetoothd|bluetooth/bluetoothd --noplugin=avrcp|' \
        "$BT_SERVICE"
    echo "  Added --noplugin=avrcp to bluetoothd."
else
    echo "  bluetoothd --noplugin=avrcp already configured or service file not found."
fi

# Create bt-agent service
cat > /etc/systemd/system/bt-agent.service <<EOF
[Unit]
Description=Bluetooth Auth Agent
After=bluetooth.service
PartOf=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput

[Install]
WantedBy=bluetooth.target
EOF
systemctl enable bt-agent
echo "  Created and enabled bt-agent.service."

# Start btuser session and enable PulseAudio
systemctl start "user@$(id -u $BTUSER).service" || true
sudo -u "$BTUSER" XDG_RUNTIME_DIR="/run/user/$(id -u $BTUSER)" \
    systemctl --user enable pulseaudio 2>/dev/null || true
echo "  Enabled PulseAudio for $BTUSER."

# --- Phase 5: HiFiBerry DAC (audio output to 30-pin adapter) ---

echo ">>> [5/8] Configuring HiFiBerry DAC audio output..."
CONFIG_TXT="/boot/firmware/config.txt"
if [[ ! -f "$CONFIG_TXT" ]]; then
    CONFIG_TXT="/boot/config.txt"
fi

sed -i --follow-symlinks 's/dtparam=audio=on/dtparam=audio=off/' "$CONFIG_TXT"
if ! grep -q "dtoverlay=hifiberry-dac" "$CONFIG_TXT"; then
    sed -i --follow-symlinks '/dtparam=audio=off/a dtoverlay=hifiberry-dac' "$CONFIG_TXT"
fi
echo "  HiFiBerry DAC overlay configured."

# --- Phase 6: UART serial (for iPod accessory protocol) ---

echo ">>> [6/8] Configuring UART serial port..."
raspi-config nonint do_serial_cons 1  # disable console on serial
raspi-config nonint do_serial_hw 0    # enable serial hardware
echo "  Serial console disabled, serial hardware enabled."

# --- Phase 7: Install pi-pod ---

echo ">>> [7/8] Installing pi-pod iPod emulator..."

# Copy project files
mkdir -p "/home/$BTUSER/pi-pod"
cp -r "$SCRIPT_DIR/pipod" "/home/$BTUSER/pi-pod/"
cp "$SCRIPT_DIR/requirements.txt" "/home/$BTUSER/pi-pod/"
chown -R "$BTUSER:$BTUSER" "/home/$BTUSER/pi-pod"

# Install systemd user service
mkdir -p "/home/$BTUSER/.config/systemd/user"
cp "$SCRIPT_DIR/systemd/pipod.service" "/home/$BTUSER/.config/systemd/user/"
chown -R "$BTUSER:$BTUSER" "/home/$BTUSER/.config/systemd"

BTUSER_UID="$(id -u $BTUSER)"
sudo -u "$BTUSER" XDG_RUNTIME_DIR="/run/user/$BTUSER_UID" \
    systemctl --user daemon-reload 2>/dev/null || true
sudo -u "$BTUSER" XDG_RUNTIME_DIR="/run/user/$BTUSER_UID" \
    systemctl --user enable pipod.service 2>/dev/null || true
echo "  pi-pod installed and enabled."

# --- Phase 8: Create post-reboot finalizer ---

echo ">>> [8/8] Registering post-reboot finalization..."

cat > /usr/local/bin/pipod-post-reboot.sh <<'PHASE2_SCRIPT'
#!/usr/bin/env bash
# pi-pod post-reboot finalization — runs once after setup.sh reboot
set -euo pipefail

LOG_TAG="pipod-setup"
logger -t "$LOG_TAG" "Post-reboot finalization starting..."

# Configure Bluetooth discoverable and pairable
bluetoothctl <<BT_EOF
power on
discoverable on
pairable on
agent on
BT_EOF
logger -t "$LOG_TAG" "Bluetooth configured: power on, discoverable, pairable."

PHASE2_SCRIPT

# Append read-only overlay setup if requested
if [[ "$ENABLE_READONLY" == "true" ]]; then
    cat >> /usr/local/bin/pipod-post-reboot.sh <<'READONLY_SCRIPT'

# Enable read-only overlay filesystem
echo "WARNING: Enabling read-only overlay filesystem."
echo "New Bluetooth pairings will not persist across reboots."
echo "To pair a new device, first disable overlay:"
echo "  sudo raspi-config nonint disable_overlayfs && sudo reboot"
raspi-config nonint enable_overlayfs
logger -t "$LOG_TAG" "Read-only overlay filesystem enabled."
READONLY_SCRIPT
fi

# Append self-cleanup to the post-reboot script
cat >> /usr/local/bin/pipod-post-reboot.sh <<'CLEANUP_SCRIPT'

# Self-cleanup
systemctl disable pipod-post-reboot.service 2>/dev/null || true
rm -f /etc/systemd/system/pipod-post-reboot.service
rm -f /usr/local/bin/pipod-post-reboot.sh
systemctl daemon-reload
logger -t "$LOG_TAG" "Post-reboot finalization complete. Cleaned up."
CLEANUP_SCRIPT

chmod +x /usr/local/bin/pipod-post-reboot.sh

# Create one-shot systemd service for post-reboot
cat > /etc/systemd/system/pipod-post-reboot.service <<EOF
[Unit]
Description=pi-pod post-reboot setup finalization
After=bluetooth.service network-online.target
Wants=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/pipod-post-reboot.sh
RemainAfterExit=false

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pipod-post-reboot.service
echo "  Post-reboot service registered."

echo ""
echo "============================================="
echo " Setup Phase 1 complete!"
echo "============================================="
echo ""
echo " The system will now reboot."
echo " After reboot, Bluetooth will be finalized automatically."
echo ""
if [[ "$ENABLE_READONLY" == "true" ]]; then
    echo " ⚠️  Read-only mode will be enabled after reboot."
    echo "    Make sure you pair your phone BEFORE the next reboot,"
    echo "    or disable overlay later to pair:"
    echo "    sudo raspi-config nonint disable_overlayfs && sudo reboot"
    echo ""
fi
echo " Once rebooted, check status with:"
echo "   sudo -u btuser XDG_RUNTIME_DIR=/run/user/$(id -u $BTUSER) systemctl --user status pipod"
echo ""
echo " Rebooting in 5 seconds... (Ctrl+C to cancel)"
sleep 5
reboot
