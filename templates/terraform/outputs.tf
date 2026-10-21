output "landing_zone_arn" {
  value = aws_controltower_landing_zone.this.arn
}

output "ou_ids" {
  value = local.ou_ids
}

output "account_ids" {
  description = "Account ids of everything this configuration created."
  value = merge(
    { for k, v in aws_organizations_account.shared : k => v.id },
    { for k, v in aws_organizations_account.member : k => v.id },
  )
}
