# Accounts are created with AWS Organizations from the emails in terraform.tfvars. Control Tower governs them once their OU
# is registered (auto-enrollment is on: see remediation_types in landing_zone.tf).
locals {
  shared_kinds    = ["log-archive", "audit"]
  shared_accounts = { for k, a in var.accounts : k => a if contains(local.shared_kinds, a.kind) }
  member_accounts = { for k, a in var.accounts : k => a if !contains(local.shared_kinds, a.kind) }
}

# Log Archive and Audit, created in the Security OU before the landing zone (landing zone API requirement).
resource "aws_organizations_account" "shared" {
  for_each = {
    for k, a in local.shared_accounts : k => a
    if !((a.kind == "log-archive" && var.log_archive_account_id != "") || (a.kind == "audit" && var.audit_account_id != ""))
  }
  name      = each.key
  email     = each.value.email
  parent_id = aws_organizations_organizational_unit.security.id

  lifecycle {
    prevent_destroy = true # AWS accounts cannot be recreated cheaply; closing one takes up to 90 days
    ignore_changes  = [role_name, iam_user_access_to_billing]
  }
}

locals {
  log_archive_account_id = var.log_archive_account_id != "" ? var.log_archive_account_id : one([for k, a in aws_organizations_account.shared : a.id if local.shared_accounts[k].kind == "log-archive"])
  audit_account_id       = var.audit_account_id != "" ? var.audit_account_id : one([for k, a in aws_organizations_account.shared : a.id if local.shared_accounts[k].kind == "audit"])
}

# Workload and other accounts named in the SOW, placed in their OU.
resource "aws_organizations_account" "member" {
  for_each  = local.member_accounts
  name      = each.key
  email     = each.value.email
  parent_id = local.ou_ids[each.value.ou]

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [role_name, iam_user_access_to_billing]
  }
}
