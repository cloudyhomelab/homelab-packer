variable "username" {
  type      = string
  sensitive = true
}

variable "password" {
  type      = string
  sensitive = true
}

variable "accelerator" {
  type = string
}

variable "source_cloud_image_url" {
  type = string
}

variable "source_cloud_image_checksum" {
  type = string
}

variable "disk_size" {
  type = string
}

variable "playbook_name" {
  type = string
}

variable "image_name" {
  type = string
}

variable "image_format" {
  type = string
}

variable "output_directory" {
  type = string
}

variable "minio_client" {
  type = string
}

variable "minio_publish_path" {
  type = string
}

variable "git_commit_ref" {
  type = string
}

variable "ansible_repo_path" {
  type = string
}

variable "ssh_user_ca_file" { type = string }
variable "ssh_private_key_file" { type = string }
variable "ssh_certificate_file" { type = string }
