import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.score import format_report, run_suite, score_run  # noqa: E402
from lzcore.scope import paginate  # noqa: E402
from lzcore.session import document  # noqa: E402

# Held out from eval/cases.py. The scorer must judge this run with no expected scope.
HELD_OUT_SOW = ("Northwind requires a Control Tower landing zone in eu-west-1 only. "
                "Logs must be retained for 365 days. A Prod OU is required. "
                "Deny AWS Marketplace subscriptions.")


def _held_out_scope():
    quote_region = "landing zone in eu-west-1 only"
    return {
        "schemaVersion": "1",
        "customer": {"orgName": "Northwind"},
        "regions": {"home": "eu-west-1", "governed": ["eu-west-1"], "extraAllowed": [], "explicitDeny": [], "enforceDeny": True},
        "logging": {"retentionDays": 365, "accessLogRetentionDays": 365, "logArchiveAccountId": "111111111111", "auditAccountId": "222222222222"},
        "evidence": {
            "regions.home": {"basis": "explicit", "source": quote_region},
            "regions.governed": {"basis": "explicit", "source": "eu-west-1 only"},
            "logging.retentionDays": {"basis": "explicit", "source": "retained for 365 days"},
        },
        "ous": [{"name": "Prod", "basis": "explicit", "source": "A Prod OU is required"}],
        "scps": [],
        "customScps": [{
            "id": "deny-marketplace", "title": "Deny AWS Marketplace subscriptions", "targets": ["Prod"],
            "document": {"Version": "2012-10-17", "Statement": [
                {"Sid": "DenyMarketplace", "Effect": "Deny", "Action": ["aws-marketplace:Subscribe"], "Resource": "*"}]},
            "basis": "explicit", "source": "Deny AWS Marketplace subscriptions",
        }],
        "controls": [],
        "unsupported": [], "assumptions": [], "openQuestions": [],
    }


def _held_out_session(sow, stub=False):
    pages = paginate(sow)
    events = [{"tool": "read_sow_page", "args": {"page": 1}, "result": "page 1" if stub else pages[0]}]
    events.append({"tool": "save_scope", "args": {}, "result": "saved. summary={}"})
    return document("held-out", len(pages), [1], events, [{"role": "assistant", "text": pages[0]}], "saved")


class EvalTests(unittest.TestCase):
    def test_suite_passes(self):
        report = run_suite()
        self.assertTrue(report["passed"], format_report(report))
        self.assertEqual(report["score"], 1.0)
        self.assertGreaterEqual(report["count"], 7)
        for name, score in report["dimensions"].items():
            self.assertEqual(score, 1.0, name)

    def test_held_out_run_is_scored_without_a_fixture(self):
        report = score_run(HELD_OUT_SOW, _held_out_scope(), _held_out_session(HELD_OUT_SOW))
        self.assertTrue(report["passed"], report["problems"])
        stub = score_run(HELD_OUT_SOW, _held_out_scope(), _held_out_session(HELD_OUT_SOW, stub=True))
        self.assertFalse(stub["passed"])
        self.assertTrue(any("session incomplete" in p for p in stub["problems"]), stub["problems"])
        invented = _held_out_scope()
        invented["ous"][0]["source"] = "the customer demands a Quarantine OU"
        bad = score_run(HELD_OUT_SOW, invented, _held_out_session(HELD_OUT_SOW))
        self.assertTrue(any("quote not found" in p for p in bad["problems"]), bad["problems"])


if __name__ == "__main__":
    unittest.main()
