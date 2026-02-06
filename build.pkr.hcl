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

  provisioner "file" {
    source      = "scripts/cleanup-user.sh"
    destination = "/home/${var.username}/cleanup-user.sh"
  }

  provisioner "file" {
    source      = "scripts/cleanup-image.sh"
    destination = "/tmp/cleanup-image.sh"
  }

  provisioner "shell" {
    inline = [
      "set -euxo pipefail",
      "chmod 700 /tmp/cleanup-image.sh",
      "chmod 700 /home/${var.username}/cleanup-user.sh",

      "sudo /tmp/cleanup-image.sh",
      "sudo /home/${var.username}/cleanup-user.sh \"${var.username}\"",

      "rm -f /tmp/cleanup-image.sh",
      "rm -f /home/${var.username}/cleanup-user.sh",
    ]
  }

  provisioner "shell" {
    expect_disconnect = true

    execute_command = "echo '${var.password}' | sudo -S bash -x {{ .Path }}"
    inline = [
      "set -euxo pipefail",
      "userdel -fr ${var.username} || true"
    ]
  }

  post-processor "shell-local" {
    inline = [
      "set -euxo pipefail",
      "( cd ${var.output_directory} && sha512sum ${local.vm_name} ) > ${local.checksum_path}",
      "qemu-img info ${local.image_path}",
      "qemu-img check ${local.image_path}",
      "${var.minio_client} mb --ignore-existing ${var.minio_publish_path}",
      "${var.minio_client} anonymous -r set download ${var.minio_publish_path}",
      "${var.minio_client} cp ${local.image_path} ${var.minio_publish_path}/",
      "${var.minio_client} cp ${local.checksum_path} ${var.minio_publish_path}/",
      # latest
      "${var.minio_client} cp ${local.image_path} ${local.latest_minio_publish_path}/${local.latest_vm_name}",
      "${var.minio_client} cp ${local.checksum_path} ${local.latest_minio_publish_path}/${local.latest_checksum_name}",
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
