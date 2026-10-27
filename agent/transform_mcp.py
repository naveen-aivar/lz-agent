"""AWS Transform MCP (stdio) for Strands deploy-phase agents."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterator

from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from strands.tools.mcp import MCPClient

from lzcore import transform_ops
from lzcore.transform_credential_process import mcp_credential_env


def _require_workspace_id() -> str:
    ws = os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip()
    if not ws:
        raise RuntimeError("TRANSFORM_WORKSPACE_ID is required for deploy (AgentCore runtime)")
    return ws


def _stdio_env(config_dir: str) -> dict[str, str]:
    env = get_default_environment()
    for key, value in os.environ.items():
        if key.startswith("AWS_") or key in ("PATH", "HOME", "USER", "USERPROFILE", "HTTP_PROXY", "HTTPS_PROXY", "PYTHONPATH"):
            env[key] = value
    # The MCP server signs every Transform call with the Transform role (stable session name),
    # never with the platform role. Its credentials come from an AWS config profile whose
    # credential_process re-assumes the role whenever botocore needs fresh credentials. Static
    # keys are dropped; container-credential variables stay so the helper can reach the
    # platform role (an explicit profile takes precedence over the container provider).
    env = mcp_credential_env(env, config_dir)
    # The MCP server discovers its region by probing ListWorkspaces in every Transform region and refuses
    # to pick one when the account has profiles in several. Pinning both endpoints to TRANSFORM_REGION makes
    # every probe hit that region's endpoint; only the probe signed for that region succeeds, so the server
    # auto-selects it (the library's documented AWS_TRANSFORM_*_ENDPOINT overrides).
    region = transform_ops.transform_region()
    env["TRANSFORM_REGION"] = region
    env["AWS_REGION"] = region
    env["AWS_TRANSFORM_API_ENDPOINT"] = f"https://api.transform.{region}.on.aws/"
    env["AWS_TRANSFORM_TCP_ENDPOINT"] = f"https://transform.{region}.api.aws"
    env["TRANSFORM_WORKSPACE_ID"] = _require_workspace_id()
    orch = os.environ.get("TRANSFORM_ORCHESTRATOR_AGENT", "").strip()
    if orch:
        env["TRANSFORM_ORCHESTRATOR_AGENT"] = orch
    return env


def server_params(config_dir: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "awslabs.aws_transform_mcp_server.server"],
        env=_stdio_env(config_dir),
    )


def client(config_dir: str) -> MCPClient:
    params = server_params(config_dir)
    return MCPClient(lambda: stdio_client(params), startup_timeout=120)


@contextmanager
def transform_tools() -> Iterator[list]:
    """Load Transform MCP tools; failures fail the deploy phase.

    The AWS config for the subprocess lives in a private temp dir (0700) for the life of the
    MCP session and is removed afterwards.
    """
    _require_workspace_id()
    with tempfile.TemporaryDirectory(prefix="lz-transform-mcp-") as config_dir:
        mcp = client(config_dir)
        mcp.__enter__()
        try:
            loaded = mcp.list_tools_sync()
            if not loaded:
                raise RuntimeError("Transform MCP started but returned no tools")
            yield loaded
        finally:
            mcp.__exit__(None, None, None)
