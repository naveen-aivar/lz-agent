"""Gap analysis and post-deployment attestation vs an approved scope.json (foundation-level)."""
from __future__ import annotations

from typing import Any

ORG_READ_FIX = (
    "Run discovery with deploy target credentials for the organization's management account, or for a "
    "delegated administrator of AWS Organizations, with organizations:DescribeOrganization, ListRoots, "
    "ListOrganizationalUnitsForParent, ListAccounts, ListPolicies and ListTargetsForPolicy allowed."
)


class FoundationUnverifiable(RuntimeError):
    """The Organizations tree was not fully read, so foundation gaps cannot be computed or trusted.

    Raised instead of returning empty gap lists that a caller would read as "foundation aligned".
    """

    def __init__(self, consumer: str, limitations: list[dict] | None = None, detail: str | None = None):
        self.consumer = consumer
        self.limitations = list(limitations or [])
        parts = [f"{consumer}: foundation gaps are unverifiable"]
        if self.limitations:
            failed = "; ".join(f"{lim.get('code')}: {lim.get('message')}" for lim in self.limitations)
            parts.append(f"Organizations discovery did not complete ({failed})")
        if detail:
            parts.append(detail)
        parts.append(ORG_READ_FIX)
        super().__init__(". ".join(parts))


def require_complete_gaps(gaps: dict, consumer: str) -> None:
    """Refuse a gap-analysis dict that was not computed from a complete Organizations read.

    Covers stored artifacts written before gap_analysis raised on partial discovery (``incomplete``),
    and dicts missing the gap lists (an absent list must never be read as "no gaps").
    """
    if not isinstance(gaps, dict):
        raise FoundationUnverifiable(consumer, detail=f"gap analysis must be an object, got {type(gaps).__name__}")
    if gaps.get("incomplete"):
        raise FoundationUnverifiable(
            consumer,
            gaps.get("discoveryLimitations") or [],
            detail="gap analysis is marked incomplete (OU/account tree was not read)",
        )
    for key in ("missingOus", "missingAccountsByName"):
        if not isinstance(gaps.get(key), list):
            raise FoundationUnverifiable(consumer, detail=f"gap analysis has no {key} list")


def _ou_names(scope: dict) -> set[str]:
    return {o["name"] for o in scope.get("ous") or [] if isinstance(o, dict) and o.get("name")}


def _account_names(scope: dict) -> set[str]:
    return {a["name"] for a in scope.get("accounts") or [] if isinstance(a, dict) and a.get("name")}


def _scp_ids(scope: dict) -> set[str]:
    return {p["id"] for p in scope.get("scps") or [] if isinstance(p, dict) and p.get("id")}


def gap_analysis(scope: dict, snapshot: dict) -> dict[str, Any]:
    """Identify foundation-level gaps between approved scope and live org (not full resource drift).

    Raises FoundationUnverifiable when the snapshot is not a complete Organizations read; never returns
    empty gap lists for a tree it could not see.
    """
    if snapshot.get("error"):
        raise FoundationUnverifiable("gap_analysis", detail=str(snapshot["error"]))
    if snapshot.get("discoveryLimitations"):
        raise FoundationUnverifiable("gap_analysis", snapshot["discoveryLimitations"])
    for key in ("organizationalUnits", "accounts"):
        if not isinstance(snapshot.get(key), list):
            raise FoundationUnverifiable("gap_analysis", detail=f"Organizations snapshot has no {key} list")
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
