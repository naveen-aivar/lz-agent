# Deploy workflow — Transform + agent-heavy orchestration

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **Step Functions** | Invoke deploy agent → wait/resume while Transform jobs run or need HITL → mark **DELIVERED** / **FAILED** |
| **Strands agent (`phase: deploy`)** | Discover, Transform, plan, render (tools + Transform MCP) |
| **`phase_invoke`** | AgentCore + **`deployment-report.json`** (deterministic attestation after agent success) |
| **`phase_deploy`** | Deploy run status only |

## Agent tools

See `agent/deploy_workflow_tools.py`: discover, Transform jobs, checkpoint/yield, plan/render, `finish_deploy_workflow`.

Poll tools set **`agent-checkpoint.json`** and stop for that invoke; Step Functions waits and re-invokes session `{runId}-deploy…`.

## Flow

1. `POST /runs/{designRunId}/deploy`
2. SFN loop → **`deploy` agent**
3. On agent success, **`phase_invoke`** runs attestation (`phase_attest`) → writes **`deployment-report.json`** (fails the run if overall is `fail`)
4. SFN → **DELIVERED**

Attestation is not a separate Step Functions state; it runs in **`phase_invoke`** after the agent returns success. It is still **rule-based code**, not LLM judgment.

## Guardrails

- **Artifact contract:** `lzcore/deploy_artifacts.py` lists S3 keys required by `finish_deploy_workflow`, agent validation, and `phase_attest` (including `classification-post.json` and `transform-poll-deploy.json`).
- **SFN:** 24h execution timeout; **200** wait/resume cycles max (`continueCount`, see `MAX_DEPLOY_CONTINUE_CYCLES`).
- **Poll cap:** at most **one** Transform analyze/deploy poll tool call per agent invoke (orchestration re-invokes the session).

See [deployment-agent-scope.md](./deployment-agent-scope.md).
