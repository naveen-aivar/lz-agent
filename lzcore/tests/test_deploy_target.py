import json
import unittest
from unittest import mock

from lzcore.aws_target_session import (
    normalize_deploy_target,
    parse_role_arn,
    public_deploy_target,
    session_for_deploy_target,
)
from lzcore.deploy_target_api import (
    credentials_key,
    delete_deploy_target_credentials,
    parse_deploy_target_from_request,
    verify_deploy_target_credentials,
)

ACCOUNT = "123456789012"
OTHER = "210987654321"
DEPLOY_ID = "0123456789abcdef0123456789abcdef"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/IngramLandingZoneDeploy"


class DeployTargetTests(unittest.TestCase):
    def test_platform_default(self):
        self.assertIsNone(parse_deploy_target_from_request({}, deploy_id=DEPLOY_ID))

    def test_role_target(self):
        dt = parse_deploy_target_from_request(
            {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE, "externalId": "abc"}},
            deploy_id=DEPLOY_ID,
        )
        self.assertEqual(dt, {"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE, "externalId": "abc"})

    def test_role_target_requires_external_id(self):
        for ext in (None, "", "   "):
            with self.subTest(ext=ext), self.assertRaises(ValueError) as cm:
                parse_deploy_target_from_request(
                    {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE, "externalId": ext}},
                    deploy_id=DEPLOY_ID,
                )
            self.assertIn("externalId is required", str(cm.exception))

    def test_keys_stored_outside_runs_prefix(self):
        stored = {}
        dt = parse_deploy_target_from_request(
            {"deployTarget": {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"}},
            deploy_id=DEPLOY_ID,
            put_credentials=lambda k, p: stored.__setitem__(k, p),
        )
        key = f"deploy-target-credentials/{DEPLOY_ID}.json"
        self.assertEqual(dt, {"mode": "keys", "accountId": ACCOUNT, "credentialsKey": key})
        self.assertEqual(list(stored), [key])
        self.assertEqual(json.loads(stored[key]), {"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"})

    def test_credentials_key_rejects_non_run_ids(self):
        for bad in ("", "abc123", "../x", DEPLOY_ID.upper()):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                credentials_key(bad)

    def test_normalize_rejects_mismatched_role_account(self):
        with self.assertRaises(ValueError) as cm:
            normalize_deploy_target(
                {"mode": "role", "accountId": ACCOUNT, "roleArn": f"arn:aws:iam::{OTHER}:role/x", "externalId": "e"}
            )
        self.assertIn(OTHER, str(cm.exception))

    def test_role_account_compared_exactly_not_by_substring(self):
        # Old check: `account_id in role_arn`. The account id appearing in the role *name* must not pass.
        arn = f"arn:aws:iam::{OTHER}:role/deploy-{ACCOUNT}"
        with self.assertRaises(ValueError):
            normalize_deploy_target({"mode": "role", "accountId": ACCOUNT, "roleArn": arn, "externalId": "e"})

    def test_parse_role_arn(self):
        self.assertEqual(parse_role_arn(ROLE), ("aws", ACCOUNT, "role/IngramLandingZoneDeploy"))
        self.assertEqual(
            parse_role_arn(f"arn:aws-us-gov:iam::{ACCOUNT}:role/path/to/R").partition, "aws-us-gov"
        )
        for bad in (
            "",
            f"arn:aws:iam::{ACCOUNT}:user/bob",
            f"arn:aws:sts::{ACCOUNT}:assumed-role/x/y",
            f"arn:aws:iam:us-east-1:{ACCOUNT}:role/x",
            f"arn:aws:iam::12345:role/x",
            f"arn:evil:iam::{ACCOUNT}:role/x",
            f"arn:aws:iam::{ACCOUNT}:role/",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_role_arn(bad)

    def test_public_view_has_no_secrets_or_pointers(self):
        role = {"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE, "externalId": "e"}
        keys = {"mode": "keys", "accountId": ACCOUNT, "credentialsKey": credentials_key(DEPLOY_ID)}
        self.assertEqual(public_deploy_target(role), {"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE})
        self.assertEqual(public_deploy_target(keys), {"mode": "keys", "accountId": ACCOUNT})
        self.assertEqual(public_deploy_target(None), {"mode": "platform"})

    def test_verify_requires_fields(self):
        r = verify_deploy_target_credentials({})
        self.assertFalse(r["ok"])
        self.assertIn("deployTarget", r["error"])


class _FakeSession:
    def __init__(self, account, org_error_code=None):
        self.account, self.org_error_code = account, org_error_code

    def client(self, name):
        from botocore.exceptions import ClientError

        outer = self

        class _C:
            def get_caller_identity(self):
                return {"Account": outer.account, "Arn": f"arn:aws:iam::{outer.account}:user/test"}

            def describe_organization(self):
                if outer.org_error_code:
                    raise ClientError({"Error": {"Code": outer.org_error_code, "Message": "boom"}}, "DescribeOrganization")
                return {"Organization": {"Id": "o-test", "MasterAccountId": outer.account}}

        return _C()


class VerifyProbeTests(unittest.TestCase):
    BODY = {"deployTarget": {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "s"}}

    def _verify(self, org_error_code):
        with mock.patch("boto3.Session", lambda **kw: _FakeSession(ACCOUNT, org_error_code)):
            return verify_deploy_target_credentials(self.BODY)

    def test_enabled_is_ok(self):
        r = self._verify(None)
        self.assertTrue(r["ok"])
        self.assertEqual(r["organizations"]["status"], "enabled")

    def test_probe_error_is_not_ok_and_names_the_error(self):
        r = self._verify("ServiceUnavailableException")
        self.assertFalse(r["ok"])
        self.assertEqual(r["organizations"]["status"], "error")
        self.assertIn("ServiceUnavailableException", r["error"])

    def test_not_in_use_and_access_denied_are_warnings(self):
        for code, status in (("AWSOrganizationsNotInUseException", "not_enabled"), ("AccessDeniedException", "access_denied")):
            with self.subTest(code=code):
                r = self._verify(code)
                self.assertTrue(r["ok"])
                self.assertEqual(r["organizations"]["status"], status)
                self.assertTrue(r["warnings"])

    def test_role_mode_without_external_id_is_rejected_before_assume_role(self):
        with mock.patch("boto3.client", side_effect=AssertionError("must not call STS")):
            r = verify_deploy_target_credentials(
                {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE}}
            )
        self.assertFalse(r["ok"])
        self.assertIn("externalId is required", r["error"])


class SessionForDeployTargetTests(unittest.TestCase):
    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError) as cm:
            session_for_deploy_target({"mode": "magic", "accountId": ACCOUNT})
        self.assertIn("magic", str(cm.exception))

    def test_keys_mode_account_mismatch_raises(self):
        creds = json.dumps({"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "s"})
        with mock.patch("boto3.Session", lambda **kw: _FakeSession(OTHER)):
            with self.assertRaises(RuntimeError):
                session_for_deploy_target(
                    {"mode": "keys", "accountId": ACCOUNT, "credentialsKey": credentials_key(DEPLOY_ID)},
                    read_credentials=lambda k: creds,
                )

    def test_role_mode_requires_external_id(self):
        with mock.patch("boto3.client", side_effect=AssertionError("must not call STS")):
            with self.assertRaises(ValueError):
                session_for_deploy_target({"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE})

    def test_role_mode_passes_external_id(self):
        calls = {}

        class _Sts:
            def assume_role(self, **kw):
                calls.update(kw)
                return {"Credentials": {"AccessKeyId": "ASIA", "SecretAccessKey": "s", "SessionToken": "t"}}

        with mock.patch("boto3.client", lambda name: _Sts()), mock.patch("boto3.Session", lambda **kw: _FakeSession(ACCOUNT)):
            session_for_deploy_target({"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE, "externalId": "ext-1"})
        self.assertEqual(calls["ExternalId"], "ext-1")
        self.assertEqual(calls["RoleArn"], ROLE)


class _FakeS3:
    def __init__(self, versions=(), markers=(), delete_errors=()):
        self.versions, self.markers, self.delete_errors = list(versions), list(markers), list(delete_errors)
        self.deleted = []

    def list_object_versions(self, **kw):
        assert kw["Prefix"].startswith("deploy-target-credentials/")
        return {"Versions": self.versions, "DeleteMarkers": self.markers, "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        self.deleted.extend(Delete["Objects"])
        return {"Errors": self.delete_errors}


class DeleteCredentialsTests(unittest.TestCase):
    KEY = f"deploy-target-credentials/{DEPLOY_ID}.json"

    def test_deletes_every_version_and_marker_of_the_exact_key(self):
        s3 = _FakeS3(
            versions=[{"Key": self.KEY, "VersionId": "v1"}, {"Key": self.KEY, "VersionId": "v2"},
                      {"Key": self.KEY + ".bak", "VersionId": "other"}],
            markers=[{"Key": self.KEY, "VersionId": "m1"}],
        )
        self.assertEqual(delete_deploy_target_credentials(s3, "bucket", self.KEY), 3)
        self.assertEqual({o["VersionId"] for o in s3.deleted}, {"v1", "v2", "m1"})

    def test_nothing_stored_is_zero(self):
        self.assertEqual(delete_deploy_target_credentials(_FakeS3(), "bucket", self.KEY), 0)

    def test_per_object_errors_raise(self):
        s3 = _FakeS3(versions=[{"Key": self.KEY, "VersionId": "v1"}],
                     delete_errors=[{"VersionId": "v1", "Code": "AccessDenied", "Message": "no"}])
        with self.assertRaises(RuntimeError) as cm:
            delete_deploy_target_credentials(s3, "bucket", self.KEY)
        self.assertIn("AccessDenied", str(cm.exception))

    def test_refuses_keys_outside_the_credentials_prefix(self):
        with self.assertRaises(ValueError):
            delete_deploy_target_credentials(_FakeS3(), "bucket", f"runs/{DEPLOY_ID}/scope.json")


if __name__ == "__main__":
    unittest.main()
