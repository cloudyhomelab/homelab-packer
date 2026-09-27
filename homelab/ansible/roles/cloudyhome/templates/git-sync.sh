#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/binarycodes/homelab-self-provisioner.git"
TARGET_DIR="{{ cloudyhome_base_path }}/ansible"

if [[ ! -d "$TARGET_DIR/.git" ]]; then
    git clone -b main --single-branch "$REPO_URL" "$TARGET_DIR"
else
    git -C "$TARGET_DIR" fetch --all --prune
    git -C "$TARGET_DIR" reset --hard origin/main
fi
