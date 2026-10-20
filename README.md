# Landing Zone Agent Platform

Upload a SOW (PDF, DOCX, TXT, MD) or paste requirements. An agent reads **all of it** and extracts the Control Tower scope. A reviewer approves the scope. Deterministic code then generates a **Terraform stack and a CloudFormation stack** with a fixed file layout. Both stacks are validated and offered for download. Customers deploy them through their own pipeline.

Nothing in this repo deploys into a customer account. **Nothing here has been deployed or run against a live AWS account.**

## Flow
```
UI upload -> S3 -> [1] extract text (Lambda, pypdf / python-docx)
  -> [2] agent extracts scope (AgentCore, Strands + Claude)   <- the only LLM step
       session history is saved with the scope
  -> Gate A: human approves the exact scope (sha256 bound)
  -> [3] render Terraform + CloudFormation (Lambda, no LLM)
       refuses a missing or incomplete session; custom SCPs go in custom-scps/
  -> [4] validate (CodeBuild: terraform fmt/validate, tflint, cfn-lint, checkov)
       scan logs are packaged into both zip downloads
  -> DELIVERED: downloads enabled
```

## How the scope is kept honest (`lzcore/`)
| Concern | Enforced by |
|---|---|
| Agent reads the whole SOW | `save_scope` refuses until every page was read (`agent/tools.py`); oversized or scanned input fails instead of truncating |
| Agent does not invent requirements | every `explicit` item needs a verbatim quote that is searched for in the SOW (`lzcore/scope.py`) |
| Regions to deny | derived in code: all regions - governed - extraAllowed. The agent cannot supply it |
| Only known controls and catalog SCPs | closed catalogs (`lzcore/catalog.py`). A policy the catalog cannot express is authored under `customScps` and written to `custom-scps/`, which the stacks do not attach. Anything else must go under `unsupported`, which is shown at review |
| SCP limits | max 3 custom SCPs per target; 5120-char policy limit checked |
| Same structure every time | the renderer writes a fixed file set; tests assert it. Static Terraform and CFN files are copied verbatim |
| Approval is for exactly this scope | gate stores the scope sha256; render re-hashes and re-checks (`phase_render.py`); approver must differ from requester |

## Bundle layout (identical for every customer)
```
terraform/        versions.tf providers.tf variables.tf prerequisites.tf landing_zone.tf organizations.tf scps.tf
                  controls.tf outputs.tf  terraform.tfvars  policies/<scp>.json  docs/{SCOPE.md,ORG-STRUCTURE.md,scope.json}  README.md
cloudformation/   00-prerequisites.yaml 01-landing-zone.yaml 02-governance.yaml
                  parameters/{01-landing-zone,02-governance}.json  docs/{SCOPE.md,ORG-STRUCTURE.md,scope.json}  README.md
custom-scps/      README.md  <id>.json          model-authored SCPs, not attached by either stack
session/          history.json                 agent transcript and tool trace
scans/            summary.json  <check>.log    added after validation, then zipped into both downloads
```
Terraform is fully driven by `terraform.tfvars` and `policies/`. CloudFormation has no loops, so `02-governance.yaml` is generated in a fixed order. The other CloudFormation files are static. `custom-scps/`, `session/`, and `scans/` are in both zip files.

## Repository map
| Path | What it does |
|---|---|
| `lzcore/` | shared deterministic core: `regions`, `catalog`, `scope` (schema + validation), `render`, `extract` |
| `templates/` | static Terraform/CFN files and the two bundle READMEs |
| `agent/` | Strands agent (4 tools: read SOW page, catalog, save scope, run state) and ARM64 container |
| `orchestration/` | Step Functions definition, Lambdas, tests |
| `buildspecs/` | CodeBuild validation (`validate.yml`, `validate.sh`) |
| `infra/platform/platform.yaml` | the platform: Cognito, CloudFront+S3 (OAC), API Gateway, Lambdas, Step Functions, AgentCore runtime, CodeBuild, DynamoDB, KMS |
| `ui/` | static SPA |
| `eval/` | offline evaluation of scope, session, custom-SCP isolation, and scan packaging (`python -m eval`) |
| `scripts/deploy.sh` | packages and deploys the platform (creates real resources) |

## What was verified, and what was not
Verified locally: 20 unit tests; a sample bundle passes `terraform validate`, `terraform fmt -check` and `cfn-lint` (all three bundle templates and the platform template); DOCX and PDF extraction work on generated files; scanned/blank PDFs are rejected.

**Not verified (written from memory, check before use):**
- Control Tower control ids and their guidance levels (`lzcore/catalog.py`).
- The `AWS::ControlTower::LandingZone` manifest shape, version `3.3`, and the four prerequisite service roles' policies.
- The hard-coded region list (`lzcore/regions.py`) and the region-deny SCP's global-service exemptions.
- The `AWS::BedrockAgentCore::Runtime` properties, the Bedrock model id (you pass it), and the Knowledge MCP endpoint.
- The agent itself, the Lambdas against real AWS, the CodeBuild run and the UI have not been executed. The agent's save-scope gating is not covered by tests because the Strands library is not installed here.

The AWS Knowledge MCP needs authorizing in your claude.ai connector settings so these can be checked against current docs.

## Known limitations
- Scanned PDFs are rejected (no OCR). SOWs over 400k characters are rejected.
- The agent phase runs inside a 15-minute Lambda. Very large SOWs could exceed it.
- The Control Tower API launch needs the Log Archive and Audit accounts to exist already. If the SOW does not give their ids, the scope is marked `needs-input` and the stacks refuse to apply until they are filled in.
- Custom KMS keys must have a policy allowing Control Tower, CloudTrail and Config; the stacks do not create one.
- A reviewer who disagrees with the scope cannot edit it. They start a new run with corrected input.
- Networking, account vending and Identity Center assignments are reported as `unsupported`, never silently dropped.
- Model-authored SCPs are delivered in `custom-scps/` for review. The stacks do not create or attach them.

## Deploy the platform (creates real resources; review first)
```
aws s3 mb s3://<code-bucket>
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id>        # pass 1: platform + ECR
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id> v1     # pass 2: agent image + runtime
```
Create Cognito users and add them to `requesters` or `approvers` (the approver must be a different person from the requester).

## Evaluation
`python -m eval` scores a fixed suite of labeled extractions. Gold cases must validate, keep every explicit quote inside the SOW, derive the denied-region list, leave custom SCPs in `custom-scps/` only, include each SOW page in the session before `save_scope`, and carry the scan reports inside both bundles. Trap cases pass only when the checker reports the planted problem.

`python -m eval run sow.txt scope.json session.json [scans-dir]` scores one saved agent run and does not compare it to a gold scope. It checks quote grounding, that the session stores every page, that denied regions were derived, that custom SCPs stayed in `custom-scps/`, and, when a scans directory is passed, that those reports package into both bundles.

## Tests
```
python -m unittest discover -s orchestration/tests -v
python -m eval
python -m eval run sow.txt scope.json session.json
```
