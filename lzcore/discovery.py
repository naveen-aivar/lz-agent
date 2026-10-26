"""Read-only landing-zone foundation snapshot (Organizations + optional Control Tower).

Used by the Deployment Agent to classify greenfield vs brownfield and to attest against an approved scope.
"""
from __future__ import annotations

from typing import Any


def _is_org_access_denied(exc: BaseException) -> bool:
    try:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            return code in ("AccessDeniedException", "AccessDenied")
    except ImportError:
        pass
    return "AccessDenied" in str(exc)


def classify_foundation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Heuristic greenfield vs brownfield from a collect_foundation() snapshot."""
    if snapshot.get("discoveryLimitations"):
        return {
            "classification": "unknown",
            "signals": {
                "accountCount": len(snapshot.get("accounts") or []),
                "nonManagementAccounts": 0,
                "ouCount": len(snapshot.get("organizationalUnits") or []),
                "controlTowerLandingZones": len((snapshot.get("controlTower") or {}).get("landingZones") or []),
            },
            "note": "Partial org discovery; classification deferred to Transform and save_foundation_assessment.",
        }
    accounts = snapshot.get("accounts") or []
    ous = snapshot.get("organizationalUnits") or []
    ct = snapshot.get("controlTower") or {}
    has_ct = bool(ct.get("landingZones"))
    # More than the management account, or any child OU, or CT present → brownfield.
    non_mgmt = [a for a in accounts if not a.get("isManagementAccount")]
    brownfield = has_ct or len(non_mgmt) > 0 or len(ous) > 0
    return {
        "classification": "brownfield" if brownfield else "greenfield",
        "signals": {
            "accountCount": len(accounts),
            "nonManagementAccounts": len(non_mgmt),
            "ouCount": len(ous),
            "controlTowerLandingZones": len(ct.get("landingZones") or []),
        },
    }


def collect_foundation(boto_session=None) -> dict[str, Any]:
    """Snapshot OUs, accounts, and SCP summaries from the caller's credentials."""
    import boto3

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
    except Exception as e:
        err = f"organizations:DescribeOrganization: {e}"
        if "NotInUse" in type(e).__name__ or "NotInUse" in str(e):
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

    if caller_account != master:
        out["discoveryLimitations"].append(
            {
                "code": "member_account",
                "message": (
                    "Organizations list/describe tree APIs require the management account or a delegated "
                    "administrator; IAM on the runtime role cannot grant ListRoots/ListAccounts from a member."
                ),
            }
        )

    root_id = None
    try:
        roots = org.list_roots().get("Roots", [])
        root_id = roots[0]["Id"] if roots else None
    except Exception as e:
        if not _is_org_access_denied(e):
            raise
        out["discoveryLimitations"].append({"code": "organizations:ListRoots", "message": str(e)})

    def walk_ous(parent_id: str, path: str) -> None:
        for ou in org.list_organizational_units_for_parent(ParentId=parent_id).get("OrganizationalUnits", []):
            name = ou["Name"]
            full = f"{path}/{name}" if path else name
            out["organizationalUnits"].append({"id": ou["Id"], "name": name, "path": full, "parentId": parent_id})
            walk_ous(ou["Id"], full)

    if root_id:
        try:
            walk_ous(root_id, "")
        except Exception as e:
            if not _is_org_access_denied(e):
                raise
            out["discoveryLimitations"].append({"code": "organizations:ListOrganizationalUnitsForParent", "message": str(e)})

    try:
        paginator = org.get_paginator("list_accounts")
        for page in paginator.paginate():
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
    except Exception as e:
        if not _is_org_access_denied(e):
            raise
        out["discoveryLimitations"].append({"code": "organizations:ListAccounts", "message": str(e)})

    try:
        for policy in org.list_policies(Filter="SERVICE_CONTROL_POLICY").get("Policies", []):
            pid = policy["Id"]
            targets = org.list_targets_for_policy(PolicyId=pid).get("Targets", [])
            out["serviceControlPolicies"].append(
                {
                    "id": pid,
                    "name": policy.get("Name"),
                    "awsManaged": policy.get("AwsManaged", False),
                    "targetCount": len(targets),
                }
            )
    except Exception as e:
        if not _is_org_access_denied(e):
            raise
        out["discoveryLimitations"].append({"code": "organizations:ListPolicies", "message": str(e)})

    try:
        ct = session.client("controltower")
        lzs = ct.list_landing_zones().get("landingZones", [])
        out["controlTower"] = {"landingZones": [{"arn": z.get("landingZoneArn"), "status": z.get("status")} for z in lzs]}
    except Exception as e:
        out["controlTower"] = {"error": str(e), "landingZones": []}

    if not out["discoveryLimitations"]:
        del out["discoveryLimitations"]

    return out
