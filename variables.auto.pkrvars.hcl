username = "packer"
password = "packer"

accelerator = "none"

output_directory            = "build"
image_name                  = "debian-custom-trixie"
image_format                = "qcow2"
debian_cloud_image_url      = "https://cdimage.debian.org/images/cloud/trixie/20251117-2299/debian-13-generic-amd64-20251117-2299.qcow2"
debian_cloud_image_checksum = "sha512:1882f2d0debfb52254db1b0fc850d222fa68470a644a914d181f744ac1511a6caa1835368362db6dee88504a13c726b3ee9de0e43648353f62e90e075f497026"

minio_client       = "mcli"
minio_publish_path = "minio/os-image/debian"
