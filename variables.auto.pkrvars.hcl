username = "packer"
password = "packer"

accelerator = "none"

output_directory            = "build"
image_name                  = "debian-custom-trixie"
image_format                = "qcow2"
debian_cloud_image_url      = "https://cloud.debian.org/images/cloud/trixie/20251117-2299/debian-13-genericcloud-amd64-20251117-2299.qcow2"
debian_cloud_image_checksum = "sha512:e5563c7bb388eebf7df385e99ee36c83cd16ba8fad4bd07f4c3fd725a6f1cf1cb9f54c6673d4274a856974327a5007a69ff24d44f9b21f7f920e1938a19edf7e"

minio_client       = "mcli"
minio_publish_path = "minio/os-image/debian"
