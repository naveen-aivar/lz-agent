# {{ORG}}: Control Tower landing zone (CloudFormation)

Generated from an approved scope. File layout is identical for every customer. `02-governance.yaml` and the
parameter files are the only customer-specific files. See `docs/SCOPE.md` for what was extracted from the SOW and
what was not codified.

## Layout
| File | Purpose |
|---|---|
| `00-prerequisites.yaml` | Control Tower service roles |
| `01-landing-zone.yaml` | The Control Tower landing zone |
| `02-governance.yaml` | Custom OUs, SCPs and controls (generated) |
| `parameters/01-landing-zone.json`, `parameters/02-governance.json` | Parameter values |
| `custom-scps/` | Model-authored SCPs. This stack does not attach them |
| `session/` | Agent session history for this run |
| `scans/` | Code-scan reports (`summary.json` and the tool logs) |
| `docs/` | `SCOPE.md`, `ORG-STRUCTURE.md`, `scope.json` |

## Before you deploy
1. Use credentials for the Organizations **management account**, in `{{HOME}}`.
2. An AWS Organization must exist, with no existing Control Tower landing zone.
3. The Log Archive and Audit accounts must already exist; fill their ids in `parameters/01-landing-zone.json` if blank.

## Deploy, in order
```
aws cloudformation create-stack --stack-name {{SLUG}}-ct-prereq --template-body file://00-prerequisites.yaml --capabilities CAPABILITY_NAMED_IAM
aws cloudformation wait stack-create-complete --stack-name {{SLUG}}-ct-prereq

aws cloudformation create-stack --stack-name {{SLUG}}-ct-landing-zone --template-body file://01-landing-zone.yaml --parameters file://parameters/01-landing-zone.json
aws cloudformation wait stack-create-complete --stack-name {{SLUG}}-ct-landing-zone
```
Then fill `parameters/02-governance.json`. These values only exist after the landing zone is created:
```
aws organizations describe-organization --query 'Organization.Id' --output text
aws organizations list-roots --query 'Roots[0].Id' --output text
aws organizations list-organizational-units-for-parent --parent-id <root-id>   # ids of Security and Sandbox
```
```
aws cloudformation create-stack --stack-name {{SLUG}}-ct-governance --template-body file://02-governance.yaml --parameters file://parameters/02-governance.json
```

## Notes
- Controls are chained with `DependsOn` so they enable one at a time (avoids Control Tower conflicts).
- The region-deny SCP exempts global services and the Control Tower execution roles.
- Landing zone version, control ids and the manifest shape were written without checking the current Control Tower docs. Review the change set before executing if you use change sets.
