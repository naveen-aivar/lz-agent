import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import render, scope as sc  # noqa: E402
from lzcore.regions import ALL_REGIONS  # noqa: E402

SOW = ("The customer, Acme Corp, requires a Control Tower landing zone in eu-west-1 and eu-central-1 only. "
       "Logs must be retained for 7 years. Workloads and Shared OUs are required. Block root user usage.")


def good():
    return {
        "schemaVersion": "1",
        "customer": {"orgName": "Acme Corp"},
        "regions": {"home": "eu-west-1", "governed": ["eu-west-1", "eu-central-1"], "extraAllowed": [], "explicitDeny": [], "enforceDeny": True},
        "logging": {"retentionDays": 2555, "accessLogRetentionDays": 365, "logArchiveAccountId": "111111111111", "auditAccountId": "222222222222"},
        "evidence": {
            "regions.home": {"basis": "explicit", "source": "landing zone in eu-west-1 and eu-central-1 only"},
            "regions.governed": {"basis": "explicit", "source": "eu-west-1 and eu-central-1 only"},
            "logging.retentionDays": {"basis": "explicit", "source": "retained for 7 years"},
        },
        "ous": [{"name": "Workloads", "basis": "explicit", "source": "Workloads and Shared OUs are required"},
                {"name": "Shared", "basis": "explicit", "source": "Workloads and Shared OUs are required"}],
        "scps": [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"}],
        "controls": [{"id": "AWS-GR_RESTRICT_ROOT_USER", "targets": ["Workloads", "Security"], "basis": "explicit", "source": "Block root user usage"}],
        "unsupported": [], "assumptions": [], "openQuestions": [],
    }


class ScopeTests(unittest.TestCase):
    def test_good_scope_validates_and_derives_denied_regions(self):
        s, errs = sc.validate(good(), SOW)
        self.assertEqual(errs, [])
        self.assertEqual(s["regions"]["allowed"], ["eu-central-1", "eu-west-1"])
        self.assertEqual(len(s["regions"]["denied"]), len(ALL_REGIONS) - 2)
        self.assertNotIn("eu-west-1", s["regions"]["denied"])
        self.assertIn("deny-region", [p["id"] for p in s["scps"]])  # auto-added
        self.assertEqual(s["status"], "complete")

    def test_agent_cannot_supply_denied_list(self):
        g = good()
        g["regions"]["denied"] = ["us-east-1"]
        s, _ = sc.validate(g, SOW)
        self.assertGreater(len(s["regions"]["denied"]), 20)

    def test_hallucinated_quote_rejected(self):
        g = good()
        g["ous"][0]["source"] = "the customer demands a Quarantine OU"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("quote not found" in e for e in errs))

    def test_unknown_control_and_scp_rejected(self):
        g = good()
        g["controls"][0]["id"] = "AWS-GR_MADE_UP"
        g["scps"][0]["id"] = "allow-everything"
        _, errs = sc.validate(g, SOW)
        self.assertEqual(sum("not in the" in e for e in errs), 2)

    def test_region_conflict_and_home_not_governed(self):
        g = good()
        g["regions"]["explicitDeny"] = ["eu-central-1"]
        g["regions"]["home"] = "us-east-1"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("contradictory" in e for e in errs))
        self.assertTrue(any("included in regions.governed" in e for e in errs))

    def test_ct_managed_ou_cannot_be_declared_but_can_be_target(self):
        g = good()
        g["ous"].append({"name": "Security", "basis": "default"})
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("created by Control Tower" in e for e in errs))

    def test_controls_cannot_target_root(self):
        g = good()
        g["controls"][0]["targets"] = ["root"]
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("must be an OU name" in e for e in errs))

    def test_missing_accounts_marks_needs_input(self):
        g = good()
        g["logging"]["auditAccountId"] = ""
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertEqual(s["status"], "needs-input")

    def test_too_many_scps_per_target(self):
        g = good()
        g["scps"] = [{"id": i, "targets": ["root"], "basis": "default"} for i in
                     ("deny-root-user", "deny-leave-org", "deny-iam-users", "protect-audit-trail")]
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("maximum" in e for e in errs))

    def test_paginate_covers_all_text(self):
        text = "\n".join(f"line {i} " + "x" * 90 for i in range(2000))
        pages = sc.paginate(text, 5000)
        self.assertEqual("".join(pages), text + "") if text.endswith("\n") else self.assertEqual("".join(pages).rstrip("\n"), text)
        self.assertTrue(all(len(p) <= 5000 for p in pages))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.scope, errs = sc.validate(good(), SOW)
        assert not errs, errs

    def test_structure_is_fixed(self):
        tf = render.render_terraform(self.scope)
        cfn = render.render_cloudformation(self.scope)
        self.assertEqual({f for f in tf if not f.startswith("policies/")}, render.TF_FIXED)
        self.assertEqual(set(cfn), render.CFN_FIXED)
        self.assertEqual({f for f in tf if f.startswith("policies/")}, {"policies/deny-region.json", "policies/deny-root-user.json"})

    def test_structure_identical_for_different_customers(self):
        g = copy.deepcopy(good())
        g["customer"]["orgName"] = "Other Co"
        g["ous"] = [g["ous"][0]]
        other, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        a, b = render.render_terraform(self.scope), render.render_terraform(other)
        self.assertEqual({k for k in a if not k.startswith("policies/")}, {k for k in b if not k.startswith("policies/")})
        for f in render.TF_STATIC:  # static files byte-identical
            self.assertEqual(a[f], b[f])

    def test_deterministic_bytes(self):
        a = render.zip_bytes(render.render_terraform(self.scope), "terraform")
        b = render.zip_bytes(render.render_terraform(self.scope), "terraform")
        self.assertEqual(a, b)

    def test_cfn_governance_content(self):
        g = render.render_cloudformation(self.scope)["02-governance.yaml"]
        self.assertIn("OuWorkloads:", g)
        self.assertIn("ScpDenyRegion:", g)
        self.assertIn("ControlAwsGrRestrictRootUserSecurity:", g)
        self.assertIn("${SecurityOuId}", g)
        self.assertIn("DependsOn: ControlAwsGrRestrictRootUserSecurity", g)  # serial chain

    def test_tfvars_has_no_template_leftovers(self):
        for fmt in (render.render_terraform(self.scope), render.render_cloudformation(self.scope)):
            self.assertNotIn("{{", fmt["README.md"])


if __name__ == "__main__":
    unittest.main()
