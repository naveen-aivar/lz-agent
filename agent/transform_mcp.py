"""AWS Transform MCP (stdio) for Strands deploy-phase agents."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from strands.tools.mcp import MCPClient


def _require_workspace_id() -> str:
    ws = os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip()
    if not ws:
        raise RuntimeError("TRANSFORM_WORKSPACE_ID is required for deploy (AgentCore runtime)")
    return ws


def _stdio_env() -> dict[str, str]:
    env = get_default_environment()
    for key, value in os.environ.items():
        if key.startswith("AWS_") or key in ("PATH", "HOME", "USER", "USERPROFILE", "HTTP_PROXY", "HTTPS_PROXY"):
            env[key] = value
    env["TRANSFORM_WORKSPACE_ID"] = _require_workspace_id()
    orch = os.environ.get("TRANSFORM_ORCHESTRATOR_AGENT", "").strip()
    if orch:
        env["TRANSFORM_ORCHESTRATOR_AGENT"] = orch
    return env


def server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "awslabs.aws_transform_mcp_server.server"],
        env=_stdio_env(),
    )


def client() -> MCPClient:
    return MCPClient(lambda: stdio_client(server_params()), startup_timeout=120)


@contextmanager
def transform_tools() -> Iterator[list]:
    """Load Transform MCP tools; failures fail the deploy phase."""
    _require_workspace_id()
    mcp = client()
    mcp.__enter__()
    try:
        loaded = mcp.list_tools_sync()
        if not loaded:
            raise RuntimeError("Transform MCP started but returned no tools")
        yield loaded
    finally:
        mcp.__exit__(None, None, None)
