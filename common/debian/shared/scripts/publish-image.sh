#!/usr/bin/env bash

set -euo pipefail

ensure_bucket() {
    local bucket_url="${S3_ENDPOINT}/${S3_BUCKET_NAME}/"

    local http_code
    http_code=$(curl -sL -o /dev/null -w '%{http_code}' \
        --user "${S3_USER}" \
        --aws-sigv4 "${S3_AWS_SIGV4}" \
        --head "${bucket_url}")

    if [[ "${http_code}" == "200" ]]; then
        printf 'Bucket '\''%s'\'' already exists.\n' "${S3_BUCKET_NAME}"
        return 0
    fi

    printf 'Bucket '\''%s'\'' not found (HTTP %s). Creating...\n' "${S3_BUCKET_NAME}" "${http_code}"

    curl -fsSL -X PUT \
        --user "${S3_USER}" \
        --aws-sigv4 "${S3_AWS_SIGV4}" \
        "${bucket_url}"

    printf 'Setting anonymous download policy on '\''%s'\''...\n' "${S3_BUCKET_NAME}"

    local policy
    policy=$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::${S3_BUCKET_NAME}/*"]
    }
  ]
}
POLICY
    )

    curl -fsSL -X PUT \
        --user "${S3_USER}" \
        --aws-sigv4 "${S3_AWS_SIGV4}" \
        -H 'Content-Type: application/json' \
        -d "${policy}" \
        "${bucket_url}?policy"

    printf 'Bucket '\''%s'\'' created with anonymous download access.\n' "${S3_BUCKET_NAME}"
}

s3_upload() {
    local upload_path="${1}"
    local upload_url="${S3_ENDPOINT}/${S3_BUCKET_NAME}/${S3_PREFIX}/${IMAGE_TYPE}/${BUILD_VERSION}/"

    curl --upload-file "${upload_path}" \
         --user "${S3_USER}" \
         --aws-sigv4 "${S3_AWS_SIGV4}" \
         "${upload_url}"
}

ensure_bucket

qemu-img info "${IMAGE_PATH}"
qemu-img check "${IMAGE_PATH}"

( cd "${OUTPUT_DIRECTORY}" && sha512sum "${VM_NAME}" ) > "${IMAGE_CHECKSUM_PATH}"

SHA512_CHECKSUM=$(awk '{print $1}' "${IMAGE_CHECKSUM_PATH}")
FINAL_IMAGE_URL="${S3_ENDPOINT}/${S3_BUCKET_NAME}/${S3_PREFIX}/${IMAGE_TYPE}/${BUILD_VERSION}/${VM_NAME}"

cat > "${IMAGE_METADATA_PATH}" <<EOF
{
  "IMAGE_NAME":         "${VM_NAME}",
  "SHA512_CHECKSUM":    "${SHA512_CHECKSUM}",
  "BUILD_DATE":         "${BUILD_TIMESTAMP}",
  "BASE_IMAGE":         "${BASE_IMAGE_URL}",
  "BASE_IMAGE_SHA512":  "${BASE_IMAGE_SHA512}",
  "PACKER_GIT_REMOTE":  "${GIT_REMOTE_URL}",
  "PACKER_GIT_COMMIT":  "${GIT_COMMIT_REF}",
  "IMAGE_URL":          "${FINAL_IMAGE_URL}"
}
EOF


s3_upload "${IMAGE_PATH}"
s3_upload "${IMAGE_CHECKSUM_PATH}"
s3_upload "${IMAGE_METADATA_PATH}"

ALL_METADATA_URL="${S3_ENDPOINT}/${S3_BUCKET_NAME}/${S3_PREFIX}/${ALL_METADATA_NAME}"
ALL_EXISTING_METADATA=$(curl -fsSL "${ALL_METADATA_URL}" 2>/dev/null || printf '%s\n' '[]')
ALL_EXISTING_METADATA=$(jq --slurpfile o "${IMAGE_METADATA_PATH}" '. + [$o[0]]' <<<"${ALL_EXISTING_METADATA}")

TMP_METADATA_PATH="$(mktemp)"
printf '%s\n' "${ALL_EXISTING_METADATA}" > "${TMP_METADATA_PATH}"

curl -fsSL --upload-file "${TMP_METADATA_PATH}" \
  --user "${S3_USER}" \
  --aws-sigv4 "${S3_AWS_SIGV4}" \
  -H 'Content-Type: application/json' \
  "${ALL_METADATA_URL}"
