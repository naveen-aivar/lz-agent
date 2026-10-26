"""AWS Transform API helpers for the Landing Zone Deployment Agent (required).

Uses awslabs.aws-transform-mcp-server's SigV4 FES and TCP clients. Deploy runs fail if the
package, workspace id, or Transform profile is missing.

Signing: the library resolves credentials from the default chain. We replace its two credential
seams (``transform_api_client._create_sigv4_client`` and ``tcp_client._resolve_tcp_config``) so
every in-process Transform call signs with the Transform role's refreshable credentials
(``lzcore.transform_credentials``). Nothing is exported to ``os.environ``. The seams are library
internals, so their shape is asserted at import against the pinned library version.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from typing import Any, Optional

from lzcore.transform_credentials import transform_botocore_credentials, transform_principal_arn

EXPECTED_LIBRARY_VERSION = "0.2.3"

TRANSFORM_AVAILABLE = False
_import_error: Optional[str] = None

try:
    import boto3
    import botocore.session
    from botocore.config import Config as BotoConfig
    from botocore.credentials import CredentialProvider, CredentialResolver

    from awslabs.aws_transform_mcp_server import __version__ as _library_version
    from awslabs.aws_transform_mcp_server import tcp_client as _tcp
    from awslabs.aws_transform_mcp_server import transform_api_client as _tac
    from awslabs.aws_transform_mcp_server.aws_helper import USER_AGENT
    from awslabs.aws_transform_mcp_server.config_store import (
        derive_tcp_endpoint,
        derive_transform_api_endpoint,
        get_sigv4_region,
        is_fes_available,
        set_sigv4_fes_available,
        set_sigv4_region,
        set_sigv4_regions,
    )
    from awslabs.aws_transform_mcp_server.consts import (
        FES_REGIONS,
        MAX_RETRIES,
        PROFILE_DISCOVERY_TIMEOUT_SECONDS,
        TIMEOUT_SECONDS,
    )
    from awslabs.aws_transform_mcp_server.tcp_client import call_tcp
    from awslabs.aws_transform_mcp_server.tools.job_status import _ACTIONABLE_HITL_STATUSES
    from awslabs.aws_transform_mcp_server.transform_api_client import (
        call_fes_direct_sigv4,
        call_transform_api,
    )
    from awslabs.aws_transform_mcp_server.transform_api_models import (
        BatchGetMessageRequest,
        ChatJobMetadata,
        CreateJobRequest,
        GetJobRequest,
        HitlTaskFilter,
        ListHitlTasksRequest,
        ListMessagesRequest,
        Metadata,
        ResourcesOnScreen,
        SendMessageRequest,
        StartJobRequest,
        StopJobRequest,
        WorkspaceMetadata,
    )

    TRANSFORM_AVAILABLE = True
except ImportError as e:
    _import_error = str(e)


# --------------------------------------------------------------------------------------
# Credential seams (installed once at import when the library is present).
# --------------------------------------------------------------------------------------
def _seam_error(detail: str) -> RuntimeError:
    return RuntimeError(
        f"awslabs.aws-transform-mcp-server {_library_version} is not compatible with lzcore.transform_ops: "
        f"{detail}. lzcore replaces the library's credential seams to sign with the Transform role; pin "
        f"awslabs.aws-transform-mcp-server=={EXPECTED_LIBRARY_VERSION} (agent/requirements.txt, "
        "orchestration/requirements.txt) or update lzcore/transform_ops.py for the new version."
    )


def _assert_library_seams() -> None:
    if _library_version != EXPECTED_LIBRARY_VERSION:
        raise _seam_error(f"expected version {EXPECTED_LIBRARY_VERSION}")
    fn = getattr(_tac, "_create_sigv4_client", None)
    if not callable(fn) or list(inspect.signature(fn).parameters) != ["endpoint", "region", "max_retries", "timeout"]:
        raise _seam_error("transform_api_client._create_sigv4_client(endpoint, region, max_retries, timeout) not found")
    if "_create_sigv4_client" not in _tac.call_fes_direct_sigv4.__code__.co_names:
        raise _seam_error("call_fes_direct_sigv4 no longer builds its client via _create_sigv4_client")
    if not callable(getattr(_tac, "_register_client_app_id", None)):
        raise _seam_error("transform_api_client._register_client_app_id not found")
    resolve = getattr(_tcp, "_resolve_tcp_config", None)
    if not callable(resolve) or list(inspect.signature(resolve).parameters):
        raise _seam_error("tcp_client._resolve_tcp_config() not found")
    if getattr(_tcp.TcpConfig, "_fields", None) != ("endpoint", "region", "credentials"):
        raise _seam_error("tcp_client.TcpConfig fields are not (endpoint, region, credentials)")
    if "_resolve_tcp_config" not in _tcp.call_tcp.__code__.co_names:
        raise _seam_error("call_tcp no longer resolves its config via _resolve_tcp_config")


if TRANSFORM_AVAILABLE:

    class _TransformRoleProvider(CredentialProvider):
        METHOD = "ingram-transform-assume-role"

        def load(self):
            return transform_botocore_credentials()

    def _transform_sigv4_client(endpoint, region="us-east-1", max_retries=MAX_RETRIES, timeout=TIMEOUT_SECONDS):
        """Library ``_create_sigv4_client`` with explicit Transform-role credentials.

        Mirrors the 0.2.3 body (service model path, user agent, retries, clientAppId header) but
        the botocore session's only credential provider is the Transform role.
        """
        from awslabs.aws_transform_mcp_server._service_model import _MODEL_DIR

        core = botocore.session.get_session()
        core.set_config_variable("region", region)
        core.register_component("credential_provider", CredentialResolver(providers=[_TransformRoleProvider()]))
        loader = core.get_component("data_loader")
        if _MODEL_DIR not in loader.search_paths:
            loader.search_paths.insert(0, _MODEL_DIR)
        session = boto3.Session(botocore_session=core)
        client = session.client(
            "elasticgumbyfrontendservice",
            region_name=region,
            endpoint_url=endpoint,
            config=BotoConfig(
                user_agent_extra=USER_AGENT,
                retries={"mode": "adaptive", "max_attempts": max_retries + 1},
                connect_timeout=timeout,
                read_timeout=timeout,
            ),
        )
        _tac._register_client_app_id(client)
        return client

    def _transform_tcp_config():
        """Library ``_resolve_tcp_config`` with explicit Transform-role credentials."""
        region = get_sigv4_region()
        if not region:
            raise RuntimeError("Transform SigV4 region is not selected; init_connection must succeed before TCP calls")
        return _tcp.TcpConfig(
            endpoint=derive_tcp_endpoint(region),
            region=region,
            credentials=transform_botocore_credentials().get_frozen_credentials(),
        )

    _assert_library_seams()
    _tac._create_sigv4_client = _transform_sigv4_client
    _tcp._resolve_tcp_config = _transform_tcp_config


def _require_library() -> None:
    if not TRANSFORM_AVAILABLE:
        raise RuntimeError(f"aws-transform-mcp-server not installed: {_import_error}")


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


def _is_403(exc: Any) -> bool:
    """Duck-type a Transform HttpError 403 without hard-importing the symbol."""
    return getattr(exc, "status_code", None) == 403


def _access_denied(operation: str, exc: Any) -> TransformAccessDenied:
    return TransformAccessDenied(operation, workspace_id(), transform_principal_arn(), cause=exc)


async def _call(operation: str, request: Any) -> Any:
    """Invoke a Transform FES operation, translating HTTP 403 into TransformAccessDenied."""
    try:
        return await call_transform_api(operation, request)
    except Exception as exc:  # noqa: BLE001 - 403 translated, everything else re-raised unchanged
        if _is_403(exc):
            raise _access_denied(operation, exc) from exc
        raise


async def _call_control_plane(operation: str, body: dict) -> Any:
    """Invoke a Transform control-plane (TCP) operation, translating HTTP 403."""
    try:
        return await call_tcp(operation, body)
    except Exception as exc:  # noqa: BLE001 - 403 translated, everything else re-raised unchanged
        if _is_403(exc):
            raise _access_denied(operation, exc) from exc
        raise


def require_workspace_id() -> str:
    ws = os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip()
    if not ws:
        raise RuntimeError("TRANSFORM_WORKSPACE_ID is required for deploy runs")
    return ws


def workspace_id() -> str:
    return require_workspace_id()


def orchestrator_agent() -> Optional[str]:
    v = os.environ.get("TRANSFORM_ORCHESTRATOR_AGENT", "").strip()
    return v or None


def _run(coro):
    return asyncio.run(coro)


async def _discover_sigv4_regions() -> tuple[list[str], dict[str, Exception]]:
    """Probe every FES region. Return (successful regions, {region: error}).

    Per-region errors are collected (not dropped) so init_connection can report why no
    region succeeded instead of a generic "probe failed".
    """
    async def _call_region(region: str) -> tuple[str, Optional[Exception]]:
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


def init_connection(preferred_region: Optional[str] = None) -> dict[str, Any]:
    """Probe SigV4 Transform access (same as MCP server startup)."""
    require_workspace_id()
    _require_library()
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
                raise _access_denied("ListWorkspaces", forbidden) from forbidden
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


def _ensure_connected() -> None:
    _require_library()
    if not is_fes_available():
        init_connection()
    if not is_fes_available():
        raise RuntimeError("Transform FES not available after init")


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
    if not isinstance(created, dict) or not created.get("jobId"):
        raise RuntimeError(f"Transform CreateJob returned no jobId: {created!r}")
    job_id = created["jobId"]
    await _call("StartJob", StartJobRequest(workspaceId=ws, jobId=job_id))
    return job_id


def _job_metadata(ws: str, job_id: str) -> "Metadata":
    return Metadata(
        resourcesOnScreen=ResourcesOnScreen(
            workspace=WorkspaceMetadata(
                workspaceId=ws,
                jobs=[ChatJobMetadata(jobId=job_id, focusState="ACTIVE")],
            ),
        ),
    )


async def _send(ws: str, job_id: str, text: str) -> dict:
    return await _call(
        "SendMessage",
        SendMessageRequest(text=text[:7000], idempotencyToken=str(uuid.uuid4()), metadata=_job_metadata(ws, job_id)),
    )


async def _get_job(ws: str, job_id: str) -> dict:
    raw = await _call("GetJob", GetJobRequest(workspaceId=ws, jobId=job_id))
    if not isinstance(raw, dict) or not isinstance(raw.get("job"), dict):
        raise RuntimeError(f"Transform GetJob for job {job_id} returned no 'job' object: {raw!r}")
    return raw["job"]


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
        try:
            await _send(ws, job_id, prompt)
            job = await _get_job(ws, job_id)
            status = job_status(job, job_id)
        except Exception as exc:  # noqa: BLE001 - job is running; stop it, then raise naming both
            raise await _stop_after_failed_start(ws, job_id, phase, exc) from exc
        return {"workspaceId": ws, "jobId": job_id, "jobStatus": status, "init": init}

    return _run(_go())


class TransformJobStartFailed(RuntimeError):
    """A Transform job was created and started, but a later setup step failed.

    ``stopped`` says whether StopJob succeeded; when it did not, the message names the job so an
    operator can stop it in the Transform console.
    """

    def __init__(self, job_id: str, phase: str, cause: Exception, stopped: bool, stop_error: Optional[Exception]):
        self.job_id = job_id
        self.cause = cause
        self.stopped = stopped
        self.stop_error = stop_error
        outcome = "the job was stopped" if stopped else f"StopJob also failed ({stop_error}); stop job {job_id} manually"
        super().__init__(f"Transform {phase} job {job_id} started but setup failed: {cause}; {outcome}")


async def _stop_after_failed_start(ws: str, job_id: str, phase: str, cause: Exception) -> TransformJobStartFailed:
    try:
        await _call("StopJob", StopJobRequest(workspaceId=ws, jobId=job_id, idempotencyToken=str(uuid.uuid4())))
    except Exception as stop_exc:  # noqa: BLE001 - reported in the raised error, never swallowed
        return TransformJobStartFailed(job_id, phase, cause, stopped=False, stop_error=stop_exc)
    return TransformJobStartFailed(job_id, phase, cause, stopped=True, stop_error=None)


def stop_job(job_id: str, workspace_id: str) -> None:
    """Stop a Transform job (StopJob). Raises on any failure, including 403."""
    if not job_id or not workspace_id:
        raise ValueError(f"stop_job needs job_id and workspace_id (got {job_id!r}, {workspace_id!r})")
    _ensure_connected()

    async def _go():
        await _call(
            "StopJob",
            StopJobRequest(workspaceId=workspace_id, jobId=job_id, idempotencyToken=str(uuid.uuid4())),
        )

    _run(_go())


def job_status(job: dict, job_id: str) -> str:
    """Job state from a GetJob ``job``: ``statusDetails.status`` (JobStatus enum) only.

    Raises when absent: an empty status would read as "still running" forever, and the legacy
    top-level ``status`` is not part of the JobInfo shape.
    """
    details = job.get("statusDetails")
    status = details.get("status") if isinstance(details, dict) else None
    if not isinstance(status, str) or not status.strip():
        raise RuntimeError(
            f"Transform GetJob for job {job_id} returned no statusDetails.status; keys: {sorted(job)}"
        )
    return status.strip().upper()


# --------------------------------------------------------------------------------------
# Pending human input (contract C1). Deterministic parsing of Transform API responses.
# --------------------------------------------------------------------------------------
PENDING_TEXT_LIMIT = 2000
_MAX_PAGES = 100
_BATCH_GET_MESSAGE_LIMIT = 100
_application_urls: dict[str, str] = {}


async def _list_pages(operation: str, make_request, items_key: str) -> list:
    """Collect every page of a list call; raise on a malformed page or the page limit."""
    items: list = []
    token = None
    for _ in range(_MAX_PAGES):
        resp = await _call(operation, make_request(token))
        if not isinstance(resp, dict) or not isinstance(resp.get(items_key), list):
            raise RuntimeError(f"Transform {operation} returned no '{items_key}' list: {resp!r}")
        items.extend(resp[items_key])
        token = resp.get("nextToken")
        if not token:
            return items
    raise RuntimeError(f"Transform {operation} returned more than {_MAX_PAGES} pages")


async def _actionable_tasks(ws: str, job_id: str) -> list[dict]:
    tasks = await _list_pages(
        "ListHitlTasks",
        lambda token: ListHitlTasksRequest(
            workspaceId=ws,
            jobId=job_id,
            taskType="NORMAL",
            taskFilter=HitlTaskFilter(taskStatuses=list(_ACTIONABLE_HITL_STATUSES)),
            nextToken=token,
        ),
        "hitlTasks",
    )
    actionable = []
    for task in tasks:
        if not isinstance(task, dict) or not task.get("taskId") or not task.get("status"):
            raise RuntimeError(f"Transform ListHitlTasks for job {job_id} returned a task without taskId/status: {task!r}")
        if task["status"] in _ACTIONABLE_HITL_STATUSES:
            actionable.append(task)
    return actionable


async def _job_messages(ws: str, job_id: str) -> list[dict]:
    metadata = _job_metadata(ws, job_id)
    ids = await _list_pages(
        "ListMessages",
        lambda token: ListMessagesRequest(metadata=metadata, maxResults=1000, nextToken=token),
        "messageIds",
    )
    messages: list[dict] = []
    for start in range(0, len(ids), _BATCH_GET_MESSAGE_LIMIT):
        chunk = ids[start:start + _BATCH_GET_MESSAGE_LIMIT]
        resp = await _call("BatchGetMessage", BatchGetMessageRequest(messageIds=chunk, workspaceId=ws))
        if not isinstance(resp, dict) or not isinstance(resp.get("messages"), list):
            raise RuntimeError(f"Transform BatchGetMessage for job {job_id} returned no 'messages' list: {resp!r}")
        if resp.get("errors"):
            raise RuntimeError(f"Transform BatchGetMessage for job {job_id} returned errors: {resp['errors']!r}")
        got = {m.get("messageId") for m in resp["messages"] if isinstance(m, dict)}
        missing = [mid for mid in chunk if mid not in got]
        if missing:
            raise RuntimeError(f"Transform BatchGetMessage for job {job_id} did not return messages {missing}")
        messages.extend(resp["messages"])
    return messages


def _by_created(items: list[dict], id_key: str, what: str) -> list[dict]:
    """Items sorted oldest -> newest by (createdAt, id); raise if any lacks createdAt."""
    for item in items:
        if item.get("createdAt") is None:
            raise RuntimeError(f"Transform {what} {item.get(id_key)!r} has no createdAt")
    return sorted(items, key=lambda i: (i["createdAt"], str(i.get(id_key))))


def _select_labels(interactions: Any, message_id: str) -> list[str]:
    """Labels of selectable options: interactions[].data.selectInteractionData.options[].label
    (group interactions' children included)."""
    labels: list[str] = []
    for interaction in interactions or []:
        if not isinstance(interaction, dict):
            raise RuntimeError(f"Transform message {message_id} has a malformed interaction: {interaction!r}")
        data = interaction.get("data") or {}
        for option in (data.get("selectInteractionData") or {}).get("options") or []:
            label = option.get("label") if isinstance(option, dict) else None
            if not isinstance(label, str) or not label.strip():
                raise RuntimeError(f"Transform message {message_id} has a select option without a label: {option!r}")
            labels.append(label)
        labels.extend(_select_labels((data.get("groupInteractionData") or {}).get("children"), message_id))
    return labels


async def _application_url() -> str:
    """Transform web app URL of the profile (TCP ListProfiles), cached per process and region."""
    region = get_sigv4_region()
    if not region:
        raise RuntimeError("Transform SigV4 region is not selected; init_connection must succeed before ListProfiles")
    cached = _application_urls.get(region)
    if cached:
        return cached
    try:
        resp = await _call_control_plane("ListProfiles", {})
    except TransformAccessDenied:
        raise
    except Exception as exc:
        raise RuntimeError(f"Transform ListProfiles failed in {region}; cannot build the console URL: {exc}") from exc
    if not isinstance(resp, dict) or not isinstance(resp.get("profiles"), list):
        raise RuntimeError(f"Transform ListProfiles in {region} returned no 'profiles' list: {resp!r}")
    if resp.get("nextToken"):
        raise RuntimeError(f"Transform ListProfiles in {region} returned more than one page; cannot pick a profile")
    urls = sorted({p["applicationUrl"] for p in resp["profiles"] if isinstance(p, dict) and p.get("applicationUrl")})
    if len(urls) != 1:
        raise RuntimeError(
            f"Transform ListProfiles in {region} returned {len(urls)} profile applicationUrls {urls}; expected exactly one"
        )
    _application_urls[region] = urls[0]
    return urls[0]


def console_url(application_url: str, ws: str, job_id: str) -> str:
    return f"{application_url.rstrip('/')}/workspaces/{ws}/jobs/{job_id}"


async def _pending_human_input(ws: str, job_id: str) -> Optional[dict]:
    """C1: (a) an actionable NORMAL HITL task, else (b) a newest non-USER message with
    selectable interactions. None when neither holds."""
    tasks = await _actionable_tasks(ws, job_id)
    if tasks:
        task = _by_created(tasks, "taskId", "HITL task")[0]  # oldest outstanding task first
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(f"Transform HITL task {task['taskId']} for job {job_id} has no title")
        return {
            "source": "transform",
            "jobId": job_id,
            "workspaceId": ws,
            "kind": "task",
            "taskId": task["taskId"],
            "title": title,
            "text": (task.get("description") or "")[:PENDING_TEXT_LIMIT],
            "options": [],
            "consoleUrl": console_url(await _application_url(), ws, job_id),
        }
    messages = await _job_messages(ws, job_id)
    if not messages:
        return None
    newest = _by_created(messages, "messageId", "message")[-1]
    origin = newest.get("messageOrigin")
    if not origin:
        raise RuntimeError(f"Transform message {newest.get('messageId')!r} for job {job_id} has no messageOrigin")
    if origin == "USER":
        return None
    options = _select_labels(newest.get("interactions"), newest.get("messageId"))
    if not options:
        return None
    return {
        "source": "transform",
        "jobId": job_id,
        "workspaceId": ws,
        "kind": "message",
        "taskId": None,
        "title": "Transform is asking for a decision",
        "text": (newest.get("text") or "")[:PENDING_TEXT_LIMIT],
        "options": options,
        "consoleUrl": console_url(await _application_url(), ws, job_id),
    }


_CANCELLED_STATUSES = {"STOPPED", "CANCELLED", "CANCELED"}
_TERMINAL_STATUSES = {"SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE", "DONE", "FAILED"}


def poll_job(job_id: str, workspace: Optional[str] = None) -> dict[str, Any]:
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        job = await _get_job(ws, job_id)
        status = job_status(job, job_id)
        # A cancelled/stopped job is a failure, not a completed one. Treating it as done
        # would let a cancelled analyze job flow silently into merge (no-fallbacks rule).
        if status in _CANCELLED_STATUSES:
            raise RuntimeError(f"Transform job {job_id} ended with status {status}")
        terminal = status in _TERMINAL_STATUSES
        pending = None if terminal else await _pending_human_input(ws, job_id)
        return {
            "ok": True,
            "jobId": job_id,
            "status": status,
            "done": terminal,
            "awaitingHumanApproval": status == "AWAITING_HUMAN_INPUT" or pending is not None,
            "pendingHumanInput": pending,
            "job": job,
        }

    return _run(_go())
