data "aws_organizations_organization" "this" {}

locals {
  root_id = data.aws_organizations_organization.this.roots[0].id
  org_id  = data.aws_organizations_organization.this.id
  mgmt_id = data.aws_organizations_organization.this.master_account_id
}

# OUs created by Control Tower (Security, Sandbox) only exist after the landing zone is applied.
data "aws_organizations_organizational_units" "root" {
  parent_id  = local.root_id
  depends_on = [aws_controltower_landing_zone.this]
}

resource "aws_organizations_organizational_unit" "custom" {
  for_each   = { for k, v in var.ous : k => v if v.parent == "root" }
  name       = each.key
  parent_id  = local.root_id
  depends_on = [aws_controltower_landing_zone.this]
}

# One level of nesting: a child's parent is always a top-level OU from the resource above.
resource "aws_organizations_organizational_unit" "custom_child" {
  for_each  = { for k, v in var.ous : k => v if v.parent != "root" }
  name      = each.key
  parent_id = aws_organizations_organizational_unit.custom[each.value.parent].id
}

locals {
  ct_ou_ids = { for ou in data.aws_organizations_organizational_units.root.children : ou.name => ou.id }
  ou_ids = merge(
    local.ct_ou_ids,
    { for k, v in aws_organizations_organizational_unit.custom : k => v.id },
    { for k, v in aws_organizations_organizational_unit.custom_child : k => v.id },
  )
  target_ids = merge({ root = local.root_id }, local.ou_ids)
}
