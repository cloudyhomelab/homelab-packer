#!/usr/bin/env bash

set -euo pipefail

: "${PACKER_USER:?}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

# drop from sudo and sudoers
deluser "${PACKER_USER}" sudo
rm -f "/etc/sudoers.d/${PACKER_USER}"
rm -f /etc/sudoers.d/90-cloud-init-users
sed -i "/^${PACKER_USER}[[:space:]]\\+ALL/d" /etc/sudoers

userdel -fr "${PACKER_USER}"
