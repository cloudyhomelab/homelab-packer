#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://cdimage.debian.org/images/cloud/trixie"
ARCH="amd64"

LATEST_DIR=$(curl -fsSL "$BASE_URL/" \
                 | grep -oE '[0-9]{8}-[0-9]{4}/' \
                 | sort -r \
                 | head -n1 \
                 | tr -d '/')

IMAGE_NAME="debian-13-genericcloud-${ARCH}-${LATEST_DIR}.qcow2"
IMAGE_URL="${BASE_URL}/${LATEST_DIR}/${IMAGE_NAME}"

CHECKSUM=$(curl -fsSL "${BASE_URL}/${LATEST_DIR}/SHA512SUMS" \
               | grep "${IMAGE_NAME}" \
               | awk '{print $1}')

TARGET_FILE="base-image.auto.pkrvars.hcl"
if [ ! -f "${TARGET_FILE}" ]; then
    touch "${TARGET_FILE}"
fi

CURRENT_URL=$(grep debian_cloud_image_url "${TARGET_FILE}" \
                  | cut -d'"' -f2)

if [ "${IMAGE_URL}" = "${CURRENT_URL}" ]; then
  echo "No new Debian cloud image"
  exit 0
fi

cat > "${TARGET_FILE}" <<EOF
debian_cloud_image_url          = "${IMAGE_URL}"
debian_cloud_image_checksum     = "sha512:${CHECKSUM}"
EOF
