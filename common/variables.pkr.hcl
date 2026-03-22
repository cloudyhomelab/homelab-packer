variable "username" {
  type      = string
  sensitive = true
}

variable "password" {
  type      = string
  sensitive = true
}

variable "accelerator" { type = string }
variable "disk_size" { type = string }

variable "source_cloud_image_url" { type = string }
variable "source_cloud_image_checksum" { type = string }

variable "image_name" { type = string }
variable "image_format" { type = string }

variable "ansible_repo_path" { type = string }
variable "playbook_name" { type = string }

variable "output_directory" { type = string }


variable "s3_user" {
  type      = string
  sensitive = true
  default   = "<REDACTED>"
}
variable "s3_endpoint" { type = string }
variable "s3_aws_sigv4" { type = string }
variable "s3_bucket_name" { type = string }
variable "s3_prefix" { type = string }

variable "git_remote_url" { type = string }
variable "git_commit_ref" { type = string }

variable "ssh_user_ca_file" { type = string }
variable "ssh_private_key_file" { type = string }
variable "ssh_certificate_file" { type = string }
