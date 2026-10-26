"""Read-only landing-zone foundation snapshot (Organizations + optional Control Tower).

Used by the Deployment Agent to classify greenfield vs brownfield and to attest against an approved scope.
"""
from __future__ import annotations

from typing import Any

# Error codes Organizations returns when the caller may not read the org tree.
ORG_ACCESS_DENIED_CODES = frozenset({"AccessDeniedException", "AccessDenied"})


def _client_error_code(exc: BaseException) -> str | None:
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        return (exc.response.get("Error") or {}).get("Code")
    return None


def _is_org_access_denied(exc: BaseException) -> bool:
    """True only for a botocore ClientError whose error code is an AccessDenied code."""
    return _client_error_code(exc) in ORG_ACCESS_DENIED_CODES


def classify_foundation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Heuristic greenfield vs brownfield from a collect_foundation() snapshot."""
    ct = snapshot.get("controlTower") or {}
    if snapshot.get("discoveryLimitations"):
        return {
            "classification": "unknown",
            "signals": {
                "accountCount": len(snapshot.get("accounts") or []),
                "nonManagementAccounts": None,
                "ouCount": len(snapshot.get("organizationalUnits") or []),
                "controlTowerLandingZones": len(ct.get("landingZones") or []),
            },
            "note": "Partial org discovery; classification deferred to Transform and save_foundation_assessment.",
        }
    accounts = snapshot.get("accounts") or []
    ous = snapshot.get("organizationalUnits") or []
    has_ct = bool(ct.get("landingZones"))
    # More than the management account, or any child OU, or CT present → brownfield.
    non_mgmt = [a for a in accounts if not a.get("isManagementAccount")]
    brownfield = has_ct or len(non_mgmt) > 0 or len(ous) > 0
    signals = {
        "accountCount": len(accounts),
        "nonManagementAccounts": len(non_mgmt),
        "ouCount": len(ous),
        "controlTowerLandingZones": len(ct.get("landingZones") or []),
    }
    if not brownfield and ct.get("error"):
        # Greenfield requires knowing Control Tower is absent; an unread CT is not "no CT".
        return {
            "classification": "unknown",
            "signals": signals,
            "note": f"Control Tower landing zones could not be listed ({ct['error']}); greenfield not confirmed.",
        }
    return {"classification": "brownfield" if brownfield else "greenfield", "signals": signals}


def collect_foundation(boto_session=None) -> dict[str, Any]:
    """Snapshot OUs, accounts, and SCP summaries from the caller's credentials.

    A list/describe call that is denied (ClientError AccessDenied code) is recorded under
    ``discoveryLimitations``; every other error propagates. ``gap_analysis`` refuses any snapshot
    carrying limitations, so a partial read can never be attested.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    session = boto_session or boto3.Session()
    org = session.client("organizations")
    out: dict[str, Any] = {
        "organizationalUnits": [],
        "accounts": [],
        "serviceControlPolicies": [],
        "controlTower": {},
        "discoveryLimitations": [],
    }

    caller_account = session.client("sts").get_caller_identity().get("Account")
    out["organization"] = {"callerAccountId": caller_account}
    try:
        org_meta = org.describe_organization().get("Organization", {})
    except ClientError as e:
        err = f"organizations:DescribeOrganization: {e}"
        if _client_error_code(e) == "AWSOrganizationsNotInUseException":
            err += (
                f" (caller account {caller_account} has no AWS Organization; "
                "use deploy target credentials for the account that owns the org, not the platform account.)"
            )
        return {**out, "error": err}

    master = org_meta.get("MasterAccountId")
    out["organization"] = {
        "id": org_meta.get("Id"),
        "masterAccountId": master,
        "featureSet": org_meta.get("FeatureSet"),
        "callerAccountId": caller_account,
        "callerIsManagementAccount": caller_account == master,
    }

    def denied(code: str, exc: BaseException) -> None:
        if not _is_org_access_denied(exc):
            raise exc
        out["discoveryLimitations"].append({"code": code, "message": str(exc)})

    root_id = None
    try:
        roots: list[dict] = []
        for page in org.get_paginator("list_roots").paginate():
            roots.extend(page.get("Roots", []))
        if roots:
            root_id = roots[0]["Id"]
        else:
            out["discoveryLimitations"].append(
                {"code": "organizations:ListRoots", "message": "ListRoots returned no roots; OU tree cannot be read."}
            )
    except ClientError as e:
        denied("organizations:ListRoots", e)

    ou_pager = org.get_paginator("list_organizational_units_for_parent")

    def walk_ous(parent_id: str, path: str) -> None:
        for page in ou_pager.paginate(ParentId=parent_id):
            for ou in page.get("OrganizationalUnits", []):
                name = ou["Name"]
                full = f"{path}/{name}" if path else name
                out["organizationalUnits"].append({"id": ou["Id"], "name": name, "path": full, "parentId": parent_id})
                walk_ous(ou["Id"], full)

    if root_id:
        try:
            walk_ous(root_id, "")
        except ClientError as e:
            denied("organizations:ListOrganizationalUnitsForParent", e)

    try:
        for page in org.get_paginator("list_accounts").paginate():
            for acct in page.get("Accounts", []):
                out["accounts"].append(
                    {
                        "id": acct["Id"],
                        "name": acct["Name"],
                        "email": acct.get("Email", ""),
                        "status": acct.get("Status"),
                        "isManagementAccount": acct["Id"] == master,
                    }
                )
    except ClientError as e:
        denied("organizations:ListAccounts", e)

    try:
        target_pager = org.get_paginator("list_targets_for_policy")
        for page in org.get_paginator("list_policies").paginate(Filter="SERVICE_CONTROL_POLICY"):
            for policy in page.get("Policies", []):
                pid = policy["Id"]
                target_count = sum(len(p.get("Targets", [])) for p in target_pager.paginate(PolicyId=pid))
                out["serviceControlPolicies"].append(
                    {
                        "id": pid,
                        "name": policy.get("Name"),
                        "awsManaged": policy.get("AwsManaged", False),
                        "targetCount": target_count,
                    }
                )
    except ClientError as e:
        denied("organizations:ListPolicies", e)

    try:
        ct = session.client("controltower")
        lzs: list[dict] = []
        for page in ct.get_paginator("list_landing_zones").paginate():
            lzs.extend(page.get("landingZones", []))
        # ListLandingZones summaries carry only the ARN (status needs GetLandingZone).
        out["controlTower"] = {"landingZones": [{"arn": z["arn"]} for z in lzs]}
    except (ClientError, BotoCoreError) as e:
        # Recorded, not hidden: classify_foundation will not call an org greenfield while this is set.
        out["controlTower"] = {"error": f"controltower:ListLandingZones: {e}", "landingZones": []}

    if out["discoveryLimitations"] and not out["organization"]["callerIsManagementAccount"]:
        out["discoveryLimitations"].append(
            {
                "code": "member_account",
                "message": (
                    f"Caller account {caller_account} is not the management account ({master}) and Organizations "
                    "denied a tree read; use management-account credentials or register a delegated administrator "
                    "for AWS Organizations."
                ),
            }
        )

    if not out["discoveryLimitations"]:
        del out["discoveryLimitations"]

    return out
