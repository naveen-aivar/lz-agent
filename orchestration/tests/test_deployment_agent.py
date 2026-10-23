import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore.attestation import build_deployment_report, gap_analysis  # noqa: E402
from lzcore.deploy_artifacts import (  # noqa: E402
    DEPLOYMENT_FILE_NAMES,
    MAX_DEPLOY_CONTINUE_CYCLES,
    deployment_artifact_keys,
)
from lzcore.deploy_workflow import evaluate_deployment_outcome, should_deliver_design_bundles  # noqa: E402
from lzcore.discovery import classify_foundation  # noqa: E402
from lzcore.foundation_assessment import build_foundation_assessment, validate_agent_classification  # noqa: E402
from lzcore.iac_plan import suggest_changes, validate as validate_plan  # noqa: E402


SCOPE = {
    "customer": {"orgName": "Acme"},
    "regions": {"home": "eu-west-1"},
    "ous": [{"name": "Workloads"}, {"name": "Shared"}],
    "accounts": [{"name": "acme-workload-dev"}, {"name": "acme-log-archive"}],
    "scps": [{"id": "deny-root-user"}],
}


class DeploymentAgentTests(unittest.TestCase):
    def test_deployment_artifact_contract(self):
        keys = deployment_artifact_keys("abc123")
        self.assertEqual(len(keys), len(DEPLOYMENT_FILE_NAMES))
        self.assertTrue(any(k.endswith("iac-manifest.json") for k in keys))
        self.assertTrue(keys[-1].endswith("transform-poll-deploy.json"))

    def test_deploy_sfn_continue_limit_matches_constant(self):
        asl_path = Path(__file__).resolve().parents[1] / "deployment.asl.json"
        doc = json.loads(asl_path.read_text(encoding="utf-8"))
        choice = doc["States"]["ContinueLimitChoice"]
        threshold = choice["Choices"][0]["NumericGreaterThanEquals"]
        self.assertEqual(threshold, MAX_DEPLOY_CONTINUE_CYCLES)

    def test_transform_deploy_success_statuses(self):
        aligned = {"missingOus": [], "missingAccountsByName": []}
        gaps = gap_analysis(SCOPE, {"organizationalUnits": [], "accounts": []})
        for status in ("SUCCEEDED", "COMPLETED", "SUCCESS"):
            overall, _ = evaluate_deployment_outcome(
                pre_gaps=gaps,
                post_gaps=aligned,
                plan={"strategy": "apply_design_stacks"},
                transform_deploy_status=status,
            )
            self.assertEqual(overall, "pass", msg=status)

    def test_greenfield_classification(self):
        snap = {
            "organizationalUnits": [],
            "accounts": [{"id": "111", "name": "mgmt", "isManagementAccount": True}],
            "controlTower": {"landingZones": []},
        }
        c = classify_foundation(snap)
        self.assertEqual(c["classification"], "greenfield")

    def test_brownfield_with_ou(self):
        snap = {
            "organizationalUnits": [{"name": "Legacy", "path": "Legacy"}],
            "accounts": [{"id": "111", "name": "mgmt", "isManagementAccount": True}],
            "controlTower": {"landingZones": []},
        }
        self.assertEqual(classify_foundation(snap)["classification"], "brownfield")

    def test_gap_analysis_pass_and_fail(self):
        live = {
            "organizationalUnits": [{"name": "Workloads"}, {"name": "Shared"}],
            "accounts": [{"name": "acme-workload-dev"}, {"name": "acme-log-archive"}, {"name": "mgmt"}],
        }
        gaps = gap_analysis(SCOPE, live)
        self.assertEqual(gaps["missingOus"], [])
        self.assertEqual(gaps["missingAccountsByName"], [])

        sparse = {"organizationalUnits": [], "accounts": [{"name": "mgmt"}]}
        gaps2 = gap_analysis(SCOPE, sparse)
        self.assertIn("Workloads", gaps2["missingOus"])
        self.assertIn("acme-workload-dev", gaps2["missingAccountsByName"])

    def test_deployment_report_shape(self):
        pre_gaps = gap_analysis(SCOPE, {"organizationalUnits": [], "accounts": []})
        post_gaps = gap_analysis(
            SCOPE,
            {
                "organizationalUnits": [{"name": "Workloads"}, {"name": "Shared"}],
                "accounts": [{"name": "acme-workload-dev"}, {"name": "acme-log-archive"}],
            },
        )
        report = build_deployment_report(
            run_id="d1",
            design_run_id="design1",
            scope=SCOPE,
            pre_snapshot={"organizationalUnits": [], "accounts": [], "serviceControlPolicies": [], "controlTower": {}},
            pre_classification={"classification": "greenfield", "signals": {"accountCount": 1}},
            post_snapshot={
                "organizationalUnits": [{"name": "Workloads"}, {"name": "Shared"}],
                "accounts": [{"name": "acme-workload-dev"}, {"name": "acme-log-archive"}],
                "serviceControlPolicies": [],
                "controlTower": {},
            },
            post_classification={"classification": "brownfield", "signals": {"accountCount": 3}},
            pre_gaps=pre_gaps,
            post_gaps=post_gaps,
            overall="pass",
            outcome_reasons=["aligned"],
        )
        self.assertEqual(report["overall"], "pass")
        self.assertEqual(report["gaps"]["postDeploy"]["missingOus"], [])

    def test_evaluate_deployment_outcome(self):
        aligned = {"missingOus": [], "missingAccountsByName": []}
        gaps = gap_analysis(SCOPE, {"organizationalUnits": [], "accounts": []})
        overall, _ = evaluate_deployment_outcome(
            pre_gaps=gaps,
            post_gaps=aligned,
            plan={"strategy": "apply_design_stacks"},
            transform_deploy_status="SUCCEEDED",
        )
        self.assertEqual(overall, "pass")
        fail, reasons = evaluate_deployment_outcome(
            pre_gaps=gaps,
            post_gaps=gaps,
            plan={"strategy": "apply_design_stacks"},
            transform_deploy_status="SUCCEEDED",
        )
        self.assertEqual(fail, "fail")
        self.assertTrue(reasons)

    def test_should_deliver_bundles(self):
        self.assertFalse(should_deliver_design_bundles({"strategy": "no_changes_needed"}))
        self.assertTrue(should_deliver_design_bundles({"strategy": "partial_manual"}))

    def test_agent_classification_validation(self):
        ok, errs = validate_agent_classification(
            {"environment": "brownfield", "rationale": "OUs and member accounts exist.", "signals": {"ouCount": 2}}
        )
        self.assertEqual(errs, [])
        self.assertEqual(ok["environment"], "brownfield")
        _, errs = validate_agent_classification({"environment": "unknown", "rationale": "x"})
        self.assertTrue(errs)

    def test_brownfield_assessment_and_iac_plan(self):
        snapshot = {
            "organization": {"id": "o-abc", "featureSet": "ALL"},
            "organizationalUnits": [{"name": "Legacy", "path": "Legacy"}],
            "accounts": [
                {"name": "mgmt", "id": "111", "isManagementAccount": True},
                {"name": "old-workload", "id": "222", "isManagementAccount": False},
            ],
            "serviceControlPolicies": [{"id": "p1", "name": "FullAWSAccess"}],
            "controlTower": {"landingZones": [{"arn": "arn:lz", "status": "ACTIVE"}]},
        }
        classification = classify_foundation(snapshot)
        self.assertEqual(classification["classification"], "brownfield")
        gaps = gap_analysis(SCOPE, snapshot)
        self.assertIn("Workloads", gaps["missingOus"])
        self.assertIn("Legacy", gaps["extraOus"])

        assessment = build_foundation_assessment(
            scope=SCOPE,
            snapshot=snapshot,
            classification=classification,
            gaps=gaps,
        )
        self.assertEqual(assessment["environment"], "brownfield")
        self.assertTrue(assessment["notes"])

        suggested = suggest_changes(SCOPE, gaps)
        actions = {c["action"] for c in suggested}
        self.assertIn("create_ou", actions)
        self.assertIn("manual", actions)

    def test_suggest_and_validate_iac_plan(self):
        gaps = gap_analysis(SCOPE, {"organizationalUnits": [], "accounts": []})
        suggested = suggest_changes(SCOPE, gaps)
        self.assertTrue(any(c["action"] == "create_ou" for c in suggested))
        plan = {
            "schemaVersion": "1",
            "planType": "landing-zone-iac-reconciliation",
            "runId": "deploy1",
            "designRunId": "design1",
            "summary": "Close foundation gaps using design stacks.",
            "strategy": "apply_design_stacks",
            "deliverDesignBundles": True,
            "changes": suggested,
        }
        normalized, errors = validate_plan(plan, run_id="deploy1", design_run_id="design1")
        self.assertEqual(errors, [])
        self.assertTrue(normalized["deliverDesignBundles"])


if __name__ == "__main__":
    unittest.main()
