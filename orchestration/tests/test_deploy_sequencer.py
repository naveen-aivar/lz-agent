"""Acceptance tests for the deterministic deploy sequencer (agent/deploy_workflow_tools.py).

Every test drives the real AgentCore entrypoint (``agent.app.invoke(payload, context)``) or a
real deploy tool and asserts BOTH the returned status and the resulting checkpoint stage.
Behaviour covered:

  * Mechanical steps run in order without the model: pre-discover, Transform init, start/poll
    analyze, merge, render, start/poll deploy, post-discover, finish (Cases A-C).
  * Checkpoint read errors other than not-found fail naming the key (D); Transform 403 names
    the principal, the workspace and Contributor (E); cancelled jobs fail (G).
  * Pre-discover failures are a named run_pre_discover error, never a HITL wait; a checkpoint
    left at the superseded ``pre_discover_blocked`` stage fails explicitly (#3).
  * The judgment model runs only at transform_merged, gets judgment tools only (#4), is
    bounded by a persisted attempt counter (#7, F), exceptions are named (#22), and a completed
    judgment returns continue so render/start-deploy run on the next invoke (#8).
  * Transform jobs are never started for a run whose META.status is not RUNNING (C4), and a job
    started before a failed write is stopped and named in the error (#23).
  * Transform pending human input (C1) is saved on the waiting checkpoint and returned in the
    continue payload (C3).

Harness rules:
  * ``strands``, ``bedrock_agentcore`` and ``mcp`` may be absent locally, so import stubs are
    installed in ``sys.modules`` before importing ``agent.app``. They carry no behaviour the
    tests rely on.
  * Nothing can reach AWS: each test installs a guard that fails the test if botocore sends an
    HTTP request or if boto3.Session/client/resource is constructed, replaces every
    credential-producing function in lzcore.transform_credentials with a recorder that fails the
    test, points AWS config files at nonexistent paths, and clears AWS credential env vars.
    deploy_boto_session returns a FakeOrgSession (never None, which would fall through to
    boto3.Session()).
  * All fixtures (FakeS3, FakeTable, FakeTransformOps, FakeOrgSession, scripted model) are
    installed per test and restored in cleanup; none is a default the application picks up.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))


def _install_import_stubs() -> None:
    if "strands" not in sys.modules:
        try:
            import strands  # noqa: F401
        except ImportError:
            strands = types.ModuleType("strands")

            def tool(fn=None, **_kw):
                if fn is None:
                    return lambda f: f
                return fn

            class Agent:  # pragma: no cover - tests patch app.Agent when they construct one
                def __init__(self, *a, **k):
                    raise RuntimeError("strands.Agent stub must not be constructed in tests")

            strands.tool = tool
            strands.Agent = Agent
            sys.modules["strands"] = strands

            models = types.ModuleType("strands.models")

            class BedrockModel:  # pragma: no cover
                def __init__(self, *a, **k):
                    raise RuntimeError("strands BedrockModel stub must not be constructed in tests")

            models.BedrockModel = BedrockModel
            sys.modules["strands.models"] = models

            strands_tools = types.ModuleType("strands.tools")
            mcp_sub = types.ModuleType("strands.tools.mcp")

            class MCPClient:  # pragma: no cover
                def __init__(self, *a, **k):
                    raise RuntimeError("MCPClient stub must not be constructed in tests")

            mcp_sub.MCPClient = MCPClient
            strands_tools.mcp = mcp_sub
            sys.modules["strands.tools"] = strands_tools
            sys.modules["strands.tools.mcp"] = mcp_sub

    if "bedrock_agentcore" not in sys.modules:
        try:
            import bedrock_agentcore.runtime  # noqa: F401
        except ImportError:
            bac = types.ModuleType("bedrock_agentcore")
            runtime = types.ModuleType("bedrock_agentcore.runtime")

            class BedrockAgentCoreApp:
                def entrypoint(self, fn):
                    return fn  # tests call app.invoke(payload, ctx) directly

                def run(self):  # pragma: no cover
                    raise RuntimeError("stub app must not run")

            runtime.BedrockAgentCoreApp = BedrockAgentCoreApp
            bac.runtime = runtime
            sys.modules["bedrock_agentcore"] = bac
            sys.modules["bedrock_agentcore.runtime"] = runtime

    if "mcp" not in sys.modules:
        try:
            import mcp.client.stdio  # noqa: F401
            import mcp.client.streamable_http  # noqa: F401
        except ImportError:
            mcp = types.ModuleType("mcp")
            client = types.ModuleType("mcp.client")
            stdio = types.ModuleType("mcp.client.stdio")
            streamable = types.ModuleType("mcp.client.streamable_http")

            class StdioServerParameters:  # pragma: no cover
                def __init__(self, *a, **k):
                    raise RuntimeError("mcp stub must not be used in tests")

            def _unused(*a, **k):  # pragma: no cover
                raise RuntimeError("mcp stub must not be used in tests")

            stdio.StdioServerParameters = StdioServerParameters
            stdio.get_default_environment = _unused
            stdio.stdio_client = _unused
            streamable.streamablehttp_client = _unused
            mcp.client = client
            client.stdio = stdio
            client.streamable_http = streamable
            sys.modules["mcp"] = mcp
            sys.modules["mcp.client"] = client
            sys.modules["mcp.client.stdio"] = stdio
            sys.modules["mcp.client.streamable_http"] = streamable


# Read at import by agent/tools.py and agent/app.py. Values only name the fake table/bucket.
os.environ["STATE_TABLE"] = "test-state-table"
os.environ["ARTIFACT_BUCKET"] = "test-artifact-bucket"
os.environ["MODEL_ID"] = "test-model-id"

_install_import_stubs()

# agent/app.py does `import tools` / `from deploy_workflow_tools import ...` with agent/ on
# sys.path, so the app uses the TOP-LEVEL modules. Patch those exact module objects.
import agent.app as app  # noqa: E402

tools = app.tools
dwt = sys.modules["deploy_workflow_tools"]
transform_mcp_mod = sys.modules["transform_mcp"]
from lzcore import deploy_transform  # noqa: E402
from lzcore import transform_credentials as tcred  # noqa: E402
from lzcore import transform_ops as real_transform_ops  # noqa: E402
from lzcore.deploy_artifacts import deployment_artifact_keys  # noqa: E402
from lzcore.iac_plan import PLAN_TYPE  # noqa: E402

assert tools is sys.modules["tools"], "test must patch the same tools module app imports"


DEPLOY_RUN = "deployrun00000000000000000000001"
DESIGN_RUN = "designrun0000000000000000000001"
DEPLOYMENT = f"runs/{DEPLOY_RUN}/deployment"
CHECKPOINT_KEY = f"{DEPLOYMENT}/agent-checkpoint.json"
ASSESSMENT_KEY = f"{DEPLOYMENT}/foundation-assessment.json"
PLAN_KEY = f"{DEPLOYMENT}/iac-change-plan.json"
WORKSPACE = "ws-test-0001"
TRANSFORM_ROLE = "arn:aws:iam::111122223333:role/TestTransformRole"
MGMT_ACCOUNT = "111111111111"
TARGET_ACCOUNT = "222222222222"
ANALYZE_JOB = f"job-analyze-{DEPLOY_RUN[:6]}"
DEPLOY_JOB = f"job-deploy-{DEPLOY_RUN[:6]}"

SCOPE = {
    "customer": {"orgName": "Acme"},
    "summary": {"ous": 1},
    "regions": {"home": "eu-west-1"},
    "ous": [{"name": "Workloads"}],
    "accounts": [{"name": "acme-management"}, {"name": "acme-prod"}],
}

PENDING = {
    "source": "transform",
    "jobId": ANALYZE_JOB,
    "workspaceId": WORKSPACE,
    "kind": "task",
    "taskId": "task-0001",
    "title": "Approve landing zone plan",
    "text": "Approve the proposed OU changes?",
    "options": ["Approve", "Reject"],
    "consoleUrl": "https://transform.example.invalid/jobs/job-analyze",
}


# --------------------------------------------------------------------------------------
# Fakes. Installed per test only; anything unscripted fails loudly.
# --------------------------------------------------------------------------------------
class _ClientError(Exception):
    """Shape of botocore ClientError (response['Error']['Code']) for injected failures."""

    def __init__(self, code: str, operation: str = "GetObject"):
        self.response = {"Error": {"Code": code, "Message": f"{code} (injected)"}}
        self.operation_name = operation
        super().__init__(f"{operation}: {code}")


class _Body:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, *a):
        return self._buf.read(*a)


class FakeS3:
    """Dict-backed S3. errors: key -> code raised on get/head; put_errors: key -> code raised on put."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.errors: dict[str, str] = {}
        self.put_errors: dict[str, str] = {}
        self.puts: list[str] = []

    def put_object(self, Bucket, Key, Body, **kw):
        if Key in self.put_errors:
            raise _ClientError(self.put_errors[Key], "PutObject")
        self.store[Key] = Body if isinstance(Body, bytes) else str(Body).encode()
        self.puts.append(Key)
        return {}

    def _check(self, key, operation):
        if key in self.errors:
            raise _ClientError(self.errors[key], operation)
        if key not in self.store:
            raise _ClientError("NoSuchKey" if operation == "GetObject" else "404", operation)

    def get_object(self, Bucket, Key, **kw):
        self._check(Key, "GetObject")
        return {"Body": _Body(self.store[Key])}

    def head_object(self, Bucket, Key, **kw):
        self._check(Key, "HeadObject")
        return {"ContentLength": len(self.store[Key])}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        self._check(CopySource["Key"], "CopyObject")
        self.store[Key] = self.store[CopySource["Key"]]
        self.puts.append(Key)
        return {}

    def put_json(self, key, obj):
        self.store[key] = json.dumps(obj).encode()

    def get_json(self, key):
        return json.loads(self.store[key].decode())


class FakeTable:
    """Serves one deploy META item (also returned for the design run META); records audit rows.
    Evaluates the sequencer's `#s = :running` condition like DynamoDB would."""

    def __init__(self, meta: dict):
        self.meta = dict(meta)
        self.audit: list[dict] = []
        self.updates: list[dict] = []

    def get_item(self, Key):
        if Key.get("SK") == "META":
            return {"Item": dict(self.meta)}
        return {}

    def put_item(self, Item):
        if str(Item.get("SK", "")).startswith("AUDIT#"):
            self.audit.append(Item)
        return {}

    def update_item(self, Key, UpdateExpression="", ExpressionAttributeValues=None,
                    ExpressionAttributeNames=None, ConditionExpression=None):
        vals = dict(ExpressionAttributeValues or {})
        if ConditionExpression is not None:
            if ConditionExpression != "#s = :running" or (ExpressionAttributeNames or {}).get("#s") != "status":
                raise AssertionError(f"FakeTable: unscripted condition {ConditionExpression!r}")
            if self.meta.get("status") != vals[":running"]:
                raise _ClientError("ConditionalCheckFailedException", "UpdateItem")
        self.updates.append({"expr": UpdateExpression, "vals": vals})
        if ":j" in vals and "transformAnalyzeJobId" in UpdateExpression:
            self.meta["transformAnalyzeJobId"] = vals[":j"]
        if ":j" in vals and "transformDeployJobId" in UpdateExpression:
            self.meta["transformDeployJobId"] = vals[":j"]
        if ":w" in vals:
            self.meta["transformWorkspaceId"] = vals[":w"]
        return {}

    def actions(self):
        return [a.get("action") for a in self.audit]


class FakeTransformOps:
    """Stand-in for lzcore.transform_ops (installed on deploy_transform and the sequencer).

    poll_script: list of statuses or (status, pendingHumanInput) pairs for successive poll_job
    calls, shaped per contract C1. Mirrors the real module: CANCELLED/STOPPED raise.
    """

    class HttpError(Exception):
        def __init__(self, status_code, message="forbidden"):
            self.status_code = status_code
            super().__init__(f"HTTP {status_code}: {message}")

    _TERMINAL_OK = {"COMPLETED", "SUCCEEDED"}

    def __init__(self, poll_script=None, create_error=None, on_create=None, stop_error=None):
        self.poll_script = list(poll_script or [])
        self.create_error = create_error
        self.on_create = on_create
        self.stop_error = stop_error
        self.started: list[tuple[str, str]] = []
        self.stopped: list[tuple[str, str]] = []
        self.polls = 0

    def workspace_id(self):
        return WORKSPACE

    def init_connection(self, preferred_region=None):
        return {"ok": True, "authMode": "sigv4", "region": "us-east-1"}

    def start_landing_zone_job(self, *, run_id, phase, prompt):
        if self.create_error is not None:
            raise self.create_error
        job_id = f"job-{phase}-{run_id[:6]}"
        self.started.append((phase, job_id))
        if self.on_create:
            self.on_create(phase, job_id)
        return {"workspaceId": WORKSPACE, "jobId": job_id, "jobStatus": "EXECUTING", "init": {}}

    def poll_job(self, job_id, workspace=None):
        if not self.poll_script:
            raise AssertionError("FakeTransformOps.poll_job called with no scripted status left")
        entry = self.poll_script.pop(0)
        status, pending = entry if isinstance(entry, tuple) else (entry, None)
        self.polls += 1
        if status in {"STOPPED", "CANCELLED"}:
            raise RuntimeError(f"Transform job {job_id} ended with status {status}")
        return {
            "ok": True,
            "jobId": job_id,
            "status": status,
            "done": status in self._TERMINAL_OK or status == "FAILED",
            "awaitingHumanApproval": status == "AWAITING_HUMAN_INPUT" or pending is not None,
            "pendingHumanInput": pending,
            "job": {"statusDetails": {"status": status}},
        }

    def stop_job(self, job_id, workspace_id):
        self.stopped.append((job_id, workspace_id))
        if self.stop_error is not None:
            raise self.stop_error


class FakeOrgSession:
    """Boto3-session-shaped fake for Organizations discovery: a management-account caller that
    can read the full tree. org_error is raised from DescribeOrganization when set."""

    def __init__(self, account_id=MGMT_ACCOUNT, org_error=None):
        self.account_id = account_id
        self.org_error = org_error
        self.clients: list[str] = []

    def client(self, name, **kw):
        self.clients.append(name)
        if name == "sts":
            return types.SimpleNamespace(
                get_caller_identity=lambda: {
                    "Account": self.account_id,
                    "Arn": f"arn:aws:sts::{self.account_id}:assumed-role/Test/test",
                }
            )
        if name == "organizations":
            return _FakeOrganizations(self)
        if name == "controltower":
            return _FakePaged({"list_landing_zones": lambda **k: {"landingZones": []}})
        raise AssertionError(f"FakeOrgSession: unexpected client {name!r}")


class _FakePaged:
    """Client exposing each scripted operation both as a method and as a one-page paginator."""

    def __init__(self, operations):
        self._ops = operations

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._ops:
            raise AttributeError(f"fake client: unscripted operation {name!r}")
        return self._ops[name]

    def get_paginator(self, name):
        if name not in self._ops:
            raise AssertionError(f"fake client: unscripted paginator {name!r}")
        op = self._ops[name]
        return types.SimpleNamespace(paginate=lambda **k: [op(**k)])


class _FakeOrganizations(_FakePaged):
    def __init__(self, session):
        def describe_organization(**k):
            if session.org_error is not None:
                raise session.org_error
            return {"Organization": {"Id": "o-test", "MasterAccountId": session.account_id, "FeatureSet": "ALL"}}

        def list_ous(ParentId, **k):
            if ParentId == "r-test":
                return {"OrganizationalUnits": [{"Id": "ou-test-workloads", "Name": "Workloads"}]}
            return {"OrganizationalUnits": []}

        accounts = [
            {"Id": session.account_id, "Name": "acme-management", "Status": "ACTIVE"},
            {"Id": "333333333333", "Name": "acme-prod", "Status": "ACTIVE"},
        ]
        super().__init__({
            "describe_organization": describe_organization,
            "list_roots": lambda **k: {"Roots": [{"Id": "r-test"}]},
            "list_organizational_units_for_parent": list_ous,
            "list_accounts": lambda **k: {"Accounts": accounts},
            "list_policies": lambda Filter, **k: {"Policies": []},
            "list_targets_for_policy": lambda PolicyId, **k: {"Targets": []},
        })


def _orgs_not_in_use():
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": "AWSOrganizationsNotInUseException", "Message": "not in use"}},
        "DescribeOrganization",
    )


class _ScriptedModel:
    """Stands in for one judgment-agent turn: runs the scripted steps, then returns."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        for step in self.steps:
            step()
        return "turn complete"


def _valid_plan() -> dict:
    return {
        "schemaVersion": "1",
        "planType": PLAN_TYPE,
        "runId": DEPLOY_RUN,
        "designRunId": DESIGN_RUN,
        "summary": "No foundation changes needed.",
        "strategy": "no_changes_needed",
        "deliverDesignBundles": False,
        "changes": [{"id": "chg-001", "category": "foundation", "action": "no_op", "target": "foundation",
                     "rationale": "names match"}],
    }


def _judgment_model_saves_both(case):
    """A judgment turn that uses the real judgment tools to save both artifacts."""

    def step():
        ctx = json.loads(tools.read_deploy_context())
        case.assertEqual(ctx["runId"], DEPLOY_RUN)
        out = tools.save_foundation_assessment(json.dumps({"environment": "brownfield", "rationale": "OUs exist"}))
        case.assertTrue(out.startswith("saved"), out)
        out = tools.save_iac_change_plan(json.dumps(_valid_plan()))
        case.assertTrue(out.startswith("saved"), out)

    return step


# --------------------------------------------------------------------------------------
# Env wiring shared by every case.
# --------------------------------------------------------------------------------------
# Pure functions of env vars / strings (no credentials, no network); everything else public in
# lzcore.transform_credentials is treated as credential-producing and blocked.
_DETERMINISTIC_CREDENTIAL_FUNCS = frozenset(
    {"transform_principal_arn", "transform_role_arn", "transform_external_id", "parse_role_arn"}
)


class _SequencerCaseBase(unittest.TestCase):
    def setUp(self):
        self.blocked: list[str] = []
        self._install_no_aws_guard()

    def _install_no_aws_guard(self):
        import boto3
        import botocore.httpsession

        blocked = self.blocked

        def _blocker(label):
            def _raise(*a, **k):
                blocked.append(label)
                raise AssertionError(f"sequencer test attempted real AWS access via {label}")
            return _raise

        for target, attr in (
            (botocore.httpsession.URLLib3Session, "send"),
            (boto3, "Session"),
            (boto3, "client"),
            (boto3, "resource"),
        ):
            p = mock.patch.object(target, attr, _blocker(f"{getattr(target, '__name__', target)}.{attr}"))
            p.start()
            self.addCleanup(p.stop)

        # Every credential-producing function in lzcore.transform_credentials (and any alias
        # imported elsewhere) fails the test. transform_principal_arn/transform_role_arn are
        # deterministic (no network) and stay real so the 403 message can be checked.
        originals = {
            name: fn
            for name, fn in vars(tcred).items()
            if callable(fn)
            and not isinstance(fn, type)
            and not name.startswith("_")
            and getattr(fn, "__module__", None) == tcred.__name__
            and name not in _DETERMINISTIC_CREDENTIAL_FUNCS
        }
        for mod in (tcred, real_transform_ops, deploy_transform, transform_mcp_mod, tools, dwt):
            for attr, value in list(vars(mod).items()):
                for name, fn in originals.items():
                    if value is fn:
                        p = mock.patch.object(mod, attr, _blocker(f"transform_credentials.{name}"))
                        p.start()
                        self.addCleanup(p.stop)

        env = mock.patch.dict(
            os.environ,
            {
                "TRANSFORM_WORKSPACE_ID": WORKSPACE,
                "TRANSFORM_ROLE_ARN": TRANSFORM_ROLE,
                "AWS_CONFIG_FILE": "/nonexistent/aws-config",
                "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/aws-credentials",
                "AWS_EC2_METADATA_DISABLED": "true",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
                    "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                    "TRANSFORM_EXTERNAL_ID", "BEDROCK_API_KEY_SECRET_ARN", "TRANSFORM_ORCHESTRATOR_AGENT"):
            os.environ.pop(key, None)
        # Runs last (cleanups are LIFO): no test may have touched AWS, even if it caught the error.
        self.addCleanup(lambda: self.assertEqual(self.blocked, [], "real AWS access was attempted"))

    def _make_env(self, *, meta_extra=None, transform_ops=None, org_session=None):
        s3 = FakeS3()
        meta = {
            "PK": f"RUN#{DEPLOY_RUN}",
            "SK": "META",
            "runKind": "deploy",
            "status": "RUNNING",
            "designRunId": DESIGN_RUN,
            "transformWorkspaceId": WORKSPACE,
            "artifacts": {},
        }
        meta.update(meta_extra or {})
        table = FakeTable(meta)
        self.fake_ops = transform_ops or FakeTransformOps()
        self.org_session = org_session or FakeOrgSession()
        self.session_calls = 0

        def _session():
            self.session_calls += 1
            return self.org_session

        @contextlib.contextmanager
        def _fake_transform_tools():
            yield []

        for target, attr, value in (
            (tools, "_s3", s3),
            (tools, "_ddb", table),
            (tools, "deploy_boto_session", _session),
            (deploy_transform, "transform_ops", self.fake_ops),
            (dwt, "transform_ops", self.fake_ops),
            (app, "transform_tools", _fake_transform_tools),
            (app, "_deploy_agent", self._model_not_scripted),
        ):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        saved_state = dict(tools._state)

        def _restore_state():
            tools._state.clear()
            tools._state.update(saved_state)

        self.addCleanup(_restore_state)
        s3.put_json(f"runs/{DESIGN_RUN}/intake/scope.json", SCOPE)
        self.s3, self.table = s3, table
        return s3, table

    def _model_not_scripted(self, prompt):
        raise AssertionError("judgment model invoked but the test did not script it")

    def _set_model(self, steps):
        model = _ScriptedModel(steps)
        p = mock.patch.object(app, "_deploy_agent", lambda prompt: model())
        p.start()
        self.addCleanup(p.stop)
        return model

    def _invoke(self):
        return app.invoke({"runId": DEPLOY_RUN, "phase": "deploy"}, context=None)

    def _checkpoint(self):
        return self.s3.get_json(CHECKPOINT_KEY) if CHECKPOINT_KEY in self.s3.store else None

    def _stage(self):
        cp = self._checkpoint()
        return cp.get("stage") if cp else None

    def _seed_checkpoint(self, stage, **extra):
        self.s3.put_json(CHECKPOINT_KEY, {"stage": stage, "updatedAt": 0, **extra})

    def _seed_foundation(self):
        self.s3.put_json(f"{DEPLOYMENT}/foundation.json", {
            "organization": {"id": "o-test", "callerAccountId": MGMT_ACCOUNT, "masterAccountId": MGMT_ACCOUNT},
            "organizationalUnits": [{"id": "ou-test-workloads", "name": "Workloads", "path": "Workloads"}],
            "accounts": [{"id": MGMT_ACCOUNT, "name": "acme-management", "isManagementAccount": True},
                         {"id": "333333333333", "name": "acme-prod", "isManagementAccount": False}],
            "serviceControlPolicies": [],
            "controlTower": {"landingZones": []},
        })
        self.s3.put_json(f"{DEPLOYMENT}/gap-analysis.json", {
            "missingOus": [], "extraOus": [], "missingAccountsByName": [], "extraAccountsByName": [],
            "expectedScpIds": [],
        })

    def _seed_judgment(self, *, assessment=True, plan=True):
        if assessment:
            self.s3.put_json(ASSESSMENT_KEY, {"environment": "brownfield"})
        if plan:
            self.s3.put_json(PLAN_KEY, _valid_plan())

    def _assert_continue(self, result, *, awaiting=False, pending=None, job_id=None):
        self.assertEqual(result.get("status"), "continue", msg=f"got {result!r}")
        self.assertEqual(
            set(result), {"status", "reason", "awaitingHitl", "jobId", "pendingHumanInput"},
            msg=f"C3 payload keys; got {result!r}",
        )
        self.assertIs(result["awaitingHitl"], awaiting, msg=f"got {result!r}")
        self.assertEqual(result["pendingHumanInput"], pending, msg=f"got {result!r}")
        if job_id is not None:
            self.assertEqual(result["jobId"], job_id, msg=f"got {result!r}")

    def _assert_error(self, result, *needles):
        self.assertEqual(result.get("status"), "error", msg=f"got {result!r}")
        for needle in needles:
            self.assertIn(needle, result.get("error", ""), msg=f"got {result!r}")


# --------------------------------------------------------------------------------------
# Case A: mechanical steps from the start / from pre_discover_done
# --------------------------------------------------------------------------------------
class CaseA_InitAndAnalyze(_SequencerCaseBase):
    def test_from_pre_discover_done_starts_analyze_and_waits(self):
        self._make_env(transform_ops=FakeTransformOps(poll_script=["EXECUTING"]))
        self._seed_foundation()
        self._seed_checkpoint("pre_discover_done")

        result = self._invoke()

        self._assert_continue(result, job_id=ANALYZE_JOB)
        self.assertEqual(self._stage(), "transform_analyze_waiting")
        self.assertEqual(self.fake_ops.started, [("analyze", ANALYZE_JOB)])
        self.assertEqual(self.table.meta["transformAnalyzeJobId"], ANALYZE_JOB)

    def test_from_no_checkpoint_runs_pre_discover_with_target_session(self):
        self._make_env(transform_ops=FakeTransformOps(poll_script=["EXECUTING"]))

        result = self._invoke()

        self._assert_continue(result, job_id=ANALYZE_JOB)
        self.assertEqual(self._stage(), "transform_analyze_waiting")
        self.assertEqual(self.session_calls, 1)
        self.assertIn("organizations", self.org_session.clients)
        gaps = self.s3.get_json(f"{DEPLOYMENT}/gap-analysis.json")
        self.assertEqual((gaps["missingOus"], gaps["missingAccountsByName"]), ([], []))

    def test_second_invoke_polls_again_and_merges_into_judgment(self):
        self._make_env(transform_ops=FakeTransformOps(poll_script=["EXECUTING", "COMPLETED"]))
        self._seed_foundation()
        self._seed_checkpoint("pre_discover_done")
        model = self._set_model([_judgment_model_saves_both(self)])

        self._assert_continue(self._invoke(), job_id=ANALYZE_JOB)
        self.assertEqual(model.calls, 0)
        result = self._invoke()

        self._assert_continue(result)
        self.assertEqual(self._stage(), "judgment_done")
        self.assertEqual(model.calls, 1)


# --------------------------------------------------------------------------------------
# Case B: merge, then the judgment path
# --------------------------------------------------------------------------------------
class CaseB_MergeThenJudgment(_SequencerCaseBase):
    def test_merge_runs_and_judgment_completes_with_continue(self):
        self._make_env(meta_extra={"transformAnalyzeJobId": ANALYZE_JOB})
        self._seed_foundation()
        self._seed_checkpoint("transform_analyze_done", jobId=ANALYZE_JOB)
        self.s3.put_json(f"{DEPLOYMENT}/transform-poll-analyze.json", {"status": "COMPLETED"})
        model = self._set_model([_judgment_model_saves_both(self)])

        result = self._invoke()

        self._assert_continue(result)
        self.assertIn("deploy_judgment complete", result["reason"])
        self.assertEqual(model.calls, 1)
        self.assertEqual(self._stage(), "judgment_done")
        self.assertEqual(self._checkpoint()["judgmentAttempts"], 1)
        merged = self.s3.get_json(f"{DEPLOYMENT}/foundation.json")
        self.assertEqual(merged["transform"]["analyzeJobId"], ANALYZE_JOB)
        # #8: render and the destructive deploy job never share an invoke with a model turn.
        self.assertNotIn(f"{DEPLOYMENT}/iac-manifest.json", self.s3.store)
        self.assertEqual(self.fake_ops.started, [])


# --------------------------------------------------------------------------------------
# Case C: render / start-deploy / post-discover / finish
# --------------------------------------------------------------------------------------
class CaseC_MechanicalStages(_SequencerCaseBase):
    def _env_at(self, stage, poll_script=("EXECUTING",), **meta_extra):
        self._make_env(transform_ops=FakeTransformOps(poll_script=list(poll_script)), meta_extra=meta_extra)
        self._seed_foundation()
        self._seed_checkpoint(stage)

    def test_judgment_done_renders_starts_deploy_and_waits(self):
        self._env_at("judgment_done")
        self._seed_judgment()

        result = self._invoke()

        self._assert_continue(result, job_id=DEPLOY_JOB)
        self.assertEqual(self._stage(), "transform_deploy_waiting")
        self.assertIn(f"{DEPLOYMENT}/iac-manifest.json", self.s3.store)
        self.assertEqual(self.fake_ops.started, [("deploy", DEPLOY_JOB)])

    def test_transform_merged_with_both_artifacts_renders_without_model(self):
        self._env_at("transform_merged")
        self._seed_judgment()

        result = self._invoke()

        self._assert_continue(result, job_id=DEPLOY_JOB)
        self.assertEqual(self._stage(), "transform_deploy_waiting")
        self.assertIn(f"{DEPLOYMENT}/iac-manifest.json", self.s3.store)

    def test_start_deploy_from_iac_render_done(self):
        self._env_at("iac_render_done")
        self._seed_judgment()

        result = self._invoke()

        self._assert_continue(result, job_id=DEPLOY_JOB)
        self.assertEqual(self._stage(), "transform_deploy_waiting")
        self.assertEqual(self.table.meta["transformDeployJobId"], DEPLOY_JOB)

    def test_deploy_done_runs_post_discover_and_finishes(self):
        self._env_at("transform_deploy_done", transformDeployJobId=DEPLOY_JOB)
        post = {f"{DEPLOYMENT}/{n}" for n in ("foundation-post.json", "gap-analysis-post.json", "classification-post.json")}
        for key in deployment_artifact_keys(DEPLOY_RUN):
            if key not in post and key not in self.s3.store:
                self.s3.put_json(key, {"ok": True})

        result = self._invoke()

        self.assertEqual(result, {"status": "ok", "summary": "deploy agent phase complete"})
        self.assertEqual(self._stage(), "agent_complete")
        self.assertTrue(post <= set(self.s3.store))
        self.assertEqual(self.session_calls, 1)

    def test_post_discover_done_with_missing_artifacts_names_them(self):
        self._env_at("post_discover_done")

        result = self._invoke()

        self._assert_error(result, "finish_deploy_workflow: missing artifacts", f"{DEPLOYMENT}/iac-manifest.json")
        self.assertEqual(self._stage(), "post_discover_done")

    def test_finish_with_all_artifacts_is_ok(self):
        self._env_at("post_discover_done")
        for key in deployment_artifact_keys(DEPLOY_RUN):
            if key not in self.s3.store:
                self.s3.put_json(key, {"ok": True})

        result = self._invoke()

        self.assertEqual(result.get("status"), "ok", msg=f"got {result!r}")
        self.assertEqual(self._stage(), "agent_complete")

    def test_unknown_stage_is_an_error(self):
        self._env_at("no_such_stage")
        self._assert_error(self._invoke(), "unknown deploy checkpoint stage 'no_such_stage'")
        self.assertEqual(self._stage(), "no_such_stage")

    def test_paused_without_resume_stage_is_an_error(self):
        self._env_at("paused")
        self._assert_error(self._invoke(), "no resumeStage")


# --------------------------------------------------------------------------------------
# Case D: non-404 read errors name the key (checkpoint, #18, #19)
# --------------------------------------------------------------------------------------
class CaseD_ReadErrors(_SequencerCaseBase):
    def test_checkpoint_access_denied_names_key_and_cause(self):
        self._make_env()
        self.s3.errors[CHECKPOINT_KEY] = "AccessDenied"

        result = self._invoke()

        self._assert_error(result, "AccessDenied", CHECKPOINT_KEY)
        self.assertEqual(self.session_calls, 0)

    def _deploy_mode(self):
        self._make_env()
        self._seed_foundation()
        tools.set_deploy_run(DEPLOY_RUN)

    def test_save_foundation_assessment_raises_on_unreadable_foundation(self):
        self._deploy_mode()
        self.s3.errors[f"{DEPLOYMENT}/foundation.json"] = "AccessDenied"
        with self.assertRaises(RuntimeError) as ctx:
            tools.save_foundation_assessment(json.dumps({"environment": "greenfield", "rationale": "r"}))
        self.assertIn(f"{DEPLOYMENT}/foundation.json", str(ctx.exception))
        self.assertIn("AccessDenied", str(ctx.exception))
        self.assertNotIn(ASSESSMENT_KEY, self.s3.store)

    def test_save_foundation_assessment_refuses_only_when_absent(self):
        self._deploy_mode()
        del self.s3.store[f"{DEPLOYMENT}/gap-analysis.json"]
        out = tools.save_foundation_assessment(json.dumps({"environment": "greenfield", "rationale": "r"}))
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertIn(f"{DEPLOYMENT}/gap-analysis.json", out)
        self.assertNotIn(ASSESSMENT_KEY, self.s3.store)

    def test_read_deploy_context_raises_on_unreadable_optional_inputs(self):
        for name in ("transform-poll-analyze.json", "classification-heuristic.json", "foundation-assessment.json"):
            with self.subTest(name=name):
                self._deploy_mode()
                key = f"{DEPLOYMENT}/{name}"
                self.s3.errors[key] = "KMS.AccessDeniedException"
                with self.assertRaises(RuntimeError) as ctx:
                    tools.read_deploy_context()
                self.assertIn(key, str(ctx.exception))

    def test_read_deploy_context_reports_absent_optional_inputs_as_null(self):
        self._deploy_mode()
        ctx = json.loads(tools.read_deploy_context())
        self.assertIsNone(ctx["transform"]["analyzePoll"])
        self.assertIsNone(ctx["heuristicClassification"])
        self.assertIsNone(ctx["foundationAssessmentSaved"])


# --------------------------------------------------------------------------------------
# Case E: CreateJob 403
# --------------------------------------------------------------------------------------
class CaseE_CreateJob403(_SequencerCaseBase):
    def test_create_job_403_names_principal_workspace_and_contributor(self):
        err403 = FakeTransformOps.HttpError(403, "User is not authorized")
        self._make_env(transform_ops=FakeTransformOps(create_error=err403))
        self._seed_foundation()
        self._seed_checkpoint("transform_init_done", workspaceId=WORKSPACE)

        result = self._invoke()

        principal = tcred.transform_principal_arn()
        self.assertIn(":assumed-role/TestTransformRole/", principal)
        self._assert_error(result, "transform_start_analyze failed", principal, WORKSPACE, "Contributor")
        self.assertEqual(self._stage(), "transform_init_done")
        self.assertEqual(self.fake_ops.stopped, [])


# --------------------------------------------------------------------------------------
# Case F + #7 + #22: bounded judgment
# --------------------------------------------------------------------------------------
class CaseF_JudgmentBounded(_SequencerCaseBase):
    def _env(self):
        self._make_env()
        self._seed_foundation()
        self._seed_checkpoint("transform_merged")
        self._seed_judgment(plan=False)

    def test_incomplete_judgment_fails_named_after_attempt_limit(self):
        self._env()
        model = self._set_model([])

        for attempt in (1, 2):
            result = self._invoke()
            self._assert_continue(result)
            self.assertIn(f"attempt {attempt}/3 incomplete", result["reason"])
            self.assertEqual(self._stage(), "transform_merged")
            self.assertEqual(self._checkpoint()["judgmentAttempts"], attempt)
        result = self._invoke()

        self._assert_error(result, "deploy_judgment failed", "save_iac_change_plan", PLAN_KEY, "after 3 model turns")
        self.assertEqual(model.calls, 3)
        self.assertIn("tool.deploy_judgment.failed", self.table.actions())
        # The limit is persisted: a further invoke does not run the model again.
        self._assert_error(self._invoke(), "deploy_judgment failed")
        self.assertEqual(model.calls, 3)

    def test_non_hitl_yield_counts_as_an_attempt(self):
        self._env()
        self._set_model([lambda: dwt.yield_for_orchestrator("thinking", awaiting_hitl=False)])

        result = self._invoke()

        self._assert_continue(result, awaiting=False)
        self.assertEqual(self._stage(), "transform_merged")
        self.assertEqual(self._checkpoint()["judgmentAttempts"], 1)

    def test_hitl_yield_continues_without_using_an_attempt_and_is_bounded(self):
        self._env()
        model = self._set_model([lambda: dwt.yield_for_orchestrator("Transform asks a question", awaiting_hitl=True)])

        for n in (1, 2, 3):
            result = self._invoke()
            self._assert_continue(result, awaiting=True)
            cp = self._checkpoint()
            self.assertEqual(cp["stage"], "paused")
            self.assertEqual(cp["resumeStage"], "transform_merged")
            self.assertEqual((cp["judgmentAttempts"], cp["judgmentHitlYields"]), (0, n))
        result = self._invoke()

        self._assert_error(result, "deploy_judgment failed", "yielded for human input 4 times")
        self.assertEqual(model.calls, 4)

    def test_hitl_yield_then_completion_resumes_from_paused(self):
        self._env()
        turns = iter([
            lambda: dwt.yield_for_orchestrator("waiting on Transform", awaiting_hitl=True),
            lambda: self.s3.put_json(PLAN_KEY, _valid_plan()),
        ])
        self._set_model([lambda: next(turns)()])

        self._assert_continue(self._invoke(), awaiting=True)
        result = self._invoke()

        self._assert_continue(result)
        self.assertEqual(self._stage(), "judgment_done")

    def test_model_exception_is_named_and_audited(self):
        self._env()

        def boom():
            raise RuntimeError("Bedrock ThrottlingException")

        self._set_model([boom])
        result = self._invoke()

        self._assert_error(result, "deploy_judgment failed: Bedrock ThrottlingException")
        self.assertIn("tool.deploy_judgment.failed", self.table.actions())
        self.assertEqual(self._checkpoint()["judgmentAttempts"], 1)


# --------------------------------------------------------------------------------------
# Case G: cancelled analyze job
# --------------------------------------------------------------------------------------
class CaseG_CancelledAnalyzeJob(_SequencerCaseBase):
    def test_cancelled_analyze_is_a_named_error(self):
        self._make_env(
            transform_ops=FakeTransformOps(poll_script=["CANCELLED"]),
            meta_extra={"transformAnalyzeJobId": ANALYZE_JOB},
        )
        self._seed_foundation()
        self._seed_checkpoint("transform_analyze_started", jobId=ANALYZE_JOB)

        result = self._invoke()

        self._assert_error(result, "transform_poll_analyze_job failed", ANALYZE_JOB, "CANCELLED")
        self.assertEqual(self._stage(), "transform_analyze_started")


# --------------------------------------------------------------------------------------
# #3: pre-discover failures are step errors, never HITL waits
# --------------------------------------------------------------------------------------
class PreDiscoverFailures(_SequencerCaseBase):
    def test_failure_without_target_is_a_named_error(self):
        self._make_env()

        def broken_session():
            raise RuntimeError("cannot read deploy target credentials")

        p = mock.patch.object(tools, "deploy_boto_session", broken_session)
        p.start()
        self.addCleanup(p.stop)

        result = self._invoke()

        self.assertEqual(result, {"status": "error",
                                  "error": "run_pre_discover failed: cannot read deploy target credentials"})
        self.assertIsNone(self._checkpoint())
        self.assertIn("tool.run_pre_discover.failed", self.table.actions())

    def test_failure_with_target_keeps_platform_account_guidance(self):
        target = {"mode": "role", "accountId": TARGET_ACCOUNT,
                  "roleArn": f"arn:aws:iam::{TARGET_ACCOUNT}:role/LzDeploy"}
        self._make_env(
            meta_extra={"deployTarget": target},
            org_session=FakeOrgSession(account_id=TARGET_ACCOUNT, org_error=_orgs_not_in_use()),
        )

        result = self._invoke()

        self._assert_error(
            result,
            "run_pre_discover failed: deploy target account " + TARGET_ACCOUNT,
            "DescribeOrganization",
            "Do not create an AWS Organization in the platform account",
        )
        self.assertNotIn("awaitingHitl", result)
        self.assertIsNone(self._checkpoint())

    def test_superseded_blocked_checkpoint_is_an_explicit_error(self):
        self._make_env()
        self._seed_checkpoint("pre_discover_blocked", reason="old failure", awaitingHitl=True)

        result = self._invoke()

        self._assert_error(result, "'pre_discover_blocked'", "old failure", "start a new deploy run")
        self.assertEqual(self.session_calls, 0)
        self.assertEqual(self._stage(), "pre_discover_blocked")


# --------------------------------------------------------------------------------------
# #8 / C4: no Transform job for a run that is not RUNNING
# --------------------------------------------------------------------------------------
class RunStatusGuard(_SequencerCaseBase):
    def test_start_analyze_refused_when_run_failed(self):
        self._make_env(meta_extra={"status": "FAILED"})
        self._seed_foundation()
        self._seed_checkpoint("transform_init_done")

        result = self._invoke()

        self.assertEqual(result, {"status": "error", "error": "transform_start_analyze refused: run is FAILED"})
        self.assertEqual(self.fake_ops.started, [])
        self.assertEqual(self._stage(), "transform_init_done")

    def test_start_deploy_refused_when_run_failed(self):
        self._make_env(meta_extra={"status": "FAILED"})
        self._seed_foundation()
        self._seed_judgment()
        self._seed_checkpoint("iac_render_done")

        result = self._invoke()

        self.assertEqual(result, {"status": "error", "error": "transform_start_deploy refused: run is FAILED"})
        self.assertEqual(self.fake_ops.started, [])
        self.assertEqual(self._stage(), "iac_render_done")

    def test_run_stopped_during_create_job_stops_the_new_job(self):
        def stop_run(phase, job_id):
            self.table.meta["status"] = "FAILED"  # /stop lands between the guard and CreateJob

        self._make_env(transform_ops=FakeTransformOps(on_create=stop_run))
        self._seed_foundation()
        self._seed_checkpoint("transform_init_done")

        result = self._invoke()

        self._assert_error(result, "transform_start_analyze failed", ANALYZE_JOB, "ConditionalCheckFailedException",
                           f"stop_job({ANALYZE_JOB}) succeeded")
        self.assertEqual(self.fake_ops.stopped, [(ANALYZE_JOB, WORKSPACE)])
        self.assertEqual(self._stage(), "transform_init_done")


# --------------------------------------------------------------------------------------
# #23: a started job whose recording fails is stopped and named
# --------------------------------------------------------------------------------------
class OrphanedJobs(_SequencerCaseBase):
    def test_analyze_artifact_write_failure_stops_job(self):
        self._make_env()
        self._seed_foundation()
        self._seed_checkpoint("transform_init_done")
        self.s3.put_errors[f"{DEPLOYMENT}/transform-analyze-started.json"] = "KMS.DisabledException"

        result = self._invoke()

        self._assert_error(result, "transform_start_analyze failed", ANALYZE_JOB, "KMS.DisabledException",
                           f"stop_job({ANALYZE_JOB}) succeeded")
        self.assertEqual(self.fake_ops.stopped, [(ANALYZE_JOB, WORKSPACE)])
        self.assertIn("tool.transform_start_analyze.orphan_stop", self.table.actions())
        self.assertEqual(self._stage(), "transform_init_done")

    def test_deploy_checkpoint_write_failure_reports_stop_failure(self):
        self._make_env(transform_ops=FakeTransformOps(stop_error=RuntimeError("StopJob throttled")))
        self._seed_foundation()
        self._seed_judgment()
        self._seed_checkpoint("iac_render_done")
        self.s3.put_errors[CHECKPOINT_KEY] = "AccessDenied"

        result = self._invoke()

        self._assert_error(result, "transform_start_deploy failed", DEPLOY_JOB,
                           f"stop_job({DEPLOY_JOB}) failed: StopJob throttled")
        self.assertEqual(self.fake_ops.stopped, [(DEPLOY_JOB, WORKSPACE)])
        self.assertEqual(self._stage(), "iac_render_done")

    def test_create_job_failure_does_not_call_stop(self):
        self._make_env(transform_ops=FakeTransformOps(create_error=RuntimeError("CreateJob 500")))
        self._seed_foundation()
        self._seed_checkpoint("transform_init_done")

        self._assert_error(self._invoke(), "transform_start_analyze failed: CreateJob 500")
        self.assertEqual(self.fake_ops.stopped, [])


# --------------------------------------------------------------------------------------
# #2 wiring: pending human input reaches the checkpoint and the C3 payload
# --------------------------------------------------------------------------------------
class PendingHumanInputWiring(_SequencerCaseBase):
    def _env(self, script, stage="transform_analyze_started"):
        self._make_env(transform_ops=FakeTransformOps(poll_script=script),
                       meta_extra={"transformAnalyzeJobId": ANALYZE_JOB})
        self._seed_foundation()
        self._seed_checkpoint(stage, jobId=ANALYZE_JOB)

    def test_pending_input_on_executing_job_sets_awaiting_hitl(self):
        self._env([("EXECUTING", PENDING)])

        result = self._invoke()

        self._assert_continue(result, awaiting=True, pending=PENDING, job_id=ANALYZE_JOB)
        cp = self._checkpoint()
        self.assertEqual(cp["stage"], "transform_analyze_waiting")
        self.assertIs(cp["awaitingHitl"], True)
        self.assertEqual(cp["pendingHumanInput"], PENDING)

    def test_awaiting_status_without_task_has_null_pending(self):
        self._env(["AWAITING_HUMAN_INPUT"])

        result = self._invoke()

        self._assert_continue(result, awaiting=True, pending=None, job_id=ANALYZE_JOB)
        self.assertEqual(self._stage(), "transform_analyze_waiting")

    def test_answered_input_clears_pending_on_next_poll(self):
        self._env([("EXECUTING", PENDING), "EXECUTING"])

        self._assert_continue(self._invoke(), awaiting=True, pending=PENDING)
        result = self._invoke()

        self._assert_continue(result, awaiting=False, pending=None)
        cp = self._checkpoint()
        self.assertIsNone(cp["pendingHumanInput"])
        self.assertIs(cp["awaitingHitl"], False)

    def test_second_poll_in_one_invoke_is_deferred_with_c3_payload(self):
        # Judgment artifacts already saved: analyze poll -> merge -> render -> start deploy, then
        # the deploy poll is deferred to the next invoke (one Transform poll per invoke).
        self._env(["COMPLETED"])
        self._seed_judgment()

        result = self._invoke()

        self._assert_continue(result, awaiting=False, pending=None, job_id=DEPLOY_JOB)
        self.assertEqual(result["reason"], "transform_poll_deploy_job already polled this invoke")
        self.assertEqual(self._stage(), "transform_deploy_started")
        self.assertEqual(self.fake_ops.polls, 1)


# --------------------------------------------------------------------------------------
# #4 / #31: judgment agent tools and prompt
# --------------------------------------------------------------------------------------
def _tool_name(t) -> str:
    return getattr(t, "tool_name", None) or getattr(t, "__name__", None) or repr(t)


class JudgmentAgentTools(_SequencerCaseBase):
    JUDGMENT = {"read_deploy_context", "read_approved_scope", "get_catalog", "save_foundation_assessment",
                "save_iac_change_plan", "yield_for_orchestrator"}

    def test_deploy_tools_are_judgment_only(self):
        names = {_tool_name(t) for t in tools.deploy_tools()}
        self.assertEqual(names, self.JUDGMENT)
        mechanical = {_tool_name(t) for t in dwt.workflow_tools()} - {"yield_for_orchestrator"}
        self.assertFalse(names & mechanical)

    def test_deploy_agent_gets_judgment_docs_and_transform_mcp_tools(self):
        self._make_env()
        captured = {}

        class FakeAgent:
            def __init__(self, *, model, system_prompt, tools):
                captured.update(system_prompt=system_prompt, tools=tools)

            def __call__(self, prompt):
                return "ok"

        @contextlib.contextmanager
        def fake_mcp():
            yield ["transform-mcp-tool"]

        for target, attr, value in (
            (app, "Agent", FakeAgent),
            (app, "BedrockModel", lambda **k: "model"),
            (app, "transform_tools", fake_mcp),
            (tools, "aws_docs_tools", lambda: ["aws-docs-tool"]),
        ):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

        self.assertEqual(_REAL_DEPLOY_AGENT("prompt"), "ok")

        names = [t if isinstance(t, str) else _tool_name(t) for t in captured["tools"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), self.JUDGMENT | {"aws-docs-tool", "transform-mcp-tool"})
        self.assertEqual(captured["system_prompt"], app.DEPLOY_SYSTEM)

    def test_deploy_prompts_have_no_account_ids(self):
        import re

        for text in (app.DEPLOY_SYSTEM, app.DEPLOY_PROMPT):
            self.assertIsNone(re.search(r"\b(556|831)\d*\b|\b\d{12}\b", text),
                              msg="hard-coded account id in deploy prompt")
        self.assertIn("deploy target account", app.DEPLOY_SYSTEM)
        self.assertIn("platform account", app.DEPLOY_SYSTEM)


_REAL_DEPLOY_AGENT = app._deploy_agent


if __name__ == "__main__":
    unittest.main()
