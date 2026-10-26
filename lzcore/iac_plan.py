"""Landing-zone IaC change plans: gap → supported renderer actions (not general AWS drift)."""
from __future__ import annotations

import copy
import re
from typing import Any

from .attestation import require_complete_gaps

SCHEMA_VERSION = "1"
PLAN_TYPE = "landing-zone-iac-reconciliation"
STRATEGIES = ("no_changes_needed", "apply_design_stacks", "partial_manual")
ACTIONS = (
    "create_ou",
    "create_account",
    "enable_control_tower_control",
    "catalog_scp",
    "custom_scp_review",
    "reuse_design_stack",
    "manual",
    "no_op",
)
CHANGE_ID = re.compile(r"^[a-z0-9-]{3,64}$")

LIMITATION = (
    "This plan addresses Control Tower landing-zone foundation gaps (OUs, accounts, catalog controls/SCPs) "
    "against an approved design scope. It is not a general-purpose IaC drift or reconciliation engine for "
    "arbitrary AWS resources."
)


def suggest_changes(scope: dict, gaps: dict) -> list[dict[str, Any]]:
    """Deterministic starter changes the agent should refine (same inputs as gap_analysis).

    Raises attestation.FoundationUnverifiable for gaps not computed from a complete Organizations read,
    so the "names match" no_op is only ever emitted from a tree that was actually listed.
    """
    require_complete_gaps(gaps, "suggest_changes")
    out: list[dict[str, Any]] = []
    seq = 0

    def add(action: str, target: str, gap_key: str, supported: bool, rationale: str, **extra):
        nonlocal seq
        seq += 1
        out.append(
            {
                "id": f"chg-{seq:03d}",
                "category": "foundation",
                "action": action,
                "target": target,
                "addressesGap": gap_key,
                "supportedByRenderer": supported,
                "basis": "inferred",
                "rationale": rationale,
                **extra,
            }
        )

    for ou in gaps.get("missingOus") or []:
        add(
            "create_ou",
            ou,
            f"missingOus:{ou}",
            True,
            f"Approved scope includes OU {ou!r}; Organizations snapshot does not list it.",
            rendererHint={"cloudformation": "02-governance.yaml", "terraform": "organizations.tf"},
        )
    acct_by_name = {a["name"]: a for a in scope.get("accounts") or [] if isinstance(a, dict) and a.get("name")}
    for name in gaps.get("missingAccountsByName") or []:
        acct = acct_by_name.get(name, {})
        prov = acct.get("provisioning", "account-factory")
        if prov == "existing":
            add("manual", name, f"missingAccountsByName:{name}", False, "Management/existing accounts are never created by the rendered stacks.")
        else:
            add(
                "create_account",
                name,
                f"missingAccountsByName:{name}",
                True,
                f"Approved scope includes account {name!r}; Organizations snapshot does not list it.",
                rendererHint={"cloudformation": "02-governance.yaml", "terraform": "accounts.tf"},
            )
    for ou in gaps.get("extraOus") or []:
        add(
            "manual",
            ou,
            f"extraOus:{ou}",
            False,
            f"Live org has OU {ou!r} not present in approved scope; reconcile organization design before apply.",
        )
    for name in gaps.get("extraAccountsByName") or []:
        add(
            "manual",
            name,
            f"extraAccountsByName:{name}",
            False,
            f"Live org has account {name!r} not in approved scope; out of scope for automated IaC generation.",
        )

    if not out and not (gaps.get("missingOus") or gaps.get("missingAccountsByName")):
        add("no_op", "foundation", "gaps:none", True, "Foundation names in scope match the Organizations snapshot.")
    return out


def _strategy_from_changes(changes: list[dict]) -> str:
    if not changes or all(c.get("action") == "no_op" for c in changes):
        return "no_changes_needed"
    if any(c.get("action") == "manual" for c in changes):
        return "partial_manual"
    return "apply_design_stacks"


def validate(plan: dict, *, run_id: str, design_run_id: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return {}, ["plan must be a JSON object"]
    p = copy.deepcopy(plan)
    if p.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION!r}")
    if p.get("planType") != PLAN_TYPE:
        errors.append(f"planType must be {PLAN_TYPE!r}")
    if p.get("runId") != run_id:
        errors.append("runId must match the deploy run")
    if p.get("designRunId") != design_run_id:
        errors.append("designRunId must match the linked design run")
    changes = p.get("changes")
    if not isinstance(changes, list):
        errors.append("changes must be a list")
        changes = []
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            errors.append(f"changes[{i}] must be an object")
            continue
        if not CHANGE_ID.match(str(ch.get("id", ""))):
            errors.append(f"changes[{i}].id must match {CHANGE_ID.pattern}")
        if ch.get("action") not in ACTIONS:
            errors.append(f"changes[{i}].action must be one of {sorted(ACTIONS)}")
        if not str(ch.get("rationale", "")).strip():
            errors.append(f"changes[{i}].rationale is required")
    strategy = p.get("strategy")
    if strategy not in STRATEGIES:
        p["strategy"] = _strategy_from_changes(changes)
    elif strategy == "no_changes_needed" and any(c.get("action") not in ("no_op",) for c in changes):
        errors.append("strategy no_changes_needed requires only no_op changes")
    deliver = p.get("deliverDesignBundles")
    if deliver is None:
        p["deliverDesignBundles"] = p["strategy"] in ("apply_design_stacks", "partial_manual")
    elif not isinstance(deliver, bool):
        errors.append("deliverDesignBundles must be boolean")
    p.setdefault("limitations", LIMITATION)
    p.setdefault("manualSteps", [])
    if not isinstance(p["manualSteps"], list):
        errors.append("manualSteps must be a list")
    if not str(p.get("summary", "")).strip():
        p["summary"] = "Landing-zone IaC reconciliation plan (foundation scope only)."
    return p, errors


def build_manifest(scope: dict, plan: dict) -> dict[str, Any]:
    """Map plan changes to deterministic render outputs (file hints)."""
    return {
        "schemaVersion": "1",
        "manifestType": "landing-zone-iac-delivery",
        "runId": plan.get("runId"),
        "designRunId": plan.get("designRunId"),
        "strategy": plan.get("strategy"),
        "customerOrgSlug": (scope.get("customer") or {}).get("orgSlug"),
        "changes": plan.get("changes") or [],
        "bundles": {
            "terraform": "terraform.zip",
            "cloudformation": "cloudformation.zip",
            "note": "Full design bundles; apply only the resources that match manualSteps and brownfield constraints.",
        },
        "limitations": plan.get("limitations") or LIMITATION,
    }
