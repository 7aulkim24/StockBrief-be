variable "name_prefix" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_instance_class" {
  type = string
}

variable "allocated_storage_gb" {
  type = number
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "secret_arn" {
  type      = string
  sensitive = true
}

variable "log_group_name" {
  type = string
}

variable "deletion_protection" {
  description = "Protect the RDS instance from accidental deletion. Set false for dev to allow teardown."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot on deletion. Set true for dev to avoid leftover snapshots."
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Number of days to retain automated backups. Use 0 to disable automated backups in dev/test; valid range is 0 to 35."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_period >= 0 && var.backup_retention_period <= 35
    error_message = "backup_retention_period must be between 0 and 35 days. Use 0 only when disabling automated backups is approved for dev/test."
  }
}
