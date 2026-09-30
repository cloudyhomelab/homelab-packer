variable "image_name" { type = string }
variable "os" { type = string }
variable "playbook_file" { type = string }
variable "disk_size" { type = string }
variable "memory" { type = number }
variable "cpus" { type = number }
variable "accelerator" { type = string }

variable "parent_name" { type = string }
variable "parent_url" { type = string }
variable "parent_checksum" { type = string }

variable "build_version" { type = string }
variable "build_timestamp" { type = string }
variable "check_hash" { type = string }
variable "git_remote" { type = string }
variable "git_commit" { type = string }

variable "username" { type = string }
variable "password" {
  type      = string
  sensitive = true
}

variable "output_directory" { type = string }

variable "ssh_user_ca_public_key_file" { type = string }
variable "ssh_private_key_file" { type = string }
variable "ssh_certificate_file" { type = string }
