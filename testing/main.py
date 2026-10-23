"""Minimal Strands agent harness for AWS Transform MCP (stdio).

Install (recommended: local venv in testing/):
  cd testing && python3 -m venv .venv && .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt

Auth: standard AWS credentials (AWS_PROFILE / SSO / env keys). Transform supports IAM and IAM Identity Center.

Run:
  export AWS_PROFILE=your-profile AWS_REGION=us-east-1
  export TRANSFORM_WORKSPACE_ID=<uuid>
  export MODEL_ID=us.anthropic.claude-sonnet-4-6

  python testing/main.py
  python testing/main.py "List Transform workspaces I can access"
"""
from __future__ import annotations

import os
import sys

from strands import Agent
from strands.models import BedrockModel

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "agent"))

import bedrock_auth  # noqa: E402
from transform_mcp import transform_tools  # noqa: E402

SYSTEM = """You are a helper for AWS Transform landing-zone and migration workflows.
Use the Transform MCP tools to inspect workspaces, connectors, jobs, and artifacts.
Prefer calling tools over guessing. Summarize results clearly for the user."""


def main() -> None:
    args = sys.argv[1:]
    list_tools_only = args == ["--list-tools"] or args == ["--list-tools-only"]
    if list_tools_only:
        args = []

    bedrock_auth.configure_bedrock_api_key()
    prompt = " ".join(args).strip() or (
        "Call Transform MCP to discover what is available in my account: "
        "list tools you have, then try the lightest read-only operation "
        "(e.g. workspaces or connectors) and report what you find."
    )
    model_id = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")

    print("Starting AWS Transform MCP server (stdio)...", file=sys.stderr)
    with transform_tools() as tools:
        print(f"Loaded {len(tools)} MCP tools.", file=sys.stderr)
        if list_tools_only:
            for t in tools:
                print(getattr(t, "tool_name", None) or getattr(t, "name", t))
            return
        agent = Agent(
            model=BedrockModel(model_id=model_id, max_tokens=8192),
            system_prompt=SYSTEM,
            tools=tools,
        )
        print("Running agent...\n", file=sys.stderr)
        out = agent(prompt)
        print(out)


if __name__ == "__main__":
    main()
