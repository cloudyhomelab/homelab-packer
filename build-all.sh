#!/usr/bin/env bash

./.github/workflows/scripts/check-debian-cloud-image-update.sh
make debian-base-build-kvm

./.github/workflows/scripts/check-debian-base-image-update.sh
make debian-container-build-kvm
make debian-kubernetes-build-kvm

./.github/workflows/scripts/check-debian-container-image-update.sh
make debian-edge-build-kvm
