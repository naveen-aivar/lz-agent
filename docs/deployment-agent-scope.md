# Landing Zone Deployment Agent — scope (item 7)

**Owner:** Billu Naveen (billu.naveen@aivar.tech) · **Project:** Ingram Landing Zone  
**Status:** Scope redefined (Architecture vs Deployment split)  
**Platform doc (technical):** [deployment-agent-transform.md](./deployment-agent-transform.md)

## One-line summary

The **Architecture Design Agent** turns a SOW or transcript into approved **scope and IaC bundles**. The **Landing Zone Deployment Agent** takes that approved design plus a **target AWS account**, uses **AWS Transform** (required) to analyze and apply landing-zone work with human approval where needed, and produces a **custom deployment attestation report** against the approved scope.

## Responsibility split

| Capability | Architecture Design Agent | Landing Zone Deployment Agent |
|------------|---------------------------|-------------------------------|
| Primary input | SOW / requirements transcript | **Delivered design run** (scope + Terraform/CloudFormation zips) |
| Generate IaC from SOW | **Yes** — deterministic render from `scope.json` | **No** — consumes design artifacts |
| Greenfield vs brownfield | N/A | **Yes** — **deploy agent** (Transform MCP + snapshot) via **`save_foundation_assessment`**; discover only provides a heuristic hint |
| Assess existing setup | N/A | **Yes** — foundation snapshot + Transform |
| Identify required IaC **changes** | N/A | **Yes** — **`foundation-assessment.json`** (discover) + agent **`iac-change-plan.json`** (uses gaps + suggested changes; not hand-edited HCL/YAML in repo) |
| Deploy / apply in target account | **No** (customer pipeline) | **Yes** — **AWS Transform** deploy job + HITL in Transform console |
| Validation report | Pre-deploy **validation report** (scans on design bundles) | **Post-deploy `deployment-report.json`** (custom attest vs approved scope; Transform job IDs recorded) |

## Expected behaviors (stakeholder list)

1. **Analyse the target AWS account** and determine **greenfield vs brownfield**.  
   - **Implemented:** Organizations/Control Tower snapshot and classification; **Transform analyze** job on every deploy run.

2. **For brownfield:** assess the existing setup and **identify the required IaC changes**.  
   - **Implemented (foundation scope):** Organizations/Control Tower snapshot → **`foundation-assessment.json`**; **Deployment Agent (`deploy`)** uses **Transform MCP** + platform context and saves **`iac-change-plan.json`**.  
   - **Not in scope of “IaC correction” today:** patching individual `.tf`/`.yaml` lines from live drift; arbitrary resource reconciliation across all AWS services.

3. **Deploy the landing zone or apply the required changes** in the target account.  
   - **Implemented:** Transform **deploy** job started by the **deploy agent**; Step Functions **wait/re-invoke** the agent while operators approve in the Transform UI.  
   - **Not implemented here:** `terraform apply` / CloudFormation stack create from this platform without Transform.

4. **Generate a validation report** confirming deployment and resulting landing-zone configuration.  
   - **Implemented:** **`deployment-report.json`** on the deploy run (pass/fail vs approved scope names at Organizations level).  
   - **Complement, not replace:** Transform deployment history and approvals in the Transform product.

## Target account and credentials

**Default:** Foundation **discover** and **attest** use the **AgentCore runtime IAM role** (platform account).

**Cross-account (UI or API):** Optional `deployTarget` on deploy runs — **AssumeRole** into a customer role or short-lived keys stored in S3 for that run. Discover and attestation run in the **target account**. See [cross-account-deploy.md](./cross-account-deploy.md).

**Transform** runs in the account named by the stack's `TransformRoleArn` (default: the platform account) with workspace `TransformWorkspaceId`. Its target connector only accepts accounts in the same AWS Organization as that Transform account, so for a customer org the Transform profile/workspace and `TransformRoleArn` live in that org (see docs/deployment-agent-transform.md).

For a valid PoC, the **target** credentials should be able to call Organizations **ListRoots** / **ListAccounts** — typically the org **management account** or a [delegated administrator](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_delegate_policies.html). If Organizations denies any tree read (for example a member account that is not a delegated administrator), discovery is **incomplete** and the run fails at `run_pre_discover` (or post-discover) with `FoundationUnverifiable`, naming the denied calls. Gaps and attestation are never computed from a partial snapshot.

## Attestation outcomes

`deployment-report.json` **`overall`** is computed in code (`evaluate_deployment_outcome`), not by the LLM.

| `overall` | Deploy run status |
|-----------|-------------------|
| `pass` | **DELIVERED** (if agent + attest succeed) |
| `pass_with_manual_steps` | **DELIVERED** — foundation/Transform ok but documented **manualSteps** or residual gaps under `partial_manual` |
| `fail` | **FAILED** — invoke/attest raises; run not delivered |

## AWS Transform

| Stakeholder question | Position |
|---------------------|----------|
| Does Transform cover discover / gap / deploy / artifacts? | **PoC integrated:** deploy workflow calls Transform analyze and deploy via the same API surface as the Transform MCP server (SigV4). Capability depends on **workspace, orchestrator agent, and account entitlements** — validate in your tenant with `testing/main.py`. |
| Transform page looked out of scope | Treat marketing/docs as **hypothesis**; **integration proof** is running a deploy run with `TRANSFORM_WORKSPACE_ID` and recording job outcomes. |
| Is Transform optional? | **No** in this codebase — deploy runs require **`TransformWorkspaceId`** on the platform stack. |

## What “identify required IaC changes” means in this program

Stakeholders usually mean:

- **What** foundation elements differ from the approved design (OUs, accounts, governance intent).  
- **What action** closes the gap (apply design stacks, Transform job, or manual step).  

It does **not** require an LLM to rewrite CloudFormation/Terraform source in git. Baseline IaC still comes from the **Architecture Design Agent**; the Deployment Agent **plans and orchestrates apply** (Transform) and **attests** the outcome.

Optional future enhancements (not committed):

- Sync **Transform-generated IaC artifacts** to the deploy run download API.  
- **Scope delta → re-render** when gaps imply design updates.  
- Richer post-deploy checks (beyond Organizations name matching).

## API / operator flow (MVP)

### Design (Architecture Design Agent)

1. `POST /runs` — upload SOW or paste requirements.  
2. `POST /runs/{runId}/start` — Step Functions **design** workflow → **DELIVERED**.  
3. Download scope, Terraform/CloudFormation zips, validation report.

### Deploy (Landing Zone Deployment Agent)

1. Design run must be **DELIVERED**; platform must have **`TransformWorkspaceId`**.  
2. `POST /runs/{designRunId}/deploy` — new deploy run + **deploy** Step Functions.  
3. Agent loop (Transform analyze → plan → Transform deploy, with SFN wait/resume for HITL) → attestation in **`phase_invoke`** → deploy run **DELIVERED** or **FAILED**.  
4. On **DELIVERED**, download on the **deploy run** id: **`foundation-assessment`**, **`deployment-report`**, **`iac-change-plan`**, **`iac-manifest`**, optional stack zips.

Full technical sequence: [deployment-agent-transform.md](./deployment-agent-transform.md).

## Open next steps (from product review)

1. **Validate Transform** in account `145770591494` (or target tenant): workspace ID, orchestrator agent name, successful analyze/deploy jobs, HITL path.  
2. Document **Transform vs custom attest** for auditors (job IDs in report + S3 audit trail).  
3. **UI** for starting deploy runs and viewing deployment-report (API exists; SPA not yet).  
4. Decide whether **IaC changes** for brownfield are **Transform-only**, **design bundle re-apply only**, or **both**, and whether to add Transform artifact download to S3.

## Confluence paste (short)

> The Landing Zone **Deployment Agent** consumes an **approved Architecture design** (scope + IaC), analyzes the **target account** (greenfield/brownfield, foundation gaps), produces an **IaC change plan**, applies changes through **AWS Transform** (with human approval), and issues a **custom deployment attestation report**. **IaC generation from the SOW stays on the Architecture Design Agent.** Transform integration is **required** in the current platform build; full fit-for-purpose must be confirmed per AWS account and Transform workspace.
