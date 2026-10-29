"""Landing Zone Deployment Agent business rules (foundation scope)."""
from __future__ import annotations

from typing import Any

from .attestation import gap_analysis, require_complete_gaps
from .discovery import classify_foundation, collect_foundation

# Terminal statuses of the Transform landing zone job treated as success (API variants).
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
    """Return (overall, reasons). overall is pass | fail | pass_with_manual_steps.

    Raises attestation.FoundationUnverifiable when either gap analysis was not computed from a complete
    Organizations read; an unread tree is never reported as "foundation aligned".
    """
    require_complete_gaps(pre_gaps, "evaluate_deployment_outcome(pre_gaps)")
    require_complete_gaps(post_gaps, "evaluate_deployment_outcome(post_gaps)")
    reasons: list[str] = []
    plan = plan or {}
    strategy = plan.get("strategy", "apply_design_stacks")

    post_missing_ous = post_gaps.get("missingOus") or []
    post_missing_accts = post_gaps.get("missingAccountsByName") or []
    foundation_aligned = not post_missing_ous and not post_missing_accts

    status = (transform_deploy_status or "").upper()
    if not status:
        reasons.append("Transform job status unknown")
        transform_ok = False
    elif status not in TRANSFORM_DEPLOY_SUCCESS_STATUSES:
        reasons.append(
            f"Transform job status is {status}, expected one of {sorted(TRANSFORM_DEPLOY_SUCCESS_STATUSES)}"
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


def verify_landing_zone(scope: dict, boto_session, region: str) -> dict[str, Any]:
    """Whether the target account holds the approved landing zone: every design OU and account exists, every design
    account is ACTIVE, and a Control Tower landing zone in ``region`` is ACTIVE.

    Returns {"ok", "problems": [...], "missingOus", "missingAccountsByName", "inactiveAccounts", "controlTower"}.
    Raises when it cannot read the account (an unreadable answer is not "not built"): Organizations discovery errors,
    Control Tower read errors, and more than one landing zone in the Region.
    """
    if not region:
        raise ValueError("verify_landing_zone needs the Control Tower Region (the run's targetRegion or the design's home)")
    snapshot, gaps = collect_snapshot_and_gaps(scope, boto_session)
    problems: list[str] = []
    if gaps["missingOus"]:
        problems.append(f"organizational units not found: {', '.join(gaps['missingOus'])}")
    if gaps["missingAccountsByName"]:
        problems.append(f"accounts not found: {', '.join(gaps['missingAccountsByName'])}")
    expected = {a.get("name") for a in scope.get("accounts") or [] if a.get("name")}
    inactive = sorted(f"{a['name']} ({a.get('status')})" for a in snapshot.get("accounts") or []
                      if a.get("name") in expected and a.get("status") != "ACTIVE")
    if inactive:
        problems.append(f"accounts not ACTIVE: {', '.join(inactive)}")
    ct = boto_session.client("controltower", region_name=region)
    arns: list[str] = []
    for page in ct.get_paginator("list_landing_zones").paginate():
        arns.extend(z["arn"] for z in page.get("landingZones", []))
    ct_state: dict[str, Any] = {"region": region, "landingZones": len(arns)}
    if not arns:
        problems.append(f"no Control Tower landing zone in {region}")
    elif len(arns) > 1:
        raise RuntimeError(f"{len(arns)} Control Tower landing zones in {region}; expected one: {arns}")
    else:
        lz = ct.get_landing_zone(landingZoneIdentifier=arns[0]).get("landingZone") or {}
        ct_state.update(arn=arns[0], status=lz.get("status"), version=lz.get("version"))
        if lz.get("status") != "ACTIVE":
            problems.append(f"Control Tower landing zone {arns[0]} is {lz.get('status')!r}, not ACTIVE")
    return {"ok": not problems, "problems": problems, "missingOus": gaps["missingOus"],
            "missingAccountsByName": gaps["missingAccountsByName"], "inactiveAccounts": inactive, "controlTower": ct_state}
