# Deploy Transform Init Stall Fix Bugfix Design

## Overview

Deploy runs fail with `deploy incomplete at checkpoint stage='transform_init_done'` because the model owns sequencing of the deploy workflow. When it ends an invoke after a mechanical step (here `transform_init_connection`), `_deploy_invoke_result` in `agent/app.py` sees a stage that is neither terminal nor a wait stage and returns an error. The same failure exists for every mechanical stage (pre_discover_done, transform_analyze_done, iac_render_done, transform_deploy_done, post_discover_done) and for "plan saved, bundles not rendered".

The fix replaces model-driven sequencing with a deterministic stage sequencer in the deploy invoke path. The sequencer reads the checkpoint, runs every mechanical step in the fixed workflow order using the same `_execute_*` implementations the tools use, and invokes the model at most once per invoke, only for the two judgment steps (`save_foundation_assessment`, `save_iac_change_plan`). The v8 patches `ensure_pre_discover()` and `ensure_transform_job_progress_after_agent()` are removed and their behavior is absorbed into the sequencer.

Three error-surface fixes ride along because the sequencer depends on them:
- Checkpoint and artifact-existence reads treat only "object does not exist" as absent. Every other S3 error raises with the key and cause (2.9).
- Every sequencer step failure returns `status: error` naming the step and cause. A Transform HTTP 403 also names the calling principal and the workspace Contributor fix (2.8).
- When the model ends its invoke with a judgment step incomplete, the run fails with the step and missing artifact key (2.10).

Decision on 2.10: the sequencer does not re-invoke the model within an invoke when a judgment step is incomplete. A bounded in-process retry would mask a model that cannot or will not produce the artifact, which conflicts with the no-retry-then-surrender rule. Step Functions already owns re-invocation for legitimate waits. The only path back to the model is an explicit `yield_for_orchestrator` call, which is a defined wait stage (3.1) and is bounded by the existing 200-cycle `ContinueLimitChoice`.

Context: the two failed executions (`fb8adcc522b64a719183b9e48ee013fb`, `d404c9262f76462e8de677b748746fb4`) ran before agent image v8. No live run has exercised v8, so the v8 patch is unvalidated and is replaced rather than extended.

## Glossary

- **Bug_Condition (C)**: The deploy invoke ends (the model returns) while the checkpoint is at a mechanical stage, or a deterministic step or checkpoint read fails in a way that is reported without naming the step, key, principal, or missing judgment artifact.
- **Property (P)**: The invoke result is `ok`, `continue`, or `error` whose message names a workflow step or artifact key. A mechanical stage is never left for the model to advance.
- **Preservation**: Wait/HITL semantics, pre-discover blocking, credential split (target vs platform SigV4), tool behavior when the model calls tools directly, model ownership of judgment artifacts, audit trail, attestation, intake phase, and unknown-phase errors.
- **Mechanical stage**: A checkpoint stage whose next step needs no judgment: `None` (no checkpoint), `pre_discover_blocked`, `pre_discover_done`, `transform_init_done`, `transform_analyze_started`, `transform_analyze_waiting`, `transform_analyze_done`, `transform_merged` with both judgment artifacts present, `iac_render_done`, `transform_deploy_started`, `transform_deploy_waiting`, `transform_deploy_done`, `post_discover_done`.
- **Judgment stage**: `transform_merged` with `foundation-assessment.json` or `iac-change-plan.json` missing. Only the model may produce these artifacts.
- **Wait stage**: `paused`, `transform_analyze_waiting`, `transform_deploy_waiting`, or any checkpoint with `awaitingHitl=true`. The invoke returns `continue`.
- **Sequencer**: New `run_deploy_invoke(run_model)` in `agent/deploy_workflow_tools.py`. Loops over checkpoint stages and dispatches to step implementations.
- **Step**: A named unit (`run_pre_discover`, `transform_init_connection`, `transform_start_analyze`, `transform_poll_analyze_job`, `transform_merge_discovery`, `render_iac_bundles`, `transform_start_deploy`, `transform_poll_deploy_job`, `run_post_discover`, `finish_deploy_workflow`). Step names match tool names so audit and error messages line up.
- **`_execute_*`**: Shared implementation behind each tool. Tools and sequencer both call it, so artifacts, checkpoint stages and audit events are identical (3.4, 3.6).
- **`resumeStage`**: New field written by `yield_for_orchestrator` so a `paused` checkpoint records the stage to resume from.
- **Poll budget**: `base._state["polls_this_invoke"]`, reset per invoke by `set_deploy_run`. Shared by tools and sequencer. At most one Transform poll per invoke.
- **`TransformAccessDenied`**: New exception in `lzcore/transform_ops.py` raised for HTTP 403 from a Transform API call. Carries operation, workspace id, and calling principal.

## Bug Details

### Bug Condition

The bug manifests when the deploy invoke reaches the end of `_deploy_agent()` and the checkpoint is at a stage the model was expected to advance but did not. `_deploy_invoke_result` treats any non-terminal, non-wait stage as failure. The v8 patch only covers `transform_init_done`, `transform_analyze_started` and `transform_deploy_started`, so the other mechanical stages still fail. Separately, `_load_checkpoint` and `_read_checkpoint` swallow every exception into `{}`, which surfaces as `stage=None`. Transform 403s surface as a generic `HTTP 403: …` without step, principal, or fix.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type DeployInvoke {
           checkpoint: Checkpoint | ReadError,
           modelOutcome: {calledTools: list, savedAssessment: bool, savedPlan: bool, yielded: bool},
           stepOutcome: Success | Failure(cause),
           artifacts: set of present keys
         }
  OUTPUT: boolean

  stageAfterModel := checkpoint stage after the model returns

  RETURN (stageAfterModel IN MECHANICAL_STAGES
          AND NOT modelOutcome.yielded)                              // 1.1–1.7
      OR (input.checkpoint IS ReadError AND ReadError.code NOT IN {NoSuchKey, 404})   // 1.9
      OR (input.stepOutcome IS Failure AND Failure.cause.httpStatus = 403
          AND step IN TRANSFORM_STEPS)                               // 1.8
      OR (stageAfterModel = "transform_merged"
          AND (NOT savedAssessment OR NOT savedPlan)
          AND NOT modelOutcome.yielded)                              // 1.10
END FUNCTION
```

### Examples

- Run `fb8adcc5…`: checkpoint `transform_init_done`, model ends after 20s. Actual: `deploy incomplete at checkpoint stage='transform_init_done'`, no analyze job. Expected: sequencer calls `_execute_transform_start_analyze()`, checkpoint becomes `transform_analyze_started`, then polls once and returns `continue` with `transform_analyze_waiting`.
- Checkpoint `pre_discover_done`, model ends. Actual: FAILED. Expected: init, start analyze, poll, `continue`. The model is not invoked at all.
- Model saves plan, ends without rendering. Actual: FAILED (stage still `transform_merged`). Expected: sequencer renders (`iac_render_done`), starts deploy (`transform_deploy_started`), and returns `continue` because the poll budget for this invoke may already be used.
- S3 `GetObject` on `agent-checkpoint.json` returns `AccessDenied`. Actual: `deploy incomplete at checkpoint stage=None`. Expected: `error: cannot read deploy checkpoint s3://…/runs/{id}/deployment/agent-checkpoint.json: AccessDenied …`.
- CreateJob for analyze returns 403. Actual: `transform_start_analyze failed: HTTP 403: …` (v8) or generic. Expected: `transform_start_analyze failed: Transform CreateJob returned HTTP 403 for principal arn:aws:sts::831493647146:assumed-role/…; add this principal as Contributor (or higher) in Transform workspace <TRANSFORM_WORKSPACE_ID>. Cause: …`.
- Edge: model ends at `transform_merged` with assessment saved, plan missing, no yield. Expected: `error: judgment step save_iac_change_plan incomplete: missing runs/{id}/deployment/iac-change-plan.json`. No model re-invoke.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Wait stages and `awaitingHitl` return `continue` with `reason`, `awaitingHitl`, `jobId`. `phase_invoke` maps to 60s/30s waits. `deployment.asl.json` is not changed (3.1).
- Pre-discover failure saves `pre_discover_blocked` with `awaitingHitl=true` and the target-account guidance text, then returns `continue`. The next invoke retries pre-discover (3.2).
- Pre/post-discover and attestation use `deploy_boto_session()`. Transform uses platform SigV4 and `TRANSFORM_WORKSPACE_ID` (3.3).
- Every `@tool` keeps its signature, return text, artifacts, checkpoint stages, and the one-poll-per-invoke refusal (3.4).
- Foundation assessment and IaC plan are produced only by the model through `save_foundation_assessment` / `save_iac_change_plan`, with Transform MCP available (3.5).
- `log_tool_event` events and checkpoint key `runs/{deployRunId}/deployment/agent-checkpoint.json` are unchanged (3.6).
- `agent_complete` with all artifacts returns `ok`; `phase_invoke` attests and registers artifacts (3.7).
- Intake branch in `app.py` unchanged (3.8). Unknown phase returns `unknown phase …` (3.9).

**Scope:**
Inputs where the bug condition does not hold are unaffected. This includes:
- Invokes that end in a wait stage or `agent_complete`.
- Model-driven tool calls that advance the workflow themselves (the sequencer then finds the stage already advanced and continues from there).
- Intake-phase invokes and unknown-phase invokes.
- Successful checkpoint reads and missing-checkpoint (NoSuchKey) reads.
- Transform errors other than 403 keep their message, now prefixed with the step name.

## Hypothesized Root Cause

1. **Model owns sequencing**: `DEPLOY_PROMPT` asks the model to run all 11 steps. Ending a turn after `transform_init_connection` is a normal LLM outcome (the tool result reads like a completed action). The runtime has no deterministic driver, only a post-hoc stage check that fails.
   - Confirmed by the audit trail: three tool calls, then "Invocation completed successfully (20s)".
2. **Post-hoc patching is partial**: v8 `ensure_transform_job_progress_after_agent()` covers three stages after the model returns. Merge, render, start deploy, post-discover and finish are not covered, and `ensure_pre_discover()` is a second, separate patch keyed on `foundation.json` presence rather than the checkpoint.
3. **Swallowed checkpoint errors**: `app._load_checkpoint` and `deploy_workflow_tools._read_checkpoint` use `except Exception: return {}`. `read_deploy_checkpoint` does the same. `ensure_pre_discover`, `_validate_deploy_artifacts` and `finish_deploy_workflow` treat any `head_object` exception as "missing".
4. **Undifferentiated Transform errors**: `transform_api_client._call_boto3` raises `HttpError(status_code=403)`. `transform_ops` lets it propagate untranslated, and `_discover_sigv4_regions` drops per-region errors entirely, so a 403 during init becomes "Transform SigV4 probe failed".
5. **Lost resume point on pause**: `yield_for_orchestrator` overwrites the stage with `paused`, so a deterministic driver cannot tell where to resume.

## Correctness Properties

Property 1: Bug Condition - Deterministic progression and named failures

_For any_ deploy invoke where the bug condition holds (isBugCondition returns true), the fixed invoke SHALL either advance the checkpoint through every mechanical stage in workflow order until it reaches a wait stage, a judgment stage, or `agent_complete`, returning `continue` or `ok`; or return `status: error` whose message names the failing step (and for Transform HTTP 403, the calling principal and the Contributor membership needed in `TRANSFORM_WORKSPACE_ID`), the unreadable checkpoint key and cause, or the incomplete judgment step and its missing artifact key. The result SHALL never be `deploy incomplete at checkpoint stage=…`, and the checkpoint SHALL NOT advance past a failed step.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11**

Property 2: Preservation - Wait semantics, tool behavior, and judgment ownership

_For any_ deploy or intake invoke where the bug condition does NOT hold (isBugCondition returns false), the fixed code SHALL produce the same result as the original code: wait stages and HITL return `continue` with the same fields, pre-discover failures return the same blocked payload, directly called tools write the same artifacts, checkpoint stages and audit events and enforce the one-poll limit, judgment artifacts are written only by the model's save tools, `agent_complete` returns `ok`, and intake and unknown-phase behavior is unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct:

**File**: `agent/deploy_workflow_tools.py`

**Functions**: new `run_deploy_invoke`, `read_checkpoint`, `object_exists`, `DeployStepError`; refactored `_execute_*`; removed `ensure_pre_discover`, `ensure_transform_job_progress_after_agent`, `_read_checkpoint`

**Specific Changes**:
1. **Strict S3 reads**: Add `read_checkpoint() -> dict | None` and `object_exists(key) -> bool`. Only `ClientError` codes `NoSuchKey`, `404`, `NotFound` mean absent. Any other exception raises `RuntimeError(f"cannot read {key}: {cause}")`. Replace `_read_checkpoint`, the `read_deploy_checkpoint` try/except, and all `head_object` existence checks (`finish_deploy_workflow`, pre-discover presence) with these.
2. **Extract `_execute_*` for every mechanical step**: `_execute_transform_init`, `_execute_merge`, `_execute_render`, `_execute_transform_start_deploy`, `_execute_post_discover`, `_execute_finish() -> list[str]` (missing keys). Each `@tool` becomes a thin wrapper: mode check, poll-budget check where it exists today, call `_execute_*`, format the same return string. Tool output text is unchanged.
3. **Record resume point on pause**: `yield_for_orchestrator` reads the current stage first and writes `resumeStage=<that stage>` alongside `stage="paused"`. If the current checkpoint is itself `paused`, it keeps the existing `resumeStage`.
4. **Sequencer**: `run_deploy_invoke(run_model: Callable[[], object]) -> dict`:
   ```
   STEPS = {
     None:                        ("run_pre_discover",          _execute_pre_discover_or_block),
     "pre_discover_blocked":      ("run_pre_discover",          _execute_pre_discover_or_block),
     "pre_discover_done":         ("transform_init_connection", _execute_transform_init),
     "transform_init_done":       ("transform_start_analyze",   _execute_transform_start_analyze),
     "transform_analyze_started": ("transform_poll_analyze_job", poll(analyze)),
     "transform_analyze_waiting": ("transform_poll_analyze_job", poll(analyze)),
     "transform_analyze_done":    ("transform_merge_discovery", _execute_merge),
     "iac_render_done":           ("transform_start_deploy",    _execute_transform_start_deploy),
     "transform_deploy_started":  ("transform_poll_deploy_job", poll(deploy)),
     "transform_deploy_waiting":  ("transform_poll_deploy_job", poll(deploy)),
     "transform_deploy_done":     ("run_post_discover",         _execute_post_discover),
     "post_discover_done":        ("finish_deploy_workflow",    _execute_finish),
   }

   FUNCTION run_deploy_invoke(run_model)
     model_ran := false; pre_discover_attempted := false
     cp := read_checkpoint()                         // raises on non-404 errors
     stage := cp.stage IF cp ELSE None
     IF stage = "paused":
        IF cp.resumeStage missing: RETURN error("checkpoint stage 'paused' has no resumeStage; cannot resume")
        stage := cp.resumeStage
     REPEAT at most MAX_STEPS_PER_INVOKE (= len(workflow) + 2) times:
        IF stage = "agent_complete": RETURN validate_complete()      // ok, or error listing missing keys
        IF stage = "transform_merged":
           missing := judgment_missing()            // [(step, key)] for assessment, plan
           IF missing empty: run step "render_iac_bundles"; stage := read stage; CONTINUE
           IF model_ran: RETURN error(f"judgment step {missing[0].step} incomplete: missing {missing[0].key}")
           run_model(); model_ran := true
           cp := read_checkpoint()
           IF cp.stage = "paused" OR cp.awaitingHitl: RETURN continue_from(cp)
           stage := cp.stage; CONTINUE
        IF stage NOT IN STEPS: RETURN error(f"unknown deploy checkpoint stage {stage!r}")
        (name, fn) := STEPS[stage]
        IF name IS poll AND polls_this_invoke >= 1: RETURN continue(reason=f"{name} already polled this invoke", jobId)
        IF name = "run_pre_discover" AND pre_discover_attempted: RETURN continue_from(read_checkpoint())
        TRY fn() EXCEPT e: RETURN step_error(name, e)   // checkpoint untouched by failed step
        log_tool_event("deploy.sequencer.step", {"step": name, "fromStage": stage})
        cp := read_checkpoint(); stage := cp.stage
        IF stage IN WAIT_STAGES OR cp.awaitingHitl: RETURN continue_from(cp)
        IF name = "finish_deploy_workflow" AND _execute_finish returned missing keys:
           RETURN error(f"finish_deploy_workflow: missing artifacts {keys}")
     RETURN error(f"deploy sequencer made no progress within {MAX} steps at stage {stage!r}")
   END FUNCTION
   ```
   - Poll steps increment `polls_this_invoke` before calling `_execute_transform_poll_*_once`, sharing the budget with the tools.
   - `_execute_pre_discover_or_block` keeps today's `ensure_pre_discover` failure handling: on exception it saves `pre_discover_blocked` with the target-account guidance and `awaitingHitl=true`. That stage is a wait (awaitingHitl), so the sequencer returns `continue` (3.2). It is a defined HITL wait, not a swallowed error: the message is persisted, audited, and returned.
   - The model is invoked at most once per invoke and only from the judgment stage. Everything the model does with tools is picked up by re-reading the checkpoint afterwards.
   - `MAX_STEPS_PER_INVOKE` is a convergence guard for a stage that does not advance (a coding defect). Reaching it is an explicit error, not a silent stop.
5. **Step error formatting**: `step_error(name, e)` returns `{"status": "error", "error": f"{name} failed: {cause}"}`. For `TransformAccessDenied` the cause already contains operation, principal and workspace. Log `tool.{name}.failed` with the message, matching the v8 event names.

**File**: `lzcore/transform_ops.py`

**Specific Changes**:
1. **`TransformAccessDenied(RuntimeError)`**: Fields `operation`, `workspace_id`, `principal_arn`, `cause`. Message: `Transform {operation} returned HTTP 403 for principal {principal_arn}; add this principal as Contributor (or higher) in Transform workspace {workspace_id} (TRANSFORM_WORKSPACE_ID). Cause: {cause}`.
2. **`_call(operation, request)` wrapper** around `call_transform_api`, used by `_create_and_start_job`, `_send`, `_get_job`. On `HttpError` with `status_code == 403`, resolve the principal with `boto3.client("sts").get_caller_identity()["Arn"]` (default session = platform SigV4 credentials, same as `AwsHelper.create_session()`) and raise `TransformAccessDenied ... from exc`. If the STS call itself fails, the message states `calling principal could not be resolved: {sts error}` explicitly instead of a placeholder value. Other errors propagate unchanged.
3. **Probe diagnostics**: `_discover_sigv4_regions` returns per-region errors alongside successes. When no region succeeds, `init_connection` raises with the per-region causes; if any is a 403, raise `TransformAccessDenied` with operation `ListWorkspaces`.

**File**: `lzcore/deploy_transform.py`

**Specific Changes**:
1. **`merge_transform_into_foundation`**: Remove the `except Exception` fallbacks that substitute `{}` for `foundation.json` and `transform-poll-analyze.json`. Missing or unreadable inputs raise naming the key. The sequencer only reaches merge after a successful analyze poll, so both files exist in a correct run.

**File**: `agent/app.py`

**Specific Changes**:
1. **Deploy branch**: `tools.set_deploy_run(run_id)` then `return run_deploy_invoke(lambda: _deploy_agent(DEPLOY_PROMPT.format(run_id=run_id)))`.
2. **Remove** `_WAIT_STAGES`, `_load_checkpoint`, `_deploy_invoke_result`, `_validate_deploy_artifacts`, and imports of `ensure_pre_discover` / `ensure_transform_job_progress_after_agent`. Completion validation moves into the sequencer (`validate_complete`, strict existence checks).
3. **Outer except**: raise the truncation from 500 to 2000 characters so step, principal and workspace survive into `phase_invoke`'s `RuntimeError` and the SFN failure cause.

**File**: `agent/prompts.py`

**Specific Changes**:
1. **`DEPLOY_PROMPT`**: Replace the 11-step procedure with the judgment task: mechanical steps are run by the orchestrator; read_deploy_context, inspect the analyze job with Transform MCP, call `save_foundation_assessment`, then `read_approved_scope` / `get_catalog` and `save_iac_change_plan`; call `yield_for_orchestrator` only when Transform needs human input before a judgment can be made. Keep the plan JSON example.
2. **`DEPLOY_SYSTEM`**: Replace "You orchestrate discover, AWS Transform…" and "After post-discover, call finish_deploy_workflow" with the judgment-only role. Keep the 403, cross-account, and no-create-organization rules.
3. Workflow tools stay registered on the deploy agent (3.4).

**Not changed**: `orchestration/deployment.asl.json`, `orchestration/lambdas/phase_invoke.py`, `lzcore/deploy_artifacts.py`, intake tools.

**Noted, not in scope (needs a decision)**: `transform_ops.poll_job` treats `STOPPED`/`CANCELLED`/`CANCELED` as `done`, and `poll_transform_job` raises only on `FAILED`. With deterministic sequencing, a cancelled analyze job would flow into merge without a model looking at it. Recommend treating these as failures in a follow-up, or in this fix if you agree.

**Operational note**: one invoke can now cover analyze-done → merge → model judgment → render → start deploy. `phase_invoke` uses a 900s read timeout. Model judgment is the dominant cost, and start-deploy adds init + CreateJob + StartJob + SendMessage + GetJob. If this approaches the timeout, the sequencer can return `continue` after render (stage `iac_render_done` is mechanical, so the next invoke starts the deploy). Not planned unless timing on a live run shows it is needed.

## Testing Strategy

### Validation Approach

First, run exploration tests against the unfixed `app.invoke` deploy path to reproduce the stall at each mechanical stage and the swallowed checkpoint error. Then verify the sequencer against every stage and preserve tool and wait semantics.

Tests live in `orchestration/tests/test_deploy_sequencer.py` and `lzcore/tests/test_transform_errors.py`, run with `python -m unittest` (or pytest) from the repo root. `strands` and `bedrock_agentcore` are not installed locally, so each test explicitly installs stub modules in `sys.modules` (identity `tool` decorator, stub `BedrockAgentCoreApp`) and sets `STATE_TABLE`, `ARTIFACT_BUCKET`, `MODEL_ID`, `TRANSFORM_WORKSPACE_ID` before import. Fixtures installed per test: `FakeS3` (dict-backed; configurable per-key `ClientError` such as `AccessDenied`; `NoSuchKey`/`404` for absent keys), `FakeTable` (records `update_item`/`put_item` for META and audit), fake `transform_ops` functions (configurable job status sequence and `HttpError(403)`), fake STS, and a scripted model callable that performs a given list of tool calls and optionally saves judgment artifacts or yields. No fixture is a default the application picks up.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples on unfixed code. Confirm or refute that the model ending early at mechanical stages is the cause.

**Test Plan**: Drive `app.invoke({"runId", "phase": "deploy"})` with a scripted model that calls tools up to stage S and returns. Run on UNFIXED code.

**Test Cases**:
1. **Init stall**: model calls `read_deploy_checkpoint`, `transform_init_connection`, returns. Expect on unfixed v8: analyze started by patch; on pre-v8 (`git stash` the uncommitted diff): `deploy incomplete at checkpoint stage='transform_init_done'` (will fail).
2. **Merge stall**: checkpoint `transform_analyze_done`, model returns without tools. Expect `deploy incomplete … 'transform_analyze_done'` (will fail).
3. **Render/deploy/post/finish stalls**: same for plan-saved, `iac_render_done`, `transform_deploy_done`, `post_discover_done` (will fail).
4. **Checkpoint AccessDenied**: FakeS3 raises `AccessDenied` on the checkpoint key. Expect `stage=None` message (will fail).
5. **CreateJob 403**: fake Transform raises `HttpError(403)` on CreateJob. Expect message without principal or workspace (will fail).

**Expected Counterexamples**:
- `deploy incomplete at checkpoint stage='<mechanical stage>'` for each mechanical stage outside v8's three.
- `stage=None` for a non-404 checkpoint read error.
- Possible causes: model owns sequencing; partial post-hoc patch; broad `except Exception`.

### Fix Checking

**Goal**: For every input where the bug condition holds, the fixed invoke produces P.

**Pseudocode:**
```
FOR ALL stage IN MECHANICAL_STAGES ∪ {judgment variants}
    , modelScript IN {no-op, partial tools, saves assessment only, saves both}
    , transformOutcome IN {running, awaiting HITL, done, HTTP 403, other error}
    , checkpointRead IN {ok, NoSuchKey, AccessDenied} DO
  result := run_deploy_invoke_fixed(input)
  ASSERT result.status IN {"ok", "continue", "error"}
  ASSERT "deploy incomplete at checkpoint stage" NOT IN result.error
  IF result.status = "error":
     ASSERT result.error names a STEP name OR an artifact/checkpoint key
     IF transformOutcome = 403: ASSERT principal ARN AND TRANSFORM_WORKSPACE_ID AND "Contributor" IN result.error
     ASSERT checkpoint stage did not advance past the failed step
  IF result.status = "continue": ASSERT final checkpoint stage IN WAIT_STAGES OR awaitingHitl OR poll budget used
END FOR
```

### Preservation Checking

**Goal**: For every input where the bug condition does not hold, fixed behavior equals original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT invoke_original(input) = invoke_fixed(input)
END FOR
```

**Testing Approach**: The stage domain is finite (13 stages plus `paused`/`agent_complete`), so the property test enumerates the full cross product with `unittest.subTest` instead of random sampling. This avoids a new dependency (`hypothesis` is not installed) and gives exhaustive coverage of the stage space. Model scripts and Transform outcomes are enumerated the same way.

**Test Plan**: Capture results from unfixed code for non-bug inputs (wait stages, pre-discover failure, direct tool calls), then assert the fixed code matches.

**Test Cases**:
1. **Wait stage preservation**: checkpoint `paused` (written by fixed `yield_for_orchestrator` with `resumeStage`) at end of model run, `transform_*_waiting`, `awaitingHitl=true` → same `continue` payload fields as original.
2. **Pre-discover blocked preservation**: target session raises "Organizations not in use" → `pre_discover_blocked`, `awaitingHitl=true`, guidance text, `continue`, identical to original `ensure_pre_discover` output.
3. **Direct tool preservation**: call each `@tool` with the same fixtures on original and fixed code; compare return strings, S3 writes, checkpoint stages, audit events. Second poll in one invoke returns the same `REFUSED` text.
4. **Judgment ownership**: across every enumerated path, `foundation-assessment.json` and `iac-change-plan.json` are only written when the scripted model calls the save tools.
5. **Intake and unknown phase**: unchanged results.

### Unit Tests

- `read_checkpoint` / `object_exists`: present, `NoSuchKey`, `404`, `AccessDenied`, KMS error → value, None/False, raise with key.
- Each `STEPS` entry advances exactly one stage with the expected artifact and audit event.
- Poll budget shared between tool and sequencer: a model poll followed by sequencer at a poll stage → `continue`, no second Transform call.
- `paused` without `resumeStage` → error naming the checkpoint condition.
- `TransformAccessDenied` message for CreateJob, StartJob, SendMessage, GetJob and probe `ListWorkspaces`; STS failure → explicit "could not be resolved" text.
- `merge_transform_into_foundation` raises naming the missing key.
- `finish` with missing artifacts → error listing keys; with all present → `ok`.
- Updated prompt tests: `DEPLOY_PROMPT.format(run_id=…)` succeeds and the plan example still parses.

### Property-Based Tests

- Exhaustive stage property: for every checkpoint stage × model script × Transform outcome, the result is `ok`, `continue`, or an error naming a step or artifact, and never `deploy incomplete at checkpoint stage=…`.
- Monotonic progress: for every success path, the recorded checkpoint stage sequence is a prefix-ordered subsequence of the canonical workflow order, and no stage is skipped.
- Failure atomicity: for every injected step failure, the checkpoint stage after the invoke equals the stage before the failed step.

### Integration Tests

- Full happy path across invokes with fakes: invoke 1 (pre-discover → init → start analyze → poll: running → `continue`), invoke 2 (poll: done → merge → model saves both → render → start deploy → `continue` on poll budget), invoke 3 (poll: done → post-discover → finish → `ok`). Assert the audit event order and final artifacts match `deployment_artifact_keys`.
- HITL path: analyze poll reports `AWAITING_HUMAN_INPUT` → `continue` with `awaitingHitl=true` → `phase_invoke` returns `waitSeconds=60`.
- Live validation (manual, after deploying the new image): one deploy run against target `556880010183`; confirm in the audit trail that `deploy.sequencer.step` events appear for each mechanical stage and the run reaches DELIVERED or fails with a named step.
