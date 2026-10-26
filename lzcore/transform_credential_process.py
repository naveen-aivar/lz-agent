"""Transform role credentials for the Transform MCP subprocess, via AWS ``credential_process``.

The MCP server builds its own boto3 sessions. Instead of handing it a static snapshot of
credentials (which expire mid-turn), it gets an AWS config profile whose ``credential_process``
runs this module. botocore re-runs the helper whenever the credentials near expiry.

Two halves:

* ``mcp_credential_env(base_env, config_dir)`` (platform process): writes the profile into a
  directory the caller owns and returns the subprocess env (AWS_CONFIG_FILE + AWS_PROFILE, no
  static keys, container-credential variables kept so the helper can reach the platform role).
* ``main()`` (``python -m lzcore.transform_credential_process``, run by botocore inside the MCP
  server): assumes TRANSFORM_ROLE_ARN from the platform credentials and prints the
  credential_process JSON. On failure it prints the reason to stderr and exits 1.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Mapping

PROFILE_NAME = "ingram-lz-transform"
CONFIG_FILE_NAME = "aws-config"
CREDENTIALS_FILE_NAME = "aws-credentials"

# Static credentials must never reach the MCP subprocess: they would not refresh.
_STATIC_CREDENTIAL_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN")
_PROFILE_VARS = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")
_LZCORE_PARENT = str(Path(__file__).resolve().parents[1])


def helper_command() -> str:
    """Shell-quoted command botocore runs for the profile's credential_process."""
    return " ".join(shlex.quote(part) for part in (sys.executable, "-m", "lzcore.transform_credential_process"))


def _write_private(path: Path, text: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def write_profile(config_dir: str) -> tuple[str, str]:
    """Write the AWS config (profile with credential_process) and an empty shared-credentials
    file into ``config_dir``. Returns (config_path, credentials_path)."""
    directory = Path(config_dir)
    if not directory.is_dir():
        raise RuntimeError(f"Transform MCP config dir {config_dir!r} does not exist")
    config_path = directory / CONFIG_FILE_NAME
    credentials_path = directory / CREDENTIALS_FILE_NAME
    _write_private(config_path, f"[profile {PROFILE_NAME}]\ncredential_process = {helper_command()}\n")
    # An empty shared-credentials file, so ~/.aws/credentials can never shadow the profile.
    _write_private(credentials_path, "")
    return str(config_path), str(credentials_path)


def mcp_credential_env(base_env: Mapping[str, str], config_dir: str) -> dict[str, str]:
    """Env for the Transform MCP subprocess: ``base_env`` plus the credential_process profile."""
    from lzcore.transform_credentials import parse_role_arn, transform_external_id, transform_role_arn

    role_arn = transform_role_arn()
    parse_role_arn(role_arn)
    config_path, credentials_path = write_profile(config_dir)

    env = {k: v for k, v in base_env.items() if k not in _STATIC_CREDENTIAL_VARS and k not in _PROFILE_VARS}
    env["AWS_CONFIG_FILE"] = config_path
    env["AWS_SHARED_CREDENTIALS_FILE"] = credentials_path
    env["AWS_PROFILE"] = PROFILE_NAME
    env["TRANSFORM_ROLE_ARN"] = role_arn
    external_id = transform_external_id()
    if external_id:
        env["TRANSFORM_EXTERNAL_ID"] = external_id
    else:
        env.pop("TRANSFORM_EXTERNAL_ID", None)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _LZCORE_PARENT + (os.pathsep + existing if existing else "")
    return env


def main() -> int:
    # This process exists only to print credentials. Its inherited AWS_PROFILE is the profile
    # that runs this helper; drop it so the base session resolves the platform (container)
    # credentials instead of recursing into credential_process.
    for key in _PROFILE_VARS:
        os.environ.pop(key, None)
    try:
        import boto3

        from lzcore.transform_credentials import credential_process_payload

        payload = credential_process_payload(boto3.Session())
    except Exception as exc:  # noqa: BLE001 - reported on stderr; non-zero exit fails the caller
        print(f"lzcore.transform_credential_process: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
