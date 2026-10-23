"""AWS Transform API helpers for the Landing Zone Deployment Agent (required).

Uses awslabs.aws-transform-mcp-server's SigV4 FES client. Deploy runs fail if the
package, workspace id, or Transform profile is missing.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

TRANSFORM_AVAILABLE = False
_import_error: str | None = None

try:
    from awslabs.aws_transform_mcp_server.config_store import (
        derive_transform_api_endpoint,
        is_fes_available,
        set_sigv4_fes_available,
        set_sigv4_region,
        set_sigv4_regions,
    )
    from awslabs.aws_transform_mcp_server.consts import FES_REGIONS, PROFILE_DISCOVERY_TIMEOUT_SECONDS
    from awslabs.aws_transform_mcp_server.transform_api_client import (
        call_fes_direct_sigv4,
        call_transform_api,
    )
    from awslabs.aws_transform_mcp_server.transform_api_models import (
        ChatJobMetadata,
        CreateJobRequest,
        GetJobRequest,
        Metadata,
        ResourcesOnScreen,
        SendMessageRequest,
        StartJobRequest,
        WorkspaceMetadata,
    )

    TRANSFORM_AVAILABLE = True
except ImportError as e:
    _import_error = str(e)


def require_workspace_id() -> str:
    ws = os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip()
    if not ws:
        raise RuntimeError("TRANSFORM_WORKSPACE_ID is required for deploy runs")
    return ws


def workspace_id() -> str:
    return require_workspace_id()


def orchestrator_agent() -> str | None:
    v = os.environ.get("TRANSFORM_ORCHESTRATOR_AGENT", "").strip()
    return v or None


def _run(coro):
    return asyncio.run(coro)


async def _discover_sigv4_regions() -> list[str]:
    async def _call_region(region: str) -> str | None:
        try:
            endpoint = derive_transform_api_endpoint(region)
            await asyncio.wait_for(
                call_fes_direct_sigv4(
                    endpoint,
                    "ListWorkspaces",
                    {},
                    timeout_seconds=PROFILE_DISCOVERY_TIMEOUT_SECONDS,
                    max_retries=0,
                    region=region,
                ),
                timeout=PROFILE_DISCOVERY_TIMEOUT_SECONDS + 2,
            )
            return region
        except Exception:
            return None

    results = await asyncio.gather(*[_call_region(r) for r in FES_REGIONS])
    return [r for r in results if r is not None]


def init_connection(preferred_region: str | None = None) -> dict[str, Any]:
    """Probe SigV4 Transform access (same as MCP server startup)."""
    require_workspace_id()
    if not TRANSFORM_AVAILABLE:
        raise RuntimeError(f"aws-transform-mcp-server not installed: {_import_error}")
    region = preferred_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    async def _probe():
        if is_fes_available():
            return {"ok": True, "authMode": "configured", "region": region}
        regions = await _discover_sigv4_regions()
        if not regions:
            set_sigv4_fes_available(False)
            raise RuntimeError("Transform SigV4 probe failed: enable Transform for this account/role in the console.")
        if len(regions) == 1:
            set_sigv4_region(regions[0])
            set_sigv4_fes_available(True)
            return {"ok": True, "authMode": "sigv4", "region": regions[0]}
        pick = region if region in regions else regions[0]
        set_sigv4_region(pick)
        set_sigv4_regions(regions)
        set_sigv4_fes_available(True)
        return {"ok": True, "authMode": "sigv4", "region": pick, "availableRegions": regions}

    return _run(_probe())


async def _create_and_start_job(ws: str, name: str, objective: str, intent: str) -> str:
    req = CreateJobRequest(
        workspaceId=ws,
        jobName=name,
        objective=objective,
        intent=intent,
        idempotencyToken=str(uuid.uuid4()),
        orchestratorAgent=orchestrator_agent(),
    )
    created = await call_transform_api("CreateJob", req)
    job_id = created["jobId"] if isinstance(created, dict) else created
    await call_transform_api("StartJob", StartJobRequest(workspaceId=ws, jobId=job_id))
    return job_id


async def _send(ws: str, job_id: str, text: str) -> dict:
    metadata = Metadata(
        resourcesOnScreen=ResourcesOnScreen(
            workspace=WorkspaceMetadata(
                workspaceId=ws,
                jobs=[ChatJobMetadata(jobId=job_id, focusState="ACTIVE")],
            ),
        ),
    )
    return await call_transform_api(
        "SendMessage",
        SendMessageRequest(text=text[:7000], idempotencyToken=str(uuid.uuid4()), metadata=metadata),
    )


async def _get_job(ws: str, job_id: str) -> dict:
    raw = await call_transform_api("GetJob", GetJobRequest(workspaceId=ws, jobId=job_id))
    return raw.get("job", raw) if isinstance(raw, dict) else {}


def start_landing_zone_job(*, run_id: str, phase: str, prompt: str) -> dict[str, Any]:
    """Create a Transform job and send the landing-zone workflow prompt."""
    init = init_connection()
    ws = workspace_id()

    async def _go():
        job_id = await _create_and_start_job(
            ws,
            f"lz-agent-{run_id[:8]}-{phase}",
            objective="Landing zone deployment agent workflow",
            intent="landing-zone",
        )
        await _send(ws, job_id, prompt)
        job = await _get_job(ws, job_id)
        return {"workspaceId": ws, "jobId": job_id, "jobStatus": job.get("status"), "init": init}

    return _run(_go())


def poll_job(job_id: str, workspace: str | None = None) -> dict[str, Any]:
    ws = workspace or workspace_id()
    if not TRANSFORM_AVAILABLE:
        raise RuntimeError(f"aws-transform-mcp-server not installed: {_import_error}")
    if not is_fes_available():
        init_connection()
    if not is_fes_available():
        raise RuntimeError("Transform FES not available after init")

    async def _go():
        job = await _get_job(ws, job_id)
        status = (job.get("status") or "").upper()
        terminal = status in {
            "SUCCEEDED",
            "SUCCESS",
            "COMPLETED",
            "COMPLETE",
            "DONE",
            "FAILED",
            "STOPPED",
            "CANCELLED",
            "CANCELED",
        }
        awaiting = status in {"AWAITING_HUMAN_INPUT", "PAUSED", "BLOCKED"} or "HITL" in status
        return {
            "ok": True,
            "jobId": job_id,
            "status": status,
            "done": terminal,
            "awaitingHumanApproval": awaiting,
            "job": job,
        }

    return _run(_go())


