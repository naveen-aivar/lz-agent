"""Stable AWS identity for the deploy phase.

AWS Transform keys workspace collaborators by ``RoleId:SessionName``. AgentCore gives each
runtime session a fresh ``BedrockAgentCore-<uuid>`` session name, so a collaborator invite
never carries over to the next run. The deploy phase therefore re-assumes the AgentCore role
under one fixed session name and exports those credentials to the process environment, so
in-process boto3 sessions (Transform SigV4 client, target-account AssumeRole) and the
Transform MCP subprocess all sign as ``<AgentRole RoleId>:STABLE_SESSION_NAME``.
"""
from __future__ import annotations

import os

import boto3

STABLE_SESSION_NAME = "ingram-lz-agent"
_CRED_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")

# Credentials the runtime started with (absent when it uses the container credential
# endpoint). Restored before every assume so a later invoke never chains from expired
# static credentials written by an earlier invoke.
_ORIGINAL_ENV = {k: os.environ.get(k) for k in _CRED_VARS}


def _restore_original_env() -> None:
    for key, value in _ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def assume_stable_session() -> str:
    """Switch process credentials to AGENT_ROLE_ARN with STABLE_SESSION_NAME. Returns the caller ARN."""
    role_arn = os.environ.get("AGENT_ROLE_ARN", "").strip()
    if not role_arn:
        raise RuntimeError(
            "AGENT_ROLE_ARN is not set on the AgentCore runtime; redeploy the platform stack "
            "(infra/platform/platform.yaml passes it) so the deploy phase can use a stable Transform identity"
        )
    _restore_original_env()
    try:
        creds = boto3.Session().client("sts").assume_role(
            RoleArn=role_arn,
            RoleSessionName=STABLE_SESSION_NAME,
            DurationSeconds=3600,
        )["Credentials"]
    except Exception as e:
        raise RuntimeError(
            f"cannot assume {role_arn} as session {STABLE_SESSION_NAME!r}: {e}. "
            "The AgentRole trust policy must allow the role to assume itself (see platform.yaml)."
        ) from e
    os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
    os.environ["AWS_SESSION_TOKEN"] = creds["SessionToken"]
    arn = boto3.Session().client("sts").get_caller_identity()["Arn"]
    if not arn.endswith(f"/{STABLE_SESSION_NAME}"):
        raise RuntimeError(f"stable identity switch failed: caller is {arn}, expected session {STABLE_SESSION_NAME!r}")
    return arn
