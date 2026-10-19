# Enabling many controls in parallel can hit Control Tower conflicts; apply with: terraform apply -parallelism=1
locals {
  control_attachments = merge({}, [
    for id, c in var.controls : { for t in c.targets : "${id}:${t}" => { control = id, target = t } }
  ]...)
}

resource "aws_controltower_control" "this" {
  for_each           = local.control_attachments
  control_identifier = "arn:${data.aws_partition.current.partition}:controltower:${var.home_region}::control/${each.value.control}"
  target_identifier  = "arn:${data.aws_partition.current.partition}:organizations::${local.mgmt_id}:ou/${local.org_id}/${local.ou_ids[each.value.target]}"
}
