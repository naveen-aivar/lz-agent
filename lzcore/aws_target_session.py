"""Boto3 sessions for deploy runs (platform default or cross-account target)."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import arns
from .arns import RoleArn

_ACCOUNT_RE = re.compile(r"^\d{12}$")


def parse_role_arn(arn: str) -> RoleArn:
    """Parse a deploy-target role ARN (shared parser, errors labelled deployTarget.roleArn)."""
    return arns.parse_role_arn(arn, label="deployTarget.roleArn")


def _require_role_in_account(role_arn: str, account_id: str) -> RoleArn:
    parsed = parse_role_arn(role_arn)
    if parsed.account_id != account_id:
        raise ValueError(
            f"deployTarget.roleArn belongs to account {parsed.account_id}, not deployTarget.accountId {account_id}"
        )
    return parsed


def require_external_id(raw: dict[str, Any]) -> str:
    ext = (raw.get("externalId") or "").strip()
    if not ext:
        raise ValueError(
            "deployTarget.externalId is required for role mode: add an sts:ExternalId condition to the target "
            "role's trust policy and enter the same value (see docs/cross-account-deploy.md)"
        )
    return ext


def normalize_deploy_target(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a stored deployTarget map, or None for platform-account deploy."""
    if not raw:
        return None
    mode = (raw.get("mode") or "platform").strip().lower()
    if mode in ("platform", "default", ""):
        return None
    account_id = (raw.get("accountId") or raw.get("targetAccountId") or "").strip()
    if not _ACCOUNT_RE.fullmatch(account_id):
        raise ValueError("deployTarget.accountId must be a 12-digit AWS account id")
    if mode == "role":
        role_arn = (raw.get("roleArn") or "").strip()
        _require_role_in_account(role_arn, account_id)
        return {"mode": "role", "accountId": account_id, "roleArn": role_arn, "externalId": require_external_id(raw)}
    if mode == "keys":
        return {"mode": "keys", "accountId": account_id, "credentialsKey": raw["credentialsKey"]}
    raise ValueError("deployTarget.mode must be platform, role, or keys")


def public_deploy_target(deploy_target: dict[str, Any] | None) -> dict[str, Any]:
    """The only deployTarget view that may leave the platform (API responses, audit rows):
    {mode, accountId, roleArn}. Never externalId or credentialsKey."""
    if not deploy_target:
        return {"mode": "platform"}
    out = {"mode": deploy_target.get("mode"), "accountId": deploy_target.get("accountId")}
    if deploy_target.get("mode") == "role":
        out["roleArn"] = deploy_target.get("roleArn")
    return out


def session_for_deploy_target(
    deploy_target: dict[str, Any] | None,
    *,
    read_credentials: Callable[[str], str] | None = None,
):
    """Build a boto3 Session for org discover/attest. None deploy_target → default chain (platform mode)."""
    import boto3

    if not deploy_target:
        return boto3.Session()

    mode = deploy_target.get("mode")
    expected = deploy_target.get("accountId")

    if mode == "role":
        _require_role_in_account(deploy_target["roleArn"], expected)
        external_id = require_external_id(deploy_target)
        creds = boto3.client("sts").assume_role(
            RoleArn=deploy_target["roleArn"],
            RoleSessionName="ingram-landing-zone-deploy",
            ExternalId=external_id,
        )["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    elif mode == "keys":
        if not read_credentials:
            raise RuntimeError("deploy target keys require read_credentials callback")
        blob = read_credentials(deploy_target["credentialsKey"])
        data = json.loads(blob)
        session = boto3.Session(
            aws_access_key_id=data["accessKeyId"],
            aws_secret_access_key=data["secretAccessKey"],
            aws_session_token=data.get("sessionToken") or None,
        )
    else:
        raise ValueError(f"unknown deployTarget.mode {mode!r} (expected 'role' or 'keys', or no deployTarget)")

    caller = session.client("sts").get_caller_identity().get("Account")
    if caller != expected:
        raise RuntimeError(
            f"deploy target account is {expected} but credentials resolved to {caller}"
        )
    return session
