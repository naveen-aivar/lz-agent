# Implementation Plan

Dependency order follows the design's "Fix Implementation" section: strict S3 reads →
Transform error translation (including cancelled-job failure) → merge input strictness →
`_execute_*` extraction + `yield_for_orchestrator` resume point → `run_deploy_invoke`
sequencer → `app.py` cut-over → prompt narrowing. Exploration and preservation tests are
written and run against the UNFIXED code first.

Test harness note (applies to every test task): `strands` and `bedrock_agentcore` are not
installed locally. Each test module MUST explicitly install stub modules in `sys.modules`
(identity `tool` decorator, stub `BedrockAgentCoreApp`) and set `STATE_TABLE`,
`ARTIFACT_BUCKET`, `MODEL_ID`, `TRANSFORM_WORKSPACE_ID` BEFORE importing `agent.app` /
`agent.deploy_workflow_tools`. Fixtures (`FakeS3`, `FakeTable`, fake `transform_ops`, fake
STS, scripted model callable) are installed per test and MUST NOT be a default the
application picks up when configuration is absent.

---

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Deterministic progression and named failures
  - **CRITICAL**: These tests MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: These tests encode the expected behavior - they will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate the model-owned-sequencing stall and the swallowed/undifferentiated errors
  - **Scoped PBT Approach**: The bug is deterministic per stage, so scope the property to the concrete failing stages enumerated below rather than random input generation
  - Create `orchestration/tests/test_deploy_sequencer.py`; install strands/bedrock_agentcore stubs and env vars before importing `agent.app`
  - Drive `app.invoke({"runId": ..., "phase": "deploy"})` with a scripted model that calls tools up to a given stage and returns; run on UNFIXED code
  - Case A (init stall): model calls `read_deploy_checkpoint`, `transform_init_connection`, returns. On pre-v8 (`git stash` the uncommitted v8 diff) expect `deploy incomplete at checkpoint stage='transform_init_done'` (from Bug Condition 1.1)
  - Case B (merge stall): checkpoint `transform_analyze_done`, model returns without tools; expect `deploy incomplete … 'transform_analyze_done'` (1.3)
  - Case C (render / start-deploy / post-discover / finish stalls): plan saved, `iac_render_done`, `transform_deploy_done`, `post_discover_done` each with model returning early; expect the matching `deploy incomplete` message (1.4, 1.5, 1.6, 1.7)
  - Case D (checkpoint AccessDenied): `FakeS3` raises `ClientError(AccessDenied)` on the checkpoint key; expect the swallowed `stage=None` message (1.9)
  - Case E (CreateJob 403): fake `transform_ops` raises `HttpError(403)` on CreateJob; expect a generic message with no principal / workspace / Contributor guidance (1.8)
  - Case F (judgment incomplete): checkpoint `transform_merged` with a judgment artifact missing, model returns without saving; expect only `deploy incomplete at checkpoint stage=…` with no named artifact key (1.10)
  - Case G (cancelled analyze job): fake Transform reports job status `CANCELLED`; expect `poll_job` / `poll_transform_job` to treat it as `done` and flow into merge on unfixed code (this is the silent substitution being fixed)
  - Run all cases on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct - it proves the bug exists)
  - Document counterexamples found in test comments to understand root cause
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Wait semantics, tool behavior, and judgment ownership
  - **IMPORTANT**: Follow observation-first methodology - observe behavior on UNFIXED code, record it, then assert it
  - In `orchestration/tests/test_deploy_sequencer.py` (preservation section) and a new `lzcore/tests/test_transform_errors.py`, using the same stubs/fixtures
  - Observe and capture on UNFIXED code, then assert the fixed code matches:
    - Wait stages: checkpoint `paused`, `transform_analyze_waiting`, `transform_deploy_waiting`, and `awaitingHitl=true` each return `continue` with `reason`, `awaitingHitl`, `jobId` (3.1)
    - Pre-discover blocked: target session raises "Organizations not in use" → checkpoint `pre_discover_blocked`, `awaitingHitl=true`, target-account guidance text, `continue` (3.2)
    - Credential split: pre/post-discover and attestation use `deploy_boto_session()`; Transform calls use platform SigV4 and `TRANSFORM_WORKSPACE_ID` (3.3)
    - Direct tool calls: call each `@tool` with the same fixtures; capture return strings, S3 writes, checkpoint stages, audit events; a second poll in one invoke returns the same `REFUSED` text (one-poll limit) (3.4)
    - Judgment ownership: `foundation-assessment.json` / `iac-change-plan.json` written only when the scripted model calls the save tools (3.5)
    - Audit + checkpoint key: `log_tool_event` events and checkpoint key `runs/{deployRunId}/deployment/agent-checkpoint.json` unchanged (3.6)
    - `agent_complete` with all artifacts returns `ok` (3.7)
    - Intake phase: intake agent runs with same tools/prompt, completes on `scope.json` (3.8)
    - Unknown phase: returns `unknown phase …` error (3.9)
  - Write these as enumerated property tests using `unittest.subTest` across the stage / model-script / Transform-outcome cross product (no `hypothesis`)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [ ] 3. Fix for deploy transform mechanical-stage stall and undifferentiated errors

  - [ ] 3.1 Add strict S3 reads in `agent/deploy_workflow_tools.py`
    - Add `read_checkpoint() -> dict | None` and `object_exists(key) -> bool`
    - Only `ClientError` codes `NoSuchKey`, `404`, `NotFound` mean absent (return `None` / `False`)
    - Any other exception raises `RuntimeError(f"cannot read {key}: {cause}")` naming the key and cause
    - Replace `_read_checkpoint`, the `read_deploy_checkpoint` try/except, and all `head_object` existence checks (`finish_deploy_workflow`, pre-discover presence) with these
    - _Bug_Condition: isBugCondition where checkpoint IS ReadError and code NOT IN {NoSuchKey, 404}_
    - _Expected_Behavior: expectedBehavior names the checkpoint key and cause; missing object = not started_
    - _Requirements: 1.9, 2.9_

  - [ ] 3.2 Add Transform error translation and cancelled-job failure in `lzcore/transform_ops.py`
    - Add `TransformAccessDenied(RuntimeError)` with fields `operation`, `workspace_id`, `principal_arn`, `cause` and the message naming principal, Contributor membership, and `TRANSFORM_WORKSPACE_ID`
    - Add a `_call(operation, request)` wrapper around `call_transform_api` used by `_create_and_start_job`, `_send`, `_get_job`; on `HttpError` `status_code == 403` resolve the principal via `boto3.client("sts").get_caller_identity()["Arn"]` and raise `TransformAccessDenied ... from exc`; if the STS call itself fails, state `calling principal could not be resolved: {sts error}` explicitly (no placeholder value)
    - Probe diagnostics: `_discover_sigv4_regions` returns per-region errors alongside successes; when no region succeeds, `init_connection` raises with the per-region causes; if any is 403, raise `TransformAccessDenied` with operation `ListWorkspaces`
    - Cancelled-job failure (scope decision): `poll_job` / `poll_transform_job` MUST treat job status `STOPPED` / `CANCELLED` / `CANCELED` as a failure that raises naming the job id and status, NOT as `done`. Letting a cancelled analyze job flow into merge is a silent substitution and violates the no-fallbacks rule
    - _Bug_Condition: isBugCondition where stepOutcome IS Failure with httpStatus 403 in a Transform step; and cancelled job silently treated as done_
    - _Expected_Behavior: expectedBehavior names step, principal, workspace; cancelled job surfaces as named failure_
    - _Requirements: 1.8, 2.8, 2.11_

  - [ ] 3.3 Enforce merge input strictness in `lzcore/deploy_transform.py`
    - In `merge_transform_into_foundation`, remove the `except Exception` fallbacks that substitute `{}` for `foundation.json` and `transform-poll-analyze.json`
    - Missing or unreadable inputs raise naming the key
    - _Bug_Condition: merge substitutes empty inputs for missing/unreadable artifacts_
    - _Expected_Behavior: merge raises naming the missing/unreadable key_
    - _Requirements: 2.3, 2.8_

  - [ ] 3.4 Extract `_execute_*` for every mechanical step and record the resume point on pause
    - Add `_execute_transform_init`, `_execute_merge`, `_execute_render`, `_execute_transform_start_deploy`, `_execute_post_discover`, `_execute_finish() -> list[str]` (missing keys), and keep existing `_execute_transform_start_analyze` / poll executors
    - Each `@tool` becomes a thin wrapper: mode check, poll-budget check where it exists today, call `_execute_*`, format the SAME return string (tool output text unchanged)
    - `yield_for_orchestrator` reads the current stage first and writes `resumeStage=<that stage>` alongside `stage="paused"`; if the current checkpoint is already `paused`, keep the existing `resumeStage`
    - _Bug_Condition: n/a (refactor enabling the sequencer); must not change tool-facing behavior_
    - _Expected_Behavior: tools write identical artifacts, stages, audit events; pause records a resume stage_
    - _Requirements: 3.4, 3.1_

  - [ ] 3.5 Implement the `run_deploy_invoke` sequencer in `agent/deploy_workflow_tools.py`
    - Add `run_deploy_invoke(run_model: Callable[[], object]) -> dict` with the `STEPS` map and loop from the design's pseudocode
    - Read checkpoint strictly; resolve `paused` via `resumeStage` (error if missing: `checkpoint stage 'paused' has no resumeStage; cannot resume`)
    - For each mechanical stage dispatch to the step executor, re-read checkpoint, and return `continue` on wait stages / `awaitingHitl` / used poll budget; poll steps share `base._state["polls_this_invoke"]` and return `continue` on the second poll
    - `transform_merged`: if judgment artifacts present → render and continue; else invoke the model at most once; if still incomplete after the model ran → `error: judgment step {step} incomplete: missing {key}` (NO deterministic or heuristic substitution, NO in-process re-invoke)
    - `_execute_pre_discover_or_block` keeps today's `ensure_pre_discover` failure handling (save `pre_discover_blocked`, `awaitingHitl=true`, guidance, return `continue`)
    - Step failures return `step_error(name, e)` = `{"status": "error", "error": f"{name} failed: {cause}"}` with the checkpoint untouched; a `TransformAccessDenied` cause already carries principal/workspace; a cancelled-job failure names job id and status; log `tool.{name}.failed`
    - `agent_complete` → `validate_complete()` returns `ok` or an error listing missing keys; `MAX_STEPS_PER_INVOKE` convergence guard returns an explicit error (never a silent stop)
    - Log `deploy.sequencer.step` with `{step, fromStage}` for each mechanical step
    - _Bug_Condition: isBugCondition where stageAfterModel IN MECHANICAL_STAGES and NOT yielded; judgment incomplete; step failure_
    - _Expected_Behavior: expectedBehavior advances through mechanical stages to a wait/judgment/complete, or errors naming step/key/principal; checkpoint never advances past a failed step_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.10, 2.11_

  - [ ] 3.6 Cut over the deploy branch in `agent/app.py` and remove the v8 patches
    - Deploy branch: `tools.set_deploy_run(run_id)` then `return run_deploy_invoke(lambda: _deploy_agent(DEPLOY_PROMPT.format(run_id=run_id)))`
    - Remove `_WAIT_STAGES`, `_load_checkpoint`, `_deploy_invoke_result`, `_validate_deploy_artifacts`, and imports of `ensure_pre_discover` / `ensure_transform_job_progress_after_agent`; delete those two functions from `deploy_workflow_tools.py`
    - Raise the outer-except truncation from 500 to 2000 characters so step / principal / workspace survive into `phase_invoke`'s `RuntimeError` and the SFN failure cause
    - Leave the intake branch unchanged
    - _Bug_Condition: isBugCondition where the post-hoc stage check marks the run FAILED_
    - _Expected_Behavior: expectedBehavior routes every invoke through the sequencer; no `deploy incomplete at checkpoint stage=…` path remains_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.7, 3.8, 3.9_

  - [ ] 3.7 Narrow the prompts in `agent/prompts.py`
    - `DEPLOY_PROMPT`: replace the 11-step procedure with the judgment-only task (read_deploy_context, inspect the analyze job via Transform MCP, `save_foundation_assessment`, then `read_approved_scope` / `get_catalog` and `save_iac_change_plan`; call `yield_for_orchestrator` only when Transform needs human input before a judgment). Keep the plan JSON example
    - `DEPLOY_SYSTEM`: replace the orchestration-role text with the judgment-only role; keep the 403, cross-account, and no-create-organization rules
    - Keep workflow tools registered on the deploy agent
    - _Bug_Condition: model owns sequencing because the prompt tells it to run all 11 steps_
    - _Expected_Behavior: model owns only the two judgment artifacts; mechanical steps run by the sequencer_
    - _Requirements: 3.5, 2.10_

  - [ ] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Deterministic progression and named failures
    - **IMPORTANT**: Re-run the SAME tests from task 1 - do NOT write new tests
    - The tests from task 1 encode the expected behavior; when they pass, the bug is resolved
    - Each mechanical-stage case advances through the workflow (returns `continue` / `ok`); the AccessDenied, 403, judgment-incomplete and cancelled-job cases return `error` naming the step / key / principal / status
    - **EXPECTED OUTCOME**: Tests PASS (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11_

  - [ ] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - Wait semantics, tool behavior, and judgment ownership
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm wait/HITL, pre-discover blocked, credential split, direct tool calls, one-poll limit, judgment ownership, audit/checkpoint key, `agent_complete`, intake, and unknown phase are unchanged
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [ ] 4. Add fix-checking and property/integration coverage
  - [ ] 4.1 Unit tests for the new primitives
    - `read_checkpoint` / `object_exists`: present, `NoSuchKey`, `404`, `AccessDenied`, KMS error → value, `None`/`False`, raise with key (2.9)
    - Each `STEPS` entry advances exactly one stage with the expected artifact and audit event (2.1–2.6)
    - Poll budget shared between tool and sequencer: a model poll followed by the sequencer at a poll stage → `continue`, no second Transform call (2.11, 3.4)
    - `paused` without `resumeStage` → error naming the checkpoint condition (3.1)
    - `TransformAccessDenied` message for CreateJob, StartJob, SendMessage, GetJob and probe `ListWorkspaces`; STS failure → explicit "could not be resolved" text (2.8)
    - Cancelled / stopped job: `poll_job` / `poll_transform_job` raise naming job id and status for `STOPPED` / `CANCELLED` / `CANCELED` (2.8, 2.11)
    - `merge_transform_into_foundation` raises naming the missing key (2.3)
    - `finish` with missing artifacts → error listing keys; with all present → `ok` (2.7)
    - Prompt tests: `DEPLOY_PROMPT.format(run_id=…)` succeeds and the plan example still parses (3.5)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.11, 3.1, 3.4, 3.5_
  - [ ] 4.2 Exhaustive stage-property tests (no `hypothesis`)
    - Using `unittest.subTest`, enumerate the full cross product of checkpoint stage × model script × Transform outcome × checkpoint-read outcome
    - Exhaustive stage property: result is always `ok`, `continue`, or an `error` naming a step or artifact, and NEVER `deploy incomplete at checkpoint stage=…` (2.1–2.11)
    - Monotonic progress: for every success path the recorded stage sequence is a prefix-ordered subsequence of the canonical workflow order; no stage skipped
    - Failure atomicity: for every injected step failure the checkpoint stage after the invoke equals the stage before the failed step (2.8)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.10, 2.11_
  - [ ] 4.3 Multi-invoke integration path with fakes
    - Invoke 1: pre-discover → init → start analyze → poll (running) → `continue`; Invoke 2: poll (done) → merge → model saves both → render → start deploy → `continue` on poll budget; Invoke 3: poll (done) → post-discover → finish → `ok`
    - Assert audit event order and final artifacts match `deployment_artifact_keys`
    - HITL path: analyze poll `AWAITING_HUMAN_INPUT` → `continue` with `awaitingHitl=true` (maps to `waitSeconds=60` in `phase_invoke`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.11, 3.1, 3.7_

- [ ] 5. Run the full test suites
  - Run `python -m unittest` (or pytest) for `orchestration/tests` and `lzcore/tests`, including the new `test_deploy_sequencer.py` and `test_transform_errors.py`
  - Confirm all exploration tests from task 1 now pass, all preservation tests from task 2 still pass, and no existing test regressed
  - If questions arise, ask the user
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [ ] 6. MANUAL — rebuild, deploy agent image v9, and validate live (REQUIRES USER CONFIRMATION)
  - **This task changes a deployed environment. DO NOT run it without explicit user confirmation.**
  - Rebuild and push the agent image with a new tag `v9` via `scripts/deploy.sh`
  - Run one fresh deploy against target account `556880010183`
  - In the audit trail confirm that `deploy.sequencer.step` events appear for each mechanical stage and the run reaches DELIVERED (or fails with a named step, not `deploy incomplete at checkpoint stage=…`)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.6, 3.7_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass. Ask the user if questions arise.
