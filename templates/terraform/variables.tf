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

variable "accounts" {
  type = map(object({
    ou    = string # OU the account is placed in ("Security" for Log Archive and Audit)
    kind  = string # log-archive | audit | workload | other
    email = string # the root email for the new account; must never have been used for another AWS account
  }))
  default     = {}
  description = "Accounts this configuration creates with AWS Organizations. The management account is not listed."
  validation {
    condition     = alltrue([for k, a in var.accounts : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", a.email))])
    error_message = "Every account needs a valid, unique root email in terraform.tfvars (accounts = { \"<name>\" = { email = \"...\" } })."
  }
}

variable "log_archive_account_id" {
  type        = string
  default     = ""
  description = "Optional. Set only if the Log Archive account already exists, and it is already in the Security OU. Leave empty to create it from its email."
  validation {
    condition     = var.log_archive_account_id == "" || can(regex("^[0-9]{12}$", var.log_archive_account_id))
    error_message = "log_archive_account_id must be empty or a 12-digit account id."
  }
}

variable "audit_account_id" {
  type        = string
  default     = ""
  description = "Optional. Set only if the Audit account already exists, and it is already in the Security OU. Leave empty to create it from its email."
  validation {
    condition     = var.audit_account_id == "" || can(regex("^[0-9]{12}$", var.audit_account_id))
    error_message = "audit_account_id must be empty or a 12-digit account id."
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
  default = "4.0"
}

variable "control_tower_baseline_arn" {
  type        = string
  default     = ""
  description = "ARN of the AWSControlTowerBaseline. Empty uses the documented identifier for home_region. Confirm with: aws controltower list-baselines"
}

variable "control_tower_baseline_version" {
  type        = string
  default     = "4.0"
  description = "Version of the AWSControlTowerBaseline used to register OUs. Confirm with: aws controltower list-baselines"
}

variable "identity_center_enabled_baseline_arn" {
  type        = string
  default     = ""
  description = "Set this AFTER the first apply (see README, step 2). Registering OUs, enabling controls need it; while it is empty they are skipped."
}

variable "ous" {
  type = map(object({
    parent = optional(string, "root") # name of a top-level OU in this map; "root" = directly under the organization root
  }))
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
