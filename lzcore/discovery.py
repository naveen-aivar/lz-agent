"""Read-only landing-zone foundation snapshot (Organizations + optional Control Tower).

Used by the Deployment Agent to classify greenfield vs brownfield and to attest against an approved scope.
"""
from __future__ import annotations

from typing import Any


def classify_foundation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Heuristic greenfield vs brownfield from a collect_foundation() snapshot."""
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
    out: dict[str, Any] = {"organizationalUnits": [], "accounts": [], "serviceControlPolicies": [], "controlTower": {}}

    try:
        org_meta = org.describe_organization().get("Organization", {})
    except Exception as e:
        return {**out, "error": f"organizations:DescribeOrganization: {e}"}

    out["organization"] = {
        "id": org_meta.get("Id"),
        "masterAccountId": org_meta.get("MasterAccountId"),
        "featureSet": org_meta.get("FeatureSet"),
    }

    roots = org.list_roots().get("Roots", [])
    root_id = roots[0]["Id"] if roots else None

    def walk_ous(parent_id: str, path: str) -> None:
        for ou in org.list_organizational_units_for_parent(ParentId=parent_id).get("OrganizationalUnits", []):
            name = ou["Name"]
            full = f"{path}/{name}" if path else name
            out["organizationalUnits"].append({"id": ou["Id"], "name": name, "path": full, "parentId": parent_id})
            walk_ous(ou["Id"], full)

    if root_id:
        walk_ous(root_id, "")

    master = org_meta.get("MasterAccountId")
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

    for policy in org.list_policies(Filter="SERVICE_CONTROL_POLICY").get("Policies", []):
        pid = policy["Id"]
        targets = org.list_targets_for_policy(PolicyId=pid, Filter="SERVICE_CONTROL_POLICY").get("Targets", [])
        out["serviceControlPolicies"].append(
            {"id": pid, "name": policy.get("Name"), "awsManaged": policy.get("AwsManaged", False), "targetCount": len(targets)}
        )

    try:
        ct = session.client("controltower")
        lzs = ct.list_landing_zones().get("landingZones", [])
        out["controlTower"] = {"landingZones": [{"arn": z.get("landingZoneArn"), "status": z.get("status")} for z in lzs]}
    except Exception as e:
        out["controlTower"] = {"error": str(e), "landingZones": []}

    return out
