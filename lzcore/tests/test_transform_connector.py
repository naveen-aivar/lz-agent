"""ensure_target_connector: find/create the workspace connector and build its console approval link."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_ops  # noqa: E402
from test_transform_pending import WS, FakeTransform, _Case  # noqa: E402

TYPE = "vmware_migration|infra_provisioning|5"


class ConnectorTransform(FakeTransform):
    """FakeTransform plus connector operations. ``connectors`` maps id -> GetConnector body."""

    def __init__(self, connectors=None, **kw):
        super().__init__(**kw)
        self.connectors = dict(connectors or {})
        self.created = []

    async def call(self, operation, request):
        body = request.model_dump(by_alias=True, exclude_none=True) if hasattr(request, "model_dump") else dict(request or {})
        if operation == "ListConnectors":
            self.calls.append((operation, body))
            return {"connectors": [{"connectorId": i, "connectorType": c["connectorType"], "targetRegions": c["targetRegions"]}
                                   for i, c in self.connectors.items()]}
        if operation == "GetConnector":
            self.calls.append((operation, body))
            return self.connectors[body["connectorId"]]
        if operation == "CreateConnector":
            self.calls.append((operation, body))
            cid = f"new-{len(self.created) + 1}"
            self.created.append(body)
            self.connectors[cid] = {
                "connectorId": cid, "connectorType": body["connectorType"], "targetRegions": body["targetRegions"],
                "accountConnection": {"awsAccountConnection": {"accountId": body["accountConnectionRequest"]
                                                              ["awsAccountConnectionRequest"]["awsAccountId"], "status": "PENDING"}}}
            return {"connectorId": cid}
        return await super().call(operation, request)


def connector(cid, account, status, regions=("us-east-1",)):
    return {"connectorId": cid, "connectorType": TYPE, "targetRegions": list(regions),
            "accountConnection": {"awsAccountConnection": {"accountId": account, "status": status}}}


class EnsureTargetConnector(_Case):
    def ensure(self, fake, region="us-east-1"):
        self.install(fake)
        return transform_ops.ensure_target_connector(connector_type=TYPE, account_id="111122223333", region=region, workspace=WS)

    def test_new_connector_link_uses_the_transform_region_not_the_target_region(self):
        fake = ConnectorTransform()
        out = self.ensure(fake, region="eu-west-1")
        self.assertEqual((out["status"], out["created"], out["connectorId"]), ("PENDING", True, "new-1"))
        # TRANSFORM_REGION is us-east-1 in the test environment; the target Region is eu-west-1.
        self.assertTrue(out["verificationLink"].startswith("https://us-east-1.console.aws.amazon.com/transform/connector/new-1/"))
        self.assertEqual(fake.created[0]["targetRegions"], ["eu-west-1"])

    def test_active_connector_is_reused_before_a_pending_one(self):
        fake = ConnectorTransform({"c-pending": connector("c-pending", "111122223333", "PENDING"),
                                   "c-active": connector("c-active", "111122223333", "ACTIVE")})
        out = self.ensure(fake)
        self.assertEqual((out["connectorId"], out["status"], out["created"]), ("c-active", "ACTIVE", False))
        self.assertEqual(fake.created, [])

    def test_connector_for_another_account_or_region_is_not_reused(self):
        fake = ConnectorTransform({"c-other-acct": connector("c-other-acct", "999999999999", "ACTIVE"),
                                   "c-other-region": connector("c-other-region", "111122223333", "ACTIVE", ("ap-south-1",)),
                                   "c-rejected": connector("c-rejected", "111122223333", "REJECTED")})
        out = self.ensure(fake)
        self.assertTrue(out["created"])


if __name__ == "__main__":
    unittest.main()
