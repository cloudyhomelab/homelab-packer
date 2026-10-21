build {
  name    = "fedora"
  sources = ["source.qemu.image"]

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
    playbook_file   = "${local.repo_root}/${var.playbook_file}"
    user            = var.username
    extra_arguments = ["--extra-vars", "image_playbook=${local.playbook_name}"]
  }

  # after the image playbook, so the SBOM sees every package it installed
  provisioner "ansible" {
    playbook_file = "${local.repo_root}/ansible/sbom.yml"
    user          = var.username
    extra_arguments = [
      "--extra-vars", "sbom_dest=${var.sbom_file}",
      "--extra-vars", "sbom_image=${var.image_name}",
      "--extra-vars", "sbom_build_version=${var.build_version}",
    ]
  }

  provisioner "shell" {
    execute_command = "chmod +x {{ .Path }}; {{ .Vars }} sudo -E bash -euo pipefail {{ .Path }}"
    env = {
      IMAGE             = var.image_name
      IMAGE_FILE        = local.vm_name
      OS                = var.os
      BUILD_VERSION     = var.build_version
      BUILD_DATE        = var.build_timestamp
      PARENT            = var.parent_name
      PARENT_URL        = var.parent_url
      PARENT_CHECKSUM   = var.parent_checksum
      CHECK_HASH        = var.check_hash
      PACKER_GIT_REMOTE = var.git_remote
      PACKER_GIT_COMMIT = var.git_commit
      PACKER_USER       = var.username
    }
    scripts = [
      "${local.os_dir}/scripts/create-image-metadata.sh",
      "${local.os_dir}/scripts/cleanup-image.sh",
      "${local.os_dir}/scripts/cleanup-user.sh",
    ]
  }
}
