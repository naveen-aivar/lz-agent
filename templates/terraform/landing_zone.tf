resource "aws_controltower_landing_zone" "this" {
  version = var.landing_zone_version
  manifest_json = jsonencode({
    governedRegions       = var.governed_regions
    organizationStructure = { security = { name = "Security" }, sandbox = { name = "Sandbox" } }
    centralizedLogging = {
      accountId = var.log_archive_account_id
      configurations = merge(
        {
          loggingBucket       = { retentionDays = var.log_retention_days }
          accessLoggingBucket = { retentionDays = var.access_log_retention_days }
        },
        var.kms_key_arn == "" ? {} : { kmsKeyArn = var.kms_key_arn }
      )
      enabled = true
    }
    securityRoles    = { accountId = var.audit_account_id }
    accessManagement = { enabled = true }
  })

  depends_on = [
    aws_iam_role_policy.ct_admin,
    aws_iam_role_policy_attachment.ct_admin,
    aws_iam_role_policy.ct_cloudtrail,
    aws_iam_role_policy.ct_stackset,
    aws_iam_role_policy_attachment.ct_config_aggregator,
  ]
}
