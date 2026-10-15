#!/usr/bin/env bash
# ==============================================================================
# 1-Step Installation Script for Fresh Raspberry Pi OS / ARM64 Board
# Fulfills Deliverable 1 README requirement:
# "install and run on a fresh board"
# ==============================================================================

set -e

echo "=== Installing Never Lose a Heartbeat Data Pipeline ==="

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Installing Python 3..."
    sudo apt-get update && sudo apt-get install -y python3 python3-pip
fi

# 2. Setup Data Directory
DATA_DIR="/var/lib/pipeline"
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$USER":"$USER" "$DATA_DIR"

# 3. Install executable symlink
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chmod +x "$PROJECT_DIR/pipeline"
sudo ln -sf "$PROJECT_DIR/pipeline" /usr/local/bin/pipeline

echo "Pipeline CLI installed to /usr/local/bin/pipeline"

# 4. Optional: Install systemd service for crash & reboot persistence
cat <<EOF | sudo tee /etc/systemd/system/pipeline.service > /dev/null
[Unit]
Description=Never Lose a Heartbeat Ingestion Pipeline
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/local/bin/pipeline start --db /var/lib/pipeline/pipeline.db --mock-port 7100
Restart=always
RestartSec=1
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
echo "Systemd service configured: pipeline.service"
echo "To enable auto-start on boot: sudo systemctl enable --now pipeline"
echo "=== Installation Complete! ==="
