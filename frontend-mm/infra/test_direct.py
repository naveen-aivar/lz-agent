"""Tests for infra/direct.py: the template, resolved and translated into what the CloudFront and S3 APIs take. No AWS calls are made.

The template is rendered here from the fixtures (infra/fixtures/), so these tests do not depend on a build having been run."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import direct  # noqa: E402
import render  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class DirectTranslation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="msp-direct-test-"))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = render.main(["--root", str(cls.root), "--manifests-dir", str(FIXTURES / "agents"), "--agent-list", str(FIXTURES / "agents.txt"), "--shell-file", str(FIXTURES / "shell" / ".msp-build.json")])
        assert code == 0, "the fixtures must render"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.stack = direct.Stack(self.root, "msp.aivar.app", "arn:aws:acm:us-east-1:455162169375:certificate/abc")
        r = self.stack.res
        self.ctx = {**self.stack.ctx, "OriginAccessControl.Id": "OAC1", "RouterFunction.FunctionARN": "arn:aws:cloudfront::1:function/router",
                    "HeadersFunction.FunctionARN": "arn:aws:cloudfront::1:function/headers", "SecurityHeadersPolicy": "HP1", "ApiOriginRequestPolicy": "RP1"}
        self.resolved = direct.resolve(r["Distribution"]["Properties"]["DistributionConfig"], self.ctx)
        self.api = direct.distribution_to_api(self.resolved, "ref-1")

    def test_the_bucket_name_is_the_templates(self):
        self.assertEqual(self.stack.bucket, "ingram-mm-dashboard-455162169375-us-east-1")

    def test_nothing_of_cloudformation_is_left_in_the_distribution(self):
        text = json.dumps(self.api)
        self.assertNotIn("Fn::", text)
        self.assertNotIn('"Ref"', text)
        self.assertNotIn("AWS::NoValue", text)

    def test_lists_become_the_apis_quantity_and_items(self):
        self.assertEqual(self.api["Aliases"], {"Quantity": 1, "Items": ["msp.aivar.app"]})
        self.assertEqual(self.api["Origins"]["Quantity"], len(self.api["Origins"]["Items"]))
        self.assertEqual(self.api["CacheBehaviors"]["Quantity"], len(self.api["CacheBehaviors"]["Items"]))
        default = self.api["DefaultCacheBehavior"]
        self.assertEqual(default["AllowedMethods"]["Items"], ["GET", "HEAD"])
        self.assertEqual(default["AllowedMethods"]["CachedMethods"], {"Quantity": 2, "Items": ["GET", "HEAD"]})
        self.assertEqual([f["EventType"] for f in default["FunctionAssociations"]["Items"]], ["viewer-request", "viewer-response"])
        self.assertIs(default["SmoothStreaming"], False)
        self.assertEqual(default["FieldLevelEncryptionId"], "")
        self.assertEqual(default["TrustedSigners"], {"Enabled": False, "Quantity": 0})
        self.assertEqual(default["TrustedKeyGroups"], {"Enabled": False, "Quantity": 0})
        self.assertEqual(default["LambdaFunctionAssociations"], {"Quantity": 0})
        self.assertEqual(default["GrpcConfig"], {"Enabled": False})

    def test_ids_and_arns_are_filled_in(self):
        s3 = next(o for o in self.api["Origins"]["Items"] if o["Id"] == "site-bucket")
        self.assertEqual(s3["OriginAccessControlId"], "OAC1")
        self.assertEqual(s3["DomainName"], "ingram-mm-dashboard-455162169375-us-east-1.s3.us-east-1.amazonaws.com")
        self.assertEqual(self.api["DefaultCacheBehavior"]["ResponseHeadersPolicyId"], "HP1")
        api_behavior = self.api["CacheBehaviors"]["Items"][0]
        self.assertEqual(api_behavior["OriginRequestPolicyId"], "RP1")
        self.assertEqual(api_behavior["FunctionAssociations"]["Items"][0]["FunctionARN"], "arn:aws:cloudfront::1:function/router")

    def test_an_agents_origin_can_be_pointed_at_its_key_gate_and_no_other(self):
        import key_gates
        config = {"Origins": [
            {"Id": "api-tco", "DomainName": key_gates.TCO.origin},
            {"Id": "api-orchestrator", "DomainName": key_gates.ORCHESTRATOR.origin},
            {"Id": "site-bucket", "DomainName": "bucket.s3.us-east-1.amazonaws.com"},
        ]}
        key_gates.point_at_gate(config, key_gates.TCO, "abc.lambda-url.us-east-1.on.aws")
        self.assertEqual([o["DomainName"] for o in config["Origins"]],
                         ["abc.lambda-url.us-east-1.on.aws", key_gates.ORCHESTRATOR.origin, "bucket.s3.us-east-1.amazonaws.com"])
        key_gates.point_at_gate(config, key_gates.ORCHESTRATOR, "def.lambda-url.us-east-1.on.aws")
        self.assertEqual(config["Origins"][1]["DomainName"], "def.lambda-url.us-east-1.on.aws")
    def test_a_gate_is_only_wanted_for_an_agent_that_is_in_the_distribution(self):
        import key_gates
        config = {"Origins": [{"DomainName": key_gates.TCO.origin}]}
        self.assertTrue(key_gates.wanted(config, key_gates.TCO))
        self.assertFalse(key_gates.wanted(config, key_gates.ORCHESTRATOR))
    def test_each_gate_has_its_own_function_role_secret_and_settings(self):
        import key_gates
        for field in ("function_name", "role_name", "secret_id", "origin"):
            values = [getattr(g, field) for g in key_gates.GATES]
            self.assertEqual(len(set(values)), len(values), field)
        self.assertEqual(key_gates.TCO.environment, {
            "PREFIX": "/agents/tco/api", "STAGE": "dev", "UPSTREAM": "sdcr1ipp07.execute-api.us-east-1.amazonaws.com",
            "SECRET_ID": "ingram-mm-dashboard/tco-access-key", "LABEL": "tco"})
        self.assertEqual(key_gates.ORCHESTRATOR.environment["PREFIX"], "/agents/orchestrator/api")
        self.assertEqual(key_gates.ORCHESTRATOR.environment["SECRET_ID"], "ingram-mm-dashboard/orchestrator-access-key")
        self.assertEqual(key_gates.ARCHITECTURE_DESIGN.environment, {
            "PREFIX": "/agents/architecture-design/api", "STAGE": "dev",
            "UPSTREAM": "xtyojvbhm9.execute-api.us-east-1.amazonaws.com", "SECRET_ID": "a05-arch-dev/access-key",
            "LABEL": "architecture-design"})
    def test_a_gate_is_not_built_when_its_secret_is_missing(self):
        import key_gates
        from unittest import mock
        with mock.patch.object(key_gates, "secret_exists", return_value=False), mock.patch.object(key_gates, "_aws") as aws:
            with self.assertRaisesRegex(key_gates.GateError, "orchestrator-access-key is missing"):
                key_gates.ensure_gate(key_gates.ORCHESTRATOR)
            aws.assert_not_called()  # nothing was created or changed
    def test_the_api_origins_are_https_only_with_the_apis_own_key_spellings(self):
        custom = [o for o in self.api["Origins"]["Items"] if "CustomOriginConfig" in o]
        self.assertEqual(len(custom), 6)
        for origin in custom:
            config = origin["CustomOriginConfig"]
            self.assertEqual(config["OriginProtocolPolicy"], "https-only")
            self.assertEqual(config["HTTPPort"], 80)
            self.assertEqual(config["OriginSslProtocols"], {"Quantity": 1, "Items": ["TLSv1.2"]})
            self.assertNotIn("OriginSSLProtocols", config)
            self.assertEqual(config["OriginReadTimeout"], 60)
            self.assertEqual(origin["ConnectionAttempts"], 3)
            self.assertEqual(origin["ConnectionTimeout"], 10)
            self.assertEqual(origin["OriginShield"], {"Enabled": False})
            self.assertEqual(origin["OriginAccessControlId"], "")

    def test_it_finds_the_live_resources_by_the_names_the_template_gives_them(self):
        self.assertEqual(self.stack.names, {
            "oac": "ingram-mm-dashboard-oac", "headers_policy": "ingram-mm-dashboard-security-headers", "request_policy": "ingram-mm-dashboard-api-origin",
            "router": "ingram-mm-dashboard-router", "headers_fn": "ingram-mm-dashboard-headers",
            "comment": "Ingram Migration and Modernization dashboard: shell, agent UIs and API proxies"})

    def test_only_the_api_paths_are_behaviours_and_the_functions_carry_the_new_shape(self):
        patterns = [b["PathPattern"] for b in self.api["CacheBehaviors"]["Items"]]
        self.assertEqual(len(patterns), 7)
        self.assertTrue(all("/api/" in pattern for pattern in patterns))
        code = {name: self.stack.res[name]["Properties"]["FunctionCode"] for name in ("RouterFunction", "HeadersFunction")}
        self.assertNotIn("rewrites", code["RouterFunction"])
        self.assertIn("frame-ancestors 'none'", code["HeadersFunction"])

    def test_the_certificate_and_ipv6_use_the_apis_names(self):
        self.assertEqual(self.api["ViewerCertificate"]["ACMCertificateArn"], "arn:aws:acm:us-east-1:455162169375:certificate/abc")
        self.assertEqual(self.api["ViewerCertificate"]["SSLSupportMethod"], "sni-only")
        self.assertIs(self.api["IsIPV6Enabled"], True)
        self.assertNotIn("IPV6Enabled", self.api)
        self.assertEqual(self.api["CallerReference"], "ref-1")

    def test_without_a_domain_there_is_no_alias_and_the_default_certificate_is_used(self):
        bare = direct.Stack(self.root, "", "")
        resolved = direct.resolve(bare.res["Distribution"]["Properties"]["DistributionConfig"], {**bare.ctx, "OriginAccessControl.Id": "O", "RouterFunction.FunctionARN": "r",
                                  "HeadersFunction.FunctionARN": "h", "SecurityHeadersPolicy": "p", "ApiOriginRequestPolicy": "q"})
        api = direct.distribution_to_api(resolved, "x")
        self.assertEqual(api["Aliases"], {"Quantity": 0})
        self.assertEqual(api["ViewerCertificate"], {"CloudFrontDefaultCertificate": True})

    def test_policies_get_their_quantity_fields(self):
        headers = direct.headers_policy_to_api(direct.resolve(self.stack.res["SecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"], self.ctx))
        self.assertEqual(headers["CustomHeadersConfig"]["Quantity"], 1)
        self.assertEqual(headers["SecurityHeadersConfig"]["FrameOptions"]["FrameOption"], "DENY")
        request = direct.origin_request_policy_to_api(direct.resolve(self.stack.res["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"], self.ctx))
        self.assertEqual(request["HeadersConfig"]["Headers"], {"Quantity": 1, "Items": ["host"]})
        self.assertEqual(request["CookiesConfig"]["CookieBehavior"], "none")

    def test_the_bucket_policy_names_the_distribution_and_keeps_the_https_rule(self):
        document = direct.resolve(self.stack.res["SiteBucketPolicy"]["Properties"]["PolicyDocument"], {**self.stack.ctx, "Distribution": "EDIST123"})
        text = json.dumps(document)
        self.assertIn("arn:aws:cloudfront::455162169375:distribution/EDIST123", text)
        self.assertIn("aws:SecureTransport", text)
        self.assertNotIn("Fn::", text)

    def test_the_same_methods_in_another_order_are_not_a_difference_but_another_method_is(self):
        self.assertTrue(direct.contains({"Items": ["GET", "HEAD", "POST"]}, {"Items": ["POST", "GET", "HEAD"]}))
        self.assertFalse(direct.contains({"Items": ["GET", "HEAD"]}, {"Items": ["GET", "POST"]}))

    def test_lists_are_matched_by_name_because_cloudfront_returns_them_in_its_own_order(self):
        current = {"Items": [{"Id": "b", "Extra": 1}, {"Id": "a", "Extra": 2}]}
        desired = {"Items": [{"Id": "a"}, {"Id": "b"}]}
        self.assertTrue(direct.contains(current, desired))
        self.assertFalse(direct.contains(current, {"Items": [{"Id": "a"}, {"Id": "c"}]}))
        out = direct.merged(current, desired)
        self.assertEqual([i["Id"] for i in out["Items"]], ["a", "b"])  # the template's order
        self.assertEqual([i["Extra"] for i in out["Items"]], [2, 1])  # each keeps what it already had

    def test_an_update_keeps_what_the_template_does_not_say_and_replaces_what_it_does(self):
        current = {"Logging": {"Enabled": False}, "Comment": "old", "Origins": {"Quantity": 1, "Items": [{"Id": "a"}]}, "Restrictions": {"X": 1}}
        desired = {"Comment": "new", "Origins": {"Quantity": 2, "Items": [{"Id": "a"}, {"Id": "b"}]}}
        out = direct.merged(current, desired)
        self.assertEqual(out["Logging"], {"Enabled": False})
        self.assertEqual(out["Restrictions"], {"X": 1})
        self.assertEqual(out["Comment"], "new")
        self.assertEqual(out["Origins"]["Quantity"], 2)

    def test_contains_ignores_the_defaults_the_api_adds_but_sees_a_real_difference(self):
        self.assertTrue(direct.contains({"A": 1, "B": {"C": 2, "D": 3}}, {"B": {"C": 2}}))
        self.assertFalse(direct.contains({"A": 1, "B": {"C": 2}}, {"B": {"C": 9}}))
        self.assertFalse(direct.contains({"L": [1, 2]}, {"L": [1]}))  # a list must be the same length: an origin added or removed is a change

    def test_adding_a_domain_replaces_the_default_certificate_instead_of_merging_it(self):
        current = {"Comment": "old", "Logging": {"Enabled": False},
                   "ViewerCertificate": {"CloudFrontDefaultCertificate": True, "CertificateSource": "cloudfront", "MinimumProtocolVersion": "TLSv1"}}
        desired = {"Comment": "old", "ViewerCertificate": {"ACMCertificateArn": "arn:aws:acm:us-east-1:455162169375:certificate/abc",
                                                           "SSLSupportMethod": "sni-only", "MinimumProtocolVersion": "TLSv1.2_2021"}}
        out = direct.distribution_update(current, desired)
        self.assertEqual(out["ViewerCertificate"], desired["ViewerCertificate"])
        self.assertNotIn("CloudFrontDefaultCertificate", out["ViewerCertificate"])
        self.assertEqual(out["Logging"], {"Enabled": False})


class NoAgentConnected(unittest.TestCase):
    """While no agent is connected the template has no API origin request policy: the direct deploy must not need one."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="mm-direct-empty-"))
        empty_list = cls.root / "agents.txt"
        empty_list.write_text("# no agent connected yet\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = render.main(["--root", str(cls.root), "--manifests-dir", str(cls.root / "agents"), "--agent-list", str(empty_list),
                                "--shell-file", str(FIXTURES / "shell" / ".msp-build.json")])
        assert code == 0, "an empty agent list must render"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_the_distribution_resolves_without_an_api_policy(self):
        stack = direct.Stack(self.root, "", "")
        self.assertFalse(stack.has_api)
        self.assertNotIn("ApiOriginRequestPolicy", stack.res)
        resolved = stack.resolved_distribution({"oac": "OAC1", "router": "arn:r", "headers_fn": "arn:h", "headers_policy": "HP1"})
        api = direct.distribution_to_api(resolved, "ref-1")
        self.assertEqual(api["Origins"]["Quantity"], 1)
        self.assertEqual(api["CacheBehaviors"], {"Quantity": 0})
        self.assertEqual(api["Aliases"], {"Quantity": 0})
        self.assertNotIn("RP1", json.dumps(api))


if __name__ == "__main__":
    unittest.main()
