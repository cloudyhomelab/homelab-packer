locals {
  build_version   = formatdate("YYYYMMDD-hhmm", timestamp())
  build_timestamp = formatdate("YYYY-MM-DD hh:mm:ss ZZZZ", timestamp())

  ansible_repo        = "https://github.com/binarycodes/homelab-self-provisioner.git"
  ansible_repo_path   = "${path.root}/tmp_ansible_checkout"
  ansible_repo_branch = "main"

  vm_name       = "${var.image_name}-${local.build_version}.${var.image_format}"
  image_path    = "${var.output_directory}/${local.vm_name}"
  checksum_path = "${var.output_directory}/${local.vm_name}.sha512"
  metadata_path = "${var.output_directory}/metadata.json"

  latest_vm_name       = "${var.image_name}-latest.${var.image_format}"
  latest_image_path    = "${var.output_directory}/${local.latest_vm_name}"
  latest_checksum_path = "${var.output_directory}/${local.latest_vm_name}.sha512"

  manifest_path             = "${var.output_directory}/packer-manifest.json"
  latest_minio_publish_path = "${var.minio_publish_path}/latest"

  user_data = templatefile("${path.root}/cloud-init/user-data.pkrtpl.yml", {
    build_username = var.username
    build_password = var.password
  })
}
