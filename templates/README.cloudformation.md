# {{ORG}}: Control Tower landing zone (CloudFormation)

Generated from an approved scope. The file layout is identical for every customer. `02-governance.yaml`, the parameter files and
`custom-scps/` are the customer-specific parts. `docs/SCOPE.md` lists what was taken from the SOW and what was not codified, and
`docs/ORG-STRUCTURE.md` draws the organization these stacks create.

## Layout
| File | Purpose |
|---|---|
| `00-prerequisites.yaml` | Security OU, Log Archive and Audit accounts (from emails), Control Tower service roles |
| `01-landing-zone.yaml` | The landing zone, version 4.0 manifest |
| `02-governance.yaml` | Your OUs, OU registration with Control Tower, SCPs, controls and workload accounts (generated) |
| `parameters/00-prerequisites.json`, `01-landing-zone.json`, `02-governance.json` | Parameter values |
| `custom-scps/` | AI-generated SCPs for **review**. Not deployed by these stacks, see its README |
| `reports/` | Validation and security scan reports for these exact templates |
| `docs/` | `SCOPE.md`, `ORG-STRUCTURE.md`, `scope.json` |

## Before you deploy
1. Use credentials for the Organizations **management account**, in `{{HOME}}`.
2. An AWS Organization must exist with all features enabled, and no Control Tower landing zone yet:
   `aws organizations list-roots --query 'Roots[0].Id' --output text` gives the root id for the first parameter file.
3. **Fill in the emails**: `LogArchiveAccountEmail` and `AuditAccountEmail` in `parameters/00-prerequisites.json`, and one `Email...`
   parameter per workload account in `parameters/02-governance.json`. Each email must be unique and must never have been used for
   another AWS account. CloudFormation creates these accounts. If the Log Archive or Audit account already exists and is already in
   a Security OU directly under the root, give its id (`LogArchiveAccountId` / `AuditAccountId`) instead of an email.
4. Review `docs/SCOPE.md` and `reports/SUMMARY.md`.

## Deploy, in order
```
aws cloudformation create-stack --stack-name {{SLUG}}-ct-prereq --template-body file://00-prerequisites.yaml \
  --parameters file://parameters/00-prerequisites.json --capabilities CAPABILITY_NAMED_IAM
aws cloudformation wait stack-create-complete --stack-name {{SLUG}}-ct-prereq
aws cloudformation describe-stacks --stack-name {{SLUG}}-ct-prereq --query 'Stacks[0].Outputs'
```
Copy `LogArchiveAccountId` and `AuditAccountId` into `parameters/01-landing-zone.json` and `SecurityOuId` into `parameters/02-governance.json`, then:
```
aws cloudformation create-stack --stack-name {{SLUG}}-ct-landing-zone --template-body file://01-landing-zone.yaml --parameters file://parameters/01-landing-zone.json
aws cloudformation wait stack-create-complete --stack-name {{SLUG}}-ct-landing-zone
```
Creating the landing zone takes a long time. When it is `ACTIVE`, fill the remaining values in `parameters/02-governance.json`:
```
aws organizations describe-organization --query 'Organization.Id' --output text                 # OrganizationId
aws organizations list-roots --query 'Roots[0].Id' --output text                                # OrganizationRootId
IC=$(aws controltower list-baselines --query 'baselines[?name==`IdentityCenterBaseline`].arn' --output text)
aws controltower list-enabled-baselines --query "enabledBaselines[?baselineIdentifier=='$IC'].arn" --output text   # IdentityCenterEnabledBaselineArn
aws controltower list-baselines --query 'baselines[?name==`AWSControlTowerBaseline`].[arn]' --output text           # confirm ControlTowerBaselineArn / version
```
```
aws cloudformation create-stack --stack-name {{SLUG}}-ct-governance --template-body file://02-governance.yaml --parameters file://parameters/02-governance.json
```

## Notes
- `02-governance.yaml` registers your OUs with Control Tower (an `EnabledBaseline` per OU, required before controls can be enabled
  on them), then enables the controls, then creates the workload accounts. They are chained with `DependsOn` because Control Tower
  runs one operation at a time.
- Accounts have `DeletionPolicy: Retain`: closing an AWS account takes up to 90 days, so deleting a stack never deletes accounts.
- The region-deny SCP exempts global services and the Control Tower execution roles. It is a custom SCP, not the Control Tower
  Region deny control, which cannot be enabled through the controls API.
- The Security OU is the foundational OU. The landing zone sets it up; check in the Control Tower console that it shows as registered.
- Verified against the AWS documentation: the 4.0 manifest and its required fields, the prerequisites, `EnabledBaseline`, `LandingZone`
  and `Account` properties. **Not verified by a deploy:** the templates pass `cfn-lint` and the scans but have never been deployed to a real
  organization. Review the change set before you execute it.
