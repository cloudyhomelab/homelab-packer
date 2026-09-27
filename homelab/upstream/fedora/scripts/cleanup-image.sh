#!/usr/bin/env bash

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

dnf -y autoremove
dnf -y clean all
rm -rf /var/cache/dnf/*

cloud-init clean --logs
rm -rf /var/lib/cloud/*

truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

rm -f /etc/ssh/ssh_host_*
rm -f /etc/ssh/sshd_config.d/0000_packer.conf
rm -f /etc/ssh/sshd_config.d/50-cloud-init.conf
rm -f /etc/ssh/packer_user_ca.pub

journalctl --rotate && journalctl --vacuum-time=1s
rm -rf /var/log/journal/* /var/tmp/* /tmp/*
find /var/log -type f -delete

fstrim -av
sync
