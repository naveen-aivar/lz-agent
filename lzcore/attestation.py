"""Gap analysis and post-deployment attestation vs an approved scope.json (foundation-level)."""
from __future__ import annotations

from typing import Any


def _ou_names(scope: dict) -> set[str]:
    return {o["name"] for o in scope.get("ous") or [] if isinstance(o, dict) and o.get("name")}


def _account_names(scope: dict) -> set[str]:
    return {a["name"] for a in scope.get("accounts") or [] if isinstance(a, dict) and a.get("name")}


def _scp_ids(scope: dict) -> set[str]:
    return {p["id"] for p in scope.get("scps") or [] if isinstance(p, dict) and p.get("id")}


def gap_analysis(scope: dict, snapshot: dict) -> dict[str, Any]:
    """Identify foundation-level gaps between approved scope and live org (not full resource drift)."""
    live_ous = {ou["name"] for ou in snapshot.get("organizationalUnits") or [] if ou.get("name")}
    live_accounts = {a["name"] for a in snapshot.get("accounts") or [] if a.get("name")}
    expected_ous = _ou_names(scope)
    expected_accounts = _account_names(scope)
    expected_scps = _scp_ids(scope)

    return {
        "missingOus": sorted(expected_ous - live_ous),
        "extraOus": sorted(live_ous - expected_ous),
        "missingAccountsByName": sorted(expected_accounts - live_accounts),
        "extraAccountsByName": sorted(live_accounts - expected_accounts),
        "expectedScpIds": sorted(expected_scps),
        "note": "SCP attachment is not verified in this MVP; only catalog ids from scope are listed.",
    }


def _observed_counts(snapshot: dict) -> dict[str, Any]:
    return {
        "ouCount": len(snapshot.get("organizationalUnits") or []),
        "accountCount": len(snapshot.get("accounts") or []),
        "scpPolicyCount": len(snapshot.get("serviceControlPolicies") or []),
        "controlTower": snapshot.get("controlTower"),
    }


def build_deployment_report(
    *,
    run_id: str,
    design_run_id: str,
    scope: dict,
    post_snapshot: dict,
    post_classification: dict,
    pre_gaps: dict,
    post_gaps: dict,
    overall: str,
    outcome_reasons: list[str] | None = None,
    pre_snapshot: dict | None = None,
    pre_classification: dict | None = None,
    iac_plan: dict | None = None,
    transform: dict | None = None,
) -> dict[str, Any]:
    """Evidence-backed deployment validation report (foundation scope)."""
    pre_classification = pre_classification or {}
    return {
        "schemaVersion": "1",
        "reportType": "landing-zone-foundation-attestation",
        "runId": run_id,
        "designRunId": design_run_id,
        "overall": overall,
        "outcomeReasons": outcome_reasons or [],
        "classification": {
            "preDeploy": pre_classification.get("classification"),
            "postDeploy": post_classification.get("classification"),
            "signals": post_classification.get("signals") or pre_classification.get("signals"),
        },
        "customer": scope.get("customer"),
        "regions": scope.get("regions"),
        "expected": {
            "ouCount": len(scope.get("ous") or []),
            "accountCount": len(scope.get("accounts") or []),
            "scpCount": len(scope.get("scps") or []),
        },
        "observed": {
            "preDeploy": _observed_counts(pre_snapshot or {}),
            "postDeploy": _observed_counts(post_snapshot),
        },
        "gaps": {"preDeploy": pre_gaps, "postDeploy": post_gaps},
        "iacPlan": iac_plan,
        "transform": transform,
        "disclaimer": (
            "This report compares approved scope names to Organizations listings in the target account after "
            "Transform deploy. It does not replace Transform job history or full resource-level drift detection."
        ),
    }
