username = "packeruser"
password = "packerpassword"

accelerator = "none"

output_directory            = "build"
image_name                  = "debian-trixie-packer"
image_format                = "qcow2"
debian_cloud_image_url      = "https://cloud.debian.org/images/cloud/trixie/20260112-2355/debian-13-genericcloud-amd64-20260112-2355.qcow2"
debian_cloud_image_checksum = "sha512:7d735e0314850bc7e452eebb86448839b52082f6be525b914f4beb45421ae1505e251b4ead0672ed7855c6420bdd0dbb862265327dc2a4ad2f2ab6df398aa9ac"

minio_client       = "mcli"
minio_publish_path = "minio/os-image/debian"
