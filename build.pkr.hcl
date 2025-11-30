build {
  name    = "debian-custom-qcow2"
  sources = ["source.qemu.debian-cloud"]

  provisioner "shell" {
    inline = [
      "set -eux",
      "cloud-init status --wait",
    ]
  }

  provisioner "shell" {
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
    ]
    inline = [
      "set -eux",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y curl vim htop qemu-guest-agent",
    ]
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

  post-processor "shell-local" {
    inline = [
      "set -eux",
      "mv ${var.output_directory}/packer-debian-cloud ${var.output_directory}/${var.image_name}.qcow2",
      "qemu-img info ${var.output_directory}/${var.image_name}.qcow2",
    ]
  }
}
