build {
  name    = "debian-custom-qcow2"
  sources = ["source.qemu.debian-cloud"]

  provisioner "shell" {
    inline = [
      "set -eux",
      "cloud-init status --wait",
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
      "set -eux",
      "chmod 700 /tmp/cleanup-image.sh",
      "chmod 700 /home/${var.username}/cleanup-user.sh",

      "sudo /tmp/cleanup-image.sh",
      "sudo /home/${var.username}/cleanup-user.sh \"${var.username}\"",

      "rm -f /tmp/cleanup-image.sh",
      "rm -f /home/${var.username}/cleanup-user.sh",
    ]
  }

  provisioner "shell" {
    execute_command = "echo '${var.password}' | sudo -S bash -x {{ .Path }}"
    inline = [
      "userdel -fr ${var.username} || true"
    ]
    expect_disconnect = true
  }

  post-processor "shell-local" {
    inline = [
      "set -eux",
      "mv ${var.output_directory}/packer-debian-cloud ${local.image_path}",
      "sha512sum ${local.image_path} > ${local.checksum_path}",
      "qemu-img info ${local.image_path}",
      "${var.minio_client} mb --ignore-existing ${var.minio_publish_path}",
      "${var.minio_client} anonymous -r set download ${var.minio_publish_path}",
      "${var.minio_client} cp ${local.image_path} ${var.minio_publish_path}/",
      "${var.minio_client} cp ${local.checksum_path} ${var.minio_publish_path}/",
    ]
  }
}
