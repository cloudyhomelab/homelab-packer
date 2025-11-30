#!/usr/bin/env bash

set -euo pipefail

PACKER_USER="${1}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

# drop from sudo and sudoers
deluser $PACKER_USER sudo
rm -f /etc/sudoers.d/$PACKER_USER
rm -f /etc/sudoers.d/90-cloud-init-users
sed -i "/^$PACKER_USER[[:space:]]\\+ALL/d" /etc/sudoers

# remove SSH keys and history
rm -rf /home/$PACKER_USER/.ssh
rm -f /home/$PACKER_USER/.bash_history

# disable interactive shell
if [ -x /usr/sbin/nologin ]; then
    usermod -s /usr/sbin/nologin $PACKER_USER
else
    sudo usermod -s /bin/false $PACKER_USER
fi

# wipe home contents but keep dir
find /home/$PACKER_USER -mindepth 1 -maxdepth 1 -exec rm -rf {} +

# lock + expire account
usermod -Le 1  $PACKER_USER
