"""S3 keys required before deploy attestation (shared by agent finish, runtime validation, and phase_attest)."""
from __future__ import annotations

# Paths under runs/{runId}/deployment/
DEPLOYMENT_FILE_NAMES: tuple[str, ...] = (
    "foundation.json",
    "gap-analysis.json",
    "classification.json",
    "foundation-assessment.json",
    "iac-change-plan.json",
    "iac-manifest.json",
    "foundation-post.json",
    "gap-analysis-post.json",
    "classification-post.json",
    "transform-poll-deploy.json",
)

# Max Step Functions wait/resume cycles (keep in sync with ContinueLimitChoice in deployment.asl.json).
MAX_DEPLOY_CONTINUE_CYCLES = 200


def deployment_prefix(run_id: str) -> str:
    return f"runs/{run_id}/deployment"


def deployment_artifact_keys(run_id: str) -> tuple[str, ...]:
    base = deployment_prefix(run_id)
    return tuple(f"{base}/{name}" for name in DEPLOYMENT_FILE_NAMES)
