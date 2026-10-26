"""Bug condition exploration tests for the deploy-transform mechanical-stage stall.

Spec: .kiro/specs/deploy-transform-init-stall-fix (bugfix). This module implements
task 1 ("Write bug condition exploration test"). It drives the UNFIXED deploy invoke
path (``agent.app.invoke(payload, context)``) with a scripted model that calls deploy
workflow tools up to a given stage and then returns, exactly as a real model does when
it ends its turn after a mechanical step.

Per the bugfix exploration-test protocol a FAILING assertion here is the SUCCESS case:
the failure is the counterexample that proves the bug exists. Cases A-G below encode the
*expected* (fixed) behaviour from bugfix.md requirements 2.x. On the unfixed code they are
expected to fail (or, where the uncommitted v8 patch masks the stall, to pass for the
wrong reason, which the test documents in-line). When the sequencer fix lands (task 3)
the SAME assertions become the acceptance test for the fix (task 3.8).

Harness notes (design.md "Testing Strategy"):
  * ``strands`` and ``bedrock_agentcore`` and ``mcp`` are not installed locally, so this
    module installs stub modules in ``sys.modules`` (identity ``tool`` decorator, stub
    ``BedrockAgentCoreApp`` whose ``entrypoint`` returns the wrapped function) and sets
    ``STATE_TABLE``, ``ARTIFACT_BUCKET``, ``MODEL_ID``, ``TRANSFORM_WORKSPACE_ID`` BEFORE
    importing ``agent.app`` / ``agent.deploy_workflow_tools``.
  * Fixtures (FakeS3, FakeTable, fake transform_ops, fake STS, scripted model callable)
    are installed per test by ``_make_env`` and are NEVER a default the application picks
    up when configuration is absent (engineering rule: no fallback/stub stand-ins that the
    app adopts silently; fixtures are installed explicitly by the test only).

Recorded counterexamples on the UNFIXED working tree (python -m unittest, this repo):
  A init stall ............ PASS (v8 masks this one stage: ensure_transform_job_progress_after_agent
                            starts analyze + polls once -> {'status':'continue'}; passes for the
                            wrong reason, see class docstring). Pre-v8 this is
                            "deploy incomplete at checkpoint stage='transform_init_done'".
  B merge stall ........... FAIL -> {'status':'error',
                            'error':"deploy incomplete at checkpoint stage='transform_analyze_done'"}
  C render stall .......... FAIL -> "...stage='transform_merged'"  (plan saved, bundles not rendered)
  C start-deploy stall .... FAIL -> "...stage='iac_render_done'"
  C post-discover stall ... FAIL -> "...stage='transform_deploy_done'"
  C finish stall .......... FAIL -> "...stage='post_discover_done'"  (all artifacts present, not finished)
  D checkpoint AccessDenied FAIL -> {'status':'error','error':'deploy incomplete at checkpoint stage=None'}
                            (S3 AccessDenied swallowed into {}; real cause hidden)
  E CreateJob 403 ......... FAIL -> {'status':'error',
                            'error':'transform_start_analyze failed: HTTP 403: User is not authorized'}
                            (no principal ARN, no workspace id, no 'Contributor' guidance)
  F judgment incomplete ... FAIL -> "...stage='transform_merged'"  (missing iac-change-plan.json not named)
  G cancelled analyze ..... FAIL -> transformDone=True, checkpoint advanced to 'transform_analyze_done'
                            (CANCELLED treated as a completed poll; flows into merge -> silent substitution)
These failures confirm: (1) model-owned sequencing stalls at every mechanical stage v8 does
not patch (B, C), (2) swallowed checkpoint read error (D), (3) undifferentiated Transform 403
(E), (4) un-named incomplete judgment artifact (F), (5) cancelled-job-as-done substitution (G).

Working-tree note: the repo currently carries the uncommitted v8 patch
(``ensure_pre_discover`` + ``ensure_transform_job_progress_after_agent`` wired into
``app.invoke``). The task description mentions ``git stash`` for the pre-v8 Case A
baseline, but this run does NOT modify the working tree; it captures v8 behaviour as-is
and documents, per case, whether v8 masks the stall.
"""
from __future__ import annotations

import io
import json
import os
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))


# --------------------------------------------------------------------------------------
# sys.modules stubs: strands / bedrock_agentcore / mcp are not installed locally.
# Installed once at import time so that `import agent.app` succeeds. These stubs carry NO
# behaviour the application relies on at runtime beyond letting the module import; all
# real behaviour under test comes from the per-test fixtures, which the test installs
# explicitly (never a silent default).
# --------------------------------------------------------------------------------------
def _install_import_stubs() -> None:
    if "strands" not in sys.modules:
        strands = types.ModuleType("strands")

        def tool(fn=None, **_kw):
            # identity decorator; supports both @tool and @tool(...)
            if fn is None:
                return lambda f: f
            return fn

        class Agent:  # pragma: no cover - never instantiated; _deploy_agent is patched
            def __init__(self, *a, **k):
                raise RuntimeError("strands.Agent stub must not be constructed in tests")

            def __call__(self, *a, **k):
                raise RuntimeError("strands.Agent stub must not be called in tests")

        strands.tool = tool
        strands.Agent = Agent
        sys.modules["strands"] = strands

        models = types.ModuleType("strands.models")

        class BedrockModel:  # pragma: no cover
            def __init__(self, *a, **k):
                pass

        models.BedrockModel = BedrockModel
        sys.modules["strands.models"] = models

        strands_tools = types.ModuleType("strands.tools")
        sys.modules["strands.tools"] = strands_tools
        mcp_sub = types.ModuleType("strands.tools.mcp")

        class MCPClient:  # pragma: no cover
            def __init__(self, *a, **k):
                pass

        mcp_sub.MCPClient = MCPClient
        sys.modules["strands.tools.mcp"] = mcp_sub
        strands_tools.mcp = mcp_sub

    if "bedrock_agentcore" not in sys.modules:
        bac = types.ModuleType("bedrock_agentcore")
        runtime = types.ModuleType("bedrock_agentcore.runtime")

        class BedrockAgentCoreApp:
            def __init__(self, *a, **k):
                self._entry = None

            def entrypoint(self, fn):
                # Return the wrapped function so tests can call app.invoke(payload, ctx).
                self._entry = fn
                return fn

            def run(self):  # pragma: no cover
                pass

        runtime.BedrockAgentCoreApp = BedrockAgentCoreApp
        bac.runtime = runtime
        sys.modules["bedrock_agentcore"] = bac
        sys.modules["bedrock_agentcore.runtime"] = runtime

    if "mcp" not in sys.modules:
        mcp = types.ModuleType("mcp")
        client = types.ModuleType("mcp.client")
        stdio = types.ModuleType("mcp.client.stdio")
        streamable = types.ModuleType("mcp.client.streamable_http")

        class StdioServerParameters:  # pragma: no cover
            def __init__(self, *a, **k):
                pass

        def get_default_environment():  # pragma: no cover
            return {}

        def stdio_client(*a, **k):  # pragma: no cover
            raise RuntimeError("mcp stdio stub must not be used in tests")

        def streamablehttp_client(*a, **k):  # pragma: no cover
            raise RuntimeError("mcp http stub must not be used in tests")

        stdio.StdioServerParameters = StdioServerParameters
        stdio.get_default_environment = get_default_environment
        stdio.stdio_client = stdio_client
        streamable.streamablehttp_client = streamablehttp_client
        mcp.client = client
        client.stdio = stdio
        client.streamable_http = streamable
        sys.modules["mcp"] = mcp
        sys.modules["mcp.client"] = client
        sys.modules["mcp.client.stdio"] = stdio
        sys.modules["mcp.client.streamable_http"] = streamable


# Env vars required at import time (tools.py reads STATE_TABLE / ARTIFACT_BUCKET at module
# load; transform_ops and transform_mcp read TRANSFORM_WORKSPACE_ID).
os.environ.setdefault("STATE_TABLE", "test-state-table")
os.environ.setdefault("ARTIFACT_BUCKET", "test-artifact-bucket")
os.environ.setdefault("MODEL_ID", "test-model-id")
os.environ.setdefault("TRANSFORM_WORKSPACE_ID", "ws-test-0001")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

_install_import_stubs()

# Import after stubs + env are in place.
#
# IMPORTANT: agent/app.py does `import tools` and `from deploy_workflow_tools import ...`
# with the agent/ directory on sys.path, so those resolve to the TOP-LEVEL modules
# `tools` / `deploy_workflow_tools`, NOT `agent.tools` / `agent.deploy_workflow_tools`.
# The test must patch the SAME module objects the app uses, so we import the top-level
# names (and read them back through `app` to guarantee object identity).
import agent.app as app  # noqa: E402

tools = app.tools  # the exact module object app.invoke() uses
dwt = sys.modules["deploy_workflow_tools"]  # imported transitively by app
from lzcore import deploy_transform  # noqa: E402  (app's tools uses lzcore.deploy_transform)
from lzcore.deploy_artifacts import deployment_artifact_keys  # noqa: E402

assert tools is sys.modules["tools"], "test must patch the same tools module app imports"


BUCKET = os.environ["ARTIFACT_BUCKET"]
DEPLOY_RUN = "deployrun00000000000000000000001"
DESIGN_RUN = "designrun0000000000000000000001"
CHECKPOINT_KEY = f"runs/{DEPLOY_RUN}/deployment/agent-checkpoint.json"


# --------------------------------------------------------------------------------------
# Fakes. All dict-backed; configurable per-key errors. Installed per test only.
# --------------------------------------------------------------------------------------
class _ClientError(Exception):
    """Mimics botocore.exceptions.ClientError for FakeS3-injected failures."""

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
    """Dict-backed S3 with per-key injectable ClientError. Absent keys raise NoSuchKey."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        # key -> ClientError code to raise on get_object/head_object for that key
        self.errors: dict[str, str] = {}
        self.puts: list[str] = []

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body if isinstance(Body, bytes) else str(Body).encode()
        self.puts.append(Key)
        return {}

    def _maybe_error(self, key):
        if key in self.errors:
            raise _ClientError(self.errors[key])
        if key not in self.store:
            raise _ClientError("NoSuchKey")

    def get_object(self, Bucket, Key, **kw):
        self._maybe_error(Key)
        return {"Body": _Body(self.store[Key])}

    def head_object(self, Bucket, Key, **kw):
        self._maybe_error(Key)
        return {"ContentLength": len(self.store[Key])}

    def copy_object(self, **kw):  # pragma: no cover - render path not exercised here
        self.store[kw["Key"]] = b"{}"
        self.puts.append(kw["Key"])
        return {}

    # test helpers
    def put_json(self, key, obj):
        self.store[key] = json.dumps(obj).encode()

    def get_json(self, key):
        return json.loads(self.store[key].decode())


class FakeTable:
    """Records update_item/put_item; serves a single deploy META item."""

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

    def update_item(self, Key, UpdateExpression="", ExpressionAttributeValues=None, **kw):
        self.updates.append(
            {"expr": UpdateExpression, "vals": dict(ExpressionAttributeValues or {})}
        )
        # Reflect job-id writes back into META so subsequent _run_meta() reads see them.
        vals = ExpressionAttributeValues or {}
        if ":j" in vals and "transformAnalyzeJobId" in UpdateExpression:
            self.meta["transformAnalyzeJobId"] = vals[":j"]
        if ":j" in vals and "transformDeployJobId" in UpdateExpression:
            self.meta["transformDeployJobId"] = vals[":j"]
        if ":w" in vals:
            self.meta["transformWorkspaceId"] = vals[":w"]
        return {}

    # audit actions seen, newest-last
    def actions(self):
        return [a.get("action") for a in self.audit]


class FakeTransformOps:
    """Scriptable stand-in for lzcore.transform_ops. Installed per test on deploy_transform.

    status_sequence drives successive poll_job() calls. create_error, when set, is raised
    on start_landing_zone_job (CreateJob path). Fail loudly on anything unscripted; never
    return a plausible default (engineering rule: no silent substitution).
    """

    class HttpError(Exception):
        def __init__(self, status_code, message="forbidden"):
            self.status_code = status_code
            super().__init__(f"HTTP {status_code}: {message}")

    def __init__(self, status_sequence=None, create_error=None):
        self.status_sequence = list(status_sequence or [])
        self.create_error = create_error
        self.started = []
        self.polls = 0

    def workspace_id(self):
        return os.environ["TRANSFORM_WORKSPACE_ID"]

    def init_connection(self, preferred_region=None):
        return {"ok": True, "authMode": "sigv4", "region": "us-east-1"}

    def start_landing_zone_job(self, *, run_id, phase, prompt):
        if self.create_error is not None:
            raise self.create_error
        job_id = f"job-{phase}-{run_id[:6]}"
        self.started.append((phase, job_id))
        return {"workspaceId": self.workspace_id(), "jobId": job_id, "jobStatus": "IN_PROGRESS", "init": {}}

    def poll_job(self, job_id, workspace=None):
        if not self.status_sequence:
            raise RuntimeError("FakeTransformOps.poll_job called with no scripted status left")
        status = self.status_sequence.pop(0)
        self.polls += 1
        s = status.upper()
        terminal = s in {
            "SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE", "DONE",
            "FAILED", "STOPPED", "CANCELLED", "CANCELED",
        }
        awaiting = s in {"AWAITING_HUMAN_INPUT", "PAUSED", "BLOCKED"} or "HITL" in s
        return {
            "ok": True,
            "jobId": job_id,
            "status": s,
            "done": terminal,
            "awaitingHumanApproval": awaiting,
            "job": {"status": s},
        }


class _ScriptedModel:
    """Scripted model: calls a list of deploy workflow tool callables, then returns.

    Mirrors a real model ending its turn after N mechanical tool calls. Returns a short
    string, like the real Strands Agent result.
    """

    def __init__(self, steps):
        self.steps = steps  # list[callable] taking no args
        self.calls = []

    def __call__(self):
        for step in self.steps:
            self.calls.append(getattr(step, "__name__", repr(step)))
            step()
        return "Invocation completed successfully (20s)"


# --------------------------------------------------------------------------------------
# Env wiring shared by every case.
# --------------------------------------------------------------------------------------
class _SequencerCaseBase(unittest.TestCase):
    def _make_env(self, *, meta_extra=None, transform_ops=None, seed=None):
        """Install FakeS3/FakeTable/fake transform_ops + fake STS, seed artifacts, patch
        app._deploy_agent with a scripted model, and return (s3, table, cleanup)."""
        s3 = FakeS3()
        meta = {
            "PK": f"RUN#{DEPLOY_RUN}",
            "SK": "META",
            "runKind": "deploy",
            "designRunId": DESIGN_RUN,
            "transformWorkspaceId": os.environ["TRANSFORM_WORKSPACE_ID"],
            "artifacts": {},
        }
        if meta_extra:
            meta.update(meta_extra)
        table = FakeTable(meta)

        saved = {
            "tools_s3": tools._s3,
            "tools_ddb": tools._ddb,
            "dt_ops": deploy_transform.transform_ops,
            "deploy_agent": app._deploy_agent,
            "transform_tools": app.transform_tools,
            "deploy_session": tools.deploy_boto_session,
            "assume_stable": app.stable_identity.assume_stable_session,
            "state": dict(tools._state),
        }

        tools._s3 = s3
        tools._ddb = table
        if transform_ops is not None:
            deploy_transform.transform_ops = transform_ops
        # Transform MCP context manager is a no-op yielding no tools.
        import contextlib

        @contextlib.contextmanager
        def _fake_transform_tools():
            yield []

        app.transform_tools = _fake_transform_tools
        # Never hit real AWS Organizations/STS for pre/post discover.
        tools.deploy_boto_session = lambda: None
        # Never call real STS for the stable Transform identity switch (fixture installed per test).
        app.stable_identity.assume_stable_session = (
            lambda: "arn:aws:sts::000000000000:assumed-role/test-AgentRole/ingram-lz-agent"
        )

        # Seed the approved design scope (needed by analyze/merge/start-deploy paths).
        s3.put_json(
            f"runs/{DESIGN_RUN}/intake/scope.json",
            {"customer": {"orgName": "Acme"}, "summary": {"ous": 2}, "regions": {"home": "eu-west-1"}},
        )
        if seed:
            seed(s3, table)

        def cleanup():
            tools._s3 = saved["tools_s3"]
            tools._ddb = saved["tools_ddb"]
            deploy_transform.transform_ops = saved["dt_ops"]
            app._deploy_agent = saved["deploy_agent"]
            app.transform_tools = saved["transform_tools"]
            tools.deploy_boto_session = saved["deploy_session"]
            app.stable_identity.assume_stable_session = saved["assume_stable"]
            tools._state.clear()
            tools._state.update(saved["state"])

        self.addCleanup(cleanup)
        return s3, table

    def _set_scripted_model(self, steps):
        model = _ScriptedModel(steps)
        app._deploy_agent = lambda prompt: model()
        return model

    def _invoke(self):
        return app.invoke({"runId": DEPLOY_RUN, "phase": "deploy"}, context=None)

    def _seed_checkpoint(self, s3, stage, **extra):
        body = {"stage": stage, "updatedAt": 0, **extra}
        s3.put_json(CHECKPOINT_KEY, body)

    def _seed_foundation(self, s3):
        """Pre-seed foundation.json so v8 ensure_pre_discover() is a no-op (skips discover)."""
        base = f"runs/{DEPLOY_RUN}/deployment"
        s3.put_json(f"{base}/foundation.json", {"organizationalUnits": [], "accounts": []})
        s3.put_json(f"{base}/gap-analysis.json", {"missingOus": [], "missingAccountsByName": []})


# --------------------------------------------------------------------------------------
# Case A: init stall (Bug Condition 1.1 / Expected 2.1)
# --------------------------------------------------------------------------------------
class CaseA_InitStall(_SequencerCaseBase):
    """Model calls read_deploy_checkpoint + transform_init_connection, then returns.

    Expected (fixed, 2.1): the sequencer starts the analyze job deterministically,
    advances to transform_analyze_started/_waiting, and returns continue/ok. The result
    must NOT be `deploy incomplete at checkpoint stage=...`.

    On the UNFIXED working tree the v8 patch (ensure_transform_job_progress_after_agent)
    partially masks this exact stage: after the model returns at transform_init_done, v8
    runs start_analyze + one poll. So v8 may turn this into a continue (masking the
    model-owned-sequencing defect for THIS one stage). We assert the fixed-behaviour
    expectation; if v8 happens to satisfy it, this case passes for the wrong reason, which
    is documented here. The pre-v8 counterexample is `deploy incomplete ... 'transform_init_done'`.
    """

    def test_init_stall_should_not_report_deploy_incomplete(self):
        fake = FakeTransformOps(status_sequence=["IN_PROGRESS"])  # one poll -> waiting
        s3, table = self._make_env(transform_ops=fake)
        self._seed_foundation(s3)  # skip pre-discover (v8 runs it before the agent)

        def init_only():
            dwt.read_deploy_checkpoint()
            # Set the pre_discover_done checkpoint the real pre-discover would have set,
            # then run init exactly as the model would.
            dwt._save_checkpoint("pre_discover_done")
            dwt.transform_init_connection()

        self._set_scripted_model([init_only])
        result = self._invoke()

        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleA(pre-v8): expected the analyze job to be started "
            f"deterministically; got {result!r}",
        )
        self.assertIn(result.get("status"), {"continue", "ok"}, msg=f"got {result!r}")


# --------------------------------------------------------------------------------------
# Case B: merge stall (Bug Condition 1.3 / Expected 2.3)
# --------------------------------------------------------------------------------------
class CaseB_MergeStall(_SequencerCaseBase):
    """Checkpoint at transform_analyze_done, model returns without calling merge.

    Expected (fixed, 2.3): the sequencer runs the merge deterministically and advances to
    transform_merged. v8 does NOT cover transform_analyze_done, so the unfixed path returns
    `deploy incomplete at checkpoint stage='transform_analyze_done'`.
    """

    def test_merge_stall_counterexample(self):
        s3, table = self._make_env()
        self._seed_foundation(s3)
        self._seed_checkpoint(s3, "transform_analyze_done", jobId="job-analyze-x")
        # analyze poll artifact exists (merge reads it)
        s3.put_json(f"runs/{DEPLOY_RUN}/deployment/transform-poll-analyze.json", {"status": "DONE"})

        self._set_scripted_model([lambda: None])  # model does nothing
        result = self._invoke()

        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleB: merge not run deterministically; got {result!r}",
        )


# --------------------------------------------------------------------------------------
# Case C: render / start-deploy / post-discover / finish stalls
# (Bug Conditions 1.4, 1.5, 1.6, 1.7 / Expected 2.4, 2.5, 2.6, 2.7)
# --------------------------------------------------------------------------------------
class CaseC_MechanicalStalls(_SequencerCaseBase):
    """Each remaining mechanical stage, with the model ending its turn early. None are
    covered by v8, so each returns the matching `deploy incomplete at checkpoint stage=...`
    on the unfixed code."""

    def _run_stage(self, stage, seed=None):
        fake = FakeTransformOps(status_sequence=["IN_PROGRESS"])
        s3, table = self._make_env(
            transform_ops=fake, meta_extra={"transformDeployJobId": "job-deploy-x"}
        )
        self._seed_foundation(s3)
        self._seed_checkpoint(s3, stage)
        if seed:
            seed(s3)
        self._set_scripted_model([lambda: None])
        return self._invoke()

    def test_render_stall_counterexample(self):
        # Plan saved, checkpoint still transform_merged -> bundles should be rendered (1.4/2.4).
        def seed(s3):
            s3.put_json(
                f"runs/{DEPLOY_RUN}/deployment/iac-change-plan.json",
                {"strategy": "no_changes_needed", "changes": []},
            )
            # judgment artifacts present so fixed sequencer treats stage as mechanical
            s3.put_json(f"runs/{DEPLOY_RUN}/deployment/foundation-assessment.json", {"environment": "greenfield"})

        result = self._run_stage("transform_merged", seed=seed)
        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleC-render: bundles not rendered; got {result!r}",
        )

    def test_start_deploy_stall_counterexample(self):
        result = self._run_stage("iac_render_done")
        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleC-start-deploy: deploy job not started; got {result!r}",
        )

    def test_post_discover_stall_counterexample(self):
        result = self._run_stage("transform_deploy_done")
        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleC-post-discover: post-discover not run; got {result!r}",
        )

    def test_finish_stall_counterexample(self):
        # post_discover_done with every required artifact present -> should finish (ok).
        def seed(s3):
            for key in deployment_artifact_keys(DEPLOY_RUN):
                s3.put_json(key, {"ok": True})

        result = self._run_stage("post_discover_done", seed=seed)
        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            str(result.get("error", "")),
            msg=f"CounterexampleC-finish: finish not run; got {result!r}",
        )


# --------------------------------------------------------------------------------------
# Case D: checkpoint AccessDenied (Bug Condition 1.9 / Expected 2.9)
# --------------------------------------------------------------------------------------
class CaseD_CheckpointAccessDenied(_SequencerCaseBase):
    """FakeS3 raises ClientError(AccessDenied) on the checkpoint key.

    Expected (fixed, 2.9): fail with an error naming the checkpoint key and the AccessDenied
    cause. Unfixed: `_load_checkpoint`/`_read_checkpoint` swallow the error into {} and the
    result is `deploy incomplete at checkpoint stage=None`, hiding the real cause.
    """

    def test_access_denied_is_not_swallowed_to_stage_none(self):
        s3, table = self._make_env()
        self._seed_foundation(s3)
        s3.errors[CHECKPOINT_KEY] = "AccessDenied"

        self._set_scripted_model([lambda: None])
        result = self._invoke()

        err = str(result.get("error", ""))
        self.assertNotIn(
            "stage=None",
            err,
            msg=f"CounterexampleD: AccessDenied swallowed to stage=None; got {result!r}",
        )
        self.assertIn("AccessDenied", err, msg=f"error should name the cause; got {result!r}")
        self.assertIn(
            "agent-checkpoint.json", err, msg=f"error should name the checkpoint key; got {result!r}"
        )


# --------------------------------------------------------------------------------------
# Case E: CreateJob 403 (Bug Condition 1.8 / Expected 2.8)
# --------------------------------------------------------------------------------------
class CaseE_CreateJob403(_SequencerCaseBase):
    """Fake transform_ops raises HttpError(403) on the CreateJob (start analyze) path.

    Expected (fixed, 2.8): error naming the step, the calling principal, and the need for
    Contributor membership in TRANSFORM_WORKSPACE_ID. Unfixed: a generic message with none
    of principal / workspace / 'Contributor' guidance.
    """

    def test_create_job_403_names_principal_and_workspace(self):
        err403 = FakeTransformOps.HttpError(403, "User is not authorized")
        fake = FakeTransformOps(create_error=err403)
        s3, table = self._make_env(transform_ops=fake)
        self._seed_foundation(s3)
        self._seed_checkpoint(s3, "transform_init_done", workspaceId=os.environ["TRANSFORM_WORKSPACE_ID"])

        # Model returns immediately; v8 (or the fixed sequencer) drives start-analyze.
        self._set_scripted_model([lambda: None])
        result = self._invoke()

        err = str(result.get("error", ""))
        self.assertEqual(result.get("status"), "error", msg=f"got {result!r}")
        for needle in ("Contributor", os.environ["TRANSFORM_WORKSPACE_ID"]):
            self.assertIn(
                needle,
                err,
                msg=f"CounterexampleE: 403 message lacks {needle!r}; got {result!r}",
            )


# --------------------------------------------------------------------------------------
# Case F: judgment incomplete (Bug Condition 1.10 / Expected 2.10)
# --------------------------------------------------------------------------------------
class CaseF_JudgmentIncomplete(_SequencerCaseBase):
    """Checkpoint transform_merged with a judgment artifact (iac-change-plan.json) missing,
    model returns without saving it.

    Expected (fixed, 2.10): error naming the incomplete judgment step and the missing
    artifact key (runs/{id}/deployment/iac-change-plan.json). Unfixed: only
    `deploy incomplete at checkpoint stage='transform_merged'`, with no named artifact key.
    """

    def test_missing_plan_names_the_artifact_key(self):
        s3, table = self._make_env()
        self._seed_foundation(s3)
        self._seed_checkpoint(s3, "transform_merged")
        # assessment saved, plan deliberately absent
        s3.put_json(f"runs/{DEPLOY_RUN}/deployment/foundation-assessment.json", {"environment": "greenfield"})

        self._set_scripted_model([lambda: None])
        result = self._invoke()

        err = str(result.get("error", ""))
        self.assertNotIn(
            "deploy incomplete at checkpoint stage",
            err,
            msg=f"CounterexampleF: judgment stall reported generically; got {result!r}",
        )
        self.assertIn(
            "iac-change-plan.json",
            err,
            msg=f"CounterexampleF: missing artifact key not named; got {result!r}",
        )


# --------------------------------------------------------------------------------------
# Case G: cancelled analyze job treated as done (silent substitution being fixed)
# (design.md "Noted, not in scope" -> task 3.2 scope decision; Expected 2.8/2.11)
# --------------------------------------------------------------------------------------
class CaseG_CancelledAnalyzeJob(_SequencerCaseBase):
    """Fake Transform reports analyze job status CANCELLED on poll.

    Unfixed: poll_transform_job only raises on FAILED; poll_job marks CANCELLED as a
    terminal `done` status, so a cancelled analyze job flows into merge as if it succeeded
    -- a silent substitution (no-fallbacks violation). Expected (fixed): poll raises naming
    the job id and the CANCELLED status.

    This test drives the poll directly via the tool (transform_poll_analyze_job) using the
    fake, because that is where the CANCELLED-as-done substitution happens. It asserts the
    fixed behaviour: done must be False (not treated as a completed analyze).
    """

    def test_cancelled_analyze_not_treated_as_done(self):
        fake = FakeTransformOps(status_sequence=["CANCELLED"])
        s3, table = self._make_env(
            transform_ops=fake, meta_extra={"transformAnalyzeJobId": "job-analyze-x"}
        )
        self._seed_foundation(s3)
        self._seed_checkpoint(s3, "transform_analyze_started", jobId="job-analyze-x")

        # Put the deploy run into deploy mode so the tool's mode guard passes.
        tools.set_deploy_run(DEPLOY_RUN)

        raised = None
        out = None
        try:
            out = dwt._execute_transform_poll_analyze_once()
        except Exception as e:  # fixed code should raise here
            raised = e

        if raised is not None:
            msg = str(raised)
            self.assertIn("CANCELLED", msg.upper(), msg=f"raise should name status; got {msg!r}")
            return

        # Unfixed path: no raise. Capture the counterexample: CANCELLED marked done=True and
        # the checkpoint advanced to transform_analyze_done, feeding merge.
        cp = s3.get_json(CHECKPOINT_KEY)
        self.assertFalse(
            out.get("transformDone"),
            msg=(
                "CounterexampleG: CANCELLED analyze job treated as done "
                f"(transformDone={out.get('transformDone')}, checkpoint stage="
                f"{cp.get('stage')!r}); a cancelled job must not flow into merge."
            ),
        )


if __name__ == "__main__":
    unittest.main()
