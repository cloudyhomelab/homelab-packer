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
    environment_vars = [
      "PACKER_USER=${var.username}"
    ]
    scripts = [
      "scripts/cleanup-image.sh",
      "scripts/cleanup-user.sh"
    ]
  }

  post-processors {
    post-processor "shell-local" {
      inline = [
        "set -euxo pipefail",
        "cp ${local.image_path} ${local.latest_image_path}",

        "( cd ${var.output_directory} && sha512sum ${local.vm_name} ) > ${local.checksum_path}",
        "( cd ${var.output_directory} && sha512sum ${local.latest_vm_name} ) > ${local.latest_checksum_path}",

        "qemu-img info ${local.image_path}",
        "qemu-img check ${local.image_path}",

        "${var.minio_client} mb --ignore-existing ${var.minio_publish_path}",
        "${var.minio_client} anonymous -r set download ${var.minio_publish_path}",

        "${var.minio_client} cp ${local.image_path} ${var.minio_publish_path}/",
        "${var.minio_client} cp ${local.checksum_path} ${var.minio_publish_path}/",

        "${var.minio_client} cp ${local.latest_image_path} ${local.latest_minio_publish_path}/",
        "${var.minio_client} cp ${local.latest_checksum_path} ${local.latest_minio_publish_path}/",
      ]
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
