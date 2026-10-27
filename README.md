# Landing Zone Agent Platform

Upload a SOW (PDF, DOCX, TXT, MD) or paste requirements. An agent reads **all of it** and extracts the Control Tower scope. Deterministic code then generates a **Terraform stack and a CloudFormation stack** with a fixed file layout. Both stacks are validated and offered for download. Customers deploy them through their own pipeline.

Design runs do not deploy into customer accounts from this platform. **Deploy runs** use **AWS Transform** (required workspace id on the stack) for analyze/apply; see `docs/deployment-agent-scope.md` (stakeholder scope) and `docs/deployment-agent-transform.md` (technical flow).

## Flow

Two **run kinds** share the API and S3 artifact bucket but use different Step Functions state machines.

### Architecture design run (`POST /runs` → `/start`)

State machine: `orchestration/statemachine.asl.json` (`{ProjectName}-run`).

```
UI upload → S3
  → [1] extract text (Lambda: pypdf / python-docx)
  → [2] intake agent (AgentCore `phase: intake`) → scope.json (validated in lzcore)
  → [3] render Terraform + CloudFormation (Lambda, deterministic)
  → [4] validate (CodeBuild: fmt, terraform validate, cfn-lint, …) → validation-report.json
  → DELIVERED — download scope + stack zips + scan reports
```

The intake agent is the **only LLM step on the design path**. Stacks are **not** applied from this platform.

### Landing zone deploy run (`POST /runs/{designRunId}/deploy`)

Requires a **DELIVERED** design run and **`TRANSFORM_WORKSPACE_ID`** on the stack.  
State machine: `orchestration/deployment.asl.json` (`{ProjectName}-deploy`).

```
API creates deploy run (runKind=deploy, links designRunId)
  → loop: phase_invoke (AgentCore `phase: deploy`)
        Strands agent + Transform MCP + tools:
          pre-discover → Transform analyze (poll/HITL) → merge
          → foundation assessment + iac-change-plan → render bundles
          → Transform deploy (poll/HITL) → post-discover → finish_deploy_workflow
        if Transform still running: SFN waits 60 s and re-invokes the same session
          progress budget 240 cycles (~4 h); HITL budget 1440 cycles (~24 h) while Transform waits on a person
          (the question is shown in the UI: "AWS Transform needs your input")
  → on agent ok: attestation in phase_invoke (deployment-report.json, rule-based pass/fail)
  → phase_deploy → DELIVERED or FAILED (stored target keys deleted; /stop deletes them too)
     (retried 3 times; an execution that times out, is aborted or fails there is cleaned up by an EventBridge rule)
```

The deploy agent's model gets only read-only Transform MCP tools (`get_resource`, `list_resources`, `get_status`, `load_instructions`); every Transform job start and stop is done by the deterministic sequencer. Transform MCP startup is preflighted (credential helper, then `get_status` must report SigV4 connected). See `docs/deployment-agent-transform.md`.

Details: [docs/deployment-agent-transform.md](docs/deployment-agent-transform.md), [docs/cross-account-deploy.md](docs/cross-account-deploy.md) and [docs/deployment-agent-scope.md](docs/deployment-agent-scope.md).

Org discover/attest run in the platform account by default, or in a cross-account target (IAM role with a required external ID, recommended; or access keys stored per run and deleted when it ends). See `docs/cross-account-deploy.md`.

## How the scope is kept honest (`lzcore/`)
| Concern | Enforced by |
|---|---|
| Agent reads the whole SOW | `save_scope` refuses until every page was read (`agent/tools.py`); oversized or scanned input fails instead of truncating |
| Agent does not invent requirements | every `explicit` item needs a verbatim quote that is searched for in the SOW (`lzcore/scope.py`) |
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
| `lzcore/` | shared deterministic core: `regions`, `catalog`, `scope` (schema + validation), `customscp` (AI-written SCP validation), `diagram` (org tree), `render`, `extract` |
| `templates/` | static Terraform/CFN files and the two bundle READMEs |
| `agent/` | Strands AgentCore: **intake** (SOW → scope) and **deploy** (discover, Transform, plan, render via tools + Transform MCP); ARM64 container |
| `orchestration/` | Step Functions definition, Lambdas, tests |
| `buildspecs/` | CodeBuild validation (`validate.yml`, `validate.sh`, `report.py` builds the scan report and bundles) |
| `infra/platform/platform.yaml` | the platform: Cognito, CloudFront+S3 (OAC), API Gateway, Lambdas, Step Functions, AgentCore runtime, CodeBuild, DynamoDB, KMS |
| `ui/` | static SPA |
| `scripts/deploy.sh` | packages and deploys the platform (creates real resources) |
| `testing/main.py` | local Transform MCP + Strands smoke test (not deployed) |

## What was verified, and what was not
Verified locally: orchestration unit tests (`orchestration/tests`); a sample bundle passes `terraform validate`, `terraform fmt -check` and `cfn-lint` (all three bundle templates and the platform template); DOCX and PDF extraction work on generated files; scanned/blank PDFs are rejected.

See `docs/AWS-REVIEW.md`: the manifest, prerequisites, baselines and resources were checked against the AWS documentation and the real
resource schemas (`terraform validate`, `cfn-lint`), which also corrected several mistakes in the first version. **Still not verified:**
- **Nothing has been applied to a real organization**, so the whole Control Tower flow is untested.
- The detective control ids (the reference pages list names, not ids) and the AWSControlTowerBaseline version.
- The `AWS::BedrockAgentCore::Runtime` properties and the Bedrock model id (you pass it).
- The CodeBuild run of the new validation step has been dry-run locally only.

## Known limitations
- Scanned PDFs are rejected (no OCR). SOWs over 400k characters are rejected.
- The agent phase runs inside a 15-minute Lambda. Very large SOWs could exceed it.
- Every account the stacks create needs a unique root email in a variable; the scope is marked `needs-input` and the stacks refuse to apply until they are filled in. AWS accounts cannot be deleted cheaply (closing takes up to 90 days), so the stacks protect them from destroy.
- Custom KMS keys must have a policy allowing Control Tower, CloudTrail and Config; the stacks do not create one.
- A reviewer who disagrees with the scope cannot edit it. They start a new run with corrected input.
- Custom SCPs are written by the model and delivered for review (`custom-scps/`), not applied. Networking, Identity Center assignments and service enablement (GuardDuty etc.) are reported as `unsupported`, never silently dropped.
- The agent does not yet ask follow-up questions when the SOW is thin.

## Deploy the platform (creates real resources; review first)
```
export TRANSFORM_WORKSPACE_ID=<aws-transform-workspace-uuid>
aws s3 mb s3://<code-bucket>
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id>        # pass 1: platform + ECR
scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id> v1     # pass 2: agent image + runtime (required for intake and deploy agent)
```
Optional deploy-time variables: `TRANSFORM_ROLE_ARN` (+ `TRANSFORM_EXTERNAL_ID`, not a secret) when Transform lives in another account, and `DEPLOY_ASSUME_ROLE_ARN` (target-role pattern, default `arn:aws:iam::*:role/IngramLandingZoneDeploy*`; never `*`). With `ENABLE_CLOUDFRONT=false` the UI is served from the API endpoint (same origin, no CORS) by a Lambda that can only read the UI bucket.

Pass 2 creates the AgentCore runtime. **Design** (`POST /runs/{id}/start`) and **deploy** (`POST /runs/{designId}/deploy`) both call that runtime; pass 1 alone is not enough for agent phases.

Create Cognito users. Any signed-in user can start a run, and each user sees only their own runs. Design runs ship generated code to the customer; deploy runs use AWS Transform in the account of `TransformRoleArn` (the platform account when it is empty), which must share the target's AWS Organization (see `docs/deployment-agent-scope.md` and `docs/deployment-agent-transform.md`).

## Tests
```
python -m unittest discover -s orchestration/tests -v
```
