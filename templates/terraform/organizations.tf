data "aws_organizations_organization" "this" {}

locals {
  root_id = data.aws_organizations_organization.this.roots[0].id
  org_id  = data.aws_organizations_organization.this.id
  mgmt_id = data.aws_organizations_organization.this.master_account_id
}

# Landing zone 4.0 does not create OUs. The Security OU (directly under the root) must exist, and hold the Log Archive and
# Audit accounts, before the landing zone is created.
resource "aws_organizations_organizational_unit" "security" {
  name      = "Security"
  parent_id = local.root_id
}

resource "aws_organizations_organizational_unit" "custom" {
  for_each  = { for k, v in var.ous : k => v if v.parent == "root" }
  name      = each.key
  parent_id = local.root_id
}

# One level of nesting: a child's parent is always a top-level OU from the resource above.
resource "aws_organizations_organizational_unit" "custom_child" {
  for_each  = { for k, v in var.ous : k => v if v.parent != "root" }
  name      = each.key
  parent_id = aws_organizations_organizational_unit.custom[each.value.parent].id
}

locals {
  ou_ids = merge(
    { Security = aws_organizations_organizational_unit.security.id },
    { for k, v in aws_organizations_organizational_unit.custom : k => v.id },
    { for k, v in aws_organizations_organizational_unit.custom_child : k => v.id },
  )
  ou_arns = merge(
    { for k, v in aws_organizations_organizational_unit.custom : k => v.arn },
    { for k, v in aws_organizations_organizational_unit.custom_child : k => v.arn },
  )
  target_ids = merge({ root = local.root_id }, local.ou_ids)

  # Stage 2: registering OUs with Control Tower and enabling controls need the Identity Center enabled baseline arn,
  # which only exists after the landing zone is created.
  governance_ready = var.identity_center_enabled_baseline_arn != ""
  ct_baseline_arn  = var.control_tower_baseline_arn != "" ? var.control_tower_baseline_arn : "arn:${data.aws_partition.current.partition}:controltower:${var.home_region}::baseline/17BSJV3IGJ2QSGA2"
}

# An OU must be registered (AWSControlTowerBaseline enabled on it) before controls can be enabled on it, and before its
# accounts are governed. The Security OU holds the service-integration accounts and is set up by the landing zone itself.
resource "aws_controltower_baseline" "ou" {
  for_each            = local.governance_ready ? local.ou_arns : {}
  baseline_identifier = local.ct_baseline_arn
  baseline_version    = var.control_tower_baseline_version
  target_identifier   = each.value

  parameters {
    key   = "IdentityCenterEnabledBaselineArn"
    value = var.identity_center_enabled_baseline_arn
  }

  depends_on = [aws_controltower_landing_zone.this]
}
