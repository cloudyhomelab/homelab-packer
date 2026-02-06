username = "packeruser"
password = "packerpassword"

accelerator = "none"

output_directory            = "build"
image_name                  = "debian-trixie-packer"
image_format                = "qcow2"
debian_cloud_image_url      = "https://cloud.debian.org/images/cloud/trixie/20260129-2372/debian-13-genericcloud-amd64-20260129-2372.qcow2"
debian_cloud_image_checksum = "sha512:a70acbedb0dc691ab77c57f3f775de435afe1d3b063dfafbdf194661a8d65543ebaa32128f4362a9a2c7be065bd9e48944f83dd3583e9765d3ab1ee06965552e"

minio_client       = "mcli"
minio_publish_path = "minio/os-image/debian"
