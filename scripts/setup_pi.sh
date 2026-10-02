#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_pi.sh – One-time setup of a Raspberry Pi 5 for the Smart Desk.
#
# Follows the installation steps from the IoT Essentials course:
#   - system packages (Python, lgpio, PIL, MariaDB, Mosquitto, I2C tools)
#   - enables I2C, SPI and hardware PWM on GPIO12
#   - creates the virtual environment .venv (with --system-site-packages)
#   - installs the Python packages from requirements*.txt
#   - installs the Mosquitto config so the Pico can connect
#
# Usage (from the repository root):
#   bash scripts/setup_pi.sh          # everything
#   bash scripts/setup_pi.sh --no-ai  # skip the large AI packages
# Reboot afterwards.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_AI=1
[[ "${1:-}" == "--no-ai" ]] && INSTALL_AI=0

echo "==> Installing system packages"
sudo apt update
sudo apt install -y \
    git python3-pip python3-venv python3-setuptools python3-dev python3-pil \
    swig liblgpio-dev libmariadb-dev i2c-tools \
    mosquitto mosquitto-clients mariadb-server

echo "==> Enabling I2C and SPI"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0

echo "==> Enabling hardware PWM on GPIO12"
CONFIG_TXT=/boot/firmware/config.txt
if ! grep -q "^dtoverlay=pwm,pin=12,func=4" "$CONFIG_TXT"; then
    echo "dtoverlay=pwm,pin=12,func=4" | sudo tee -a "$CONFIG_TXT" > /dev/null
fi

echo "==> Creating virtual environment .venv"
cd "$REPO"
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [[ $INSTALL_AI -eq 1 ]]; then
    echo "==> Installing AI packages (this takes a while)"
    pip install -r requirements-ai.txt
fi

echo "==> Configuring Mosquitto (accept connections from the Pico)"
sudo cp config/mosquitto/smartdesk.conf /etc/mosquitto/conf.d/smartdesk.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "==> Enabling MariaDB"
sudo systemctl enable mariadb
sudo systemctl start mariadb

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "==> Created .env from .env.example – fill in your secrets!"
fi

echo
echo "Setup finished. Reboot now:  sudo reboot"
echo "Then check:  source .venv/bin/activate && python pi/check_setup.py"
