"""Parse deploy target from API POST /runs/{id}/deploy body; store and delete key-mode credentials."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .aws_target_session import _require_role_in_account, normalize_deploy_target, require_external_id

_ACCOUNT_RE = re.compile(r"^\d{12}$")

# Deploy-target access keys live outside runs/* so only AgentRole can read them (IAM + bucket policy in
# infra/platform/platform.yaml). Written with the stack CMK; every version is deleted at DELIVERED, FAILED and /stop.
CREDENTIALS_PREFIX = "deploy-target-credentials/"


def credentials_key(deploy_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", deploy_id or ""):
        raise ValueError(f"deploy run id {deploy_id!r} must be 32 lowercase hex characters")
    return f"{CREDENTIALS_PREFIX}{deploy_id}.json"


def delete_deploy_target_credentials(s3_client, bucket: str, key: str) -> int:
    """Delete every version and delete marker of the credentials object (the bucket is versioned).

    Returns the number of versions/markers removed (0 when nothing was stored or it was already removed).
    Raises on any S3 error or per-object delete error; callers must audit and surface the failure.
    """
    if not key.startswith(CREDENTIALS_PREFIX):
        raise ValueError(f"refusing to delete {key!r}: deploy-target credentials live under {CREDENTIALS_PREFIX}")
    versions: list[dict[str, str]] = []
    kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": key}
    while True:
        page = s3_client.list_object_versions(**kwargs)
        for entry in (page.get("Versions") or []) + (page.get("DeleteMarkers") or []):
            if entry["Key"] == key:
                versions.append({"Key": key, "VersionId": entry["VersionId"]})
        if not page.get("IsTruncated"):
            break
        kwargs["KeyMarker"] = page["NextKeyMarker"]
        kwargs["VersionIdMarker"] = page["NextVersionIdMarker"]
    for i in range(0, len(versions), 1000):
        out = s3_client.delete_objects(Bucket=bucket, Delete={"Objects": versions[i:i + 1000], "Quiet": True})
        errors = out.get("Errors") or []
        if errors:
            detail = "; ".join(f"{e.get('VersionId')}: {e.get('Code')} {e.get('Message')}" for e in errors[:5])
            raise RuntimeError(f"failed to delete {len(errors)} version(s) of s3://{bucket}/{key}: {detail}")
    return len(versions)


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
        _require_role_in_account(role_arn, account_id)
        ext = require_external_id(raw)
        sts = boto3.client("sts")
        try:
            creds = sts.assume_role(
                RoleArn=role_arn, RoleSessionName="ingram-lz-deploy-verify", ExternalId=ext
            )["Credentials"]
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
        if code == "AWSOrganizationsNotInUseException":
            return {
                "status": "not_enabled",
                "detail": "AWS Organizations is not enabled for this account. Enable it in the target account before deploy discover.",
            }
        if code in ("AccessDeniedException", "AccessDenied"):
            return {
                "status": "access_denied",
                "detail": "Credentials are valid but cannot describe the organization (org read permissions may be missing).",
            }
        return {"status": "error", "detail": f"DescribeOrganization failed ({code or 'ClientError'}): {str(e)[:300]}"}


def verify_deploy_target_credentials(body: dict[str, Any]) -> dict[str, Any]:
    """
    Test deploy target credentials without storing secrets.
    Returns {ok: true, message, ...}, or {ok: false, error} when the credentials or the Organizations probe fail.
    """
    try:
        raw = _inline_deploy_target_raw(body)
        session, account_id, ident = session_from_inline_deploy_target(raw)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    org = _probe_organizations(session)
    if org["status"] == "error":
        return {
            "ok": False,
            "error": f"Connected to account {ident.get('Account')}, but the Organizations probe failed: {org['detail']}",
            "callerAccountId": ident.get("Account"),
            "callerArn": ident.get("Arn"),
            "targetAccountId": account_id,
            "organizations": org,
        }
    warnings: list[str] = []
    if org["status"] in ("not_enabled", "access_denied"):
        warnings.append(org["detail"])

    parts = [
        f"Connected to account {ident.get('Account')} as {ident.get('Arn', 'unknown')}.",
    ]
    if org["status"] == "enabled":
        parts.append(
            f"Organizations enabled (org {org.get('organizationId', '?')}, "
            f"management account {org.get('masterAccountId', '?')})."
        )
    elif org["status"] == "not_enabled":
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
      { "deployTarget": { "accountId": "...", "roleArn": "...", "externalId": "..." } }   (externalId required)
      { "deployTarget": { "accountId": "...", "accessKeyId", "secretAccessKey", "sessionToken"? } }
    """
    raw = body.get("deployTarget")
    if raw is None:
        # Shorthand top-level fields
        if body.get("roleArn") or body.get("accessKeyId"):
            raw = body
        else:
            return None
    if not isinstance(raw, dict):
        raise ValueError("deployTarget must be an object")

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
        key = credentials_key(deploy_id)
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
