source "qemu" "image" {
  vm_name          = local.vm_name
  disk_image       = true
  iso_url          = var.parent_url
  iso_checksum     = var.parent_checksum
  use_backing_file = false

  format      = "qcow2"
  disk_size   = var.disk_size
  memory      = var.memory
  cpus        = var.cpus
  accelerator = var.accelerator
  headless    = true

  cd_files = [
    "${local.os_dir}/cloud-init/meta-data",
    "${local.os_dir}/cloud-init/network-config",
  ]
  cd_content = {
    "user-data" = local.user_data
  }
  cd_label = "cidata"

  ssh_username              = var.username
  ssh_private_key_file      = var.ssh_private_key_file
  ssh_certificate_file      = var.ssh_certificate_file
  ssh_clear_authorized_keys = true
  ssh_timeout               = "10m"

  qemuargs = [
    ["-serial", "mon:stdio"]
  ]

  output_directory = var.output_directory
}
