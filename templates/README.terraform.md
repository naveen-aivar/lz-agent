# {{ORG}}: Control Tower landing zone (Terraform)

Generated from an approved scope. The file layout is identical for every customer; only `terraform.tfvars`, `policies/` and
`custom-scps/` change. `docs/SCOPE.md` lists exactly what was taken from the SOW and what was not codified, and
`docs/ORG-STRUCTURE.md` draws the organization this configuration creates.

## Layout
| File | Purpose |
|---|---|
| `versions.tf`, `providers.tf` | Terraform and provider pins; the provider uses `home_region` |
| `variables.tf` | Input schema. `accounts` validates that every account has an email |
| `prerequisites.tf` | The Control Tower service roles |
| `organizations.tf` | The Security OU, your other OUs, and registration of the OUs with Control Tower |
| `accounts.tf` | Log Archive and Audit (before the landing zone) and your workload accounts |
| `landing_zone.tf` | The landing zone, version 4.0 manifest |
| `scps.tf` | Service control policies from `policies/*.json`, and their attachments |
| `controls.tf` | Control Tower controls enabled on the OUs |
| `terraform.tfvars` | All customer-specific values |
| `policies/` | One JSON file per catalog SCP (applied by `scps.tf`) |
| `custom-scps/` | AI-generated SCPs for **review**. Not applied by this configuration, see its README |
| `reports/` | Validation and security scan reports for this exact configuration |
| `docs/` | `SCOPE.md`, `ORG-STRUCTURE.md`, `scope.json` |

## Before you apply
1. Use credentials for the Organizations **management account**, in `{{HOME}}`.
2. An AWS Organization must exist (`aws organizations describe-organization`), with all features enabled, and no Control Tower landing zone yet.
3. **Fill in the email for every account** in `terraform.tfvars` (`accounts = { ... email = "" }`). Each email must be unique and must
   never have been used for another AWS account. `terraform plan` refuses an empty email. Terraform creates these accounts.
   If the Log Archive or Audit account already exists and is already in a Security OU directly under the root, leave it out of
   `accounts` and set `log_archive_account_id` / `audit_account_id` instead.
4. Add a remote backend (`backend "s3"` block) if you do not want local state.
5. Review `docs/SCOPE.md` (open questions, unsupported requirements) and `reports/SUMMARY.md` (scan results).
6. Optional pre-flight: confirm the control ids in `terraform.tfvars` exist: `aws controlcatalog list-controls` (or the console).
   Detective control ids could not be verified against the AWS documentation when this was generated.

## Apply, in two stages
Landing zone 4.0 needs the Security OU and the two shared accounts first, and OUs must be registered with Control Tower before
controls can be enabled on them. The Identity Center baseline that registration needs only exists after the landing zone does.

**Stage 1.** Creates the roles, Security OU, shared accounts, landing zone (this step takes a long time), your OUs, SCPs and accounts:
```
terraform init
terraform plan -out=lz.plan
terraform apply -parallelism=1 lz.plan
```
**Stage 2.** After the landing zone is `ACTIVE`, find the enabled Identity Center baseline and set it in `terraform.tfvars`:
```
IC=$(aws controltower list-baselines --query 'baselines[?name==`IdentityCenterBaseline`].arn' --output text)
aws controltower list-enabled-baselines --query "enabledBaselines[?baselineIdentifier=='$IC'].arn" --output text
aws controltower list-baselines --query 'baselines[?name==`AWSControlTowerBaseline`].[arn]' --output text   # confirm the default arn / version
```
Set `identity_center_enabled_baseline_arn = "<the enabled baseline arn>"` (and `control_tower_baseline_arn` / `control_tower_baseline_version`
if they differ from the defaults), then:
```
terraform apply -parallelism=1
```
This registers your OUs with Control Tower, which enrolls the accounts in them, and enables the controls. `-parallelism=1` avoids
Control Tower conflicts.

## Notes
- AWS accounts cannot be deleted cheaply (closing one takes up to 90 days), so the account resources have `prevent_destroy`.
- The region-deny SCP exempts global services and the Control Tower execution roles. It is a custom SCP, not the Control Tower
  Region deny control, which cannot be enabled through the controls API.
- The Security OU is the foundational OU. The landing zone sets it up; check in the Control Tower console that it shows as registered.
- Verified against the AWS documentation: the 4.0 manifest and its required fields, the prerequisites, the baseline and account
  resources. **Not verified by an apply:** the whole flow has been validated (`terraform validate`, lint, scans) but never applied to a real
  organization. Run `terraform plan` and read it before applying.
