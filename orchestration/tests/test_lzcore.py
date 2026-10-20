import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import diagram, render, scope as sc  # noqa: E402
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

    def test_child_ou_parent_is_accepted_and_normalized(self):
        g = good()
        g["ous"][1]["parent"] = "Workloads"
        g["ous"][0]["parent"] = "root"  # explicit root is the same as absent
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        by = {o["name"]: o for o in s["ous"]}
        self.assertEqual(by["Shared"]["parent"], "Workloads")
        self.assertNotIn("parent", by["Workloads"])
        self.assertIn("- Shared (under Workloads) [explicit]", sc.scope_markdown(s))

    def test_bad_ou_parents_rejected(self):
        for parent, text in (("Shared", "own parent"), ("Nope", "unknown parent"), ("Security", "created by Control Tower")):
            g = good()
            g["ous"][1]["parent"] = parent
            _, errs = sc.validate(g, SOW)
            self.assertTrue(any(text in e for e in errs), (parent, errs))
        g = good()  # grandchild: three OUs in a chain
        g["ous"].append({"name": "Deep", "basis": "explicit", "source": "Workloads and Shared OUs are required", "parent": "Shared"})
        g["ous"][1]["parent"] = "Workloads"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("one level of nesting" in e for e in errs), errs)

    def _with_accounts(self):
        g = good()
        g["ous"][1]["parent"] = "Workloads"
        q = "Workloads and Shared OUs are required"
        g["accounts"] = [
            {"name": "acme-log-archive", "ou": "Security", "kind": "log-archive", "provisioning": "control-tower", "basis": "explicit", "source": q},
            {"name": "acme-ml-dev", "ou": "Shared", "kind": "workload", "provisioning": "account-factory", "basis": "explicit", "source": q},
            {"name": "acme-mgmt", "ou": "root", "kind": "management", "provisioning": "existing", "basis": "inferred", "source": "the existing account"},
        ]
        return g

    def test_accounts_validate(self):
        s, errs = sc.validate(self._with_accounts(), SOW)
        self.assertEqual(errs, [])
        self.assertEqual(s["summary"]["accounts"], 3)
        self.assertIn("acme-ml-dev: workload, account-factory, in Shared", sc.scope_markdown(s))

    def test_bad_accounts_rejected(self):
        for field, value, text in (("ou", "Nowhere", ".ou must be"), ("ou", ["x"], ".ou must be"), ("kind", "pet", ".kind must be"),
                                   ("provisioning", "magic", ".provisioning must be"), ("name", 'a"];x', "name invalid")):
            g = self._with_accounts()
            g["accounts"][1][field] = value
            _, errs = sc.validate(g, SOW)
            self.assertTrue(any(text in e for e in errs), (field, errs))
        g = self._with_accounts()
        g["accounts"][1]["name"] = "acme-mgmt"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("duplicate account" in e for e in errs), errs)
        g = self._with_accounts()
        g["accounts"][0]["source"] = "a quote the SOW never says"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("quote not found" in e for e in errs), errs)

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
        self.assertEqual(render.stable_names(tf), render.TF_FIXED)
        self.assertEqual(render.stable_names(cfn), render.CFN_FIXED)
        self.assertEqual(set(cfn), render.CFN_FIXED)
        self.assertIn("session/history.json", tf)
        self.assertIn("custom-scps/README.md", cfn)
        self.assertEqual({f for f in tf if f.startswith("policies/")}, {"policies/deny-region.json", "policies/deny-root-user.json"})

    def test_structure_identical_for_different_customers(self):
        g = copy.deepcopy(good())
        g["customer"]["orgName"] = "Other Co"
        g["ous"] = [g["ous"][0]]
        other, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        a, b = render.render_terraform(self.scope), render.render_terraform(other)
        self.assertEqual(render.stable_names(a), render.stable_names(b))
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

    def test_child_ou_rendered_under_parent_in_both_stacks(self):
        g = good()
        g["ous"][1]["parent"] = "Workloads"
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        cfn = render.render_cloudformation(s)["02-governance.yaml"]
        self.assertIn("ParentId: !GetAtt OuWorkloads.Id", cfn)
        self.assertEqual(cfn.count("ParentId: !Ref OrganizationRootId"), 1)  # only Workloads stays under the root
        tfvars = render.render_terraform(s)["terraform.tfvars"]
        self.assertIn('"Shared"    = { parent = "Workloads" }', tfvars)
        self.assertIn('"Workloads" = {}', tfvars)
        self.assertEqual(render.stable_names(render.render_terraform(s)), render.TF_FIXED)

    def test_org_diagram_shows_tree_and_who_creates_what(self):
        g = ScopeTests._with_accounts(ScopeTests())
        g["logging"]["auditAccountId"] = ""
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        d = diagram.org_mermaid(s)
        self.assertTrue(d.startswith("flowchart TD\n"))
        for edge in ("ROOT --> OuSecurity", "ROOT --> OuSandbox", "ROOT --> OuWorkloads", "OuWorkloads --> OuShared",
                     "OuSecurity --> AcctAcmeLogArchive", "ROOT --> AcctAcmeMgmt"):
            self.assertIn(edge, d)
        self.assertIn("OuShared -.-> AcctAcmeMlDev", d)  # not created by the stacks: dotted edge
        self.assertIn("AcctAcmeMlDev(", d)
        self.assertIn(":::planned", d)
        self.assertIn("OuWorkloads[", d)
        self.assertIn("id: 111111111111", d)  # log archive id from the scope
        self.assertIn("SCPs: deny-region", d)  # root label
        self.assertEqual(d, diagram.org_mermaid(s))  # deterministic

    def test_diagram_label_text_is_sanitized(self):
        self.assertNotRegex(diagram._t('a"b<c>d`e{f}g[h]i|j#k&l;m'), r'["<>`{}\[\]|#&;]')

    def test_bundles_include_org_structure_doc(self):
        for files in (render.render_terraform(self.scope), render.render_cloudformation(self.scope)):
            doc = files["docs/ORG-STRUCTURE.md"]
            self.assertIn("```mermaid\nflowchart TD", doc)
            self.assertIn("## Legend", doc)

    def test_flat_scope_renders_without_parents(self):
        cfn = render.render_cloudformation(self.scope)["02-governance.yaml"]
        self.assertNotIn("ParentId: !GetAtt", cfn)
        self.assertNotIn("parent =", render.render_terraform(self.scope)["terraform.tfvars"])

    def test_tfvars_has_no_template_leftovers(self):
        for fmt in (render.render_terraform(self.scope), render.render_cloudformation(self.scope)):
            self.assertNotIn("{{", fmt["README.md"])

    def _with_custom(self):
        g = good()
        g["customScps"] = [{
            "id": "deny-marketplace", "title": "Deny AWS Marketplace subscriptions", "targets": ["Workloads"],
            "document": {"Version": "2012-10-17", "Statement": [
                {"Sid": "DenyMarketplace", "Effect": "Deny", "Action": ["aws-marketplace:Subscribe"], "Resource": "*"}]},
            "basis": "explicit", "source": "Block root user usage",
        }]
        # The shared SOW does not mention Marketplace; use a quote that is actually in it.
        return g

    def test_custom_scp_is_isolated_from_the_stacks(self):
        s, errs = sc.validate(self._with_custom(), SOW)
        self.assertEqual(errs, [])
        tf, cfn = render.render_terraform(s), render.render_cloudformation(s)
        self.assertIn("aws-marketplace:Subscribe", tf["custom-scps/deny-marketplace.json"])
        self.assertIn("aws-marketplace:Subscribe", cfn["custom-scps/deny-marketplace.json"])
        self.assertNotIn("policies/deny-marketplace.json", tf)
        self.assertNotIn('"deny-marketplace"', tf["terraform.tfvars"])
        self.assertNotIn("deny-marketplace", cfn["02-governance.yaml"])
        self.assertIn("custom-scps/", render.render_terraform(s)["docs/ORG-STRUCTURE.md"])
        self.assertEqual(render.stable_names(tf), render.TF_FIXED)
        self.assertIn("- `deny-marketplace` Deny AWS Marketplace subscriptions", sc.scope_markdown(s))

    def test_custom_scp_rejected_when_it_is_not_a_policy(self):
        g = self._with_custom()
        g["customScps"][0]["id"] = "deny-root-user"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("catalog SCP" in e for e in errs), errs)
        g = self._with_custom()
        g["customScps"][0]["document"] = {"Version": "2012-10-17", "Statement": [{"Effect": "Sometimes", "Action": "*", "Resource": "*"}]}
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("Effect must be Allow or Deny" in e for e in errs), errs)
        g = self._with_custom()
        g["customScps"][0]["source"] = "a quote the SOW never says"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("quote not found" in e for e in errs), errs)

    def test_custom_scp_over_the_attach_quota_warns_and_still_validates(self):
        g = self._with_custom()
        g["scps"] = [
            {"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"},
            {"id": "deny-leave-org", "targets": ["Workloads"], "basis": "default"},
            {"id": "deny-iam-users", "targets": ["Workloads"], "basis": "default"},
        ]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertTrue(any("model-authored" in w for w in s["warnings"]), s["warnings"])
        self.assertIn("## Warnings", sc.scope_markdown(s))

    def test_custom_scp_document_must_be_attachable_later(self):
        g = self._with_custom()
        g["customScps"][0]["document"] = {"Version": "2012-10-17", "Statement": [{
            "Sid": "has space", "Effect": "Deny", "Action": {"bad": True}, "Resource": "*", "Principal": "*",
        }]}
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("cannot set Principal" in e for e in errs), errs)
        self.assertTrue(any("Action must be a string" in e for e in errs), errs)
        self.assertTrue(any("Sid must be alphanumeric" in e for e in errs), errs)

    def test_scans_are_added_beside_the_code(self):
        scans = {"summary.json": '{"overall": "pass", "checks": [{"name": "tf-fmt", "result": "pass", "log": "scans/tf-fmt.log"}]}',
                 "tf-fmt.log": "ok\n"}
        merged = render.with_scans(render.render_terraform(self.scope), scans)
        self.assertIn("scans/summary.json", merged)
        self.assertIn("scans/tf-fmt.log", merged)
        self.assertIn("versions.tf", merged)
        self.assertEqual(render.stable_names(merged), render.TF_FIXED)


if __name__ == "__main__":
    unittest.main()
