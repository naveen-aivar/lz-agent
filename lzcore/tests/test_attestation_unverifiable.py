"""Consumers of gap analysis refuse anything not computed from a complete Organizations read
(review finding #1): no "pass", no "foundation aligned", no "names match" no_op from unread data."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore.attestation import FoundationUnverifiable, gap_analysis, require_complete_gaps  # noqa: E402
from lzcore.deploy_workflow import evaluate_deployment_outcome  # noqa: E402
from lzcore.foundation_assessment import build_foundation_assessment  # noqa: E402
from lzcore.iac_plan import suggest_changes  # noqa: E402

SCOPE = {"ous": [{"name": "Workloads"}], "accounts": [{"name": "acme-workload-dev"}]}
LIMITATIONS = [
    {"code": "organizations:ListAccounts", "message": "AccessDeniedException: not authorized"},
    {"code": "member_account", "message": "caller is not the management account"},
]
# Shape gap_analysis wrote for partial reads before this fix; such artifacts may still be stored in S3.
LEGACY_INCOMPLETE = {
    "missingOus": [],
    "extraOus": [],
    "missingAccountsByName": [],
    "extraAccountsByName": [],
    "expectedScpIds": [],
    "incomplete": True,
}
COMPLETE = {"missingOus": [], "missingAccountsByName": [], "extraOus": [], "extraAccountsByName": []}


class GapAnalysisTests(unittest.TestCase):
    def test_limitations_raise_naming_failed_calls_and_fix(self):
        snap = {"organizationalUnits": [], "accounts": [], "discoveryLimitations": LIMITATIONS}
        with self.assertRaises(FoundationUnverifiable) as ctx:
            gap_analysis(SCOPE, snap)
        msg = str(ctx.exception)
        self.assertIn("organizations:ListAccounts", msg)
        self.assertIn("member_account", msg)
        self.assertIn("management account", msg)

    def test_snapshot_error_raises(self):
        with self.assertRaises(FoundationUnverifiable):
            gap_analysis(SCOPE, {"organizationalUnits": [], "accounts": [], "error": "DescribeOrganization failed"})

    def test_snapshot_without_tree_lists_raises(self):
        with self.assertRaises(FoundationUnverifiable):
            gap_analysis(SCOPE, {"organizationalUnits": []})

    def test_require_complete_gaps_rejects_missing_lists(self):
        for gaps in ({}, {"missingOus": []}, {"missingOus": None, "missingAccountsByName": []}):
            with self.subTest(gaps=gaps), self.assertRaises(FoundationUnverifiable):
                require_complete_gaps(gaps, "test")


class EvaluateDeploymentOutcomeTests(unittest.TestCase):
    def _evaluate(self, pre, post, strategy):
        return evaluate_deployment_outcome(
            pre_gaps=pre, post_gaps=post, plan={"strategy": strategy}, transform_deploy_status="SUCCEEDED"
        )

    def test_refuses_incomplete_post_gaps(self):
        for strategy in ("no_changes_needed", "apply_design_stacks", "partial_manual"):
            with self.subTest(strategy=strategy), self.assertRaises(FoundationUnverifiable) as ctx:
                self._evaluate(COMPLETE, LEGACY_INCOMPLETE, strategy)
            self.assertIn("post_gaps", str(ctx.exception))

    def test_refuses_incomplete_pre_gaps(self):
        with self.assertRaises(FoundationUnverifiable) as ctx:
            self._evaluate(LEGACY_INCOMPLETE, COMPLETE, "no_changes_needed")
        self.assertIn("pre_gaps", str(ctx.exception))

    def test_refuses_empty_post_gaps_dict(self):
        with self.assertRaises(FoundationUnverifiable):
            self._evaluate(COMPLETE, {}, "apply_design_stacks")

    def test_complete_aligned_still_passes(self):
        overall, reasons = self._evaluate(COMPLETE, COMPLETE, "apply_design_stacks")
        self.assertEqual(overall, "pass")
        self.assertEqual(reasons, ["Foundation aligned after Transform deploy"])


class SuggestChangesTests(unittest.TestCase):
    def test_refuses_incomplete(self):
        with self.assertRaises(FoundationUnverifiable) as ctx:
            suggest_changes(SCOPE, LEGACY_INCOMPLETE)
        self.assertIn("suggest_changes", str(ctx.exception))

    def test_refuses_missing_lists(self):
        with self.assertRaises(FoundationUnverifiable):
            suggest_changes(SCOPE, {})

    def test_no_op_only_from_complete_gaps(self):
        changes = suggest_changes(SCOPE, COMPLETE)
        self.assertEqual([c["action"] for c in changes], ["no_op"])


class FoundationAssessmentTests(unittest.TestCase):
    def test_refuses_incomplete(self):
        with self.assertRaises(FoundationUnverifiable):
            build_foundation_assessment(
                scope=SCOPE,
                snapshot={"organizationalUnits": [], "accounts": []},
                classification={"classification": "greenfield"},
                gaps=LEGACY_INCOMPLETE,
            )

    def test_unknown_classification_is_not_labelled_greenfield(self):
        with self.assertRaises(ValueError):
            build_foundation_assessment(
                scope=SCOPE,
                snapshot={"organizationalUnits": [], "accounts": []},
                classification={"classification": "unknown"},
                gaps=COMPLETE,
            )


if __name__ == "__main__":
    unittest.main()
