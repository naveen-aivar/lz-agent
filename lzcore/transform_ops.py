"""AWS Transform API helpers for the Landing Zone Deployment Agent (required).

Uses awslabs.aws-transform-mcp-server's SigV4 FES client. Deploy runs fail if the
package, workspace id, or Transform profile is missing.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import boto3

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


class TransformAccessDenied(RuntimeError):
    """A Transform API call returned HTTP 403.

    Carries enough context for the operator to fix it without reading logs: which
    operation failed, which workspace, and which principal must be granted Contributor
    (or higher) membership in the Transform console.
    """

    def __init__(self, operation: str, workspace_id: str, principal_arn: str, cause: Any):
        self.operation = operation
        self.workspace_id = workspace_id
        self.principal_arn = principal_arn
        self.cause = cause
        super().__init__(
            f"Transform {operation} returned HTTP 403 for principal {principal_arn}; "
            f"add this principal as Contributor (or higher) in Transform workspace "
            f"{workspace_id} (TRANSFORM_WORKSPACE_ID). Cause: {cause}"
        )


def _resolve_principal() -> str:
    """Resolve the calling principal ARN via STS.

    On failure, return an explicit "could not be resolved" marker string (NOT a fabricated
    ARN) so the error message never implies a principal we did not actually observe.
    """
    try:
        # Fresh Session: boto3's default session caches the credentials it resolved at import,
        # which are not the credentials the Transform client signed with after the identity switch.
        return boto3.Session().client("sts").get_caller_identity()["Arn"]
    except Exception as sts_error:  # noqa: BLE001 - message must name the STS failure
        return f"<unresolved: calling principal could not be resolved: {sts_error}>"


def _is_403(exc: Any) -> bool:
    """Duck-type a Transform HttpError 403 without hard-importing the symbol."""
    return getattr(exc, "status_code", None) == 403


async def _call(operation: str, request: Any) -> Any:
    """Invoke a Transform API operation, translating HTTP 403 into TransformAccessDenied.

    Other errors propagate unchanged. 403 detection is by duck-typing ``status_code`` so we
    do not hard-depend on ``HttpError`` at import time (the package may be absent).
    """
    try:
        return await call_transform_api(operation, request)
    except Exception as exc:  # noqa: BLE001 - re-raised below; 403 translated, others re-raised
        if _is_403(exc):
            raise TransformAccessDenied(
                operation, workspace_id(), _resolve_principal(), cause=exc
            ) from exc
        raise


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


async def _discover_sigv4_regions() -> tuple[list[str], dict[str, Exception]]:
    """Probe every FES region. Return (successful regions, {region: error}).

    Per-region errors are collected (not dropped) so init_connection can report why no
    region succeeded instead of a generic "probe failed".
    """
    async def _call_region(region: str) -> tuple[str, Exception | None]:
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
            return region, None
        except Exception as exc:  # noqa: BLE001 - error retained for diagnostics
            return region, exc

    results = await asyncio.gather(*[_call_region(r) for r in FES_REGIONS])
    ok = [region for region, err in results if err is None]
    errors = {region: err for region, err in results if err is not None}
    return ok, errors


def init_connection(preferred_region: str | None = None) -> dict[str, Any]:
    """Probe SigV4 Transform access (same as MCP server startup)."""
    require_workspace_id()
    if not TRANSFORM_AVAILABLE:
        raise RuntimeError(f"aws-transform-mcp-server not installed: {_import_error}")
    region = preferred_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    async def _probe():
        if is_fes_available():
            return {"ok": True, "authMode": "configured", "region": region}
        regions, region_errors = await _discover_sigv4_regions()
        if not regions:
            set_sigv4_fes_available(False)
            forbidden = next(
                (err for err in region_errors.values() if _is_403(err)), None
            )
            if forbidden is not None:
                raise TransformAccessDenied(
                    "ListWorkspaces", workspace_id(), _resolve_principal(), cause=forbidden
                ) from forbidden
            causes = "; ".join(f"{r}: {e}" for r, e in region_errors.items()) or "no regions probed"
            raise RuntimeError(
                "Transform SigV4 probe failed: enable Transform for this account/role in "
                f"the console. Per-region causes: {causes}"
            )
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
    created = await _call("CreateJob", req)
    job_id = created["jobId"] if isinstance(created, dict) else created
    await _call("StartJob", StartJobRequest(workspaceId=ws, jobId=job_id))
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
    return await _call(
        "SendMessage",
        SendMessageRequest(text=text[:7000], idempotencyToken=str(uuid.uuid4()), metadata=metadata),
    )


async def _get_job(ws: str, job_id: str) -> dict:
    raw = await _call("GetJob", GetJobRequest(workspaceId=ws, jobId=job_id))
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


def job_status(job: dict, job_id: str) -> str:
    """Job state from a GetJob response: ``statusDetails.status`` (JobStatus enum).

    Raises when absent: an empty status would read as "still running" forever.
    """
    status = ((job.get("statusDetails") or {}).get("status") or job.get("status") or "").strip().upper()
    if not status:
        raise RuntimeError(
            f"Transform GetJob for job {job_id} returned no statusDetails.status; keys: {sorted(job)}"
        )
    return status


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
        status = job_status(job, job_id)
        # A cancelled/stopped job is a failure, not a completed one. Treating it as done
        # would let a cancelled analyze job flow silently into merge (no-fallbacks rule).
        if status in {"STOPPED", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"Transform job {job_id} ended with status {status}")
        terminal = status in {
            "SUCCEEDED",
            "SUCCESS",
            "COMPLETED",
            "COMPLETE",
            "DONE",
            "FAILED",
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


