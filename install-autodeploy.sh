#!/bin/bash
# One-time installer for the auto-deploy timer.
# Run this ONCE on the Pi, from inside the cloned repo, as user jdogweb:
#
#     cd ~/lights_camera_action
#     ./install-autodeploy.sh
#
# It will:
#   1. Copy the systemd unit + timer to /etc/systemd/system/
#   2. Add a passwordless sudoers rule so jdogweb can restart lca.service only
#   3. Enable and start the 60s timer
#
# Requires: sudo access (it will prompt).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
EXPECTED_DIR="/home/jdogweb/lights_camera_action"

if [ "$REPO_DIR" != "$EXPECTED_DIR" ]; then
    echo "ERROR: This installer expects the repo at $EXPECTED_DIR, but it is at $REPO_DIR."
    echo "Either move the repo, or edit systemd/lca-deploy.service to point at the new path."
    exit 1
fi

echo "==> Installing systemd units..."
sudo install -m 644 "$REPO_DIR/systemd/lca-deploy.service" /etc/systemd/system/
sudo install -m 644 "$REPO_DIR/systemd/lca-deploy.timer"   /etc/systemd/system/

echo "==> Writing sudoers rule for passwordless 'systemctl restart lca.service'..."
SUDOERS_TMP=$(mktemp)
echo "jdogweb ALL=(root) NOPASSWD: /bin/systemctl restart lca.service" > "$SUDOERS_TMP"
# Validate before installing — bad sudoers files can lock you out.
sudo visudo -cf "$SUDOERS_TMP"
sudo install -m 440 "$SUDOERS_TMP" /etc/sudoers.d/lca-deploy
rm -f "$SUDOERS_TMP"

echo "==> Ensuring deploy.sh is executable..."
chmod +x "$REPO_DIR/deploy.sh"

echo "==> Enabling + starting timer..."
sudo systemctl daemon-reload
sudo systemctl enable --now lca-deploy.timer

echo ""
echo "Installed. Timer status:"
sudo systemctl status lca-deploy.timer --no-pager | head -20
echo ""
echo "Tail the deploy log with:  journalctl -u lca-deploy.service -f"
echo "The timer fires every 60s. Push to origin/main and wait up to a minute."
