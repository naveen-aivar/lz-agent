# Landing Zone Agent Platform

Upload a SOW (PDF, DOCX, TXT, MD) or paste requirements. An agent reads **all of it, one page at a time**, and extracts the Control Tower scope. Deterministic code then generates a **Terraform stack and a CloudFormation stack** with a fixed file layout. Both stacks are validated and offered for download. Customers deploy them through their own pipeline.

Nothing in this repo deploys into a customer account. **Nothing here has been deployed or run against a live AWS account.**

## Flow
```
UI upload -> S3 -> [1] extract text (Lambda, pypdf / python-docx)
  -> [2] agent extracts scope, one SOW page per model call (AgentCore, Strands + Claude)
  -> [3] render Terraform + CloudFormation (Lambda, no LLM)
  -> [4] validate (CodeBuild: terraform fmt/validate, tflint, cfn-lint, checkov) -> report with scanned / passed / failed counts
  -> DELIVERED: downloads enabled (each stack zip carries its own scan reports; a separate reports zip has them all)
```

## How the scope is kept honest (`lzcore/`)
| Concern | Enforced by |
|---|---|
| Agent reads the whole SOW | each page is its own model call and is saved before the next page (`lzcore/page_scope.py`); a retry skips pages already saved. Oversized or scanned input fails instead of truncating |
| Agent does not invent requirements | every `explicit` quote must be an exact character slice of the page that produced it, and that quote must still occur in the SOW (`lzcore/page_scope.py`, `lzcore/scope.py`) |
| Regions to deny | derived in code: all regions - governed - extraAllowed. The agent cannot supply it |
| Only known SCP ids and control ids | catalog SCPs and Control Tower controls come from closed catalogs (`lzcore/catalog.py`). Any other SCP is written by the model under `customScps`: validated (`lzcore/customscp.py`), delivered for review, never applied by the stacks. Everything else goes under `unsupported` |
| SCP limits | max 3 catalog SCPs per target; 5120-char limit checked on every policy, catalog and custom |
| Same structure every time | the renderer writes a fixed file set; tests assert it. Static Terraform and CFN files are copied verbatim |

## Bundle layout (identical for every customer)
```
terraform/        versions.tf providers.tf variables.tf prerequisites.tf accounts.tf landing_zone.tf organizations.tf scps.tf
                  controls.tf outputs.tf  terraform.tfvars  policies/<scp>.json  custom-scps/{README.md,index.json,<id>.json}
                  reports/  docs/{SCOPE.md,ORG-STRUCTURE.md,scope.json}  README.md
cloudformation/   00-prerequisites.yaml 01-landing-zone.yaml 02-governance.yaml
                  parameters/{00-prerequisites,01-landing-zone,02-governance}.json  custom-scps/  reports/  docs/  README.md
```
Landing zone **4.0**. The stacks create the Security OU, the Log Archive and Audit accounts and every other OU and account in the SOW
from **emails the customer types into variables** (`accounts` in `terraform.tfvars`, the parameter files for CloudFormation), register the
OUs with Control Tower, and enable the controls. This is a two-stage apply because registration needs the landing zone's Identity Center
baseline. `custom-scps/` holds AI-generated SCPs for human review: they are validated but never applied by the stacks.
See `docs/AWS-REVIEW.md` for how the design was checked against the AWS documentation and what is still unverified.

## Repository map
| Path | What it does |
|---|---|
| `lzcore/` | shared deterministic core: `regions`, `catalog`, `scope` (schema + validation), `page_scope` (one page at a time, then merge), `customscp` (AI-written SCP validation), `diagram` (org tree), `render`, `extract` |
| `templates/` | static Terraform/CFN files and the two bundle READMEs |
| `agent/` | Strands agent (one page per call, then a deterministic merge) and ARM64 container |
| `orchestration/` | Step Functions definition, Lambdas, tests |
| `buildspecs/` | CodeBuild validation (`validate.yml`, `validate.sh`, `report.py` builds the scan report and bundles) |
| `infra/platform/platform.yaml` | the platform: Cognito, CloudFront+S3 (OAC), API Gateway, Lambdas, Step Functions, AgentCore runtime, CodeBuild, DynamoDB, KMS |
| `ui/` | static SPA |
| `scripts/deploy.sh` | packages and deploys the platform (creates real resources) |

## What was verified, and what was not
Verified locally: 20 unit tests; a sample bundle passes `terraform validate`, `terraform fmt -check` and `cfn-lint` (all three bundle templates and the platform template); DOCX and PDF extraction work on generated files; scanned/blank PDFs are rejected.

See `docs/AWS-REVIEW.md`: the manifest, prerequisites, baselines and resources were checked against the AWS documentation and the real
resource schemas (`terraform validate`, `cfn-lint`), which also corrected several mistakes in the first version. **Still not verified:**
- **Nothing has been applied to a real organization**, so the whole Control Tower flow is untested.
- The detective control ids (the reference pages list names, not ids) and the AWSControlTowerBaseline version.
- The `AWS::BedrockAgentCore::Runtime` properties and the Bedrock model id (you pass it).
- The CodeBuild run of the new validation step has been dry-run locally only.

## Known limitations
- Scanned PDFs are rejected (no OCR). SOWs over 400k characters are rejected.
- The agent phase runs inside a 15-minute Lambda. Pages already saved are kept, and the one automatic retry continues from the next unsaved page. A second timeout fails the run.
- Every account the stacks create needs a unique root email in a variable; the scope is marked `needs-input` and the stacks refuse to apply until they are filled in. AWS accounts cannot be deleted cheaply (closing takes up to 90 days), so the stacks protect them from destroy.
- Custom KMS keys must have a policy allowing Control Tower, CloudTrail and Config; the stacks do not create one.
- A reviewer who disagrees with the scope cannot edit it. They start a new run with corrected input.
- Custom SCPs are written by the model and delivered for review (`custom-scps/`), not applied. Networking, Identity Center assignments and service enablement (GuardDuty etc.) are reported as `unsupported`, never silently dropped.
- The agent does not yet ask follow-up questions when the SOW is thin.

## Deploy the platform (creates real resources; review first)
```
aws s3 mb s3://<code-bucket>
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id>        # pass 1: platform + ECR
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id> v1     # pass 2: agent image + runtime
```
Create Cognito users. Any signed-in user can start a run, and each user sees only their own runs. There is no approval step: the generated code is shipped to the customer, never deployed from here.

## Tests
```
python -m unittest discover -s orchestration/tests -v
```
