"""Boto3 sessions for deploy runs (platform default or cross-account target)."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

_ACCOUNT_RE = re.compile(r"^\d{12}$")


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
        if not role_arn.startswith("arn:aws:iam::") or ":role/" not in role_arn:
            raise ValueError("deployTarget.roleArn must be an IAM role ARN in the target account")
        if account_id not in role_arn:
            raise ValueError("deployTarget.roleArn must belong to deployTarget.accountId")
        out: dict[str, Any] = {"mode": "role", "accountId": account_id, "roleArn": role_arn}
        ext = (raw.get("externalId") or "").strip()
        if ext:
            out["externalId"] = ext
        return out
    if mode == "keys":
        return {"mode": "keys", "accountId": account_id, "credentialsKey": raw["credentialsKey"]}
    raise ValueError("deployTarget.mode must be platform, role, or keys")


def session_for_deploy_target(
    deploy_target: dict[str, Any] | None,
    *,
    read_credentials: Callable[[str], str] | None = None,
):
    """Build a boto3 Session for org discover/attest. None deploy_target → default chain."""
    import boto3

    if not deploy_target:
        return boto3.Session()

    mode = deploy_target.get("mode")
    expected = deploy_target.get("accountId")

    if mode == "role":
        sts = boto3.client("sts")
        kwargs: dict[str, Any] = {
            "RoleArn": deploy_target["roleArn"],
            "RoleSessionName": "ingram-landing-zone-deploy",
        }
        if deploy_target.get("externalId"):
            kwargs["ExternalId"] = deploy_target["externalId"]
        creds = sts.assume_role(**kwargs)["Credentials"]
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
        return boto3.Session()

    caller = session.client("sts").get_caller_identity().get("Account")
    if expected and caller != expected:
        raise RuntimeError(
            f"deploy target account is {expected} but credentials resolved to {caller}"
        )
    return session
