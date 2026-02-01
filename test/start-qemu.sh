#!/usr/bin/env sh

DOWNLOAD_FILE_NAME="debian-trixie-packer-20260129-0849.qcow2"
DEBIAN_IMAGE_NAME="debian-trixie-packer.qcow2"
CLOUD_INIT_FILE="seed.iso"

if ! [ -f ${DEBIAN_IMAGE_NAME} ]; then
    curl -L http://moria.ip.cloudyhome.net:9000/os-image/debian/${DOWNLOAD_FILE_NAME} \
         --output ${DEBIAN_IMAGE_NAME}
fi

if ! [ -f ${CLOUD_INIT_FILE} ]; then
    genisoimage -output ${CLOUD_INIT_FILE} \
                -volid cidata -joliet -rock \
                user-data meta-data network-config
fi

qemu-system-x86_64 \
  -m 2048 \
  -smp 2 \
  -enable-kvm \
  -drive file=${DEBIAN_IMAGE_NAME},if=virtio,index=0 \
  -drive file=${CLOUD_INIT_FILE},format=raw,if=virtio,index=1 \
  -nic user,model=virtio \
  -nographic \
  -serial mon:stdio
