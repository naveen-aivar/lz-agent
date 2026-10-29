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
import datetime
import inspect
import os
import json
import uuid

from botocore.exceptions import ConnectionClosedError, ReadTimeoutError

from lzcore.transform_answers import SendOutcomeUnknown
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
    )
    from awslabs.aws_transform_mcp_server.consts import FES_REGIONS, MAX_RETRIES, TIMEOUT_SECONDS
    from awslabs.aws_transform_mcp_server.tcp_client import call_tcp
    from awslabs.aws_transform_mcp_server.hitl_schemas import format_and_validate
    from awslabs.aws_transform_mcp_server.tools.hitl import download_agent_artifact
    from awslabs.aws_transform_mcp_server.tools.job_status import _ACTIONABLE_HITL_STATUSES
    from awslabs.aws_transform_mcp_server.upload_helper import upload_json_artifact
    from awslabs.aws_transform_mcp_server.transform_api_client import (
        call_fes_direct_sigv4,
        call_transform_api,
    )
    from awslabs.aws_transform_mcp_server.transform_api_models import (
        AccountConnectionRequest,
        AwsAccountConnectionRequest,
        BatchGetMessageRequest,
        ChatJobMetadata,
        CreateConnectorRequest,
        CreateJobRequest,
        GetConnectorRequest,
        GetHitlTaskRequest,
        GetJobRequest,
        HitlTaskArtifact,
        HitlTaskFilter,
        SubmitCriticalHitlTaskRequest,
        SubmitStandardHitlTaskRequest,
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


def transform_region() -> str:
    """AWS Transform region of the profile and workspace (TRANSFORM_REGION). Required, no default.

    A Transform account can have a profile in more than one region (each with its own tenant and
    workspaces), so the region is configuration, never discovered or guessed.
    """
    _require_library()
    region = os.environ.get("TRANSFORM_REGION", "").strip()
    if not region:
        raise RuntimeError(
            "TRANSFORM_REGION is not set: the AWS Transform region of the profile that owns "
            "TRANSFORM_WORKSPACE_ID (TransformRegion stack parameter)"
        )
    if region not in FES_REGIONS:
        raise RuntimeError(f"TRANSFORM_REGION {region!r} is not an AWS Transform region; expected one of {list(FES_REGIONS)}")
    return region


def init_connection() -> dict[str, Any]:
    """Probe SigV4 Transform access in TRANSFORM_REGION (ListWorkspaces) and select that region."""
    require_workspace_id()
    region = transform_region()

    async def _probe():
        if is_fes_available() and get_sigv4_region() == region:
            return {"ok": True, "authMode": "configured", "region": region}
        try:
            await call_fes_direct_sigv4(derive_transform_api_endpoint(region), "ListWorkspaces", {}, region=region)
        except Exception as exc:
            set_sigv4_fes_available(False)
            if _is_403(exc):
                raise _access_denied("ListWorkspaces", exc) from exc
            raise RuntimeError(
                f"Transform SigV4 probe failed in {region} (TRANSFORM_REGION): {exc}. Enable AWS Transform "
                "with IAM access in that region for the Transform account."
            ) from exc
        set_sigv4_region(region)
        set_sigv4_fes_available(True)
        return {"ok": True, "authMode": "sigv4", "region": region}

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


def job_status_now(job_id: str, workspace: Optional[str] = None) -> str:
    """The job's current status, whatever it is (including STOPPED). For the platform's job close only."""
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        return job_status(await _get_job(ws, job_id), job_id)

    return _run(_go())


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
        if not isinstance(resp, dict):
            raise RuntimeError(f"Transform {operation} returned a non-object response: {resp!r}")
        # The service model marks hitlTasks/messageIds optional: the service omits the key when the list
        # is empty (observed live: ListHitlTasks -> {} on a new job). Absent means empty; any other type
        # is malformed and fails loudly.
        page = resp.get(items_key, [])
        if not isinstance(page, list):
            raise RuntimeError(f"Transform {operation} returned a non-list '{items_key}': {resp!r}")
        items.extend(page)
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


def _select_choices(interactions: Any, message_id: str) -> list[dict]:
    """Selectable options as [{label, value}]: interactions[].data.selectInteractionData.options[]
    (group interactions' children included). value is None when Transform sent none."""
    choices: list[dict] = []
    for interaction in interactions or []:
        if not isinstance(interaction, dict):
            raise RuntimeError(f"Transform message {message_id} has a malformed interaction: {interaction!r}")
        data = interaction.get("data") or {}
        for option in (data.get("selectInteractionData") or {}).get("options") or []:
            label = option.get("label") if isinstance(option, dict) else None
            if not isinstance(label, str) or not label.strip():
                raise RuntimeError(f"Transform message {message_id} has a select option without a label: {option!r}")
            value = option.get("value")
            if value is not None and not isinstance(value, str):
                raise RuntimeError(f"Transform message {message_id} has a select option with a non-string value: {option!r}")
            choices.append({"label": label, "value": value})
        choices.extend(_select_choices((data.get("groupInteractionData") or {}).get("children"), message_id))
    return choices


def _select_labels(interactions: Any, message_id: str) -> list[str]:
    return [c["label"] for c in _select_choices(interactions, message_id)]


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
    # Live TCP ListProfiles shape (verified 2026-10-27): {"Profiles": [{"ProfileName", "accountId",
    # "applicationUrl", "arn", "status", ...}]}. Only profiles of this region are returned.
    if not isinstance(resp, dict) or not isinstance(resp.get("Profiles"), list):
        raise RuntimeError(f"Transform ListProfiles in {region} returned no 'Profiles' list: {resp!r}")
    if resp.get("NextToken") or resp.get("nextToken"):
        raise RuntimeError(f"Transform ListProfiles in {region} returned more than one page; cannot pick a profile")
    urls = sorted({p["applicationUrl"] for p in resp["Profiles"] if isinstance(p, dict) and p.get("applicationUrl")})
    if len(urls) != 1:
        raise RuntimeError(
            f"Transform ListProfiles in {region} returned {len(urls)} profile applicationUrls {urls}; expected exactly one"
        )
    _application_urls[region] = urls[0]
    return urls[0]


def console_url(application_url: str, ws: str, job_id: str) -> str:
    return f"{application_url.rstrip('/')}/workspaces/{ws}/jobs/{job_id}"


async def _pending_human_input(ws: str, job_id: str, free_text: bool = False) -> Optional[dict]:
    """C1: (a) an actionable NORMAL HITL task, else (b) a newest non-USER message with
    selectable interactions, else (c) when ``free_text`` (the job reports AWAITING_HUMAN_INPUT),
    or the newest non-USER message is a FINAL_RESPONSE (Transform ended its turn), that message as a
    free-text question (options []). None when none holds."""
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
            "messageId": None,
            # TOOL_APPROVAL tasks are approve/reject gates a signed-in approver can decide from the platform UI.
            "category": task.get("category"),
            "title": title,
            "text": (task.get("description") or "")[:PENDING_TEXT_LIMIT],
            "options": [],
            "choices": [],
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
    message_id = newest.get("messageId")
    if not isinstance(message_id, str) or not message_id:
        raise RuntimeError(f"Transform message for job {job_id} has no messageId: {newest!r}")
    choices = _select_choices(newest.get("interactions"), message_id)
    # A SYSTEM message of type FINAL_RESPONSE ends Transform's chat turn: it is waiting for the reply,
    # even while GetJob still says EXECUTING (seen live 2026-10-27 for the MAP question).
    turn_ended = (newest.get("processingInfo") or {}).get("messageType") == "FINAL_RESPONSE"
    if not choices and not (free_text or turn_ended):
        return None
    return {
        "source": "transform",
        "jobId": job_id,
        "workspaceId": ws,
        "kind": "message",
        "taskId": None,
        "messageId": message_id,
        "title": "Transform is asking for a decision" if choices else "Transform is asking for a reply",
        "text": (newest.get("text") or "")[:PENDING_TEXT_LIMIT],
        "options": [c["label"] for c in choices],
        "choices": choices,
        # True when the job itself reports AWAITING_HUMAN_INPUT: Transform is blocked on a reply, so the
        # message is never "just progress".
        "jobAwaitingInput": bool(free_text),
        # Transform's own timestamp of the question (integer epoch milliseconds, so DynamoDB stores it exactly):
        # any USER message newer than this is a reply to it. Used to tell whether an interrupted reply reached
        # Transform, with no local clock.
        "createdAtMs": _epoch_ms(newest["createdAt"], f"message {message_id}"),
        "consoleUrl": console_url(await _application_url(), ws, job_id),
    }


ANSWER_TEXT_LIMIT = 4000
# Errors after which a SendMessage may or may not have reached Transform.
_UNKNOWN_OUTCOME_ERRORS = (ReadTimeoutError, ConnectionClosedError, asyncio.TimeoutError)


class QuestionChanged(RuntimeError):
    """The Transform job is no longer waiting on the message the caller is answering."""


def answer_message(
    job_id: str,
    message_id: str,
    *,
    idempotency_token: str,
    option: Optional[str] = None,
    text: Optional[str] = None,
    workspace: Optional[str] = None,
) -> dict[str, Any]:
    """Reply to the select question a Transform job is waiting on.

    The live question is re-read first: the reply is sent only while message_id is still the newest
    system message with options (else QuestionChanged). option must be one of its labels and is sent as
    that option's value, the way a reply typed in the Transform chat reaches the job. text is a free-form
    reply. Exactly one of option/text.
    """
    if (option is None) == (text is None):
        raise ValueError("answer_message needs exactly one of option or text")
    if text is not None and not (0 < len(text.strip()) <= ANSWER_TEXT_LIMIT):
        raise ValueError(f"reply text must be 1-{ANSWER_TEXT_LIMIT} characters")
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        # Same predicate as poll_job: a reply to a question without options is accepted only while the job
        # reports AWAITING_HUMAN_INPUT or the message ended Transform's turn (FINAL_RESPONSE).
        job = await _get_job(ws, job_id)
        live = await _pending_human_input(ws, job_id, free_text=job_status(job, job_id) == "AWAITING_HUMAN_INPUT")
        if live is None or live["kind"] != "message" or live["messageId"] != message_id:
            now_waiting = (
                "nothing is pending" if live is None
                else f"it now waits on {live['kind']} {live.get('messageId') or live.get('taskId')}"
            )
            raise QuestionChanged(f"Transform job {job_id} is no longer waiting on message {message_id}; {now_waiting}")
        if option is not None:
            matches = [c for c in live["choices"] if c["label"] == option]
            if len(matches) > 1:
                raise RuntimeError(
                    f"Transform message {message_id} offers {len(matches)} options labelled {option!r}; "
                    "answer it in AWS Transform"
                )
            choice = matches[0] if matches else None
            if choice is None:
                raise ValueError(f"{option!r} is not one of the offered options {[c['label'] for c in live['choices']]}")
            if not choice["value"]:
                raise RuntimeError(f"Transform option {option!r} has no value; reply with a message instead")
            reply = choice["value"]
        else:
            reply = text.strip()
        try:
            resp = await _call(
                "SendMessage",
                SendMessageRequest(text=reply, idempotencyToken=idempotency_token, metadata=_job_metadata(ws, job_id)),
            )
        except _UNKNOWN_OUTCOME_ERRORS as e:
            # The request may have been processed; the caller checks the conversation before calling it failed.
            raise SendOutcomeUnknown(f"Transform SendMessage for job {job_id}: {type(e).__name__}: {e}") from e
        sent = resp.get("message") if isinstance(resp, dict) else None
        if not isinstance(sent, dict) or not sent.get("messageId"):
            raise SendOutcomeUnknown(f"Transform SendMessage for job {job_id} returned no message: {resp!r}")
        return {"jobId": job_id, "answeredMessageId": message_id, "sentMessageId": sent["messageId"], "text": reply}

    return _run(_go())


# --------------------------------------------------------------------------------------
# Target-account connector task (HITL uxComponentId CreateOrSelectConnectors).
# Transform asks for a connector of the type named in the task's agent artifact. The platform
# finds (or creates) that connector for the deploy target account; a person approves it once in
# the AWS console (verification link); the platform then submits the task with its id.
# --------------------------------------------------------------------------------------
CONNECTOR_TASK_COMPONENT = "CreateOrSelectConnectors"
# Connector types the platform will create. The type comes from Transform's task artifact (untrusted text);
# an unknown type is a contract change to review, not something to create blindly.
SUPPORTED_CONNECTOR_TYPES = frozenset({"vmware_migration|infra_provisioning|5"})


def check_connector_type(connector_type: str) -> str:
    if connector_type not in SUPPORTED_CONNECTOR_TYPES:
        raise RuntimeError(
            f"Transform asks for connector type {connector_type!r}; the platform only creates "
            f"{sorted(SUPPORTED_CONNECTOR_TYPES)}. Review the type and add it to SUPPORTED_CONNECTOR_TYPES."
        )
    return connector_type


class ConnectorRejected(RuntimeError):
    """The target-account connector was rejected in the AWS console."""


def connector_verification_link(connector_id: str, region: str) -> str:
    """Same link the library's create_connector returns (AWS console approval page).

    ``region`` is the AWS Transform Region (where the connector is registered), NOT the connector's target
    Region: the console page reads the connector from the Transform service of the Region in its URL, and
    answers "not authorized" in any Region where Transform is not enabled."""
    return f"https://{region}.console.aws.amazon.com/transform/connector/{connector_id}/configure?region={region}"


async def _get_task(ws: str, job_id: str, task_id: str) -> dict:
    resp = await _call("GetHitlTask", GetHitlTaskRequest(workspaceId=ws, jobId=job_id, taskId=task_id))
    task = resp.get("task") if isinstance(resp, dict) else None
    if not isinstance(task, dict):
        raise RuntimeError(f"Transform GetHitlTask for task {task_id} returned no task: {resp!r}")
    return task


def connector_task(job_id: str, task_id: str, workspace: Optional[str] = None) -> Optional[dict[str, Any]]:
    """The connector request of a CreateOrSelectConnectors task, or None for any other task.

    Returns {taskId, severity, status, connectorType, artifact}. Raises when the task's agent
    artifact does not name exactly one connector type (min 1, max 1), the only shape handled.
    """
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        task = await _get_task(ws, job_id, task_id)
        if task.get("uxComponentId") != CONNECTOR_TASK_COMPONENT:
            return None
        artifact_id = (task.get("agentArtifact") or {}).get("artifactId")
        if not artifact_id:
            raise RuntimeError(f"Transform connector task {task_id} has no agent artifact")
        artifact = (await download_agent_artifact(workspace_id=ws, job_id=job_id, artifact_id=artifact_id)).get("content")
        wanted = ((artifact or {}).get("properties") or {}).get("connectors")
        if not isinstance(wanted, list) or len(wanted) != 1 or not isinstance(wanted[0], dict) \
                or not wanted[0].get("connectorType") or wanted[0].get("min") != 1 or wanted[0].get("max") != 1:
            raise RuntimeError(
                f"Transform connector task {task_id} asks for {wanted!r}; only exactly one connector type "
                "(min 1, max 1) is supported"
            )
        return {"taskId": task_id, "severity": task.get("severity"), "status": task.get("status"),
                "connectorType": check_connector_type(wanted[0]["connectorType"]), "artifact": artifact}

    return _run(_go())


def _connector_status(connector: dict) -> tuple[Optional[str], Optional[str]]:
    conn = (connector.get("accountConnection") or {}).get("awsAccountConnection") or {}
    return conn.get("accountId"), conn.get("status")


def create_target_connector(*, run_id: str, connector_type: str, account_id: str, region: str,
                            workspace: Optional[str] = None) -> dict[str, Any]:
    """Create the workspace connector for this deploy run (PENDING until a person approves it in the AWS console).

    Every run creates its own connector: a connector some earlier run or person approved is never reused,
    because approving one grants Transform landing-zone permissions in the account and that approval belongs
    to the run that asks for it. The idempotency token is derived from the run and target, so a retry after a
    crash returns the same connector. Returns {connectorId, status, verificationLink}.
    """
    check_connector_type(connector_type)
    ws = workspace or workspace_id()
    _ensure_connected()
    token = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lz-agent:{run_id}:{account_id}:{region}:{connector_type}"))

    async def _go():
        resp = await _call("CreateConnector", CreateConnectorRequest(
            workspaceId=ws,
            connectorName=f"lz-agent-{run_id[:8]}-{account_id}-{region}",
            connectorType=connector_type,
            configuration={},
            accountConnectionRequest=AccountConnectionRequest(
                awsAccountConnectionRequest=AwsAccountConnectionRequest(awsAccountId=account_id)),
            idempotencyToken=token,
            targetRegions=[region],
            description=f"Landing zone target account (created by lz-agent deploy run {run_id[:8]})",
        ))
        if not isinstance(resp, dict) or not resp.get("connectorId"):
            raise RuntimeError(f"Transform CreateConnector returned no connectorId: {resp!r}")
        chosen = await _call("GetConnector", GetConnectorRequest(workspaceId=ws, connectorId=resp["connectorId"]))
        acct, status = _connector_status(chosen)
        if acct != account_id or status not in ("ACTIVE", "PENDING"):
            raise RuntimeError(
                f"Transform connector {resp['connectorId']} is for account {acct!r} with status {status!r}; "
                f"expected account {account_id} and ACTIVE or PENDING"
            )
        return {"connectorId": chosen["connectorId"], "status": status,
                "verificationLink": connector_verification_link(chosen["connectorId"], transform_region())}

    return _run(_go())


def connector_state(connector_id: str, workspace: Optional[str] = None) -> str:
    """ACTIVE | PENDING; raises ConnectorRejected for REJECTED and RuntimeError for anything else."""
    ws = workspace or workspace_id()
    _ensure_connected()
    full = _run(_call("GetConnector", GetConnectorRequest(workspaceId=ws, connectorId=connector_id)))
    _, status = _connector_status(full)
    if status == "REJECTED":
        raise ConnectorRejected(f"Transform connector {connector_id} was rejected in the AWS console")
    if status not in ("ACTIVE", "PENDING"):
        raise RuntimeError(f"Transform connector {connector_id} has status {status!r}")
    return status


def submit_connector_task(*, job_id: str, task_id: str, connector_id: str, connector_type: str,
                          workspace: Optional[str] = None) -> dict[str, Any]:
    """Approve the CreateOrSelectConnectors task with an ACTIVE connector (library submit path:
    validate against the component schema, upload the response artifact, Submit*HitlTask)."""
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        task = await _get_task(ws, job_id, task_id)
        if task.get("uxComponentId") != CONNECTOR_TASK_COMPONENT or task.get("status") not in _ACTIONABLE_HITL_STATUSES:
            raise QuestionChanged(
                f"Transform task {task_id} is {task.get('uxComponentId')}/{task.get('status')}, not an open connector task"
            )
        artifact_id = (task.get("agentArtifact") or {}).get("artifactId")
        artifact = (await download_agent_artifact(workspace_id=ws, job_id=job_id, artifact_id=artifact_id)).get("content") \
            if artifact_id else None
        fmt = format_and_validate(CONNECTOR_TASK_COMPONENT,
                                  json.dumps({"connectorId": connector_id, "connectorType": connector_type}), artifact)
        if not fmt.ok:
            raise RuntimeError(f"connector task response failed the {CONNECTOR_TASK_COMPONENT} schema: {fmt.error}")
        response_id = await upload_json_artifact(workspace_id=ws, job_id=job_id, content=fmt.content)
        request_cls = SubmitCriticalHitlTaskRequest if task.get("severity") == "CRITICAL" else SubmitStandardHitlTaskRequest
        # Stable per task and connector: a resubmission after a crash is a duplicate Transform ignores.
        token = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lz-agent-submit:{task_id}:{connector_id}"))
        await _call(
            "SubmitCriticalHitlTask" if task.get("severity") == "CRITICAL" else "SubmitStandardHitlTask",
            request_cls(workspaceId=ws, jobId=job_id, taskId=task_id, action="APPROVE",
                        humanArtifact=HitlTaskArtifact(artifactId=response_id), idempotencyToken=token),
        )
        after = await _get_task(ws, job_id, task_id)
        if after.get("status") in _ACTIONABLE_HITL_STATUSES:
            raise RuntimeError(
                f"Transform task {task_id} is still {after.get('status')} after the submit; the connector "
                f"{connector_id} was not accepted"
            )
        return {"taskId": task_id, "status": after.get("status"), "responseArtifactId": response_id}

    return _run(_go())


def decide_tool_approval(*, job_id: str, task_id: str, decision: str, idempotency_token: str,
                         workspace: Optional[str] = None) -> dict[str, Any]:
    """Approve or reject an open TOOL_APPROVAL task (the library's own path for these: no response artifact).

    Called only by the platform's /decision route for a signed-in approver; the deploy agent has no tool for it.
    Raises QuestionChanged when the task is not an open TOOL_APPROVAL task, and RuntimeError when Transform still
    shows it open after the submit."""
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError(f"decision must be APPROVE or REJECT, got {decision!r}")
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        task = await _get_task(ws, job_id, task_id)
        if task.get("category") != "TOOL_APPROVAL" or task.get("status") != "AWAITING_APPROVAL":
            raise QuestionChanged(
                f"Transform task {task_id} is {task.get('category')}/{task.get('status')}, not an open approval task"
            )
        await _call(
            "SubmitCriticalHitlTask",
            SubmitCriticalHitlTaskRequest(workspaceId=ws, jobId=job_id, taskId=task_id, action=decision,
                                          idempotencyToken=idempotency_token),
        )
        after = await _get_task(ws, job_id, task_id)
        if after.get("status") == "AWAITING_APPROVAL":
            raise RuntimeError(f"Transform task {task_id} is still AWAITING_APPROVAL after the {decision}")
        return {"taskId": task_id, "status": after.get("status"), "action": decision}

    return _run(_go())


def newest_system_message_id(job_id: str, workspace: Optional[str] = None) -> Optional[str]:
    """Id of the newest chat message when Transform wrote it (not a USER message); None otherwise.

    Used right after the platform completes a task: a message Transform wrote before the task must not be
    mistaken for a new question afterwards."""
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        messages = await _job_messages(ws, job_id)
        if not messages:
            return None
        newest = _by_created(messages, "messageId", "message")[-1]
        origin = newest.get("messageOrigin")
        if not origin:
            raise RuntimeError(f"Transform message {newest.get('messageId')!r} for job {job_id} has no messageOrigin")
        return None if origin == "USER" else newest.get("messageId")

    return _run(_go())


def _epoch(value: Any, what: str) -> float:
    if isinstance(value, datetime.datetime):
        return value.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise RuntimeError(f"Transform {what} has an unreadable createdAt: {value!r}")


def _epoch_ms(value: Any, what: str) -> int:
    return int(round(_epoch(value, what) * 1000))


def user_reply_since(job_id: str, since_ms: int, workspace: Optional[str] = None) -> Optional[str]:
    """Message id of the first USER message in the job created strictly after ``since_ms`` (epoch milliseconds);
    None if none.

    ``since_ms`` is the pending question's own Transform createdAtMs, so both sides are Transform timestamps.
    Used to tell whether an interrupted answer already reached Transform before sending it again."""
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        for m in _by_created(await _job_messages(ws, job_id), "messageId", "message"):
            if m.get("messageOrigin") == "USER" and _epoch_ms(m["createdAt"], f"message {m.get('messageId')}") > since_ms:
                return m.get("messageId")
        return None

    return _run(_go())


CONVERSATION_TEXT_LIMIT = 1500


def recent_conversation(job_id: str, workspace: Optional[str] = None, limit: int = 12) -> list[dict[str, Any]]:
    """The last ``limit`` chat messages of a job, oldest first, for the deploy agent's context.

    Each entry: {messageId, origin (USER | SYSTEM | ...), createdAt, text (truncated), options}.
    Raises on a malformed message (no messageOrigin / createdAt), like the pending-input parser.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    ws = workspace or workspace_id()
    _ensure_connected()

    async def _go():
        messages = _by_created(await _job_messages(ws, job_id), "messageId", "message")
        out = []
        for m in messages[-limit:]:
            origin = m.get("messageOrigin")
            if not origin:
                raise RuntimeError(f"Transform message {m.get('messageId')!r} for job {job_id} has no messageOrigin")
            out.append({
                "messageId": m.get("messageId"),
                "origin": origin,
                "createdAt": str(m["createdAt"]),
                "text": (m.get("text") or "")[:CONVERSATION_TEXT_LIMIT],
                "options": _select_labels(m.get("interactions"), m.get("messageId")),
            })
        return out

    return _run(_go())


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
        pending = None if terminal else await _pending_human_input(ws, job_id, free_text=status == "AWAITING_HUMAN_INPUT")
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
