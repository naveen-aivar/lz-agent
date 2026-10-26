# Bugfix Requirements Document

## Introduction

Landing Zone deploy runs fail with `agent phase deploy failed: deploy incomplete at checkpoint stage='transform_init_done'`. Observed on deploy run `fb8adcc522b64a719183b9e48ee013fb` (design run `bb68280df80b43a89c56e95da6a526d4`, target account `556880010183`) and on a later run. The audit trail shows `run_pre_discover`, `read_deploy_checkpoint` and `transform_init_connection` succeeding. After that the model ended its invoke ("Invocation completed successfully (20s)") without calling `transform_start_analyze`. No analyze job was created and the run was marked FAILED.

The deploy workflow has a fixed order: pre-discover → Transform init → start analyze → poll analyze → merge discovery → foundation assessment → IaC change plan → render bundles → start deploy → poll deploy → post-discover → finish. Today the model drives every step through tool calls. If the model stops at any checkpoint stage that is neither terminal nor a defined wait stage, the run fails, even when the next step needs no model judgment. Only two steps need judgment: the greenfield/brownfield foundation assessment and the IaC change plan. Every other step is mechanical and can be run in order by deterministic code.

The partial fix (agent image v8, uncommitted, not validated on a live run) only patches the stages around init and job start, after the model returns. The model still owns sequencing, and later mechanical stages (merge, render, start deploy, post-discover, finish) can still stall the same way. Separately, checkpoint reads currently swallow every exception and return an empty checkpoint, so a storage or permission error looks like "stage=None" instead of naming the real cause.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the deploy checkpoint stage is `transform_init_done` and the model ends its invoke without calling `transform_start_analyze` THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='transform_init_done'" and no analyze job is created.

1.2 WHEN the deploy checkpoint stage is `pre_discover_done` and the model ends its invoke without calling `transform_init_connection` THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='pre_discover_done'".

1.3 WHEN the deploy checkpoint stage is `transform_analyze_done` and the model ends its invoke without calling `transform_merge_discovery` THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='transform_analyze_done'".

1.4 WHEN the IaC change plan has been saved and the model ends its invoke without calling `render_iac_bundles` THEN the system marks the deploy run FAILED with a "deploy incomplete" error instead of rendering the bundles.

1.5 WHEN the deploy checkpoint stage is `iac_render_done` and the model ends its invoke without calling `transform_start_deploy` THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='iac_render_done'".

1.6 WHEN the deploy checkpoint stage is `transform_deploy_done` and the model ends its invoke without calling `run_post_discover` THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='transform_deploy_done'".

1.7 WHEN the deploy checkpoint stage is `post_discover_done` and every required deployment artifact exists, but the model ends its invoke without calling `finish_deploy_workflow`, THEN the system marks the deploy run FAILED with "deploy incomplete at checkpoint stage='post_discover_done'".

1.8 WHEN a Transform job API call (for example CreateJob for the analyze job) is rejected with HTTP 403 THEN the system reports a generic error that does not name the failing workflow step, the calling principal, or the required workspace Contributor membership.

1.9 WHEN reading the deploy checkpoint fails for a reason other than the checkpoint object not existing yet (for example S3 access denied or a KMS error) THEN the system treats the checkpoint as empty and reports "deploy incomplete at checkpoint stage=None", which hides the real cause.

1.10 WHEN a step that needs model judgment (save foundation assessment or save IaC change plan) has not been completed and the model ends its invoke THEN the system reports only "deploy incomplete at checkpoint stage=…" and does not name the missing judgment artifact.

### Expected Behavior (Correct)

2.1 WHEN the deploy checkpoint stage is `transform_init_done` THEN the system SHALL start the Transform analyze job with deterministic code, persist the analyze job id on the run META, write the analyze-started artifact, and advance the checkpoint to `transform_analyze_started`, whether or not the model calls `transform_start_analyze`.

2.2 WHEN the deploy checkpoint stage is `pre_discover_done` THEN the system SHALL run Transform init with deterministic code and advance the checkpoint to `transform_init_done`, then continue with the next mechanical step in the same invoke.

2.3 WHEN the Transform analyze job has completed (stage `transform_analyze_done`) THEN the system SHALL run the merge into foundation.json with deterministic code and advance the checkpoint to `transform_merged` before the model performs the foundation assessment.

2.4 WHEN the IaC change plan has been saved THEN the system SHALL render the IaC bundles with deterministic code and advance the checkpoint to `iac_render_done`.

2.5 WHEN the deploy checkpoint stage is `iac_render_done` THEN the system SHALL start the Transform deploy job with deterministic code, persist the deploy job id, and advance the checkpoint to `transform_deploy_started`.

2.6 WHEN the Transform deploy job has completed (stage `transform_deploy_done`) THEN the system SHALL run post-discover with deterministic code and advance the checkpoint to `post_discover_done`.

2.7 WHEN the deploy checkpoint stage is `post_discover_done` and every required deployment artifact exists THEN the system SHALL mark the checkpoint `agent_complete` with deterministic code and return status `ok` to the orchestrator. WHEN any required artifact is missing THEN the system SHALL fail with an error that lists the missing artifact keys.

2.8 WHEN a deterministic workflow step fails THEN the system SHALL return status `error` with a message that names the failing step and the underlying cause. For an HTTP 403 from a Transform job API, the message SHALL also name the calling principal and say that the principal needs Contributor (or higher) membership in the Transform workspace identified by `TRANSFORM_WORKSPACE_ID`. The system SHALL NOT swallow the error, retry and then give up silently, or move the checkpoint forward.

2.9 WHEN reading the deploy checkpoint fails for any reason other than the checkpoint object not existing THEN the system SHALL fail with an error that names the checkpoint key and the underlying error. WHEN the checkpoint object does not exist THEN the system SHALL treat the run as not started.

2.10 WHEN the model ends its invoke and a judgment step (foundation assessment or IaC change plan) is still incomplete THEN the system SHALL NOT produce that artifact with deterministic code or heuristics. It SHALL return status `error` with a message that names the incomplete judgment step and the missing artifact key.

2.11 WHEN a Transform analyze or deploy job is still running or is waiting for human approval after a deterministic poll THEN the system SHALL put the checkpoint in the matching wait stage (`transform_analyze_waiting` / `transform_deploy_waiting`, with `awaitingHitl` set as reported) and return status `continue`, so a run is never marked FAILED only because the model ended its invoke early.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a deploy run's checkpoint is in a wait stage (`paused`, `transform_analyze_waiting`, `transform_deploy_waiting`) or `awaitingHitl` is true THEN the system SHALL CONTINUE TO return status `continue` with reason, awaitingHitl and jobId, so Step Functions waits (60s for HITL, 30s otherwise) and re-invokes the same AgentCore session.

3.2 WHEN pre-discover fails (for example Organizations not enabled in the target account or wrong credentials) THEN the system SHALL CONTINUE TO save checkpoint `pre_discover_blocked` with `awaitingHitl=true` and return status `continue`, with the target-account guidance that says not to create an organization in the platform account.

3.3 WHEN pre-discover, post-discover or attestation run THEN the system SHALL CONTINUE TO use target-account credentials for the deploy target. WHEN any Transform API is called THEN the system SHALL CONTINUE TO use platform SigV4 credentials and `TRANSFORM_WORKSPACE_ID`.

3.4 WHEN the model calls any existing deploy workflow tool directly THEN the system SHALL CONTINUE TO run that tool with the same effects, write the same artifacts and checkpoint stages, and enforce the one-poll-per-invoke limit on Transform polling tools.

3.5 WHEN the foundation assessment (greenfield/brownfield with rationale) and the IaC change plan are produced THEN the system SHALL CONTINUE TO have the model produce them through `save_foundation_assessment` and `save_iac_change_plan`, using Transform MCP and platform context.

3.6 WHEN any workflow step runs, whether called by the model or by deterministic code, THEN the system SHALL CONTINUE TO write audit events through `log_tool_event` to the run's DynamoDB audit trail and to keep the checkpoint at `runs/{deployRunId}/deployment/agent-checkpoint.json`.

3.7 WHEN a deploy run reaches `agent_complete` with all required artifacts THEN the system SHALL CONTINUE TO return status `ok`, after which the phase-invoke Lambda runs attestation and registers the foundation-assessment, iac-change-plan, iac-manifest and deployment-report artifacts.

3.8 WHEN the intake (design) phase is invoked THEN the system SHALL CONTINUE TO run the intake agent with the same tools and prompt and to complete only when `scope.json` is saved.

3.9 WHEN an unknown agent phase is requested THEN the system SHALL CONTINUE TO return an error naming the unknown phase.
