# AWS Transform research notes (landing-zone deploy agent)

Working notes: what we know about AWS Transform, what we observed live, and the open questions to check later.
Last updated: 2026-10-27. Contains real account and workspace ids (not secrets) and no credentials. Keep it out of
public repos; `docs/research/` is gitignored.

Status legend: ✅ confirmed (docs or live test) · ⚠️ assumed / partly verified · ❓ open question

---

## 1. Account layout

| Role | Account | Org | Notes |
|---|---|---|---|
| Platform (UI, API, Step Functions, Lambdas, AgentCore agent, DynamoDB, S3) | 831493647146 | `o-wl6vsb2yko` (management account 724772073478, aivar) | Agent image **v13** deployed. Stack `ingram-landing-zone`. |
| Customer landing-zone target | 556880010183 | `o-dstyfog9a6` (556 is the **management account**; no member accounts yet) | Discovery works with the `target` IAM user (AdministratorAccess). |
| Transform (current setup) | 556880010183 | same as target | Profile `arn:aws:transform:us-east-1:556880010183:profile/99CXDV4YDUQ9`, tenant `72236d629ae7f6e07`, app URL `https://72236d629ae7f6e07.transform.us-east-1.on.aws/`, IAM sign-in (SigV4) enabled. |
| Transform (previous setup) | 831493647146 | `o-wl6vsb2yko` | Profile `…:profile/4CCMAQ3YPGHK`, tenant `7223683482b716406`, workspace `landing-zone` = `e937eb9d-cccd-437d-8b75-631adce1c584`. |

556 Transform resources created by us:
- Workspace `landing-zone` = `44f8c300-7365-476c-9c03-3736f7049d2e` (us-east-1).
- IAM role `IngramLandingZoneTransform`: `transform:*`. It trusts the 831 AgentRole `ingram-landing-zone-AgentRole-LBinaFbV3RCO` with `sts:ExternalId` (the value is only in `.deploy-env.local`), plus a **bootstrap trust for user `target` that must be removed**.
- Workspace collaborators: `AROAYDKFCTPDTS3FA5G4L:ingram-lz-agent` (our role session) = ADMIN, `target` user = ADMIN.

---

## 2. Confirmed from AWS documentation

### Accounts and organizations
- ✅ **The Transform account must be in the same AWS Organization as the connector target.** The docs define the Transform account as any member account in your organization where Transform is set up; it does not have to be the management account. [Connect target AWS accounts and regions](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-connect-target-account.html)
- ✅ The re:Post walkthrough says the same, and recommends a separate Transform instance in the target org for cross-org use. [Assess LZ readiness with Kiro and AWS Transform](https://repost.aws/articles/ARjmoIyUOaRoW6PbjQ06Pgnw/assess-your-aws-landing-zone-readiness-in-minutes-using-kiro-and-aws-transform)
- ✅ For a landing zone (multi-account), the connector targets the **management account** or a **delegated administrator (DA)**. A DA for network/server migration must also be registered for MGN (`mgn.amazonaws.com`) and StackSets (`member.org.stacksets.cloudformation.amazonaws.com`). For landing zone only, an Organizations delegation policy (`organizations put-resource-policy`, read actions) is enough. [Connect target accounts](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-connect-target-account.html)

### Connector
- ✅ Approving the connector creates `AWSTransform-Connector-role-*` in the management or DA account, with managed policies `AWSTransformLandingZoneAgentPolicy`, `AWSTransformNetworkMigrationAgentPolicy` and `AWSTransformServerMigrationAgentPolicy`. The current connector type version is **5**. Setup also creates an S3 bucket in the target account, without SecureTransport enforced by default. [Connect target accounts](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-connect-target-account.html)
- ✅ The connector role trusts `transform.amazonaws.com` with `sts:AssumeRole` + `sts:SetContext`, conditioned on `aws:SourceAccount`. The target-account owner approves the connector. [AWS Transform connectors](https://docs.aws.amazon.com/transform/latest/userguide/transform-user-connectors.html)
- ✅ The connector region should match the Control Tower / IAM Identity Center home region. Our design home region is `ap-south-1`. [Build landing zone](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-landing-zone.html)
- ✅ A target region that differs from the Transform region means cross-region data transfer. [Connect target accounts](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-connect-target-account.html)

### Landing-zone modes
- ✅ **Full deployment** (management-account connector): Transform provisions Control Tower, OUs, accounts and SCPs. [Build landing zone](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-landing-zone.html)
- ✅ **IaC-only**: forced with a DA connector, optional with a management-account connector (chosen at the start of the job). Outputs AWS CDK (TypeScript), Terraform/HCL, or LZA config YAML (Universal Configuration 1.1.0). Needs read-only Organizations access. Transform does not verify the deployment. A DA cannot see or change Control Tower-managed SCPs. **No CloudFormation output.** [Generate landing zone IaC without deployment](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-lz-iac-only-flow.html)

---

## 3. Confirmed from live testing (our accounts)

| Date (IST) | Observation |
|---|---|
| Oct 26 | ✅ Transform keys IAM collaborators by **`RoleId:SessionName`** (ListUserRoleMappings shows e.g. `AROA…:BedrockAgentCore-<uuid>`). AgentCore uses a new session name per run, so we assume the role with a fixed session name `ingram-lz-agent`. |
| Oct 26 | ✅ `PutUserRoleMappings` fails with "does not belong or has not logged in to tenant" until that exact identity has made one call to the tenant. The identity has to call first, then get granted. |
| Oct 26 | ✅ `CreateJob` requires `orchestratorAgent`. Landing zone uses **`vmware-migration-agent-v2`**, which hands work to the sub-agent `lz-subagent-v1` (described as a landing-zone agent that provisions via Landing Zone Accelerator). |
| Oct 26 | ✅ The job state is in `GetJob.job.statusDetails.status`, a JobStatus enum: CREATED, STARTING, ASSESSING, PLANNING, PLANNED, EXECUTING, AWAITING_HUMAN_INPUT, COMPLETED, FAILED, STOPPING, STOPPED. |
| Oct 26 | ✅ **The orchestrator is chat-driven and stays `EXECUTING` while it waits.** It ignored the first SendMessage sent right after StartJob. It then asked, in order: workflow ("Landing Zone"), plan approval (Proceed / Add migration planning), migration type (defaulted to multi-account), MAP agreement, and the Set up Target Connector HITL task (`CreateOrSelectConnectors`, connector type `vmware_migration\|infra_provisioning\|5`). |
| Oct 26 | ✅ Chat messages are per user: a job created by our role session is not visible to the SSO admin's ListMessages. |
| Oct 26 | ✅ The connector task was **listed as `AWAITING_HUMAN_INPUT`** by ListHitlTasks, while GetHitlTask showed `IN_PROGRESS`. |
| Oct 26 | ✅ **Cross-org connector rejected** (both API and console): "The account associated with this application (831…) cannot use target account (556…). … same AWS Organization or … trusted access configuration." |
| Oct 26–27 | ✅ **CreateJob blocked in 556's Transform**: HTTP 400 "We are unable to process your request. Please reach out to your support representative." Same result for the role session and the `target` admin user (no permissions boundary, no SCPs since it is the management account), and for orchestrators `vmware-migration-agent-v2` and `migration-assessment-agent-v2`. Other calls work (ListWorkspaces, CreateWorkspace, PutUserRoleMappings, ListAgents, GetAccountSettings). Last re-check: **Oct 27 10:02 IST, still blocked.** |
| Oct 26 | ✅ The same 61 agents are enabled in 556 and 831; GetAccountSettings is the same (crossRegionKnowledge ENABLED, no encryptionConfiguration). |
| Oct 26 | ✅ The 556 Transform profile and `AWSServiceRoleForAWSTransform` were both created on Oct 26 (new tenant). |

---

## 4. Current blockers

1. ❌ **556 CreateJob hold**: an account-level block that only AWS can lift. Support case to open from account 556 (Service: AWS Transform):
   > CreateJob returns HTTP 400 "We are unable to process your request. Please reach out to your support representative." for every principal (including an IAM user with AdministratorAccess who is workspace Admin) and every orchestrator agent. Profile `arn:aws:transform:us-east-1:556880010183:profile/99CXDV4YDUQ9`, workspace `44f8c300-7365-476c-9c03-3736f7049d2e`, us-east-1, created 2026-10-26. Please confirm whether the account needs enabling or allow-listing for job creation.
2. ❌ **Cross-org Transform (831 → 556)** isn't possible per the docs. The only lead is the "trusted access configuration" in the error text (see Q1).

---

## 5. Open questions (check later)

| # | Question | How to check | Status |
|---|---|---|---|
| Q1 | What is the "trusted access configuration" in the cross-org error? An Organizations trusted-access setting for a Transform service principal, a Transform account setting, or something AWS enables? | Service Authorization Reference for `transform`, the Organizations "services that work with Organizations" list, an AWS Support question from 831 | ❓ |
| Q2 | What causes CreateJob "please reach out to your support representative" on a new profile? (billing/payment verification, new-account restriction, allowlist, quota, region, Identity Center requirement) | Billing console on 556 (payment method, verification), the Transform console banner, the AWS Support case | ❓ |
| Q3 | Does a **new member account** in `o-dstyfog9a6` (Transform there, connector → 556 management account) avoid the hold? | Create a member account, enable Transform, test CreateJob (needs approval: account creation is hard to undo) | ❓ |
| Q4 | Exact IAM action names that authorize Transform job/workspace/message/HITL/artifact operations (`transform:CreateJob`?). cfn-lint knows only profile/agent actions. | [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html) for the `transform` prefix, CloudTrail `eventName` from one live run | ❓ |
| Q5 | Response shape of TCP `ListProfiles` (we assume `profiles[].applicationUrl`) and the console deep-link path (`/workspaces/<ws>/jobs/<job>`) | One live call, then commit it as a recorded test fixture | ⚠️ |
| Q6 | Meaning of `IN_PROGRESS` on HITL tasks: human-owned or Transform processing? (affects which wait budget is charged) | Observe a live task lifecycle | ⚠️ |
| Q7 | Is there a documented non-interactive mode, or a way to preselect workflow / IaC-only / format in the CreateJob objective, so the chat questions are skipped? | Transform user guide (jobs, landing zone), MCP server `load_instructions`, test with a first message such as "Landing Zone, IaC-only, Terraform" | ❓ |
| Q8 | How should programmatic clients answer chat questions (SendMessage with the option value?) and complete HITL tasks (UpdateHitlTask / the MCP `complete_task` schema)? | MCP server source (`tools/hitl.py`, `hitl_schemas.py`), a live test | ⚠️ We answered via SendMessage with the option label and it worked. |
| Q9 | Can a connector be created programmatically and approved with an existing role (`AssociateConnectorResource` with a role ARN), so no console approval is needed? | MCP `accept_connector` (TCP AssociateConnectorResource, called with target-account credentials) | ⚠️ |
| Q10 | Is a standalone landing-zone job type or orchestrator available, rather than going through the VMware migration agent? | ListAgents, docs | ❓ (only `lz-subagent-v1` as a sub-agent seen) |
| Q11 | Does the connector need a customer-managed KMS key in the target region, or are S3-managed keys fine? | Docs say S3-managed keys are an option at connector creation | ✅ S3-managed is allowed |
| Q12 | Does Transform require IAM Identity Center in the target org for landing zone, and in which region? | Build landing zone page (Identity Center requirement) | ⚠️ Page says IAM Identity Center is required and the connector region must match its home region |

---

## 6. Implications for our platform

- Long term, a customer must run Transform **inside their own org**, or AWS must enable cross-org trusted access (Q1).
- The Transform orchestrator needs **interactive answers**. Our platform must detect pending questions and tasks and show them (round-2 work: `pendingHumanInput`), or pre-answer them (Q7, Q8).
- **IaC-only** fits our architecture best: Transform analyses and generates IaC with read-only access, and our platform deploys through a customer role and attests. Gap: Transform outputs CDK/Terraform/LZA, not CloudFormation.

## 7. Sources read so far

- https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-connect-target-account.html
- https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-lz-iac-only-flow.html
- https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-landing-zone.html (partly)
- https://docs.aws.amazon.com/transform/latest/userguide/transform-user-connectors.html
- https://repost.aws/articles/ARjmoIyUOaRoW6PbjQ06Pgnw/assess-your-aws-landing-zone-readiness-in-minutes-using-kiro-and-aws-transform
- awslabs.aws-transform-mcp-server 0.2.3 source (installed locally)

Not yet read: IAM/security pages, the Service Authorization Reference for `transform`, setup/onboarding, quotas, troubleshooting, release notes, user management.
