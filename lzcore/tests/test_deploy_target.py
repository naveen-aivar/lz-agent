import unittest

from lzcore.aws_target_session import normalize_deploy_target
from lzcore.deploy_target_api import parse_deploy_target_from_request, verify_deploy_target_credentials


class DeployTargetTests(unittest.TestCase):
    def test_platform_default(self):
        self.assertIsNone(parse_deploy_target_from_request({}, deploy_id="x"))

    def test_role_target(self):
        dt = parse_deploy_target_from_request(
            {
                "deployTarget": {
                    "accountId": "556880010183",
                    "roleArn": "arn:aws:iam::556880010183:role/LzDeploy",
                    "externalId": "abc",
                }
            },
            deploy_id="deadbeef",
        )
        self.assertEqual(dt["mode"], "role")
        self.assertEqual(dt["accountId"], "556880010183")
        self.assertEqual(dt["externalId"], "abc")

    def test_keys_stored(self):
        stored = {}

        def put(key, payload):
            stored[key] = payload

        dt = parse_deploy_target_from_request(
            {
                "deployTarget": {
                    "accountId": "556880010183",
                    "accessKeyId": "AKIAEXAMPLE",
                    "secretAccessKey": "secret",
                }
            },
            deploy_id="abc123",
            put_credentials=put,
        )
        self.assertEqual(dt["mode"], "keys")
        self.assertTrue(stored["runs/abc123/deployment/target-credentials.json"])

    def test_normalize_rejects_mismatched_role_account(self):
        with self.assertRaises(ValueError):
            normalize_deploy_target(
                {
                    "mode": "role",
                    "accountId": "111111111111",
                    "roleArn": "arn:aws:iam::222222222222:role/x",
                }
            )

    def test_verify_requires_fields(self):
        r = verify_deploy_target_credentials({})
        self.assertFalse(r["ok"])
        self.assertIn("deployTarget", r["error"])


if __name__ == "__main__":
    unittest.main()
