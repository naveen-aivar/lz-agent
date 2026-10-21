# Review of the platform against the AWS Control Tower documentation

Reviewed 2026-10-20 against docs.aws.amazon.com and the Terraform AWS provider docs. "Verified" means checked against a documentation
page or by `terraform validate` / `cfn-lint` against the real resource schemas. Nothing here has been applied to a real organization.

## What the review found, and what changed

| # | Finding in the original design | Source | Change |
|---|---|---|---|
| 1 | The landing zone API needs the Log Archive and Audit accounts to exist first, in a **Security OU directly under the root**. The platform asked the customer for account ids and created neither the accounts nor the OU. | [Step 1: Configure your landing zone](https://docs.aws.amazon.com/controltower/latest/userguide/lz-api-prereques.html), [CloudFormation prerequisites](https://docs.aws.amazon.com/controltower/latest/userguide/lz-apis-cfn-setup.html) | The stacks create the Security OU and both accounts with `AWS::Organizations::Account` / `aws_organizations_account` from an email variable. Ids are only an optional override. |
| 2 | The manifest was a 3.3-style manifest (`organizationStructure`, no `enabled` flags, no `config`). The SOW asks for 4.0 or later. | [Landing zone schemas](https://docs.aws.amazon.com/controltower/latest/userguide/landing-zone-schemas.html), [Launch with the APIs](https://docs.aws.amazon.com/controltower/latest/userguide/lz-api-launch.html) | 4.0 manifest: explicit `enabled` flags, `config` section (Audit account), Backup off, no `organizationStructure`, version `4.0`. |
| 3 | OUs created in Organizations are not registered with Control Tower, and controls can only be enabled on registered OUs. The stacks never registered them. | [Types of baselines](https://docs.aws.amazon.com/controltower/latest/userguide/types-of-baselines.html), [Register an OU with APIs](https://docs.aws.amazon.com/controltower/latest/userguide/walkthrough-baseline-steps.html) | An `EnabledBaseline` / `aws_controltower_baseline` per OU (AWSControlTowerBaseline), which needs the landing zone's Identity Center enabled baseline. Hence the two-stage apply. |
| 4 | Workload accounts were only drawn, never created. | [Move and enroll accounts with auto-enrollment](https://docs.aws.amazon.com/controltower/latest/userguide/account-auto-enrollment.html) | Accounts are created from emails and placed in their OU. `RemediationTypes: INHERITANCE_DRIFT` turns auto-enrollment on, so registering an OU enrolls its accounts. |
| 5 | The `AWSControlTowerConfigAggregatorRoleForOrganizations` role is not required from 4.0. | lz-api-prereques (above) | Removed. The other three roles and their policies match the documented ones. |
| 6 | Control catalog: `AWS-GR_EBS_SNAPSHOT_PUBLIC_RESTORABLE_CHECK` is in none of the strongly-recommended or elective lists; IAM-user MFA and EBS optimization were misclassified; the VPN and log-archive-retention controls the SOW asks for were missing. | [Strongly recommended](https://docs.aws.amazon.com/controltower/latest/controlreference/strongly-recommended-detective-controls.html), [Elective preventive](https://docs.aws.amazon.com/controltower/latest/controlreference/elective-preventive-controls.html) | Removed the unlisted control, fixed the guidance levels, added `AWS-GR_DISALLOW_VPN_CONNECTIONS`, `AWS-GR_AUDIT_BUCKET_RETENTION_POLICY` and `AWS-GR_EC2_VOLUME_INUSE_CHECK`. |
| 7 | The Region deny guardrail cannot be enabled through the controls API. | [aws_controltower_control](https://github.com/hashicorp/terraform-provider-aws/blob/main/website/docs/r/controltower_control.html.markdown) | Kept the generated custom region-deny SCP and said so in both READMEs. |
| 8 | `--soft-fail` security scans produced no counts. | | A report with scanned / passed / failed per stack, bundled with the stacks. |
| 9 | Custom SCPs from the SOW were dropped into `unsupported`. | | LLM-written, validated, delivered in `custom-scps/` for human review, never applied by the stacks. |

## Verified
- Prerequisites, the roles and their policies, the 4.0 manifest shape and required fields, `RemediationTypes`, the baseline parameter
  key (`IdentityCenterEnabledBaselineArn`), baseline id `17BSJV3IGJ2QSGA2` and version `4.0` (as printed in the docs and the provider examples).
- Terraform: `terraform validate` against AWS provider 6.69.1 for `aws_controltower_landing_zone` (with `remediation_types`),
  `aws_controltower_baseline`, `aws_organizations_account`. CloudFormation: `cfn-lint` for `AWS::ControlTower::LandingZone`,
  `EnabledBaseline`, `EnabledControl`, `AWS::Organizations::Account`.
- Preventive control ids shown on the reference pages (see `lzcore/catalog.py`).

## Not verified (needs a real apply, or a check in your account)
- **No end-to-end apply has been done.** Passing validation and lint does not prove Control Tower accepts the flow.
- The Security OU is assumed to be set up and registered by the landing zone as the foundational OU. Check it in the console.
- The `AWSControlTowerBaseline` version (`4.0`) and id are the documented example values; confirm with `aws controltower list-baselines`.
- Detective control ids: the reference pages list the controls by name, not by id, so those ids remain unverified. Pre-flight:
  `aws controlcatalog list-controls`.
- A customer-managed KMS key for Control Tower: its key policy is not generated.
- The minimum AWS provider version (`>= 6.0`) is a floor; only 6.69.1 was exercised.

## The agent and the platform: what this review did not change
- The agent still extracts the scope in one pass. It does not yet ask follow-up questions when the SOW is thin (planned).
- Service enablement from the Audit account (GuardDuty, Security Hub, Access Analyzer, Inspector, Macie) is still `unsupported`
  (planned: a deterministic catalog).
- Scanned PDFs are rejected (no OCR). The agent phase runs inside a 15-minute Lambda.
