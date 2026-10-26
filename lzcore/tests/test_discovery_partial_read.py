"""collect_foundation: limitations only on real denials, ClientError-code AccessDenied detection,
and partial reads that can never reach a passing gap analysis (review findings #1, #20)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from lzcore.attestation import FoundationUnverifiable, gap_analysis  # noqa: E402
from lzcore.deploy_workflow import (  # noqa: E402
    collect_snapshot_and_gaps,
    evaluate_deployment_outcome,
    run_foundation_assessment,
)
from lzcore.discovery import _is_org_access_denied, classify_foundation, collect_foundation  # noqa: E402

MGMT = "111111111111"
DELEGATED = "222222222222"
ROOT = "r-ab12"
OU_ID = "ou-ab12-11111111"

SCOPE = {
    "ous": [{"name": "Workloads"}],
    "accounts": [{"name": "mgmt"}, {"name": "acme-workload-dev"}],
}


class _StubSession:
    """Explicit per-test fixture: hands collect_foundation pre-stubbed botocore clients."""

    def __init__(self, clients):
        self._clients = clients

    def client(self, name):
        return self._clients[name]


class _Env:
    def __init__(self, caller=DELEGATED):
        real = boto3.Session(
            aws_access_key_id="testing", aws_secret_access_key="testing", region_name="us-east-1"
        )
        self.clients = {n: real.client(n) for n in ("sts", "organizations", "controltower")}
        self.stubs = {n: Stubber(c) for n, c in self.clients.items()}
        self.session = _StubSession(self.clients)
        self.stubs["sts"].add_response(
            "get_caller_identity",
            {"Account": caller, "Arn": f"arn:aws:iam::{caller}:role/Discover", "UserId": "AROAEXAMPLE"},
        )

    @property
    def org(self):
        return self.stubs["organizations"]

    def describe_org(self):
        self.org.add_response(
            "describe_organization",
            {"Organization": {"Id": "o-abcdefghij", "MasterAccountId": MGMT, "FeatureSet": "ALL"}},
        )

    def roots(self, roots=None):
        self.org.add_response("list_roots", {"Roots": [{"Id": ROOT, "Name": "Root"}] if roots is None else roots})

    def ous(self):
        self.org.add_response(
            "list_organizational_units_for_parent",
            {"OrganizationalUnits": [{"Id": OU_ID, "Name": "Workloads"}]},
            {"ParentId": ROOT},
        )
        self.org.add_response("list_organizational_units_for_parent", {"OrganizationalUnits": []}, {"ParentId": OU_ID})

    def accounts(self, names=(("mgmt", MGMT), ("acme-workload-dev", "333333333333"))):
        self.org.add_response(
            "list_accounts",
            {"Accounts": [{"Id": i, "Name": n, "Email": f"{n}@example.com", "Status": "ACTIVE"} for n, i in names]},
        )

    def policies(self):
        self.org.add_response(
            "list_policies",
            {"Policies": [{"Id": "p-FullAWSAccess", "Name": "FullAWSAccess", "AwsManaged": True}]},
            {"Filter": "SERVICE_CONTROL_POLICY"},
        )
        self.org.add_response(
            "list_targets_for_policy",
            {"Targets": [{"TargetId": ROOT, "Name": "Root", "Type": "ROOT"}]},
            {"PolicyId": "p-FullAWSAccess"},
        )

    def control_tower(self, landing_zones=True):
        lzs = [{"arn": f"arn:aws:controltower:us-east-1:{MGMT}:landingzone/ABC"}] if landing_zones else []
        self.stubs["controltower"].add_response("list_landing_zones", {"landingZones": lzs})

    def full_tree(self):
        self.describe_org()
        self.roots()
        self.ous()
        self.accounts()
        self.policies()
        self.control_tower()

    def __enter__(self):
        for s in self.stubs.values():
            s.activate()
        return self

    def __exit__(self, *exc):
        for s in self.stubs.values():
            s.deactivate()
        return False

    def assert_consumed(self):
        for s in self.stubs.values():
            s.assert_no_pending_responses()


class DelegatedAdminCompleteReadTests(unittest.TestCase):
    def test_delegated_admin_full_read_has_no_limitations(self):
        env = _Env(caller=DELEGATED)
        env.full_tree()
        with env:
            snap = collect_foundation(env.session)
        env.assert_consumed()
        self.assertNotIn("discoveryLimitations", snap)
        self.assertFalse(snap["organization"]["callerIsManagementAccount"])
        self.assertEqual([o["path"] for o in snap["organizationalUnits"]], ["Workloads"])
        self.assertEqual({a["name"] for a in snap["accounts"]}, {"mgmt", "acme-workload-dev"})
        self.assertEqual(snap["serviceControlPolicies"][0]["targetCount"], 1)
        self.assertEqual(len(snap["controlTower"]["landingZones"]), 1)
        self.assertEqual(classify_foundation(snap)["classification"], "brownfield")

        gaps = gap_analysis(SCOPE, snap)
        self.assertEqual(gaps["missingOus"], [])
        self.assertEqual(gaps["missingAccountsByName"], [])
        overall, _ = evaluate_deployment_outcome(
            pre_gaps=gaps, post_gaps=gaps, plan={"strategy": "no_changes_needed"}, transform_deploy_status="SUCCEEDED"
        )
        self.assertEqual(overall, "pass")

    def test_complete_read_reports_real_missing_names(self):
        env = _Env(caller=MGMT)
        env.describe_org()
        env.roots()
        env.org.add_response("list_organizational_units_for_parent", {"OrganizationalUnits": []}, {"ParentId": ROOT})
        env.accounts(names=(("mgmt", MGMT),))
        env.policies()
        env.control_tower(landing_zones=False)
        with env:
            snapshot, gaps = collect_snapshot_and_gaps(SCOPE, env.session)
        self.assertNotIn("discoveryLimitations", snapshot)
        self.assertEqual(gaps["missingOus"], ["Workloads"])
        self.assertEqual(gaps["missingAccountsByName"], ["acme-workload-dev"])


class PartialReadRefusedTests(unittest.TestCase):
    def _denied_list_accounts_env(self, caller=DELEGATED):
        env = _Env(caller=caller)
        env.describe_org()
        env.roots()
        env.ous()
        env.org.add_client_error(
            "list_accounts", service_error_code="AccessDeniedException", service_message="not authorized", http_status_code=400
        )
        env.policies()
        env.control_tower()
        return env

    def test_access_denied_on_list_accounts_is_recorded_with_member_account(self):
        env = self._denied_list_accounts_env()
        with env:
            snap = collect_foundation(env.session)
        env.assert_consumed()
        codes = [lim["code"] for lim in snap["discoveryLimitations"]]
        self.assertEqual(codes, ["organizations:ListAccounts", "member_account"])
        self.assertEqual(classify_foundation(snap)["classification"], "unknown")

    def test_access_denied_on_list_accounts_management_caller_has_no_member_account_entry(self):
        env = self._denied_list_accounts_env(caller=MGMT)
        with env:
            snap = collect_foundation(env.session)
        self.assertEqual([lim["code"] for lim in snap["discoveryLimitations"]], ["organizations:ListAccounts"])

    def test_gap_analysis_raises_instead_of_empty_gaps(self):
        env = self._denied_list_accounts_env()
        with env:
            snap = collect_foundation(env.session)
        with self.assertRaises(FoundationUnverifiable) as ctx:
            gap_analysis(SCOPE, snap)
        msg = str(ctx.exception)
        self.assertIn("organizations:ListAccounts", msg)
        self.assertIn("delegated administrator", msg)
        self.assertEqual(ctx.exception.limitations, snap["discoveryLimitations"])

    def test_pre_discover_path_raises(self):
        env = self._denied_list_accounts_env()
        with env, self.assertRaises(FoundationUnverifiable):
            collect_snapshot_and_gaps(SCOPE, env.session)

    def test_post_discover_path_raises(self):
        env = self._denied_list_accounts_env()
        with env, self.assertRaises(FoundationUnverifiable):
            run_foundation_assessment(SCOPE, env.session)

    def test_empty_roots_is_a_limitation(self):
        env = _Env(caller=MGMT)
        env.describe_org()
        env.roots(roots=[])
        env.accounts()
        env.policies()
        env.control_tower()
        with env:
            snap = collect_foundation(env.session)
        self.assertEqual([lim["code"] for lim in snap["discoveryLimitations"]], ["organizations:ListRoots"])
        with self.assertRaises(FoundationUnverifiable):
            gap_analysis(SCOPE, snap)

    def test_organizations_not_in_use_raises_named_error(self):
        env = _Env(caller=DELEGATED)
        env.org.add_client_error(
            "describe_organization",
            service_error_code="AWSOrganizationsNotInUseException",
            service_message="Your account is not a member of an organization.",
            http_status_code=400,
        )
        with env, self.assertRaises(RuntimeError) as ctx:
            collect_snapshot_and_gaps(SCOPE, env.session)
        self.assertIn("has no AWS Organization", str(ctx.exception))

    def test_control_tower_unreadable_is_not_greenfield(self):
        env = _Env(caller=MGMT)
        env.describe_org()
        env.roots()
        env.org.add_response("list_organizational_units_for_parent", {"OrganizationalUnits": []}, {"ParentId": ROOT})
        env.accounts(names=(("mgmt", MGMT),))
        env.policies()
        env.stubs["controltower"].add_client_error(
            "list_landing_zones", service_error_code="AccessDeniedException", http_status_code=400
        )
        with env:
            snap = collect_foundation(env.session)
        self.assertIn("error", snap["controlTower"])
        self.assertEqual(classify_foundation(snap)["classification"], "unknown")


class AccessDeniedDetectionTests(unittest.TestCase):
    @staticmethod
    def _client_error(code, message="boom"):
        return ClientError({"Error": {"Code": code, "Message": message}}, "ListAccounts")

    def test_access_denied_codes(self):
        self.assertTrue(_is_org_access_denied(self._client_error("AccessDeniedException")))
        self.assertTrue(_is_org_access_denied(self._client_error("AccessDenied")))

    def test_no_substring_matching(self):
        self.assertFalse(_is_org_access_denied(Exception("AccessDenied: not authorized")))
        self.assertFalse(_is_org_access_denied(self._client_error("ServiceException", "AccessDenied upstream")))
        self.assertFalse(_is_org_access_denied(self._client_error("TooManyRequestsException")))

    def test_non_access_denied_client_error_reraises(self):
        for code in ("TooManyRequestsException", "ServiceException"):
            with self.subTest(code=code):
                env = _Env(caller=MGMT)
                env.describe_org()
                env.roots()
                env.ous()
                env.org.add_client_error(
                    "list_accounts",
                    service_error_code=code,
                    service_message="AccessDenied appears in this message but the code is not AccessDenied",
                    http_status_code=400,
                )
                with env, self.assertRaises(ClientError) as ctx:
                    collect_foundation(env.session)
                self.assertEqual(ctx.exception.response["Error"]["Code"], code)

    def test_non_access_denied_in_ou_walk_reraises(self):
        env = _Env(caller=MGMT)
        env.describe_org()
        env.roots()
        env.org.add_client_error(
            "list_organizational_units_for_parent", service_error_code="ParentNotFoundException", http_status_code=400
        )
        with env, self.assertRaises(ClientError):
            collect_foundation(env.session)


if __name__ == "__main__":
    unittest.main()
