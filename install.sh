#!/usr/bin/env bash
# Install pi-pod on a Raspberry Pi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing pi-pod iPod Emulator ==="

# Install Python dependencies
echo "Installing Python dependencies..."
sudo apt-get install -y python3-serial python3-dbus 2>/dev/null || true
pip3 install --user -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# Ensure btuser has serial port access
echo "Adding btuser to dialout group..."
sudo usermod -aG dialout btuser

# Copy project to btuser home
echo "Copying project files..."
sudo mkdir -p /home/btuser/pi-pod
sudo cp -r "$SCRIPT_DIR/pipod" /home/btuser/pi-pod/
sudo cp "$SCRIPT_DIR/requirements.txt" /home/btuser/pi-pod/
sudo chown -R btuser:btuser /home/btuser/pi-pod

# Install systemd service (as a user service for btuser)
echo "Installing systemd user service..."
sudo mkdir -p /home/btuser/.config/systemd/user
sudo cp "$SCRIPT_DIR/systemd/pipod.service" /home/btuser/.config/systemd/user/
sudo chown -R btuser:btuser /home/btuser/.config/systemd

# Enable and start the service
echo "Enabling service..."
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user daemon-reload
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user enable pipod.service
sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user restart pipod.service

echo ""
echo "=== Installation complete ==="
echo "Check status: sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 systemctl --user status pipod"
echo "View logs:    sudo -u btuser XDG_RUNTIME_DIR=/run/user/1001 journalctl --user -u pipod -f"
