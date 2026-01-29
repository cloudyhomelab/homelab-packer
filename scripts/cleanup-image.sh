#!/usr/bin/env bash

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

apt-get autoremove --purge
apt-get clean

cloud-init clean --logs
rm -rf /var/lib/cloud/*

truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

rm -f /etc/ssh/ssh_host_*

rm -rf /var/log/* /var/tmp/* /tmp/*

dd if=/dev/zero of=/var/tmp/bigfile bs=1M || true
rm /var/tmp/bigfile
sync
