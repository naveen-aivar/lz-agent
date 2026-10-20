# {{ORG}}: Control Tower landing zone (Terraform)

Generated from an approved scope. File layout is identical for every customer; only `terraform.tfvars`
and `policies/` change. See `docs/SCOPE.md` for exactly what was extracted from the SOW and what was not codified.

## Layout
| File | Purpose |
|---|---|
| `versions.tf`, `providers.tf` | Terraform and provider pins; provider uses `home_region` |
| `variables.tf` | Input schema (validates account ids) |
| `prerequisites.tf` | Control Tower service roles |
| `landing_zone.tf` | The Control Tower landing zone |
| `organizations.tf` | Organization lookups and custom OUs |
| `scps.tf` | Service control policies from `policies/*.json` and their attachments |
| `controls.tf` | Control Tower controls enabled on OUs |
| `terraform.tfvars` | All customer-specific values |
| `policies/` | One JSON file per catalog SCP. These are the policies the stack attaches |
| `custom-scps/` | Model-authored SCPs. This stack does not attach them |
| `session/` | Agent session history for this run |
| `scans/` | Code-scan reports (`summary.json` and the tool logs) |
| `docs/` | `SCOPE.md`, `ORG-STRUCTURE.md`, `scope.json` |

## Before you apply
1. Use credentials for the Organizations **management account**, in `{{HOME}}`.
2. An AWS Organization must exist, with no existing Control Tower landing zone.
3. The Log Archive and Audit accounts must already exist; set their ids in `terraform.tfvars` if blank.
4. Add a remote backend (`backend "s3"` block) if you do not want local state.
5. Review `docs/SCOPE.md` (open questions, unsupported requirements, and any model-authored SCPs in `custom-scps/`).

## Apply
```
terraform init
terraform plan -out=lz.plan
terraform apply -parallelism=1 lz.plan
```
`-parallelism=1` avoids Control Tower conflicts when many controls are enabled.

## Notes
- The region-deny SCP exempts global services and the Control Tower execution roles.
- Landing zone version, control ids and the manifest shape were written without checking the current Control Tower docs. Run `terraform plan` and read it before applying.
