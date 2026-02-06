locals {
  build_stamp         = formatdate("YYYYMMDD-hhmm", timestamp())
  ansible_repo        = "https://github.com/binarycodes/homelab-self-provisioner.git"
  ansible_repo_path   = "${path.root}/tmp_ansible_checkout"
  ansible_repo_branch = "main"

  vm_name       = "${var.image_name}-${local.build_stamp}.${var.image_format}"
  image_path    = "${var.output_directory}/${local.vm_name}"
  checksum_path = "${var.output_directory}/${local.vm_name}.sha512"
  manifest_path = "${var.output_directory}/packer-manifest.json"

  user_data = templatefile("${path.root}/cloud-init/user-data.pkrtpl.yml", {
    build_username = var.username
    build_password = var.password
  })
}
