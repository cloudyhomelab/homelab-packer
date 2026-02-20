source "qemu" "debian-cloud" {
  vm_name          = local.vm_name
  disk_image       = true
  iso_url          = var.source_cloud_image_url
  iso_checksum     = var.source_cloud_image_checksum
  use_backing_file = false

  format      = var.image_format
  disk_size   = var.disk_size
  accelerator = var.accelerator
  headless    = true

  cd_files = [
    "cloud-init/meta-data",
    "cloud-init/network-config",
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
