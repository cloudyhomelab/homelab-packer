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
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E bash -euxo pipefail {{ .Path }}"
    env = {
      BASE_IMAGE_URL  = var.debian_cloud_image_url
      BUILD_TIMESTAMP = local.build_timestamp
      GIT_COMMIT_REF  = var.git_commit_ref
      PACKER_USER     = var.username
      VM_NAME         = local.vm_name
    }
    scripts = [
      "scripts/create-image-metadata.sh",
      "scripts/cleanup-image.sh",
      "scripts/cleanup-user.sh"
    ]
  }

  post-processors {
    post-processor "shell-local" {
      env = {
        ALL_METADATA_NAME   = local.all_metadata_name
        BASE_IMAGE_URL      = var.debian_cloud_image_url
        BUILD_TIMESTAMP     = local.build_timestamp
        BUILD_VERSION       = local.build_version
        CHECKSUM_PATH       = local.checksum_path
        GIT_COMMIT_REF      = var.git_commit_ref
        IMAGE_METADATA_NAME = local.image_metadata_name
        IMAGE_PATH          = local.image_path
        MINIO_CLIENT        = var.minio_client
        MINIO_PUBLISH_PATH  = var.minio_publish_path
        OUTPUT_DIRECTORY    = var.output_directory
        VM_NAME             = local.vm_name
      }
      script = "scripts/publish-image.sh"
    }
  }
}
