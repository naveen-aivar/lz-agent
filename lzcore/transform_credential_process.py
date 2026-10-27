"""Transform role credentials for the Transform MCP subprocess, via AWS ``credential_process``.

The MCP server builds its own boto3 sessions. Instead of handing it a static snapshot of
credentials (which expire mid-turn), it gets an AWS config profile whose ``credential_process``
runs this module. botocore re-runs the helper whenever it needs credentials.

Three parts:

* ``mcp_credential_env(base_env, config_dir)`` (platform process): writes the profile into a
  private directory the caller owns and returns the subprocess env (AWS_CONFIG_FILE +
  AWS_PROFILE, no static keys). It requires the container-credential variables
  (AWS_CONTAINER_CREDENTIALS_FULL_URI or AWS_CONTAINER_CREDENTIALS_RELATIVE_URI) and rejects
  web-identity variables (AWS_ROLE_ARN / AWS_WEB_IDENTITY_TOKEN_FILE): botocore resolves web
  identity before ``credential_process``, so the MCP server would sign as the platform role. The
  design assumes the AgentCore runtime delivers the platform role through the container
  credential endpoint. If a runtime uses another mechanism this raises at MCP startup, by design;
  confirm once on a live runtime (``boto3.Session().get_credentials().method`` is
  ``container-role``).
* ``preflight_helper(env)`` (platform process, before the MCP server is spawned): runs the helper
  once with the subprocess env and requires valid credential_process JSON. A broken helper fails
  the deploy phase here instead of leaving the MCP server silently unconfigured.
* ``main()`` (``python -m lzcore.transform_credential_process``, run by botocore inside the MCP
  server): prints the credential_process JSON for TRANSFORM_ROLE_ARN. The JSON is cached in the
  private config dir (one 0600 file per role ARN + external id, under ``fcntl.flock``) and reused
  until less than 15 minutes of validity remain, so the MCP server's per-call botocore sessions
  do not each call STS AssumeRole. On a cache miss the helper requires its base credentials to
  come from the container provider, then assumes the role. On failure it prints the reason to
  stderr and exits 1.
"""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping

PROFILE_NAME = "ingram-lz-transform"
CONFIG_FILE_NAME = "aws-config"
CREDENTIALS_FILE_NAME = "aws-credentials"
CACHE_DIR_VAR = "LZ_TRANSFORM_CREDENTIAL_CACHE_DIR"
CACHE_MIN_REMAINING = datetime.timedelta(minutes=15)
PREFLIGHT_TIMEOUT_SECONDS = 60
_PAYLOAD_KEYS = ("Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration")
_EXPIRATION_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Static credentials must never reach the MCP subprocess: they would not refresh.
_STATIC_CREDENTIAL_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN")
_PROFILE_VARS = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")
CONTAINER_CREDENTIAL_VARS = ("AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
WEB_IDENTITY_VARS = ("AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE")
BASE_CREDENTIAL_METHOD = "container-role"
_LZCORE_PARENT = str(Path(__file__).resolve().parents[1])


def helper_command() -> str:
    """Shell-quoted command botocore runs for the profile's credential_process."""
    return " ".join(shlex.quote(part) for part in (sys.executable, "-m", "lzcore.transform_credential_process"))


def _write_private(path: Path, text: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def _require_private_dir(path: str, what: str) -> Path:
    """The directory must exist, belong to this user and grant nothing to group/other."""
    directory = Path(path)
    if not directory.is_dir():
        raise RuntimeError(f"{what} {path!r} does not exist")
    st = directory.stat()
    if st.st_uid != os.getuid():
        raise RuntimeError(f"{what} {path!r} is owned by uid {st.st_uid}, not this process (uid {os.getuid()})")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise RuntimeError(f"{what} {path!r} has mode {oct(stat.S_IMODE(st.st_mode))}; it must be 0700")
    return directory


def write_profile(config_dir: str) -> tuple[str, str]:
    """Write the AWS config (profile with credential_process) and an empty shared-credentials
    file into ``config_dir``. Returns (config_path, credentials_path)."""
    directory = _require_private_dir(config_dir, "Transform MCP config dir")
    config_path = directory / CONFIG_FILE_NAME
    credentials_path = directory / CREDENTIALS_FILE_NAME
    _write_private(config_path, f"[profile {PROFILE_NAME}]\ncredential_process = {helper_command()}\n")
    # An empty shared-credentials file, so ~/.aws/credentials can never shadow the profile.
    _write_private(credentials_path, "")
    return str(config_path), str(credentials_path)


def _require_container_credentials(base_env: Mapping[str, str]) -> None:
    web_identity = [k for k in WEB_IDENTITY_VARS if (base_env.get(k) or "").strip()]
    if web_identity:
        raise RuntimeError(
            f"Transform MCP subprocess env has web-identity variables {web_identity}: botocore resolves web "
            "identity before credential_process, so the MCP server would sign as the platform role instead "
            "of TRANSFORM_ROLE_ARN. lzcore expects the runtime to deliver platform credentials through the "
            f"container credential endpoint ({' or '.join(CONTAINER_CREDENTIAL_VARS)}); remove "
            f"{web_identity} or update lzcore/transform_credential_process.py for this runtime"
        )
    if not any((base_env.get(k) or "").strip() for k in CONTAINER_CREDENTIAL_VARS):
        raise RuntimeError(
            f"Transform MCP subprocess env has neither {CONTAINER_CREDENTIAL_VARS[0]} nor "
            f"{CONTAINER_CREDENTIAL_VARS[1]}: the credential_process helper needs the platform role from the "
            "container credential endpoint (AgentCore runtime) to assume TRANSFORM_ROLE_ARN. Static keys are "
            "not passed to the MCP subprocess because they cannot refresh"
        )


def mcp_credential_env(base_env: Mapping[str, str], config_dir: str) -> dict[str, str]:
    """Env for the Transform MCP subprocess: ``base_env`` plus the credential_process profile."""
    from lzcore.transform_credentials import parse_role_arn, transform_external_id, transform_role_arn

    role_arn = transform_role_arn()
    parse_role_arn(role_arn)
    _require_container_credentials(base_env)
    config_path, credentials_path = write_profile(config_dir)

    env = {k: v for k, v in base_env.items() if k not in _STATIC_CREDENTIAL_VARS and k not in _PROFILE_VARS}
    env["AWS_CONFIG_FILE"] = config_path
    env["AWS_SHARED_CREDENTIALS_FILE"] = credentials_path
    env["AWS_PROFILE"] = PROFILE_NAME
    env[CACHE_DIR_VAR] = str(Path(config_dir))
    env["TRANSFORM_ROLE_ARN"] = role_arn
    external_id = transform_external_id()
    if external_id:
        env["TRANSFORM_EXTERNAL_ID"] = external_id
    else:
        env.pop("TRANSFORM_EXTERNAL_ID", None)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _LZCORE_PARENT + (os.pathsep + existing if existing else "")
    return env


# --------------------------------------------------------------------------------------
# credential_process payload validation (shared by the cache and the preflight)
# --------------------------------------------------------------------------------------
def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def validate_payload(payload: object, source: str) -> datetime.datetime:
    """Require credential_process JSON (Version 1). Returns its expiration (UTC); raises naming ``source``."""
    if not isinstance(payload, dict) or set(payload) != set(_PAYLOAD_KEYS):
        keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise RuntimeError(f"{source} is not credential_process JSON with keys {list(_PAYLOAD_KEYS)} (got {keys})")
    if payload["Version"] != 1:
        raise RuntimeError(f"{source} has Version {payload['Version']!r}; credential_process requires 1")
    for key in ("AccessKeyId", "SecretAccessKey", "SessionToken"):
        if not isinstance(payload[key], str) or not payload[key]:
            raise RuntimeError(f"{source} has no {key}")
    try:
        expiration = datetime.datetime.strptime(payload["Expiration"], _EXPIRATION_FORMAT).replace(
            tzinfo=datetime.timezone.utc
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{source} has an unparseable Expiration {payload['Expiration']!r}") from exc
    return expiration


# --------------------------------------------------------------------------------------
# Helper (runs inside the MCP server, via botocore's ProcessProvider)
# --------------------------------------------------------------------------------------
def _cache_path(cache_dir: Path, role_arn: str, external_id: str | None) -> Path:
    digest = hashlib.sha256(f"{role_arn}\0{external_id or ''}".encode()).hexdigest()[:32]
    return cache_dir / f"transform-credentials-{digest}.json"


def _read_cache(path: Path) -> dict | None:
    """Cached payload with at least CACHE_MIN_REMAINING left, else None (absent or near expiry).

    A cache file that is not valid credential_process JSON raises: it is written atomically by
    this module, so a malformed file means something else wrote it.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except ValueError as exc:
        raise RuntimeError(f"Transform credential cache {path} is not JSON: {exc}") from exc
    expiration = validate_payload(payload, f"Transform credential cache {path}")
    if expiration - _now() < CACHE_MIN_REMAINING:
        return None
    return payload


def _write_cache(path: Path, payload: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(payload))
    os.replace(tmp, path)


def _assume_from_container() -> dict:
    import boto3

    from lzcore.transform_credentials import credential_process_payload

    base = boto3.Session()
    creds = base.get_credentials()
    method = getattr(creds, "method", None)
    if creds is None or method != BASE_CREDENTIAL_METHOD:
        raise RuntimeError(
            f"base credentials resolved via {method!r}, expected {BASE_CREDENTIAL_METHOD!r} (the AgentCore "
            "container credential endpoint); the helper assumes TRANSFORM_ROLE_ARN only from the platform role"
        )
    payload = credential_process_payload(base)
    validate_payload(payload, "STS AssumeRole result")
    return payload


def cached_credential_process_payload() -> dict:
    """credential_process JSON for TRANSFORM_ROLE_ARN, from the private cache when still valid."""
    from lzcore.transform_credentials import parse_role_arn, transform_external_id, transform_role_arn

    cache_dir_value = os.environ.get(CACHE_DIR_VAR, "").strip()
    if not cache_dir_value:
        raise RuntimeError(
            f"{CACHE_DIR_VAR} is not set: the helper caches credentials in the private Transform MCP config "
            "dir, which mcp_credential_env sets for the MCP subprocess"
        )
    cache_dir = _require_private_dir(cache_dir_value, f"{CACHE_DIR_VAR}")
    role_arn = transform_role_arn()
    parse_role_arn(role_arn)
    path = _cache_path(cache_dir, role_arn, transform_external_id())
    lock_fd = os.open(str(path.with_name(path.name + ".lock")), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        payload = _read_cache(path)
        if payload is None:
            payload = _assume_from_container()
            _write_cache(path, payload)
        return payload
    finally:
        os.close(lock_fd)  # closing the descriptor releases the flock


def main() -> int:
    # This process exists only to print credentials. Its inherited AWS_PROFILE is the profile
    # that runs this helper; drop it so the base session resolves the platform (container)
    # credentials instead of recursing into credential_process.
    for key in _PROFILE_VARS:
        os.environ.pop(key, None)
    try:
        payload = cached_credential_process_payload()
    except Exception as exc:  # noqa: BLE001 - reported on stderr; non-zero exit fails the caller
        print(f"lzcore.transform_credential_process: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(payload))
    return 0


# --------------------------------------------------------------------------------------
# Preflight (platform process, before spawning the MCP server)
# --------------------------------------------------------------------------------------
def preflight_helper(env: Mapping[str, str], timeout: float = PREFLIGHT_TIMEOUT_SECONDS) -> dict:
    """Run the profile's credential_process command once with the MCP subprocess env.

    Raises unless it exits 0 with valid, unexpired credential_process JSON. Returns only
    ``{"expiration": <ISO>}``, never the credentials. The run also fills the helper cache, so the
    MCP server's startup probe reuses these credentials instead of calling STS again.
    """
    command = shlex.split(helper_command())
    try:
        proc = subprocess.run(command, env=dict(env), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Transform credential_process helper did not finish within {timeout}s: {command}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"Transform credential_process helper failed (exit {proc.returncode}): {proc.stderr.strip() or '<no stderr>'}"
        )
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(f"Transform credential_process helper printed non-JSON output ({len(proc.stdout)} chars)") from exc
    expiration = validate_payload(payload, "Transform credential_process helper output")
    if expiration <= _now():
        raise RuntimeError(f"Transform credential_process helper returned expired credentials ({payload['Expiration']})")
    return {"expiration": payload["Expiration"]}


if __name__ == "__main__":
    sys.exit(main())
