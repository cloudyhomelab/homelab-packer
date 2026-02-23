#!/usr/bin/env bash

set -euo pipefail

TEST_IMAGE_NAME="$1"
: "${TEST_IMAGE_NAME:?Test image name is empty or unset}"

BASE_URL="https://s3-api.cloudyhome.net"
BASE_IMAGE_PATH="os-image/debian"
METADATA_FILENAME="metadata_all.json"
CLOUD_INIT_FILE="seed.iso"

find_image() {
  local field="$1" # "IMAGE_NAME", "SHA512_CHECKSUM", "BUILD_VERSION", etc
  local prefix="${TEST_IMAGE_NAME}"
  local json_file="${METADATA_FILENAME}"

  jq -r --arg prefix "${prefix}-" --arg field "$field" '
     map(select(.IMAGE_NAME | startswith($prefix)))
     | max_by(.BUILD_DATE)
     | .[$field] // empty
     ' "$json_file"
}


curl -fsSL "${BASE_URL}/${BASE_IMAGE_PATH}/${METADATA_FILENAME}" --output "${METADATA_FILENAME}"
IMAGE_NAME=$(find_image "IMAGE_NAME")
IMAGE_CHECKSUM=$(find_image "SHA512_CHECKSUM")
BUILD_VERSION=$(find_image "BUILD_VERSION")


: "${IMAGE_NAME:?Image name is empty or unset}"
: "${IMAGE_CHECKSUM:?Image checksum is empty or unset}"
: "${BUILD_VERSION:?Build version is empty or unset}"


if [ ! -f "${IMAGE_NAME}" ]; then
    rm -f --preserve-root=all --one-file-system ./*.qcow2
    curl -fsSL "${BASE_URL}/${BASE_IMAGE_PATH}/${BUILD_VERSION}/${IMAGE_NAME}" --output "${IMAGE_NAME}"

    if ! printf '%s  %s\n' "${IMAGE_CHECKSUM}" "${IMAGE_NAME}" | sha512sum -c - >/dev/null; then
        rm -f --preserve-root=all --one-file-system -- "${IMAGE_NAME}"
        echo "Checksum mismatch ${IMAGE_CHECKSUM} - deleted ${IMAGE_NAME}"
        exit 1
    fi
fi

if ! [ -f ${CLOUD_INIT_FILE} ]; then
    genisoimage -output "${CLOUD_INIT_FILE}" \
                -volid cidata -joliet -rock \
                user-data meta-data network-config
fi

qemu-system-x86_64 \
  -m 2048 \
  -smp 2 \
  -enable-kvm \
  -drive file="${IMAGE_NAME}",if=virtio,index=0 \
  -drive file="${CLOUD_INIT_FILE}",format=raw,if=virtio,index=1 \
  -nic user,model=virtio \
  -nographic \
  -serial mon:stdio
