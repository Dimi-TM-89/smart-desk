#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_services.sh – Run the Smart Desk programs as systemd services.
#
# Installs the units from systemd/ into /etc/systemd/system, with this
# repository's path and your user name filled in:
#   smartdesk-controller.service   pi/desk_controller.py
#   smartdesk-posture.service      pi/posture_ai.py
#   smartdesk-cloud.service        pi/cloud_bridge.py
#   smartdesk-db.service           pi/db_logger.py
#   smartdesk.target               the four together, started at boot
#
# Run it again after a change in systemd/ (or after moving the repository).
#
# Usage (from the repository root, as your normal user – NOT with sudo):
#   bash scripts/install_services.sh              # install + enable at boot
#   bash scripts/install_services.sh --no-ai      # same, without the posture AI
#   bash scripts/install_services.sh --uninstall  # stop and remove everything
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"
UNIT_DIR=/etc/systemd/system
SERVICES=(smartdesk-controller smartdesk-posture smartdesk-cloud smartdesk-db)

if [[ "$RUN_USER" == "root" ]]; then
    echo "Run this as your normal user (e.g. pi), not with sudo: the services run as that user."
    exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "==> Stopping and removing the Smart Desk services"
    sudo systemctl disable --now smartdesk.target "${SERVICES[@]/%/.service}" 2>/dev/null || true
    for unit in smartdesk.target "${SERVICES[@]/%/.service}"; do
        sudo rm -f "$UNIT_DIR/$unit"
    done
    sudo systemctl daemon-reload
    echo "Removed. Run the programs by hand again (see README)."
    exit 0
fi

INSTALL_AI=1
[[ "${1:-}" == "--no-ai" ]] && INSTALL_AI=0

# --- Checks ----------------------------------------------------------------
if [[ "$REPO" == *" "* ]]; then
    echo "The repository path contains a space ($REPO): move it, e.g. to ~/smart-desk"
    exit 1
fi
if [[ ! -x "$REPO/.venv/bin/python" ]]; then
    echo "No virtual environment in $REPO/.venv – run scripts/setup_pi.sh first."
    exit 1
fi
if [[ ! -f "$REPO/.env" ]]; then
    echo "No .env file – run:  cp .env.example .env  and fill it in."
    exit 1
fi

# The services run without a terminal: the user needs the hardware groups
missing=()
for group in gpio i2c spi video; do
    id -nG "$RUN_USER" | tr ' ' '\n' | grep -qx "$group" || missing+=("$group")
done
if (( ${#missing[@]} )); then
    echo "WARNING: $RUN_USER is not in the group(s): ${missing[*]}"
    echo "         sudo usermod -aG $(IFS=,; echo "${missing[*]}") $RUN_USER   (then log out and in)"
fi

if [[ $INSTALL_AI -eq 1 && ! -d "$REPO/models/yolo11n-pose_ncnn_model" ]]; then
    echo "NOTE: the pose model is not exported yet. Run once by hand first:"
    echo "        source .venv/bin/activate && python pi/posture_ai.py"
    echo "      (or the service downloads it at its first start, which needs internet)"
fi

# --- Install ---------------------------------------------------------------
echo "==> Installing the units for user '$RUN_USER', repository $REPO"
for unit in smartdesk.target "${SERVICES[@]/%/.service}"; do
    sed -e "s|@USER@|$RUN_USER|g" -e "s|@REPO@|$REPO|g" "$REPO/systemd/$unit" \
        | sudo tee "$UNIT_DIR/$unit" > /dev/null
done
sudo systemctl daemon-reload

echo "==> Enabling at boot"
ENABLED=(smartdesk-controller smartdesk-cloud smartdesk-db)
if [[ $INSTALL_AI -eq 1 ]]; then
    ENABLED+=(smartdesk-posture)
else
    sudo systemctl disable --now smartdesk-posture.service 2>/dev/null || true
    echo "    (posture AI left out – enable later: sudo systemctl enable --now smartdesk-posture)"
fi
sudo systemctl enable smartdesk.target "${ENABLED[@]/%/.service}"

echo
echo "Installed. The Smart Desk now starts at every boot. Useful commands:"
echo "  sudo systemctl start smartdesk.target       # start all programs now"
echo "  sudo systemctl stop smartdesk.target        # stop all (before running a test by hand!)"
echo "  sudo systemctl restart smartdesk.target     # after a git pull"
echo "  systemctl list-units 'smartdesk*'           # which programs run"
echo "  journalctl -u 'smartdesk-*' -f              # live output of all programs"
echo "  sudo systemctl disable smartdesk.target     # no longer start at boot"
