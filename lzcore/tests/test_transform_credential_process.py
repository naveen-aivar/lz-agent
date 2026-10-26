"""Transform MCP subprocess credentials via AWS credential_process (contract C6).

Covers the helper (``python -m lzcore.transform_credential_process``), the profile/env written
for the MCP subprocess, botocore precedence (the profile's credential_process wins over the
container provider), and agent/transform_mcp.py's env. Fixtures are installed per test.
"""
from __future__ import annotations

import contextlib
import datetime
import importlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from lzcore import transform_credential_process as tcp  # noqa: E402

ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"
STATIC = {"AWS_ACCESS_KEY_ID": "AKIAPLATFORM", "AWS_SECRET_ACCESS_KEY": "p", "AWS_SESSION_TOKEN": "pt"}
CONTAINER = {
    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://127.0.0.1:1/never-called",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN": "tok",
}


class _FakeSts:
    def __init__(self):
        self.calls = []

    def assume_role(self, **kw):
        self.calls.append(kw)
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        return {"Credentials": {"AccessKeyId": "ASIATRANSFORM", "SecretAccessKey": "s", "SessionToken": "t", "Expiration": exp}}


class _FakeSession:
    def __init__(self, sts):
        self._sts = sts

    def client(self, name):
        assert name == "sts", name
        return self._sts


class _Base(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"TRANSFORM_ROLE_ARN": ROLE})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TRANSFORM_EXTERNAL_ID", None)
        self.dir = tempfile.mkdtemp(prefix="lz-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))


class HelperMainTests(_Base):
    def test_prints_credential_process_json(self):
        sts = _FakeSts()
        os.environ["AWS_PROFILE"] = tcp.PROFILE_NAME
        out = io.StringIO()
        with mock.patch("boto3.Session", return_value=_FakeSession(sts)), contextlib.redirect_stdout(out):
            code = tcp.main()
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["Version"], 1)
        self.assertEqual(payload["AccessKeyId"], "ASIATRANSFORM")
        self.assertEqual(set(payload), {"Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"})
        self.assertRegex(payload["Expiration"], r"Z$")
        self.assertEqual(sts.calls[0]["RoleSessionName"], "ingram-lz-agent")
        # The helper must not recurse into its own profile.
        self.assertNotIn("AWS_PROFILE", os.environ)

    def test_failure_exits_non_zero_with_stderr(self):
        os.environ.pop("TRANSFORM_ROLE_ARN")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tcp.main()
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("TRANSFORM_ROLE_ARN is not set", err.getvalue())

    def test_module_entrypoint_fails_loudly_without_role(self):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO), "AWS_EC2_METADATA_DISABLED": "true"}
        proc = subprocess.run(
            [sys.executable, "-m", "lzcore.transform_credential_process"],
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("TRANSFORM_ROLE_ARN is not set", proc.stderr)


class McpEnvTests(_Base):
    def _env(self, extra=None):
        base = {"PATH": "/usr/bin", "AWS_REGION": "us-east-1", "AWS_PROFILE": "someone-else",
                "AWS_DEFAULT_PROFILE": "x", **STATIC, **CONTAINER, **(extra or {})}
        return tcp.mcp_credential_env(base, self.dir)

    def test_env_has_profile_and_no_static_keys(self):
        env = self._env()
        self.assertEqual(env["AWS_PROFILE"], tcp.PROFILE_NAME)
        self.assertEqual(env["AWS_CONFIG_FILE"], os.path.join(self.dir, tcp.CONFIG_FILE_NAME))
        self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], os.path.join(self.dir, tcp.CREDENTIALS_FILE_NAME))
        for key in (*STATIC, "AWS_SECURITY_TOKEN", "AWS_DEFAULT_PROFILE"):
            self.assertNotIn(key, env)
        for key, value in CONTAINER.items():
            self.assertEqual(env[key], value)
        self.assertEqual(env["TRANSFORM_ROLE_ARN"], ROLE)
        self.assertNotIn("TRANSFORM_EXTERNAL_ID", env)
        self.assertTrue(env["PYTHONPATH"].split(os.pathsep)[0] == str(REPO))

    def test_external_id_forwarded(self):
        os.environ["TRANSFORM_EXTERNAL_ID"] = "ext-1"
        self.assertEqual(self._env()["TRANSFORM_EXTERNAL_ID"], "ext-1")

    def test_profile_file_runs_helper_and_is_private(self):
        env = self._env()
        text = Path(env["AWS_CONFIG_FILE"]).read_text()
        self.assertIn(f"[profile {tcp.PROFILE_NAME}]", text)
        self.assertIn("credential_process = ", text)
        self.assertIn("-m lzcore.transform_credential_process", text)
        for path in (env["AWS_CONFIG_FILE"], env["AWS_SHARED_CREDENTIALS_FILE"]):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_missing_role_fails_before_spawn(self):
        os.environ.pop("TRANSFORM_ROLE_ARN")
        with self.assertRaisesRegex(RuntimeError, "TRANSFORM_ROLE_ARN is not set"):
            self._env()

    def test_credential_process_takes_precedence_over_container_provider(self):
        # Point the profile at a stand-in helper; botocore must resolve credentials from it,
        # not from the container endpoint (which would fail: port 1) or static env keys.
        fake = Path(self.dir) / "fake_helper.py"
        exp = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fake.write_text(textwrap.dedent(f"""
            import json
            print(json.dumps({{"Version": 1, "AccessKeyId": "ASIAFROMPROCESS", "SecretAccessKey": "s",
                              "SessionToken": "t", "Expiration": "{exp}"}}))
        """))
        with mock.patch.object(tcp, "helper_command", return_value=f"{sys.executable} {fake}"):
            env = self._env()
        import boto3
        import botocore.session

        self.assertIn("AWS_CONTAINER_CREDENTIALS_FULL_URI", env)
        with mock.patch.dict(os.environ, env, clear=True):
            # Env-chosen profile (botocore default chain) and explicit profile (the MCP
            # library's AwsHelper.create_session / _create_sigv4_client) both use the process.
            for creds in (
                botocore.session.Session().get_credentials(),
                boto3.Session(profile_name=os.environ["AWS_PROFILE"]).get_credentials(),
            ):
                self.assertEqual(creds.method, "custom-process")
                self.assertEqual(creds.get_frozen_credentials().access_key, "ASIAFROMPROCESS")


class AgentTransformMcpEnvTests(_Base):
    """agent/transform_mcp.py builds the subprocess env through mcp_credential_env.

    mcp/strands are stubbed per test (they are not installed in the lzcore test envs)."""

    def _import_agent_module(self):
        stdio = types.ModuleType("mcp.client.stdio")
        stdio.StdioServerParameters = lambda **kw: types.SimpleNamespace(**kw)
        stdio.get_default_environment = lambda: {"PATH": "/usr/bin", "HOME": "/home/agent"}
        stdio.stdio_client = lambda params: None
        smcp = types.ModuleType("strands.tools.mcp")
        smcp.MCPClient = object
        stubs = {
            "mcp": types.ModuleType("mcp"), "mcp.client": types.ModuleType("mcp.client"), "mcp.client.stdio": stdio,
            "strands": types.ModuleType("strands"), "strands.tools": types.ModuleType("strands.tools"),
            "strands.tools.mcp": smcp,
        }
        p = mock.patch.dict(sys.modules, stubs)
        p.start()
        self.addCleanup(p.stop)
        sys.modules.pop("transform_mcp", None)
        sys.path.insert(0, str(REPO / "agent"))
        self.addCleanup(lambda: sys.path.remove(str(REPO / "agent")))
        self.addCleanup(lambda: sys.modules.pop("transform_mcp", None))
        return importlib.import_module("transform_mcp")

    def test_server_env_uses_credential_process_profile(self):
        mod = self._import_agent_module()
        os.environ.update({"TRANSFORM_WORKSPACE_ID": "ws-1", **STATIC, **CONTAINER})
        params = mod.server_params(self.dir)
        env = params.env
        self.assertEqual(env["AWS_PROFILE"], tcp.PROFILE_NAME)
        self.assertTrue(os.path.isfile(env["AWS_CONFIG_FILE"]))
        for key in STATIC:
            self.assertNotIn(key, env)
        self.assertEqual(env["AWS_CONTAINER_CREDENTIALS_FULL_URI"], CONTAINER["AWS_CONTAINER_CREDENTIALS_FULL_URI"])
        self.assertEqual(env["TRANSFORM_WORKSPACE_ID"], "ws-1")
        self.assertEqual(params.args, ["-m", "awslabs.aws_transform_mcp_server.server"])


if __name__ == "__main__":
    unittest.main()
