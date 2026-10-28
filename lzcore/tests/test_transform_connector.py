"""create_target_connector: a fresh connector per run, a stable token, and the console approval link."""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_ops  # noqa: E402
from test_transform_pending import WS, FakeTransform, _Case  # noqa: E402

TYPE = "vmware_migration|infra_provisioning|5"
ACCOUNT = "111122223333"


class ConnectorTransform(FakeTransform):
    """FakeTransform plus connector operations."""

    def __init__(self, existing=None, status="PENDING", account=ACCOUNT, **kw):
        super().__init__(**kw)
        self.status, self.account = status, account
        self.created = []
        self.existing = dict(existing or {})  # connectors other runs/people made; must never be touched

    async def call(self, operation, request):
        body = request.model_dump(by_alias=True, exclude_none=True) if hasattr(request, "model_dump") else dict(request or {})
        if operation == "CreateConnector":
            self.calls.append((operation, body))
            self.created.append(body)
            return {"connectorId": "new-1"}
        if operation == "GetConnector":
            self.calls.append((operation, body))
            return {"connectorId": body["connectorId"], "connectorType": TYPE,
                    "accountConnection": {"awsAccountConnection": {"accountId": self.account, "status": self.status}}}
        if operation == "ListConnectors":
            raise AssertionError("an existing connector must never be looked up or reused")
        return await super().call(operation, request)


class CreateTargetConnector(_Case):
    def create(self, fake, run_id="run-1234567890", region="eu-west-1", **kw):
        self.install(fake)
        return transform_ops.create_target_connector(run_id=run_id, connector_type=TYPE, account_id=ACCOUNT,
                                                     region=region, workspace=WS, **kw)

    def test_link_uses_the_transform_region_not_the_target_region(self):
        fake = ConnectorTransform()
        out = self.create(fake, region="eu-west-1")
        self.assertEqual((out["status"], out["connectorId"]), ("PENDING", "new-1"))
        # TRANSFORM_REGION is us-east-1 in the test environment; the target Region is eu-west-1.
        self.assertTrue(out["verificationLink"].startswith("https://us-east-1.console.aws.amazon.com/transform/connector/new-1/"))
        self.assertEqual(fake.created[0]["targetRegions"], ["eu-west-1"])
        self.assertEqual(fake.created[0]["connectorName"], f"lz-agent-run-1234-{ACCOUNT}-eu-west-1")

    def test_token_is_stable_per_run_and_target_so_a_retry_returns_the_same_connector(self):
        a, b, other = ConnectorTransform(), ConnectorTransform(), ConnectorTransform()
        self.create(a); self.create(b); self.create(other, run_id="another-run-id")
        self.assertEqual(a.created[0]["idempotencyToken"], b.created[0]["idempotencyToken"])
        self.assertNotEqual(a.created[0]["idempotencyToken"], other.created[0]["idempotencyToken"])
        uuid.UUID(a.created[0]["idempotencyToken"])

    def test_no_connector_is_ever_looked_up_or_reused(self):
        fake = ConnectorTransform(existing={"c-active": {}})
        self.create(fake)
        self.assertNotIn("ListConnectors", fake.ops())

    def test_unexpected_account_or_status_raises(self):
        with self.assertRaisesRegex(RuntimeError, "expected account"):
            self.create(ConnectorTransform(account="999999999999"))
        with self.assertRaisesRegex(RuntimeError, "expected account"):
            self.create(ConnectorTransform(status="REJECTED"))

    def test_unsupported_connector_type_is_refused_before_any_call(self):
        fake = ConnectorTransform()
        self.install(fake)
        with self.assertRaisesRegex(RuntimeError, "only creates"):
            transform_ops.create_target_connector(run_id="r", connector_type="other|type|1", account_id=ACCOUNT,
                                                  region="eu-west-1", workspace=WS)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
