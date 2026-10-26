"""agent/stable_identity.py: fixed Transform session name; fails loudly when it cannot switch."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

import stable_identity  # noqa: E402

ROLE = "arn:aws:iam::111122223333:role/stack-AgentRole-ABC"


class _FakeSts:
    def __init__(self, caller_arn, assume_error=None):
        self.caller_arn = caller_arn
        self.assume_error = assume_error
        self.assume_calls = []

    def assume_role(self, **kw):
        self.assume_calls.append(kw)
        if self.assume_error:
            raise self.assume_error
        return {"Credentials": {"AccessKeyId": "AKIATEST", "SecretAccessKey": "s", "SessionToken": "t"}}

    def get_caller_identity(self):
        return {"Arn": self.caller_arn}


class _FakeSession:
    def __init__(self, sts):
        self._sts = sts

    def client(self, name):
        assert name == "sts"
        return self._sts


class StableIdentityTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"AGENT_ROLE_ARN": ROLE}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def _patch_sts(self, sts):
        p = mock.patch.object(stable_identity.boto3, "Session", lambda: _FakeSession(sts))
        p.start()
        self.addCleanup(p.stop)

    def test_assumes_role_with_fixed_session_name_and_exports_creds(self):
        sts = _FakeSts(f"arn:aws:sts::111122223333:assumed-role/stack-AgentRole-ABC/{stable_identity.STABLE_SESSION_NAME}")
        self._patch_sts(sts)
        arn = stable_identity.assume_stable_session()
        self.assertTrue(arn.endswith("/ingram-lz-agent"))
        self.assertEqual(sts.assume_calls[0]["RoleArn"], ROLE)
        self.assertEqual(sts.assume_calls[0]["RoleSessionName"], "ingram-lz-agent")
        self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "AKIATEST")

    def test_missing_role_env_raises(self):
        os.environ.pop("AGENT_ROLE_ARN")
        with self.assertRaisesRegex(RuntimeError, "AGENT_ROLE_ARN"):
            stable_identity.assume_stable_session()

    def test_assume_failure_names_role_and_trust_fix(self):
        self._patch_sts(_FakeSts("unused", assume_error=Exception("AccessDenied")))
        with self.assertRaisesRegex(RuntimeError, "trust policy must allow the role to assume itself"):
            stable_identity.assume_stable_session()

    def test_wrong_caller_after_switch_raises(self):
        self._patch_sts(_FakeSts("arn:aws:sts::111122223333:assumed-role/stack-AgentRole-ABC/BedrockAgentCore-x"))
        with self.assertRaisesRegex(RuntimeError, "stable identity switch failed"):
            stable_identity.assume_stable_session()

    def tearDown(self):
        for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            stable_identity._ORIGINAL_ENV.get(k) is None and os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
