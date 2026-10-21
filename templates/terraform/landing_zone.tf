# Landing zone version 4.0 manifest. Every service integration needs an explicit "enabled" flag, and an integration that is
# enabled needs the account id of its central account. organizationStructure no longer exists in 4.0 (see organizations.tf).
resource "aws_controltower_landing_zone" "this" {
  version = var.landing_zone_version

  # Accounts moved or created into a registered OU are enrolled automatically.
  remediation_types = ["INHERITANCE_DRIFT"]

  manifest_json = jsonencode({
    governedRegions  = var.governed_regions
    accessManagement = { enabled = true }
    backup           = { enabled = false }
    centralizedLogging = {
      enabled   = true
      accountId = local.log_archive_account_id
      configurations = merge(
        {
          loggingBucket       = { retentionDays = var.log_retention_days }
          accessLoggingBucket = { retentionDays = var.access_log_retention_days }
        },
        var.kms_key_arn == "" ? {} : { kmsKeyArn = var.kms_key_arn }
      )
    }
    securityRoles = {
      enabled   = true
      accountId = local.audit_account_id
    }
    config = {
      enabled   = true
      accountId = local.audit_account_id
      configurations = merge(
        {
          loggingBucket       = { retentionDays = var.log_retention_days }
          accessLoggingBucket = { retentionDays = var.access_log_retention_days }
        },
        var.kms_key_arn == "" ? {} : { kmsKeyArn = var.kms_key_arn }
      )
    }
  })

  depends_on = [
    aws_iam_role.ct_admin,
    aws_iam_role_policy.ct_admin,
    aws_iam_role_policy_attachment.ct_admin,
    aws_iam_role_policy.ct_cloudtrail,
    aws_iam_role_policy.ct_stackset,
    aws_organizations_account.shared,
  ]
}
