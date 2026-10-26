"""Parse deploy target from API POST /runs/{id}/deploy body."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .aws_target_session import normalize_deploy_target

_ACCOUNT_RE = re.compile(r"^\d{12}$")


def _inline_deploy_target_raw(body: dict[str, Any]) -> dict[str, Any]:
    raw = body.get("deployTarget")
    if raw is None:
        if body.get("roleArn") or body.get("accessKeyId"):
            raw = body
        else:
            raise ValueError("deployTarget is required")
    if not isinstance(raw, dict):
        raise ValueError("deployTarget must be an object")
    return raw


def session_from_inline_deploy_target(raw: dict[str, Any]):
    """Build a boto3 Session from inline deployTarget fields (not stored)."""
    import boto3
    from botocore.exceptions import ClientError

    account_id = (raw.get("accountId") or raw.get("targetAccountId") or "").strip()
    role_arn = (raw.get("roleArn") or "").strip()
    access_key = (raw.get("accessKeyId") or "").strip()
    secret_key = (raw.get("secretAccessKey") or "").strip()

    if not _ACCOUNT_RE.fullmatch(account_id or ""):
        raise ValueError("deployTarget.accountId must be a 12-digit AWS account id")

    if access_key:
        if not secret_key:
            raise ValueError("deployTarget.secretAccessKey is required with accessKeyId")
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=(raw.get("sessionToken") or "").strip() or None,
        )
    elif role_arn:
        if not role_arn.startswith("arn:aws:iam::") or ":role/" not in role_arn:
            raise ValueError("deployTarget.roleArn must be an IAM role ARN in the target account")
        if account_id not in role_arn:
            raise ValueError("deployTarget.roleArn must belong to deployTarget.accountId")
        sts = boto3.client("sts")
        kwargs: dict[str, Any] = {
            "RoleArn": role_arn,
            "RoleSessionName": "ingram-lz-deploy-verify",
        }
        ext = (raw.get("externalId") or "").strip()
        if ext:
            kwargs["ExternalId"] = ext
        try:
            creds = sts.assume_role(**kwargs)["Credentials"]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "ClientError")
            msg = e.response.get("Error", {}).get("Message", str(e))
            raise ValueError(f"AssumeRole failed ({code}): {msg}") from e
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    else:
        raise ValueError("deployTarget requires roleArn or accessKeyId/secretAccessKey")

    try:
        caller = session.client("sts").get_caller_identity()
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "ClientError")
        msg = e.response.get("Error", {}).get("Message", str(e))
        raise ValueError(f"STS GetCallerIdentity failed ({code}): {msg}") from e

    resolved = caller.get("Account")
    if resolved != account_id:
        raise ValueError(
            f"Credentials resolved to account {resolved}, not the target account {account_id}"
        )
    return session, account_id, caller


def _probe_organizations(session) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    try:
        org = session.client("organizations").describe_organization().get("Organization", {})
        return {
            "status": "enabled",
            "organizationId": org.get("Id"),
            "masterAccountId": org.get("MasterAccountId"),
        }
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if "NotInUse" in code or "NotInUse" in str(e):
            return {
                "status": "not_enabled",
                "detail": "AWS Organizations is not enabled for this account. Enable it in the target account before deploy discover.",
            }
        if code in ("AccessDeniedException", "AccessDenied"):
            return {
                "status": "access_denied",
                "detail": "Credentials are valid but cannot describe the organization (org read permissions may be missing).",
            }
        return {"status": "error", "detail": str(e)[:300]}


def verify_deploy_target_credentials(body: dict[str, Any]) -> dict[str, Any]:
    """
    Test deploy target credentials without storing secrets.
    Returns {ok, message, ...} or {ok: false, error}.
    """
    try:
        raw = _inline_deploy_target_raw(body)
        session, account_id, ident = session_from_inline_deploy_target(raw)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    org = _probe_organizations(session)
    warnings: list[str] = []
    if org.get("status") == "not_enabled":
        warnings.append(org["detail"])
    elif org.get("status") == "access_denied":
        warnings.append(org["detail"])

    parts = [
        f"Connected to account {ident.get('Account')} as {ident.get('Arn', 'unknown')}.",
    ]
    if org.get("status") == "enabled":
        parts.append(
            f"Organizations enabled (org {org.get('organizationId', '?')}, "
            f"management account {org.get('masterAccountId', '?')})."
        )
    elif org.get("status") == "not_enabled":
        parts.append("Organizations is not enabled on this account yet.")

    return {
        "ok": True,
        "message": " ".join(parts),
        "callerAccountId": ident.get("Account"),
        "callerArn": ident.get("Arn"),
        "targetAccountId": account_id,
        "organizations": org,
        "warnings": warnings,
    }


def parse_deploy_target_from_request(
    body: dict[str, Any],
    *,
    deploy_id: str,
    put_credentials: Callable[[str, bytes], None] | None = None,
) -> dict[str, Any] | None:
    """
    Returns deployTarget for DynamoDB META, or None for platform-account deploy.

    Body shapes:
      {}  → platform account
      { "deployTarget": { "accountId": "...", "roleArn": "...", "externalId": "..." } }
      { "deployTarget": { "accountId": "...", "accessKeyId", "secretAccessKey", "sessionToken"? } }
    """
    raw = body.get("deployTarget")
    if raw is None:
        # Shorthand top-level fields
        if body.get("roleArn") or body.get("accessKeyId"):
            raw = body
        else:
            return None

    account_id = (raw.get("accountId") or raw.get("targetAccountId") or "").strip()
    role_arn = (raw.get("roleArn") or "").strip()
    access_key = (raw.get("accessKeyId") or "").strip()
    secret_key = (raw.get("secretAccessKey") or "").strip()

    if not account_id and not role_arn and not access_key:
        return None
    if not _ACCOUNT_RE.fullmatch(account_id or ""):
        raise ValueError("deployTarget.accountId (12 digits) is required for cross-account deploy")

    if access_key:
        if not secret_key:
            raise ValueError("deployTarget.secretAccessKey is required with accessKeyId")
        if not put_credentials:
            raise ValueError("internal: put_credentials required for key-based deploy")
        key = f"runs/{deploy_id}/deployment/target-credentials.json"
        cred_doc = {
            "accessKeyId": access_key,
            "secretAccessKey": secret_key,
        }
        token = (raw.get("sessionToken") or "").strip()
        if token:
            cred_doc["sessionToken"] = token
        put_credentials(key, json.dumps(cred_doc).encode())
        return normalize_deploy_target(
            {"mode": "keys", "accountId": account_id, "credentialsKey": key}
        )

    if role_arn:
        return normalize_deploy_target(
            {"mode": "role", "accountId": account_id, "roleArn": role_arn, "externalId": raw.get("externalId")}
        )

    raise ValueError("deployTarget requires roleArn or accessKeyId/secretAccessKey")
