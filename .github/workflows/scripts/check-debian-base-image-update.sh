#!/usr/bin/env bash

set -euo pipefail

URL_KEY="source_cloud_image_url"
CHECKSUM_KEY="source_cloud_image_checksum"

OS="debian"
BASE_URL="http://moria.ip.cloudyhome.net:9000"
BASE_IMAGE_PATH="os-image/${OS}"
METADATA_FILENAME="metadata_all.json"


find_image() {
  local field="${1}" # "IMAGE_NAME", "SHA512_CHECKSUM", "BUILD_VERSION", etc
  local prefix="${OS}-${2}"
  local json_file="${3}"

  : "${field:?field value is required}"
  : "${prefix:?prefix value is required}"
  : "${json_file:?json_file value is required}"

  jq -r --arg prefix "${prefix}-" --arg field "${field}" '
     map(select(.IMAGE_NAME | startswith($prefix)))
     | max_by(.BUILD_DATE)
     | .[$field] // empty
     ' "${json_file}"
}

check_update_source_image() {
    local role="${1}"

    : "${role:?Argument for role is empty or unset}"

    local metadata_filepath
    metadata_filepath=$(mktemp)

    curl -fsSL "${BASE_URL}/${BASE_IMAGE_PATH}/${METADATA_FILENAME}" --output "${metadata_filepath}"

    local image_name image_checksum build_version
    image_name=$(find_image "IMAGE_NAME" "${role}" "${metadata_filepath}")
    image_checksum=$(find_image "SHA512_CHECKSUM" "${role}" "${metadata_filepath}")
    build_version=$(find_image "BUILD_VERSION" "${role}" "${metadata_filepath}")

    local image_url="${BASE_URL}/${BASE_IMAGE_PATH}/${build_version}/${image_name}"

    local target_file="./common/${OS}/images/${role}/source-image.auto.pkrvars.hcl"
    if [ ! -f "${target_file}" ]; then
        touch "${target_file}"
    fi

    local current_url
    current_url=$(grep -F "${URL_KEY}" "${target_file}" | cut -d'"' -f2)

    if [ "${image_url}" = "${current_url}" ]; then
        echo "No update required"
    else
    cat > "${target_file}" <<EOF
${URL_KEY}          = "${image_url}"
${CHECKSUM_KEY}     = "sha512:${image_checksum}"
EOF
    fi
}

check_update_source_image "container"
check_update_source_image "kubernetes"
