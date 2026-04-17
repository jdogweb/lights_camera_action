#!/bin/bash
# One-shot: generate (or reuse) an SSH key, hand it to GitHub, push the repo.
# Safe to re-run — skips key generation if a key already exists.

set -e

KEY=~/.ssh/id_ed25519

echo ""
echo "=== Step 1: SSH key ==="
if [ ! -f "$KEY" ]; then
    echo "No SSH key found at $KEY — generating one..."
    mkdir -p ~/.ssh
    ssh-keygen -t ed25519 -C "julesallen@gmail.com" -f "$KEY" -N ""
    echo "Key generated."
else
    echo "Using existing key at $KEY."
fi

echo ""
echo "=== Step 2: Copy the public key to your clipboard ==="
pbcopy < "$KEY.pub"
echo "Public key copied to clipboard. First few chars:"
head -c 60 "$KEY.pub"
echo "..."

echo ""
echo "=== Step 3: Add the key to GitHub ==="
echo "Opening https://github.com/settings/ssh/new in your browser..."
open "https://github.com/settings/ssh/new"
cat <<'EOF'

   On the GitHub page:
     1. Click inside the "Key" box and paste (⌘V)
     2. Give it a title like "Mac"
     3. Click the green "Add SSH key" button
        (GitHub may ask for your GitHub password to confirm)

EOF
read -p "Press Enter here once you've added the key on GitHub: " _

echo ""
echo "=== Step 4: Test GitHub SSH auth ==="
# ssh -T always exits 1 when it succeeds (it closes the shell) — that's normal.
ssh -T git@github.com || true

echo ""
echo "=== Step 5: Push the repo ==="
cd ~/lights_camera_action

# Make sure there's at least one commit to push
if ! git rev-parse HEAD >/dev/null 2>&1; then
    echo "No commits yet — making an initial commit..."
    git add .
    git commit -m "Initial commit: 360 video + auto-deploy"
fi

# Make sure branch is main
if [ "$(git branch --show-current)" != "main" ]; then
    git branch -M main
fi

git push -u origin main

echo ""
echo "Done! Repo is on GitHub."
