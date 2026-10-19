variable "org_name" {
  type = string
}

variable "home_region" {
  type = string
}

variable "governed_regions" {
  type = list(string)
}

# tflint-ignore: terraform_unused_declarations
variable "allowed_regions" {
  type        = list(string)
  description = "Informational here; the region-deny SCP policy file already embeds this list."
}

variable "log_archive_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.log_archive_account_id))
    error_message = "log_archive_account_id must be a 12-digit account id (Control Tower API launch needs an existing account)."
  }
}

variable "audit_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.audit_account_id))
    error_message = "audit_account_id must be a 12-digit account id (Control Tower API launch needs an existing account)."
  }
}

variable "log_retention_days" {
  type = number
}

variable "access_log_retention_days" {
  type = number
}

variable "kms_key_arn" {
  type        = string
  default     = ""
  description = "Optional customer-managed key for Control Tower. Its key policy must allow Control Tower, CloudTrail and Config."
}

variable "landing_zone_version" {
  type    = string
  default = "3.3"
}

variable "ous" {
  type    = map(object({}))
  default = {}
}

variable "scps" {
  type = map(object({
    targets = list(string)
  }))
  default = {}
}

variable "controls" {
  type = map(object({
    targets = list(string)
  }))
  default = {}
}
