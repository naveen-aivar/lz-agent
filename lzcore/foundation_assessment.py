"""Brownfield / greenfield foundation assessment vs approved design scope."""
from __future__ import annotations

from typing import Any

from .attestation import require_complete_gaps

ENVIRONMENTS = ("greenfield", "brownfield")


def build_foundation_assessment(
    *,
    scope: dict,
    snapshot: dict,
    classification: dict,
    gaps: dict,
) -> dict[str, Any]:
    """Document existing org setup and gap summary for operators and auditors.

    Raises attestation.FoundationUnverifiable for gaps from an incomplete Organizations read, and
    ValueError when the classification is not greenfield/brownfield.
    """
    require_complete_gaps(gaps, "build_foundation_assessment")
    env = classification.get("classification")
    if env not in ENVIRONMENTS:
        raise ValueError(f"build_foundation_assessment: classification must be one of {ENVIRONMENTS}, got {env!r}")
    ous = snapshot.get("organizationalUnits") or []
    accounts = snapshot.get("accounts") or []
    expected_ous = [o.get("name") for o in scope.get("ous") or [] if isinstance(o, dict)]
    expected_accounts = [a.get("name") for a in scope.get("accounts") or [] if isinstance(a, dict)]

    notes: list[str] = []
    if env == "brownfield":
        notes.append(
            "Brownfield: org already has OUs, member accounts, and/or Control Tower. "
            "Required IaC changes are derived by comparing this snapshot to the approved design, not by editing live resources in place."
        )
        if gaps.get("extraOus") or gaps.get("extraAccountsByName"):
            notes.append(
                "Live org contains names not in the approved design; reconcile manually or update the design scope before apply."
            )
        if (gaps.get("missingOus") or gaps.get("missingAccountsByName")) and (
            gaps.get("extraOus") or gaps.get("extraAccountsByName")
        ):
            notes.append("Simultaneous missing and extra foundation names usually implies a design mismatch, not a simple stack apply.")
    else:
        notes.append(
            "Greenfield: minimal org footprint. Design stacks and Transform deploy are intended to establish the approved foundation."
        )

    return {
        "schemaVersion": "1",
        "assessmentType": "landing-zone-foundation",
        "environment": env,
        "signals": classification.get("signals") or {},
        "existingSetup": {
            "organizationId": (snapshot.get("organization") or {}).get("id"),
            "featureSet": (snapshot.get("organization") or {}).get("featureSet"),
            "organizationalUnits": [{"name": o.get("name"), "path": o.get("path")} for o in ous],
            "accounts": [
                {"name": a.get("name"), "id": a.get("id"), "isManagementAccount": a.get("isManagementAccount")}
                for a in accounts
            ],
            "serviceControlPolicyCount": len(snapshot.get("serviceControlPolicies") or []),
            "controlTower": snapshot.get("controlTower"),
        },
        "approvedDesign": {
            "customer": scope.get("customer"),
            "ouNames": expected_ous,
            "accountNames": expected_accounts,
            "scpIds": [p.get("id") for p in scope.get("scps") or [] if isinstance(p, dict)],
            "controlIds": [c.get("id") for c in scope.get("controls") or [] if isinstance(c, dict)],
        },
        "gaps": gaps,
        "notes": notes,
    }


def validate_agent_classification(submission: dict) -> tuple[dict, list[str]]:
    """Validate agent greenfield/brownfield decision before persisting assessment artifacts."""
    errors: list[str] = []
    if not isinstance(submission, dict):
        return {}, ["submission must be a JSON object"]
    env = submission.get("environment")
    if env not in ENVIRONMENTS:
        errors.append(f"environment must be one of {ENVIRONMENTS}")
    rationale = str(submission.get("rationale", "")).strip()
    if not rationale:
        errors.append("rationale is required (cite org snapshot + Transform analyze evidence)")
    signals = submission.get("signals")
    if signals is not None and not isinstance(signals, dict):
        errors.append("signals must be an object when provided")
    extra_notes = submission.get("notes")
    if extra_notes is not None and not isinstance(extra_notes, list):
        errors.append("notes must be a list of strings when provided")
    normalized = {
        "environment": env,
        "rationale": rationale,
        "signals": signals or {},
        "notes": [str(n) for n in (extra_notes or []) if str(n).strip()],
        "transformAnalyzeInsights": str(submission.get("transformAnalyzeInsights", "")).strip() or None,
    }
    return normalized, errors


def classification_from_agent(normalized: dict) -> dict[str, Any]:
    return {
        "classification": normalized["environment"],
        "signals": normalized["signals"],
        "rationale": normalized["rationale"],
        "decidedBy": "agent",
    }
