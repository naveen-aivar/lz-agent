output "landing_zone_arn" {
  value = aws_controltower_landing_zone.this.arn
}

output "custom_ou_ids" {
  value = { for k, v in aws_organizations_organizational_unit.custom : k => v.id }
}
