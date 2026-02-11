#!/usr/bin/env bash

cat > /etc/os-image-metadata <<EOF
IMAGE_NAME="${VM_NAME}",
BUILD_DATE="${BUILD_TIMESTAMP}",
BASE_IMAGE="${BASE_IMAGE_URL}",
PACKER_GIT_COMMIT="${GIT_COMMIT_REF}"
EOF
