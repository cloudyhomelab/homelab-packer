#!/usr/bin/env bash

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get -f -y install
apt-get -y autoremove --purge
apt-get -y clean
rm -rf /var/lib/apt/lists/*

cloud-init clean --logs
rm -rf /var/lib/cloud/*

truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

rm -f /etc/ssh/ssh_host_*

journalctl --rotate && journalctl --vacuum-time=1s
rm -rf /var/log/* /var/tmp/* /tmp/*

dd if=/dev/zero of=/var/tmp/bigfile bs=1M || true
rm /var/tmp/bigfile
sync
