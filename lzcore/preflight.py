"""Pre-flight check before a deploy run starts: find leftover state that makes AWS Transform's Control Tower setup fail
halfway, and refuse the run with a list of what to fix.

Three findings are blockers (each failed a live run):
  * the foundational "Security" OU exists but there is no Control Tower landing zone (the bootstrap stack creates that
    OU and fails with AlreadyExists);
  * an ``AtxLzBootstrapStack`` is in a failed or rolled-back state (it must be deleted before the link can recreate it);
  * IAM Identity Center is not enabled in the Control Tower Region.
Plus the email check: an account the design still has to create would use an address a live account already uses.

A check the account does not let us run (AccessDenied) is returned under ``unverified`` and audited by the caller; it is
never reported as passed.
"""
from __future__ import annotations

import re
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

BOOTSTRAP_STACK = "AtxLzBootstrapStack"
# Stack states that block recreating the stack, or that mean a setup is half done.
BAD_STACK_STATES = frozenset({
    "CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "ROLLBACK_IN_PROGRESS", "DELETE_FAILED",
    "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS",
})
FOUNDATIONAL_OU = "security"


def _denied(exc: BaseException) -> bool:
    code = exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else ""
    return code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedException") \
        or "not authorized" in str(exc).lower()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def planned_emails(scope: dict, snapshot: dict, email_base: str | None) -> dict[str, str]:
    """{account name: address} for design accounts not yet in the organization, by Transform's plus addressing."""
    if not email_base or "@" not in email_base:
        return {}
    local, domain = email_base.split("@", 1)
    live = {a.get("name") for a in snapshot.get("accounts") or []}
    return {a["name"]: f"{local}+{_slug(a['name'])}@{domain}" for a in scope.get("accounts") or []
            if a.get("name") and a["name"] not in live and a.get("provisioning") != "existing"}


def preflight_findings(*, scope: dict, snapshot: dict, session, region: str, email_base: str | None = None) -> dict[str, Any]:
    """{"blockers": [...], "unverified": [...], "checked": [...]} for the target account in ``region``."""
    blockers: list[str] = []
    unverified: list[str] = []
    checked: list[str] = []
    ct = snapshot.get("controlTower") or {}
    if ct.get("error"):
        unverified.append(f"Control Tower landing zones could not be read ({ct['error']})")
        has_lz = None
    else:
        has_lz = bool(ct.get("landingZones"))
        checked.append("controlTower")
    live_ous = {str(o.get("name", "")).lower() for o in snapshot.get("organizationalUnits") or []}
    if has_lz is False and FOUNDATIONAL_OU in live_ous:
        blockers.append(
            "The account has a 'Security' OU but no Control Tower landing zone. Control Tower's setup creates that OU and "
            "fails because it already exists. Set Control Tower up by hand using the existing Security OU and its Audit "
            "and Log Archive accounts, or remove the leftover OU (it must be empty), then start the run again."
        )

    try:
        cfn = session.client("cloudformation", region_name=region)
        stack = cfn.describe_stacks(StackName=BOOTSTRAP_STACK)["Stacks"][0]
        checked.append("bootstrapStack")
        if stack["StackStatus"] in BAD_STACK_STATES:
            blockers.append(f"Stack {BOOTSTRAP_STACK} in {region} is {stack['StackStatus']}. Delete it before starting a run.")
    except ClientError as e:
        if "does not exist" in str(e):
            checked.append("bootstrapStack")
        elif _denied(e):
            unverified.append(f"{BOOTSTRAP_STACK} could not be checked (cloudformation:DescribeStacks denied)")
        else:
            raise
    except BotoCoreError as e:
        raise RuntimeError(f"pre-flight CloudFormation check failed: {e}") from e

    try:
        sso = session.client("sso-admin", region_name=region)
        instances = sso.list_instances().get("Instances", [])
        checked.append("identityCenter")
        if not instances:
            blockers.append(f"IAM Identity Center is not enabled in {region}. Control Tower needs it in its home Region.")
    except ClientError as e:
        if _denied(e):
            unverified.append("IAM Identity Center could not be checked (sso:ListInstances denied)")
        else:
            raise
    except BotoCoreError as e:
        raise RuntimeError(f"pre-flight Identity Center check failed: {e}") from e

    live_emails = {str(a.get("email", "")).lower(): a for a in snapshot.get("accounts") or [] if a.get("email")}
    for name, address in planned_emails(scope, snapshot, email_base).items():
        owner = live_emails.get(address.lower())
        if owner:
            blockers.append(f"The address {address} planned for the new account '{name}' is already used by account "
                            f"'{owner.get('name')}' ({owner.get('id')}, {owner.get('status')}). Use a different account "
                            "email base.")
    if email_base:
        checked.append("accountEmails")
    return {"blockers": blockers, "unverified": unverified, "checked": checked}
