"""Landing Zone Deployment Agent business rules (foundation scope)."""
from __future__ import annotations

from typing import Any

from .attestation import gap_analysis
from .discovery import classify_foundation, collect_foundation

# Terminal Transform deploy job statuses treated as success (API variants).
TRANSFORM_DEPLOY_SUCCESS_STATUSES = frozenset(
    {"SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE", "DONE"},
)


def collect_snapshot_and_gaps(scope: dict, boto_session=None) -> tuple[dict, dict]:
    """Live org snapshot and name-level gaps vs approved scope (no environment label)."""
    snapshot = collect_foundation(boto_session)
    if snapshot.get("error"):
        raise RuntimeError(snapshot["error"])
    gaps = gap_analysis(scope, snapshot)
    return snapshot, gaps


def run_foundation_assessment(scope: dict, boto_session=None) -> tuple[dict, dict, dict]:
    """Post-deploy discover: snapshot, heuristic classification, and gaps."""
    snapshot, gaps = collect_snapshot_and_gaps(scope, boto_session)
    classification = classify_foundation(snapshot)
    return snapshot, classification, gaps


def deployment_paths(run_id: str, phase: str) -> dict[str, str]:
    """S3 keys for pre- or post-deploy foundation artifacts."""
    base = f"runs/{run_id}/deployment"
    suffix = "" if phase == "pre" else "-post"
    return {
        "foundation": f"{base}/foundation{suffix}.json",
        "classification": f"{base}/classification{suffix}.json",
        "gapAnalysis": f"{base}/gap-analysis{suffix}.json",
    }


def should_deliver_design_bundles(plan: dict) -> bool:
    """Architecture IaC zips are delivered when the plan calls for stack-based remediation."""
    strategy = plan.get("strategy")
    if plan.get("deliverDesignBundles") is False:
        return False
    if plan.get("deliverDesignBundles") is True:
        return True
    return strategy in ("apply_design_stacks", "partial_manual")


def evaluate_deployment_outcome(
    *,
    pre_gaps: dict,
    post_gaps: dict,
    plan: dict | None,
    transform_deploy_status: str | None,
) -> tuple[str, list[str]]:
    """Return (overall, reasons). overall is pass | fail | pass_with_manual_steps."""
    reasons: list[str] = []
    plan = plan or {}
    strategy = plan.get("strategy", "apply_design_stacks")

    post_missing_ous = post_gaps.get("missingOus") or []
    post_missing_accts = post_gaps.get("missingAccountsByName") or []
    foundation_aligned = not post_missing_ous and not post_missing_accts

    status = (transform_deploy_status or "").upper()
    if not status:
        reasons.append("Transform deploy job status unknown")
        transform_ok = False
    elif status not in TRANSFORM_DEPLOY_SUCCESS_STATUSES:
        reasons.append(
            f"Transform deploy job status is {status}, expected one of {sorted(TRANSFORM_DEPLOY_SUCCESS_STATUSES)}"
        )
        transform_ok = False
    else:
        transform_ok = True

    if strategy == "no_changes_needed":
        pre_missing = (pre_gaps.get("missingOus") or []) + (pre_gaps.get("missingAccountsByName") or [])
        if pre_missing:
            reasons.append("Plan says no changes needed but pre-deploy gaps were present")
            return "fail", reasons
        if foundation_aligned and transform_ok:
            return "pass", ["Foundation matched approved scope before and after Transform deploy"]
        if foundation_aligned and not transform_ok:
            return "fail", reasons
        return "fail", reasons + ["Post-deploy foundation still diverges from approved scope"]

    manual = (plan.get("manualSteps") or []) if strategy == "partial_manual" else []
    if foundation_aligned and transform_ok:
        if manual:
            return "pass_with_manual_steps", ["Foundation aligned; complete documented manual steps"]
        return "pass", ["Foundation aligned after Transform deploy"]

    if strategy == "partial_manual" and transform_ok and not foundation_aligned:
        reasons.append("Post-deploy gaps remain; see manualSteps in iac-change-plan")
        return "pass_with_manual_steps", reasons

    if not foundation_aligned:
        reasons.append(
            f"Post-deploy missing OUs={post_missing_ous}, accounts={post_missing_accts}"
        )
    return "fail", reasons
