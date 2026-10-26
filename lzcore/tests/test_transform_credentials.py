"""lzcore/transform_credentials.py: explicit Transform-role credentials (contract C6).

Every fixture is installed per test: env via mock.patch.dict, the platform base session via
mock.patch.object. Nothing here can reach AWS.
"""
from __future__ import annotations

import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_credentials as tc  # noqa: E402

ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"
PLATFORM_ENV = {"AWS_ACCESS_KEY_ID": "AKIAPLATFORM", "AWS_SECRET_ACCESS_KEY": "p", "AWS_SESSION_TOKEN": "pt"}


def _utc(minutes: int) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)


class FakeSts:
    """Scripted STS: each assume_role returns the next (access key, expiry minutes)."""

    def __init__(self, script=(("ASIATRANSFORM1", 60),), error=None):
        self.script = list(script)
        self.error = error
        self.calls = []

    def assume_role(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        key, minutes = self.script.pop(0)
        return {"Credentials": {"AccessKeyId": key, "SecretAccessKey": "s", "SessionToken": "t", "Expiration": _utc(minutes)}}


class FakeBase:
    def __init__(self, sts):
        self._sts = sts

    def client(self, name):
        assert name == "sts", name
        return self._sts


class NoNetworkBase:
    def client(self, name):
        raise AssertionError(f"unexpected AWS client {name!r}: this code path must not call AWS")


class _Base(unittest.TestCase):
    env: dict = {}

    def setUp(self):
        for patcher in (
            mock.patch.dict(os.environ, {"TRANSFORM_ROLE_ARN": ROLE, **PLATFORM_ENV, **self.env}),
            mock.patch.dict(tc._refreshable, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("TRANSFORM_EXTERNAL_ID", None)

    def install_base(self, base):
        p = mock.patch.object(tc, "_BASE_SESSION", base)
        p.start()
        self.addCleanup(p.stop)


class PrincipalArnTests(_Base):
    def setUp(self):
        super().setUp()
        self.install_base(NoNetworkBase())

    def test_principal_is_assumed_role_arn_with_fixed_session(self):
        self.assertEqual(
            tc.transform_principal_arn(),
            "arn:aws:sts::111122223333:assumed-role/IngramLandingZoneTransform/ingram-lz-agent",
        )

    def test_role_path_is_dropped_and_partition_kept(self):
        os.environ["TRANSFORM_ROLE_ARN"] = "arn:aws-cn:iam::111122223333:role/platform/team/TransformRole"
        self.assertEqual(
            tc.transform_principal_arn(),
            "arn:aws-cn:sts::111122223333:assumed-role/TransformRole/ingram-lz-agent",
        )

    def test_invalid_role_arns_raise(self):
        for bad in (
            "IngramLandingZoneTransform",
            "arn:aws:sts::111122223333:assumed-role/X/y",
            "arn:aws:iam::12345:role/X",
            "arn:aws:iam::111122223333:user/X",
            "arn:aws:iam:us-east-1:111122223333:role/X",
            "arn:aws:iam::111122223333:role/",
        ):
            with self.subTest(arn=bad):
                os.environ["TRANSFORM_ROLE_ARN"] = bad
                with self.assertRaises(ValueError):
                    tc.transform_principal_arn()

    def test_missing_role_arn_raises(self):
        os.environ.pop("TRANSFORM_ROLE_ARN")
        with self.assertRaisesRegex(RuntimeError, "TRANSFORM_ROLE_ARN is not set"):
            tc.transform_principal_arn()


class AssumeRoleTests(_Base):
    def test_assume_uses_fixed_session_name_and_external_id(self):
        sts = FakeSts()
        self.install_base(FakeBase(sts))
        os.environ["TRANSFORM_EXTERNAL_ID"] = "ext-1"
        tc.assume_transform_role()
        self.assertEqual(sts.calls[0]["RoleArn"], ROLE)
        self.assertEqual(sts.calls[0]["RoleSessionName"], "ingram-lz-agent")
        self.assertEqual(sts.calls[0]["ExternalId"], "ext-1")

    def test_no_external_id_when_unset(self):
        sts = FakeSts()
        self.install_base(FakeBase(sts))
        tc.assume_transform_role()
        self.assertNotIn("ExternalId", sts.calls[0])

    def test_assume_failure_names_role_and_fix(self):
        self.install_base(FakeBase(FakeSts(error=Exception("AccessDenied"))))
        with self.assertRaisesRegex(RuntimeError, "cannot assume Transform role .*IngramLandingZoneTransform.*trust policy"):
            tc.transform_botocore_credentials()


class RefreshableCredentialsTests(_Base):
    def test_credentials_are_explicit_and_env_is_untouched(self):
        self.install_base(FakeBase(FakeSts()))
        before = dict(os.environ)
        creds = tc.transform_botocore_credentials()
        self.assertEqual(creds.get_frozen_credentials().access_key, "ASIATRANSFORM1")
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "AKIAPLATFORM")

    def test_cached_per_process(self):
        sts = FakeSts()
        self.install_base(FakeBase(sts))
        self.assertIs(tc.transform_botocore_credentials(), tc.transform_botocore_credentials())
        self.assertEqual(len(sts.calls), 1)

    def test_refreshes_before_expiry(self):
        # First credentials expire in 5 minutes (inside botocore's mandatory refresh window), so
        # the next signing read must re-assume rather than sign with near-expired credentials.
        sts = FakeSts(script=(("ASIAOLD", 5), ("ASIANEW", 60)))
        self.install_base(FakeBase(sts))
        creds = tc.transform_botocore_credentials()
        self.assertEqual(creds.get_frozen_credentials().access_key, "ASIANEW")
        self.assertEqual(len(sts.calls), 2)
        self.assertEqual(sts.calls[1]["RoleSessionName"], "ingram-lz-agent")


class CredentialProcessPayloadTests(_Base):
    def test_payload_format(self):
        base = FakeBase(FakeSts())
        payload = tc.credential_process_payload(base)
        self.assertEqual(set(payload), {"Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"})
        self.assertEqual(payload["Version"], 1)
        self.assertEqual(payload["AccessKeyId"], "ASIATRANSFORM1")
        self.assertRegex(payload["Expiration"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


if __name__ == "__main__":
    unittest.main()
