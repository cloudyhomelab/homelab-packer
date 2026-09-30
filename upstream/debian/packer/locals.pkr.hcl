locals {
  # packer resolves relative paths in file functions against the template dir, so anchor them
  os_dir    = abspath("${path.root}/..")
  repo_root = abspath("${path.root}/../../..")

  vm_name = "${var.image_name}-${var.build_version}.qcow2"

  user_data = templatefile("${local.os_dir}/cloud-init/user-data.pkrtpl.yml", {
    build_username     = var.username
    build_password     = var.password
    ca_user_public_key = trimspace(file(var.ssh_user_ca_public_key_file))
  })
}
