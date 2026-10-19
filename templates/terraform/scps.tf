# Policy documents live in policies/<id>.json (generated from the approved scope).
resource "aws_organizations_policy" "scp" {
  for_each = var.scps
  name     = "${var.org_name}-${each.key}"
  type     = "SERVICE_CONTROL_POLICY"
  content  = file("${path.module}/policies/${each.key}.json")
}

locals {
  scp_attachments = merge({}, [
    for id, s in var.scps : { for t in s.targets : "${id}:${t}" => { policy = id, target = t } }
  ]...)
}

resource "aws_organizations_policy_attachment" "scp" {
  for_each  = local.scp_attachments
  policy_id = aws_organizations_policy.scp[each.value.policy].id
  target_id = local.target_ids[each.value.target]
}
