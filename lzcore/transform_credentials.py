"""Credentials for AWS Transform calls, passed explicitly (never through os.environ).

AWS Transform may live in a different account from the platform (it must sit in the same AWS
Organization as the landing-zone target). The platform keeps using its own role for Bedrock,
S3 and DynamoDB; only Transform calls use TRANSFORM_ROLE_ARN.

The role is always assumed with one fixed session name: Transform keys workspace
collaborators by ``RoleId:SessionName``, so a fixed name is one stable collaborator identity.

Two consumers:

* In-process Transform calls (``lzcore.transform_ops``) sign with
  ``transform_botocore_credentials()``: a botocore ``RefreshableCredentials`` that re-assumes the
  role before expiry. It is handed to the Transform client explicitly, so no other code in the
  process (fresh ``boto3.Session()`` objects on other threads included) ever sees it.
* The Transform MCP subprocess gets an AWS config profile whose ``credential_process`` runs
  ``lzcore.transform_credential_process``; that helper prints ``credential_process_payload()``.

``transform_principal_arn()`` is the STS assumed-role ARN those credentials act as. It is
computed from TRANSFORM_ROLE_ARN with no network call.
"""
from __future__ import annotations

import datetime
import os
import threading
from typing import Any, NamedTuple, Optional

import boto3
from botocore.credentials import RefreshableCredentials

STABLE_SESSION_NAME = "ingram-lz-agent"
ASSUME_DURATION_SECONDS = 3600
_CREDENTIAL_METHOD = "ingram-transform-assume-role"

# Platform credentials (the container's own role). Created lazily: boto3 resolves credentials
# on first client use from the default chain, and the credential_process helper must clear its
# AWS_PROFILE before any session reads it (see lzcore/transform_credential_process.py).
_BASE_SESSION: Optional[boto3.Session] = None
_lock = threading.Lock()
_refreshable: dict = {}


class RoleArnParts(NamedTuple):
    partition: str
    account_id: str
    role_name: str


def transform_role_arn() -> str:
    arn = os.environ.get("TRANSFORM_ROLE_ARN", "").strip()
    if not arn:
        raise RuntimeError(
            "TRANSFORM_ROLE_ARN is not set: the platform stack must pass the IAM role used to call "
            "AWS Transform (TransformRoleArn parameter, or the AgentRole when Transform is in the platform account)"
        )
    return arn


def transform_external_id() -> Optional[str]:
    value = os.environ.get("TRANSFORM_EXTERNAL_ID", "").strip()
    return value or None


def parse_role_arn(arn: str) -> RoleArnParts:
    """Parse ``arn:<partition>:iam::<account>:role[/<path>]/<name>``; raise on anything else."""
    parts = arn.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn" or not parts[1]:
        raise ValueError(f"TRANSFORM_ROLE_ARN {arn!r} is not an ARN (expected arn:<partition>:iam::<account>:role/<name>)")
    _, partition, service, region, account_id, resource = parts
    if service != "iam" or region:
        raise ValueError(f"TRANSFORM_ROLE_ARN {arn!r} is not an IAM ARN (service must be iam, region empty)")
    if len(account_id) != 12 or not account_id.isdigit():
        raise ValueError(f"TRANSFORM_ROLE_ARN {arn!r} has an invalid account id {account_id!r}")
    if not resource.startswith("role/"):
        raise ValueError(f"TRANSFORM_ROLE_ARN {arn!r} is not an IAM role ARN (resource must start with role/)")
    role_name = resource.rsplit("/", 1)[-1]
    if not role_name:
        raise ValueError(f"TRANSFORM_ROLE_ARN {arn!r} has an empty role name")
    return RoleArnParts(partition, account_id, role_name)


def transform_principal_arn() -> str:
    """STS ARN the Transform credentials act as. Deterministic, no network call.

    STS assumed-role ARNs carry the role name without its IAM path.
    """
    p = parse_role_arn(transform_role_arn())
    return f"arn:{p.partition}:sts::{p.account_id}:assumed-role/{p.role_name}/{STABLE_SESSION_NAME}"


def _base_session() -> boto3.Session:
    global _BASE_SESSION
    if _BASE_SESSION is None:
        _BASE_SESSION = boto3.Session()
    return _BASE_SESSION


def assume_transform_role(base_session: Any = None) -> dict:
    """AssumeRole into TRANSFORM_ROLE_ARN with the fixed session name. Returns STS Credentials."""
    role_arn = transform_role_arn()
    parse_role_arn(role_arn)
    kwargs = {"RoleArn": role_arn, "RoleSessionName": STABLE_SESSION_NAME, "DurationSeconds": ASSUME_DURATION_SECONDS}
    external_id = transform_external_id()
    if external_id:
        kwargs["ExternalId"] = external_id
    session = base_session if base_session is not None else _base_session()
    try:
        creds = session.client("sts").assume_role(**kwargs)["Credentials"]
    except Exception as e:
        raise RuntimeError(
            f"cannot assume Transform role {role_arn} as session {STABLE_SESSION_NAME!r}: {e}. "
            "Check the role's trust policy (platform AgentRole + sts:ExternalId) and TRANSFORM_EXTERNAL_ID."
        ) from e
    for key in ("AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"):
        if not creds.get(key):
            raise RuntimeError(f"STS AssumeRole for {role_arn} returned no {key}")
    if not isinstance(creds["Expiration"], datetime.datetime):
        raise RuntimeError(f"STS AssumeRole for {role_arn} returned a non-datetime Expiration {creds['Expiration']!r}")
    return creds


def _utc_iso(ts: datetime.datetime) -> str:
    if ts.tzinfo is None:
        raise RuntimeError(f"credential expiration {ts!r} has no timezone")
    return ts.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refresh_metadata() -> dict:
    creds = assume_transform_role()
    return {
        "access_key": creds["AccessKeyId"],
        "secret_key": creds["SecretAccessKey"],
        "token": creds["SessionToken"],
        "expiry_time": _utc_iso(creds["Expiration"]),
    }


def transform_botocore_credentials() -> RefreshableCredentials:
    """Process-wide refreshable Transform credentials (per role ARN + external id).

    botocore refreshes them before expiry (advisory 15 min, mandatory 10 min), so long jobs
    never sign with expired credentials. The first call assumes the role and raises on failure.
    """
    key = (transform_role_arn(), transform_external_id())
    with _lock:
        creds = _refreshable.get(key)
        if creds is None:
            creds = RefreshableCredentials.create_from_metadata(
                metadata=_refresh_metadata(),
                refresh_using=_refresh_metadata,
                method=_CREDENTIAL_METHOD,
            )
            _refreshable[key] = creds
        return creds


def credential_process_payload(base_session: Any = None) -> dict:
    """AWS ``credential_process`` JSON (Version 1) for the Transform role."""
    creds = assume_transform_role(base_session)
    return {
        "Version": 1,
        "AccessKeyId": creds["AccessKeyId"],
        "SecretAccessKey": creds["SecretAccessKey"],
        "SessionToken": creds["SessionToken"],
        "Expiration": _utc_iso(creds["Expiration"]),
    }
