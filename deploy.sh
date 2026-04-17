#!/bin/bash
# Auto-deploy: pull latest main and restart lca if anything changed.
# Triggered every 60s by lca-deploy.timer (systemd). See install-autodeploy.sh.

set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

# Only deploy from main.
BRANCH="main"

# Fetch without pulling so we can compare first.
git fetch --quiet origin "$BRANCH"

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    # Already up to date — exit quietly so journal isn't spammed every minute.
    exit 0
fi

echo "[lca-deploy] New commits on origin/$BRANCH: ${LOCAL:0:7} -> ${REMOTE:0:7}"

# Check if requirements.txt is about to change, so we can run pip install after.
REQS_CHANGED=0
if ! git diff --quiet "$LOCAL" "$REMOTE" -- requirements.txt 2>/dev/null; then
    REQS_CHANGED=1
fi

git pull --ff-only origin "$BRANCH"

if [ "$REQS_CHANGED" = "1" ]; then
    echo "[lca-deploy] requirements.txt changed — running pip install"
    # Use --user so we don't need root; adjust if you use a venv.
    python3 -m pip install --user -r requirements.txt || \
        echo "[lca-deploy] WARNING: pip install failed; continuing with restart"
fi

# Restart the app. Passwordless sudo rule installed by install-autodeploy.sh
# allows jdogweb to run just this exact command.
sudo /bin/systemctl restart lca.service
echo "[lca-deploy] Restarted lca.service"
