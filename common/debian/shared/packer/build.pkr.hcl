build {
  name    = "debian-custom-qcow2"
  sources = ["source.qemu.debian-cloud"]

  provisioner "shell" {
    start_retry_timeout = "5m"
    expect_disconnect   = true

    inline = [
      "set -euo pipefail",
      "cloud-init status --wait",
    ]
  }

  provisioner "shell" {
    start_retry_timeout = "5m"
    pause_before        = "30s"
    inline = [
      "set -euo pipefail",
      "cloud-init status --wait",
      "cloud-init status --long || true",
      "test -f /var/lib/cloud/instance/boot-finished",
    ]
  }

  provisioner "ansible" {
    playbook_file = "${var.ansible_repo_path}/${var.playbook_name}.yml"
    user          = "${var.username}"
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E bash -euo pipefail {{ .Path }}"
    env = {
      BASE_IMAGE_SHA512 = var.source_cloud_image_checksum
      BASE_IMAGE_URL    = var.source_cloud_image_url
      BUILD_TIMESTAMP   = local.build_timestamp
      BUILD_VERSION     = local.build_version
      GIT_COMMIT_REF    = var.git_commit_ref
      GIT_REMOTE_URL    = var.git_remote_url
      PACKER_USER       = var.username
      VM_NAME           = local.vm_name
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
        BASE_IMAGE_SHA512   = var.source_cloud_image_checksum
        BASE_IMAGE_URL      = var.source_cloud_image_url
        BUILD_TIMESTAMP     = local.build_timestamp
        BUILD_VERSION       = local.build_version
        GIT_COMMIT_REF      = var.git_commit_ref
        GIT_REMOTE_URL      = var.git_remote_url
        IMAGE_CHECKSUM_PATH = local.image_checksum_path
        IMAGE_METADATA_PATH = local.image_metadata_path
        IMAGE_PATH          = local.image_path
        IMAGE_TYPE          = var.image_name
        OUTPUT_DIRECTORY    = var.output_directory
        S3_AWS_SIGV4        = var.s3_aws_sigv4
        S3_BUCKET_NAME      = var.s3_bucket_name
        S3_ENDPOINT         = var.s3_endpoint
        S3_PREFIX           = var.s3_prefix
        S3_USER             = var.s3_user
        VM_NAME             = local.vm_name
      }
      script = "scripts/publish-image.sh"
    }
  }
}
