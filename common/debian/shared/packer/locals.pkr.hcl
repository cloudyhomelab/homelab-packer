locals {
  build_version   = formatdate("YYYYMMDD-hhmm", timestamp())
  build_timestamp = formatdate("YYYY-MM-DD hh:mm:ss ZZZZ", timestamp())

  ssh_user_ca_public_key = file("${var.ssh_user_ca_file}.pub")

  vm_name       = "${var.image_name}-${local.build_version}.${var.image_format}"
  image_path    = "${var.output_directory}/${local.vm_name}"
  checksum_path = "${var.output_directory}/${local.vm_name}.sha512"

  image_metadata_name = "metadata.json"
  all_metadata_name   = "metadata_all.json"

  user_data = templatefile("${path.root}/cloud-init/user-data.pkrtpl.yml", {
    build_username     = var.username
    build_password     = var.password
    ca_user_public_key = local.ssh_user_ca_public_key
  })
}
