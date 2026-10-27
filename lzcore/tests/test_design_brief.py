"""The opening message of the Transform landing zone job carries the approved design itself."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore.deploy_transform import DESIGN_BRIEF_LIMIT, scope_summary_from_scope  # noqa: E402

SCOPE = {
    "customer": {"orgName": "Acme"},
    "regions": {"home": "ap-south-1", "governed": ["ap-south-1", "us-east-1"]},
    "ous": [{"name": "Security"}, {"name": "Workloads"}, {"name": "Production", "parent": "Workloads"}],
    "accounts": [
        {"name": "Management", "ou": "root", "kind": "management", "provisioning": "existing"},
        {"name": "Log Archive", "ou": "Security", "kind": "log-archive", "provisioning": "control-tower"},
        {"name": "Prod", "ou": "Production", "kind": "workload", "provisioning": "account-factory"},
    ],
    "scps": [{"id": "deny-region", "targets": ["root"]}],
    "customScps": [{"id": "deny-public-s3", "targets": ["Workloads"]}],
    "controls": [{"id": "AWS-GR_RESTRICT_ROOT_USER", "targets": ["Workloads"]}],
    "unsupported": [{"requirement": "x"}],
    "openQuestions": ["a", "b"],
}


class DesignBrief(unittest.TestCase):
    def test_brief_names_the_design_structure(self):
        brief = scope_summary_from_scope(SCOPE)
        for needle in ("Acme", "Home Region: ap-south-1", "ap-south-1, us-east-1",
                       "Production (parent Workloads)", "Security (parent Root)",
                       "Prod [workload, OU Production, account-factory]",
                       "deny-region -> root", "deny-public-s3 -> Workloads",
                       "AWS-GR_RESTRICT_ROOT_USER -> Workloads",
                       "1 unsupported item(s) and 2 open question(s)", "landing zone only"):
            self.assertIn(needle, brief)

    def test_empty_lists_say_none(self):
        brief = scope_summary_from_scope({"customer": {"orgName": "Acme"}, "regions": {"home": "eu-west-1"}})
        self.assertIn("Organizational units: none.", brief)
        self.assertIn("Governed Regions: none.", brief)

    def test_oversized_design_raises_instead_of_truncating(self):
        big = dict(SCOPE, ous=[{"name": f"OU-{i:04d}-" + "x" * 40} for i in range(200)])
        with self.assertRaisesRegex(RuntimeError, f"limit {DESIGN_BRIEF_LIMIT}"):
            scope_summary_from_scope(big)


if __name__ == "__main__":
    unittest.main()
