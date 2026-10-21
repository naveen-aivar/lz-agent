import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import diagram, render, scope as sc  # noqa: E402
from lzcore.regions import ALL_REGIONS  # noqa: E402

SOW = ("The customer, Acme Corp, requires a Control Tower landing zone in eu-west-1 and eu-central-1 only. "
       "Logs must be retained for 7 years. Workloads and Shared OUs are required. Block root user usage.")


def _fixed(files):
    """The fixed part of a bundle: everything except the per-scope policies/ and custom-scps/<id>.json files."""
    return {f for f in files if not f.startswith("policies/") and not (f.startswith("custom-scps/") and f not in render.CUSTOM_SCP_FIXED)}


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

    def test_security_ou_always_present_and_sandbox_added_when_referenced(self):
        s, errs = sc.validate(good(), SOW)
        self.assertEqual(errs, [])
        names = {o["name"] for o in s["ous"]}
        self.assertIn("Security", names)  # landing zone 4.0 needs it before the landing zone is created
        self.assertNotIn("Sandbox", names)
        g = good()
        g["controls"][0]["targets"].append("Sandbox")
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertIn("Sandbox", {o["name"] for o in s["ous"]})
        g = good()
        g["ous"].append({"name": "Security", "basis": "explicit", "source": "Workloads and Shared OUs are required", "parent": "Workloads"})
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("directly under the root" in e for e in errs), errs)

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
        for parent, text in (("Shared", "own parent"), ("Nope", "unknown parent"), ("Security", "Security OU must hold only the shared accounts")):
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
        self.assertEqual(s["summary"]["accounts"], 4)  # + the Audit account that is added when missing
        self.assertIn("acme-ml-dev: workload, in Shared", sc.scope_markdown(s))

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

    def test_validation_is_idempotent_on_its_own_output(self):
        """phase_render re-validates the saved (normalized) scope, so normalization must be a fixed point."""
        g = self._with_accounts()
        g["logging"]["logArchiveAccountId"] = g["logging"]["auditAccountId"] = ""
        g["controls"][0]["targets"].append("Sandbox")
        g["customScps"] = [{"id": "protect-kms", "title": "t", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage",
                            "policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": ["kms:DisableKey"], "Resource": "*",
                                                                                   "Condition": {"ArnNotLike": {"aws:PrincipalArn": ["arn:aws:iam::*:role/{{ADMIN_ROLE}}"]}}}]},
                            "inputs": [{"name": "ADMIN_ROLE", "description": "d"}]}]
        once, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        twice, errs = sc.validate(once, SOW)
        self.assertEqual(errs, [])
        self.assertEqual(json.dumps(once, sort_keys=True), json.dumps(twice, sort_keys=True))

    def test_review_hints_catch_scps_and_catalog_controls_left_under_unsupported(self):
        g = good()
        g["unsupported"] = [
            {"requirement": "Protect KMS keys from deletion (Workloads)", "reason": "Custom SCP not in catalog."},
            {"requirement": "Disallow VPN connections", "reason": "Control id not in the catalog."},
            {"requirement": "Set a retention policy for the log archive", "reason": "Not in the control catalog."},
            {"requirement": "Network baseline for ML accounts", "reason": "Network design is not expressible."},
        ]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        hints = " ".join(sc.review_hints(s))
        self.assertIn("look like SCP requirements", hints)
        self.assertIn("AWS-GR_DISALLOW_VPN_CONNECTIONS", hints)
        self.assertIn("AWS-GR_AUDIT_BUCKET_RETENTION_POLICY", hints)
        self.assertNotIn("Network baseline", hints)  # a genuine unsupported item is left alone

    def test_review_hints_are_quiet_when_the_scope_is_right(self):
        s, errs = sc.validate(good(), SOW)
        self.assertEqual(errs, [])
        self.assertEqual(sc.review_hints(s), [])
        g = good()
        g["controls"].append({"id": "AWS-GR_DISALLOW_VPN_CONNECTIONS", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"})
        g["unsupported"] = [{"requirement": "Disallow VPN connections", "reason": "see controls"}]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertEqual([h for h in sc.review_hints(s) if "VPN" in h], [])  # already used, so no nudge

    def test_markdown_does_not_say_account_ids_are_missing(self):
        g = good()
        g["logging"]["logArchiveAccountId"] = g["logging"]["auditAccountId"] = ""
        s, errs = sc.validate(g, SOW)
        md = sc.scope_markdown(s)
        self.assertNotIn("NOT PROVIDED", md)
        self.assertIn("created by the stacks from the email you provide", md)

    def test_shared_accounts_are_added_and_need_emails_not_ids(self):
        g = good()
        g["logging"]["logArchiveAccountId"] = g["logging"]["auditAccountId"] = ""
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        kinds = {a["kind"]: a for a in s["accounts"]}
        self.assertEqual(kinds["log-archive"]["name"], "acme-corp-log-archive")
        self.assertEqual(kinds["audit"]["ou"], "Security")
        self.assertEqual(s["status"], "needs-input")
        self.assertEqual(s["missingRequired"], ["email for account acme-corp-audit", "email for account acme-corp-log-archive"])
        self.assertFalse(any("account id" in m for m in s["missingRequired"]))

    def test_existing_account_ids_replace_the_email_requirement(self):
        s, errs = sc.validate(good(), SOW)  # good() supplies both shared account ids
        self.assertEqual(errs, [])
        self.assertEqual(s["missingRequired"], [])

    def test_shared_account_rules(self):
        g = self._with_accounts()
        g["accounts"][0]["ou"] = "Shared"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("must be in the Security OU" in e for e in errs), errs)
        g = self._with_accounts()
        g["accounts"].append({"name": "second-audit", "ou": "Security", "kind": "audit", "provisioning": "control-tower",
                              "basis": "explicit", "source": "Workloads and Shared OUs are required"})
        g["accounts"].append({"name": "third-audit", "ou": "Security", "kind": "audit", "provisioning": "control-tower",
                              "basis": "explicit", "source": "Workloads and Shared OUs are required"})
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("only one audit account" in e for e in errs), errs)
        g = self._with_accounts()
        g["accounts"][2]["ou"] = "Shared"
        _, errs = sc.validate(g, SOW)
        self.assertTrue(any("management account is existing" in e for e in errs), errs)

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
        self.assertEqual(_fixed(tf), render.TF_FIXED)
        self.assertEqual(set(cfn), render.CFN_FIXED)
        self.assertEqual({f for f in tf if f.startswith("policies/")}, {"policies/deny-region.json", "policies/deny-root-user.json"})

    def test_structure_identical_for_different_customers(self):
        g = copy.deepcopy(good())
        g["customer"]["orgName"] = "Other Co"
        g["ous"] = [g["ous"][0]]
        other, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        a, b = render.render_terraform(self.scope), render.render_terraform(other)
        self.assertEqual(_fixed(a), _fixed(b))
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
        self.assertEqual(_fixed(render.render_terraform(s)), render.TF_FIXED)

    def test_org_diagram_shows_tree_and_who_creates_what(self):
        g = ScopeTests._with_accounts(ScopeTests())
        g["logging"]["auditAccountId"] = ""
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        d = diagram.org_mermaid(s)
        self.assertTrue(d.startswith("flowchart TD\n"))
        for edge in ("ROOT --> OuSecurity", "ROOT --> OuWorkloads", "OuWorkloads --> OuShared",
                     "OuSecurity --> AcctAcmeLogArchive", "OuSecurity --> AcctAcmeCorpAudit", "ROOT --> AcctAcmeMgmt",
                     "OuShared --> AcctAcmeMlDev"):
            self.assertIn(edge, d)
        self.assertIn("OuSecurity[", d)
        self.assertIn(":::shared", d)   # Security OU and the shared accounts
        self.assertIn(":::existing", d)  # the management account
        self.assertIn("email required", d)  # accounts the stacks create from an email
        self.assertIn("id: 111111111111", d)  # log archive id supplied in the scope
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

    def _moon(self):
        """A scope shaped like the Moon Trades SOW: nested OUs, shared + workload accounts, no account ids supplied."""
        q = "Workloads and Shared OUs are required"
        g = good()
        g["logging"]["logArchiveAccountId"] = g["logging"]["auditAccountId"] = ""
        g["ous"][1]["parent"] = "Workloads"
        g["accounts"] = [
            {"name": "acme-log-archive", "ou": "Security", "kind": "log-archive", "provisioning": "control-tower", "basis": "explicit", "source": q},
            {"name": "acme-audit", "ou": "Security", "kind": "audit", "provisioning": "control-tower", "basis": "explicit", "source": q},
            {"name": "acme-ml-dev", "ou": "Shared", "kind": "workload", "provisioning": "account-factory", "basis": "explicit", "source": q},
            {"name": "acme-ml-prod", "ou": "Workloads", "kind": "workload", "provisioning": "account-factory", "basis": "explicit", "source": q},
            {"name": "acme-mgmt", "ou": "root", "kind": "management", "provisioning": "existing", "basis": "inferred", "source": "the existing account"},
        ]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        return s

    def test_emails_are_variables_in_both_stacks(self):
        s = self._moon()
        tfvars = render.render_terraform(s)["terraform.tfvars"]
        for name in ("acme-log-archive", "acme-audit", "acme-ml-dev", "acme-ml-prod"):
            self.assertIn(f'"{name}" = {{', tfvars)
        self.assertEqual(tfvars.count('email = ""'), 4)  # one empty email per created account, none for the management account
        self.assertNotIn("acme-mgmt", tfvars)
        self.assertIn('"Security"', tfvars)  # Security is an account placement, not an `ous` entry
        self.assertNotIn('"Security"   =', tfvars)
        self.assertNotIn("@", tfvars)  # no email is ever baked in
        cfn = render.render_cloudformation(s)
        gov = cfn["02-governance.yaml"]
        for p in ("EmailAcmeMlDev", "EmailAcmeMlProd"):
            self.assertIn(f"  {p}:", gov)
            self.assertIn(f"Email: !Ref {p}", gov)
        self.assertNotIn("EmailAcmeLogArchive", gov)  # shared accounts live in 00-prerequisites
        pre = json.loads(cfn["parameters/00-prerequisites.json"])
        keys = {x["ParameterKey"]: x["ParameterValue"] for x in pre}
        self.assertEqual(keys["LogArchiveAccountName"], "acme-log-archive")
        self.assertEqual(keys["AuditAccountEmail"], "")
        gp = {x["ParameterKey"] for x in json.loads(cfn["parameters/02-governance.json"])}
        self.assertTrue({"EmailAcmeMlDev", "EmailAcmeMlProd", "IdentityCenterEnabledBaselineArn", "SecurityOuId"} <= gp)

    def test_cfn_registers_ous_creates_accounts_and_orders_them(self):
        gov = render.render_cloudformation(self._moon())["02-governance.yaml"]
        self.assertIn("  BaselineWorkloads:\n    Type: AWS::ControlTower::EnabledBaseline", gov)
        self.assertIn("  BaselineShared:", gov)  # the child OU is registered too
        self.assertNotIn("BaselineSecurity", gov)  # the foundational OU is set up by the landing zone
        self.assertNotIn("  OuSecurity:", gov)  # created in 00-prerequisites
        self.assertIn("AWS::Organizations::Account", gov)
        self.assertIn("ParentIds: [!GetAtt OuShared.Id]", gov)
        self.assertIn("DeletionPolicy: Retain", gov)
        order = [gov.index(x) for x in ("  BaselineWorkloads:", "  ControlAwsGrRestrictRootUserWorkloads:", "  AcctAcmeMlDev:")]
        self.assertEqual(order, sorted(order))  # baselines, then controls, then accounts

    def test_terraform_static_files_cover_accounts_and_4_0(self):
        tf = render.render_terraform(self._moon())
        self.assertIn('version = var.landing_zone_version', tf["landing_zone.tf"])
        self.assertIn('default = "4.0"', tf["variables.tf"])
        self.assertIn("aws_organizations_account", tf["accounts.tf"])
        self.assertIn("aws_controltower_baseline", tf["organizations.tf"])
        self.assertNotIn("organizationStructure =", tf["landing_zone.tf"])  # removed in 4.0
        self.assertNotIn("ct_config_aggregator", tf["prerequisites.tf"])  # not needed from landing zone 4.0

    def test_custom_scps_validated_and_delivered_in_their_own_folder(self):
        q = "Workloads and Shared OUs are required"
        g = good()
        g["customScps"] = [{
            "id": "protect-kms", "title": "Protect KMS keys", "description": "Deny key deletion", "targets": ["Workloads"],
            "basis": "explicit", "source": q,
            "policy": {"Version": "2012-10-17", "Statement": [{
                "Sid": "ProtectKms", "Effect": "Deny", "Action": ["kms:ScheduleKeyDeletion"], "Resource": "*",
                "Condition": {"ArnNotLike": {"aws:PrincipalArn": ["arn:aws:iam::*:role/{{ADMIN_ROLE_NAME}}"]}}}]},
            "inputs": [{"name": "ADMIN_ROLE_NAME", "description": "Role allowed to delete keys", "example": "MT-Administrator"}]}]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertTrue(any("placeholders" in w for w in s["customScps"][0]["warnings"]))
        for files in (render.render_terraform(s), render.render_cloudformation(s)):
            self.assertIn("custom-scps/protect-kms.json", files)
            self.assertIn("{{ADMIN_ROLE_NAME}}", files["custom-scps/protect-kms.json"])
            idx = json.loads(files["custom-scps/index.json"])
            self.assertTrue(idx["aiGenerated"] and idx["reviewRequired"] and not idx["appliedByStacks"])
            self.assertEqual(idx["policies"][0]["inputs"][0]["name"], "ADMIN_ROLE_NAME")
            self.assertIn("AI-generated, review required", files["custom-scps/README.md"])
        self.assertNotIn("protect-kms", render.render_terraform(s)["terraform.tfvars"])  # never applied by the stacks
        self.assertNotIn("protect-kms", render.render_cloudformation(s)["02-governance.yaml"])

    def test_bad_custom_scps_rejected(self):
        q = "Workloads and Shared OUs are required"
        base = lambda **kw: {**{"id": "my-scp", "title": "t", "targets": ["Workloads"], "basis": "explicit", "source": q, "inputs": [],
                                "policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}]}}, **kw}
        stmt = lambda **kw: {"Version": "2012-10-17", "Statement": [{**{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}, **kw}]}
        cases = [
            (base(id="deny-region"), "is a catalog SCP"),
            (base(id="Bad Id"), "lowercase"),
            (base(targets=["Nowhere"]), "unknown target"),
            (base(policy=stmt(Effect="Allow")), "only Effect 'Deny'"),
            (base(policy=stmt(Principal="*")), "no Principal"),
            (base(policy=stmt(NotAction="s3:*")), "exactly one of Action or NotAction"),
            (base(policy=stmt(NotResource="*")), "exactly one of Resource or NotResource"),
            (base(policy={"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": {"s3": "*"}, "Resource": "*"}]}), "Action must be"),
            (base(policy=stmt(Resource="arn:aws:s3:::bucket-111122223333")), "12-digit account id"),
            (base(policy={"Version": "2008-10-17", "Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}), "Version"),
            (base(policy=stmt(Resource="x" * 6000)), "SCP limit"),
            (base(policy=stmt(Condition={"StringEquals": {"a": "{{UNDECLARED}}"}})), "not declared under inputs"),
            (base(inputs=[{"name": "UNUSED_ONE", "description": "d"}]), "never used"),
            (base(source="a quote the SOW never says"), "quote not found"),
            (base(policy="{not json"), "not valid JSON"),
        ]
        for entry, text in cases:
            g = good()
            g["customScps"] = [entry]
            _, errs = sc.validate(g, SOW)
            self.assertTrue(any(text in e for e in errs), (text, errs))

    def test_risky_custom_scp_is_flagged_not_hidden(self):
        g = good()
        g["customScps"] = [{"id": "deny-all", "title": "Deny all", "targets": ["Workloads"], "basis": "inferred", "source": "deny everything in suspended accounts",
                            "policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}, "inputs": []}]
        s, errs = sc.validate(g, SOW)
        self.assertEqual(errs, [])
        self.assertTrue(any("no Condition" in w for w in s["customScps"][0]["warnings"]))

    def test_custom_scp_warns_before_the_attach_budget_is_exceeded(self):
        def custom(targets):
            return {"id": "protect-kms", "title": "t", "targets": targets, "basis": "explicit", "source": "Block root user usage",
                    "inputs": [], "policy": {"Version": "2012-10-17", "Statement": [
                        {"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]}}

        over = good()
        over["scps"] = [{"id": i, "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"} for i in
                        ("deny-root-user", "deny-leave-org", "deny-iam-users")]
        over["customScps"] = [custom(["Workloads"])]
        s, errs = sc.validate(over, SOW)
        self.assertEqual(errs, [])
        self.assertTrue(any("would have 4" in w for w in s["customScps"][0]["warnings"]))

        under = good()
        under["scps"] = [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"},
                         {"id": "deny-leave-org", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"}]
        under["customScps"] = [custom(["Workloads"])]
        s, errs = sc.validate(under, SOW)
        self.assertEqual(errs, [])
        self.assertFalse(any("would have" in w for w in s["customScps"][0]["warnings"]))

    def test_region_deny_matches_the_control_tower_exemption_list(self):
        from lzcore.catalog import GLOBAL_SERVICES_NOT_ACTION, build_scp
        s, errs = sc.validate(good(), SOW)
        self.assertEqual(errs, [])
        doc = build_scp("deny-region", s)
        stmt = doc["Statement"][0]
        self.assertEqual(stmt["NotAction"], list(GLOBAL_SERVICES_NOT_ACTION))
        self.assertIn("notifications:*", stmt["NotAction"])
        self.assertIn("aws:PrincipalARN", stmt["Condition"]["ArnNotLike"])
        self.assertLess(len(sc.scp_json("deny-region", s)), 5120)
        guard = build_scp("deny-guardduty-disable", s)["Statement"][0]
        self.assertIn("arn:aws:iam::*:role/AWSControlTowerExecution", guard["Condition"]["ArnNotLike"]["aws:PrincipalARN"])


if __name__ == "__main__":
    unittest.main()
