source "qemu" "debian-cloud" {
  disk_image       = true
  iso_url          = var.debian_cloud_image_url
  iso_checksum     = var.debian_cloud_image_checksum
  use_backing_file = false

  format      = var.image_format
  disk_size   = "3G"
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

  ssh_username = var.username
  ssh_password = var.password
  ssh_timeout  = "10m"

  qemuargs = [
    ["-serial", "mon:stdio"]
  ]

  output_directory = var.output_directory
}
