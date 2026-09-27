#!/usr/bin/env bash

set -euo pipefail

keys=(
  IMAGE
  IMAGE_FILE
  OS
  BUILD_VERSION
  BUILD_DATE
  PARENT
  PARENT_URL
  PARENT_CHECKSUM
  CHECK_HASH
  PACKER_GIT_REMOTE
  PACKER_GIT_COMMIT
)

for key in "${keys[@]}"; do
  : "${!key:?${key} is empty or unset}"
done

for key in "${keys[@]}"; do
  printf '%s="%s"\n' "${key}" "${!key}"
done > /etc/os-image-metadata
