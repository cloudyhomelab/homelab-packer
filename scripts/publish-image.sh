#!/usr/bin/env bash

set -euxo pipefail
cp "${IMAGE_PATH}" "${LATEST_IMAGE_PATH}"

( cd "${OUTPUT_DIRECTORY}" && sha512sum "${VM_NAME}" ) > "${CHECKSUM_PATH}"
( cd "${OUTPUT_DIRECTORY}" && sha512sum "${LATEST_VM_NAME}" ) > "${LATEST_CHECKSUM_PATH}"

qemu-img info "${IMAGE_PATH}"
qemu-img check "${IMAGE_PATH}"

"${MINIO_CLIENT}" mb --ignore-existing "${MINIO_PUBLISH_PATH}"
"${MINIO_CLIENT}" anonymous -r set download "${MINIO_PUBLISH_PATH}"

"${MINIO_CLIENT}" cp "${IMAGE_PATH}" "${MINIO_PUBLISH_PATH}"/"${BUILD_VERSION}"/
"${MINIO_CLIENT}" cp "${CHECKSUM_PATH}" "${MINIO_PUBLISH_PATH}"/"${BUILD_VERSION}"/

"${MINIO_CLIENT}" cp "${LATEST_IMAGE_PATH}" "${LATEST_MINIO_PUBLISH_PATH}"/
"${MINIO_CLIENT}" cp "${LATEST_CHECKSUM_PATH}" "${LATEST_MINIO_PUBLISH_PATH}"/
