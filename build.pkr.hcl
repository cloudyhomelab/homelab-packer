build {
  name    = "debian-custom-qcow2"
  sources = ["source.qemu.debian-cloud"]

  provisioner "shell" {
    start_retry_timeout = "5m"
    expect_disconnect   = true

    inline = [
      "set -euxo pipefail",
      "cloud-init status --wait",
    ]
  }

  provisioner "shell" {
    start_retry_timeout = "5m"
    pause_before        = "30s"
    inline = [
      "set -euxo pipefail",
      "cloud-init status --wait",
      "cloud-init status --long || true",
      "test -f /var/lib/cloud/instance/boot-finished",
    ]
  }

  provisioner "shell-local" {
    inline = [
      "set -euxo pipefail",
      "rm -r '${local.ansible_repo_path}'",
      "git clone -b '${local.ansible_repo_branch}' --single-branch '${local.ansible_repo}' '${local.ansible_repo_path}'",
    ]
  }

  provisioner "ansible" {
    playbook_file = "${local.ansible_repo_path}/packer.yml"
    user          = "${var.username}"
  }

  provisioner "shell" {
    execute_command = "sudo bash -x -c '{{ .Vars }} {{ .Path }}'"
    env = {
      PACKER_USER = var.username
    }
    scripts = [
      "scripts/cleanup-image.sh",
      "scripts/cleanup-user.sh"
    ]
  }

  post-processors {
    post-processor "shell-local" {
      env = {
        BUILD_VERSION             = local.build_version
        CHECKSUM_PATH             = local.checksum_path
        IMAGE_PATH                = local.image_path
        LATEST_CHECKSUM_PATH      = local.latest_checksum_path
        LATEST_IMAGE_PATH         = local.latest_image_path
        LATEST_MINIO_PUBLISH_PATH = local.latest_minio_publish_path
        LATEST_VM_NAME            = local.latest_vm_name
        MINIO_CLIENT              = var.minio_client
        MINIO_PUBLISH_PATH        = var.minio_publish_path
        OUTPUT_DIRECTORY          = var.output_directory
        VM_NAME                   = local.vm_name
      }
      script = "scripts/publish-image.sh"
    }

    post-processor "manifest" {
      output     = local.manifest_path
      strip_path = true
      custom_data = {
        image_path    = "${var.minio_publish_path}/${local.image_path}",
        checksum_path = "${var.minio_publish_path}/${local.checksum_path}"
      }
    }
  }
}
