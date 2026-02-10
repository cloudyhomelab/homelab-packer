#!/usr/bin/env sh

BASE_URL="http://moria.ip.cloudyhome.net:9000"
BASE_IMAGE_PATH="os-image/debian"

DOWNLOAD_FILE_NAME="debian-trixie-packer-latest.qcow2"
CHECKSUM_FILE_NAME="debian-trixie-packer-latest.qcow2.sha512"
CLOUD_INIT_FILE="seed.iso"


download_vm_image() {
    rm -f --preserve-root=all --one-file-system ./*.qcow2
    curl -L ${BASE_URL}/${BASE_IMAGE_PATH}/latest/${DOWNLOAD_FILE_NAME} --output ${DOWNLOAD_FILE_NAME}
}

redownload_required() {
    if [ ! -f ${CHECKSUM_FILE_NAME} ]; then
        curl -L ${BASE_URL}/${BASE_IMAGE_PATH}/latest/${CHECKSUM_FILE_NAME} --output ${CHECKSUM_FILE_NAME}
        return 0;
    fi

    # download the latest checksum regardless
    curl -L ${BASE_URL}/${BASE_IMAGE_PATH}/latest/${CHECKSUM_FILE_NAME} --output ${CHECKSUM_FILE_NAME}

    if ! [ -f ${DOWNLOAD_FILE_NAME} ]; then
        return 0;
    fi

    sha512sum --status -c ${CHECKSUM_FILE_NAME}
    SHA512_MATCH=$?

    if [ ${SHA512_MATCH} -ne 0 ]; then
        return 0;
    fi

    return 1;
}

if redownload_required ; then
    download_vm_image
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
  -drive file="${DOWNLOAD_FILE_NAME}",if=virtio,index=0 \
  -drive file="${CLOUD_INIT_FILE}",format=raw,if=virtio,index=1 \
  -nic user,model=virtio \
  -nographic \
  -serial mon:stdio
