#!/usr/bin/env bash

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

apt-get clean
apt-get autoremove --purge

# cloud-init: clean instance state so Proxmox cloud-init treats it as fresh
cloud-init clean --logs
rm -rf /var/lib/cloud/*

# reset machine-id so each clone gets a unique one
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

# remove SSH host keys so they regenerate on first boot
rm -f /etc/ssh/ssh_host_*

# scrub logs/tmp (optional, but nice)
rm -rf /var/log/* /var/tmp/* /tmp/*

dd if=/dev/zero of=/var/tmp/bigfile bs=1M || true
rm /var/tmp/bigfile
sync
