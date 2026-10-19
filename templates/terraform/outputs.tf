output "landing_zone_arn" {
  value = aws_controltower_landing_zone.this.arn
}

output "custom_ou_ids" {
  value = merge(
    { for k, v in aws_organizations_organizational_unit.custom : k => v.id },
    { for k, v in aws_organizations_organizational_unit.custom_child : k => v.id },
  )
}
