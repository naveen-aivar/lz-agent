#!/usr/bin/env python3
"""Tests for infra/render.py: the template, the two CloudFront Functions (run in Node) and the validation.

    python3 -I -m unittest discover -s infra -p "test_*.py"      (needs python3 and node; no network, no AWS)
    python3 infra/test_render.py -v

The fixtures in infra/fixtures/ are six made-up agents' manifests (illustrative API domains) and a dashboard build's
.msp-build.json. TestRealManifests renders the repository's real agents/*/manifest.json too.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

INFRA = Path(__file__).resolve().parent
ROOT = INFRA.parent
sys.path.insert(0, str(INFRA))
sys.dont_write_bytecode = True

import render  # noqa: E402
from msp_render.jsnode import run_function  # noqa: E402
from msp_render.sitecheck import script_source_hash  # noqa: E402

FIXTURES = INFRA / "fixtures"
AGENT_IDS = ["secops", "wafr", "sre", "devops", "onboarding", "backupdr"]
COGNITO = "https://cognito-idp.us-east-1.amazonaws.com"


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def shell_hashes() -> List[str]:
    return load(FIXTURES / "shell" / ".msp-build.json")["scriptHashes"]


def fixture_policy() -> str:
    """The one policy the six fixture manifests must produce, written out by hand (not by the code under test):
    sre brings the two Google font hosts, onboarding the S3 hosts, and every agent's Cognito, data: and 'unsafe-inline' are the base's."""
    return (
        "default-src 'self'; "
        + "script-src " + " ".join(["'self'", *shell_hashes()]) + "; "
        + "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        + "img-src 'self' data: https://*.s3.amazonaws.com; "
        + "font-src 'self' data: https://fonts.gstatic.com; "
        + f"connect-src 'self' {COGNITO} https://onboarding-uploads.s3.us-east-1.amazonaws.com; "
        + "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )


class Workspace:
    """A temporary copy of the fixtures that a test may damage, plus a place to render into."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="msp-render-test-"))
        self.agents = self.dir / "agents"
        shutil.copytree(FIXTURES / "agents", self.agents)
        self.shell_file = self.dir / "shell.json"
        shutil.copy(FIXTURES / "shell" / ".msp-build.json", self.shell_file)
        self.out = self.dir / "out"

    def edit(self, agent_id: str, change: Callable[[Dict[str, Any]], None]) -> None:
        path = self.agents / agent_id / "manifest.json"
        data = load(path)
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def edit_shell(self, change: Callable[[Dict[str, Any]], None]) -> None:
        data = load(self.shell_file)
        change(data)
        self.shell_file.write_text(json.dumps(data), encoding="utf-8")

    def render(self, *extra: str) -> Tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = render.main(["--manifests-dir", str(self.agents), "--agent-list", str(FIXTURES / "agents.txt"), "--shell-file", str(self.shell_file), "--out-dir", str(self.out), *extra])
        return code, err.getvalue()

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


class WorkspaceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Workspace()
        self.addCleanup(self.ws.cleanup)

    def other_workspace(self) -> Workspace:
        ws = Workspace()
        self.addCleanup(ws.cleanup)
        return ws

    def render_ok(self, *extra: str) -> None:
        code, err = self.ws.render(*extra)
        self.assertEqual(code, 0, err)

    def assert_refused(self, expected_message: str, *extra: str) -> None:
        code, err = self.ws.render(*extra)
        self.assertEqual(code, 1, f"expected a refusal, got {code}: {err}")
        self.assertIn(expected_message, err)
        self.assertFalse((self.ws.out / "template.json").exists(), "nothing may be written when a declaration is refused")


class TestRenderOutput(WorkspaceCase):
    def setUp(self) -> None:
        super().setUp()
        self.render_ok()
        self.template = load(self.ws.out / "template.json")
        self.resources = self.template["Resources"]
        self.config = self.resources["Distribution"]["Properties"]["DistributionConfig"]

    def test_outputs_exist_and_fit_the_limits(self) -> None:
        for name in ("template.json", "router.js", "headers.js", "summary.txt", "smoke.txt"):
            self.assertTrue((self.ws.out / name).is_file(), name)
        self.assertLess((self.ws.out / "template.json").stat().st_size, 51_200)
        self.assertLess((self.ws.out / "router.js").stat().st_size, 10_000)
        self.assertLess((self.ws.out / "headers.js").stat().st_size, 10_000)

    def test_the_functions_are_small(self) -> None:
        """One policy and API prefixes only: the old per-agent tables (7.5 KB headers, 2.5 KB router) are gone."""
        self.assertLess((self.ws.out / "router.js").stat().st_size, 1_800)
        self.assertLess((self.ws.out / "headers.js").stat().st_size, 2_500)
        self.assertNotIn("rewrites", (self.ws.out / "router.js").read_text())

    def test_the_same_declarations_render_byte_identical_files(self) -> None:
        other = self.ws.dir / "out2"
        code, err = self.ws.render("--out-dir", str(other))
        self.assertEqual(code, 0, err)
        for name in ("template.json", "router.js", "headers.js", "summary.txt", "smoke.txt"):
            self.assertEqual((self.ws.out / name).read_bytes(), (other / name).read_bytes(), name)

    def test_functions_in_the_template_are_the_files(self) -> None:
        self.assertEqual(self.resources["RouterFunction"]["Properties"]["FunctionCode"], (self.ws.out / "router.js").read_text())
        self.assertEqual(self.resources["HeadersFunction"]["Properties"]["FunctionCode"], (self.ws.out / "headers.js").read_text())
        for name in ("RouterFunction", "HeadersFunction"):
            properties = self.resources[name]["Properties"]
            self.assertEqual(properties["FunctionConfig"]["Runtime"], "cloudfront-js-2.0")
            self.assertTrue(properties["AutoPublish"])

    def test_generated_code_uses_nothing_cloudfront_functions_lack(self) -> None:
        for name in ("router.js", "headers.js"):
            code = (self.ws.out / name).read_text()
            for forbidden in ("eval(", "Function(", "setTimeout", "require(", "module.", "process.", "async ", "await ", "console.log"):
                self.assertNotIn(forbidden, code, f"{name} uses {forbidden}")
            self.assertNotIn("__CONFIG__", code)
            comments = [line for line in code.splitlines() if line.lstrip().startswith("//")]
            self.assertEqual(len(comments), 1, f"{name}: only the one generated-by line may be a comment (every byte counts against 10 KB)")

    def test_bucket_is_private_encrypted_and_only_cloudfront_reads(self) -> None:
        bucket = self.resources["SiteBucket"]["Properties"]
        self.assertEqual(set(bucket["PublicAccessBlockConfiguration"].values()), {True})
        self.assertEqual(bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["SSEAlgorithm"], "AES256")
        statements = self.resources["SiteBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        allows = [s for s in statements if s["Effect"] == "Allow"]
        self.assertEqual(len(allows), 2)
        for statement in allows:
            self.assertEqual(statement["Principal"], {"Service": "cloudfront.amazonaws.com"})
            self.assertIn("AWS:SourceArn", statement["Condition"]["StringEquals"])
            self.assertIn(statement["Action"], ("s3:GetObject", "s3:ListBucket"))
        deny = [s for s in statements if s["Effect"] == "Deny"][0]
        self.assertEqual(deny["Condition"], {"Bool": {"aws:SecureTransport": "false"}})
        origin = self.config["Origins"][0]
        self.assertEqual(origin["S3OriginConfig"], {"OriginAccessIdentity": ""})
        self.assertIn("OriginAccessControlId", origin)

    def test_distribution_settings_from_the_design(self) -> None:
        self.assertEqual(self.config["PriceClass"], "PriceClass_100")
        self.assertEqual(self.config["HttpVersion"], "http2and3")
        self.assertNotIn("WebACLId", self.config)
        self.assertNotIn("Logging", self.config)
        self.assertEqual(self.resources["Distribution"]["Properties"]["Tags"], [{"Key": "Project", "Value": "ingram-mm-dashboard"}])
        parameters = self.template["Parameters"]
        self.assertEqual(parameters["DomainName"]["Default"], "", "no custom domain until one is chosen: the cloudfront.net name only")
        self.assertTrue(parameters["CertificateArn"]["Default"].endswith("certificate/df4a2cb0-96be-4c56-9639-fad4dd000d8d"))
        aliases = self.config["Aliases"]["Fn::If"]
        self.assertEqual(aliases[0], "HasAlias")
        self.assertEqual(aliases[2], {"Ref": "AWS::NoValue"})
        certificate = self.config["ViewerCertificate"]["Fn::If"]
        self.assertEqual(certificate[1]["SslSupportMethod"], "sni-only")
        self.assertEqual(certificate[1]["MinimumProtocolVersion"], "TLSv1.2_2021")
        self.assertEqual(certificate[2], {"CloudFrontDefaultCertificate": True})

    def test_the_names_a_direct_deploy_finds_the_live_resources_by_are_unchanged(self) -> None:
        """infra/direct.py looks resources up by name: a reworded name would make it create a second one next to the live one."""
        self.assertEqual(self.config["Comment"], "Ingram Migration and Modernization dashboard: shell, agent UIs and API proxies")
        self.assertEqual(self.resources["RouterFunction"]["Properties"]["Name"], "ingram-mm-dashboard-router")
        self.assertEqual(self.resources["HeadersFunction"]["Properties"]["Name"], "ingram-mm-dashboard-headers")
        self.assertEqual(self.resources["SecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"]["Name"], "ingram-mm-dashboard-security-headers")
        self.assertEqual(self.resources["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"]["Name"], "ingram-mm-dashboard-api-origin")
        self.assertEqual(self.resources["OriginAccessControl"]["Properties"]["OriginAccessControlConfig"]["Name"], "ingram-mm-dashboard-oac")

    def test_default_behaviour_serves_the_site_with_both_functions(self) -> None:
        default = self.config["DefaultCacheBehavior"]
        self.assertEqual(default["TargetOriginId"], "site-bucket")
        self.assertEqual(default["ViewerProtocolPolicy"], "redirect-to-https")
        self.assertEqual(default["AllowedMethods"], ["GET", "HEAD"])
        self.assertTrue(default["Compress"])
        self.assertEqual(default["CachePolicyId"], "658327ea-f89d-4fab-a63d-7e88639e58f6")
        events = {a["EventType"]: a["FunctionARN"] for a in default["FunctionAssociations"]}
        self.assertEqual(events, {"viewer-request": {"Fn::GetAtt": ["RouterFunction", "FunctionARN"]}, "viewer-response": {"Fn::GetAtt": ["HeadersFunction", "FunctionARN"]}})

    def test_api_behaviours_follow_the_apiproxy_lists_and_nothing_else_is_proxied(self) -> None:
        behaviours = self.config["CacheBehaviors"]
        patterns = [b["PathPattern"] for b in behaviours]
        self.assertEqual(sorted(patterns), sorted(["/agents/secops/api/*", "/agents/wafr/api/*", "/agents/sre/api/*", "/agents/devops/api/*", "/agents/devops/api/stream/*", "/agents/onboarding/api/*", "/agents/backupdr/api/*"]))
        self.assertTrue(all("/api/" in pattern for pattern in patterns), "static files under /agents/<id>/ come from the bucket: no behaviour for them")
        self.assertLess(patterns.index("/agents/devops/api/stream/*"), patterns.index("/agents/devops/api/*"), "the longer pattern must come first")
        for behaviour in behaviours:
            self.assertEqual(behaviour["CachePolicyId"], "4135ea2d-6df8-44a3-9df3-4b5a84be39ad")
            self.assertEqual(behaviour["ViewerProtocolPolicy"], "https-only")
            self.assertEqual(sorted(behaviour["AllowedMethods"]), sorted(["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]))
            self.assertEqual([a["EventType"] for a in behaviour["FunctionAssociations"]], ["viewer-request"])

    def test_one_https_only_origin_per_distinct_domain(self) -> None:
        custom = [o for o in self.config["Origins"] if "CustomOriginConfig" in o]
        domains = sorted(o["DomainName"] for o in custom)
        self.assertEqual(domains, sorted(set(domains)))
        self.assertEqual(len(domains), 6, "devops and onboarding share api.example-msp.aivar.app: six domains for seven prefixes")
        for origin in custom:
            settings = origin["CustomOriginConfig"]
            self.assertEqual((settings["OriginProtocolPolicy"], settings["OriginSSLProtocols"]), ("https-only", ["TLSv1.2"]))
            self.assertNotIn("OriginPath", origin, "the router adds originPath, not the origin")
        targets = {b["TargetOriginId"] for b in self.config["CacheBehaviors"]}
        self.assertEqual(targets, {o["Id"] for o in custom})

    def test_api_requests_carry_no_cookies(self) -> None:
        config = self.resources["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"]
        self.assertEqual(config["CookiesConfig"], {"CookieBehavior": "none"})
        self.assertEqual(config["HeadersConfig"], {"HeaderBehavior": "allExcept", "Headers": ["host"]})
        self.assertEqual(config["QueryStringsConfig"], {"QueryStringBehavior": "all"})

    def test_response_headers_policy(self) -> None:
        config = self.resources["SecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"]
        security = config["SecurityHeadersConfig"]
        self.assertEqual(security["StrictTransportSecurity"]["AccessControlMaxAgeSec"], 31_536_000)
        self.assertEqual(security["FrameOptions"], {"FrameOption": "DENY", "Override": True}, "nothing frames the dashboard and it frames nothing")
        self.assertEqual(security["ReferrerPolicy"]["ReferrerPolicy"], "strict-origin-when-cross-origin")
        self.assertTrue(security["ContentTypeOptions"]["Override"])
        self.assertNotIn("ContentSecurityPolicy", security, "the CSP comes from the headers function")
        permissions = config["CustomHeadersConfig"]["Items"][0]
        self.assertEqual(permissions["Header"], "Permissions-Policy")
        for feature in ("camera=()", "microphone=()", "geolocation=()"):
            self.assertIn(feature, permissions["Value"])

    def test_smoke_list_names_the_dashboard_every_agents_static_folder_and_every_api(self) -> None:
        lines = (self.ws.out / "smoke.txt").read_text().splitlines()
        self.assertEqual([line.split("|")[0] for line in lines], ["shell"] + ["agent"] * 6 + ["api"] * 7)
        self.assertEqual(lines[0], f"shell||/|{shell_hashes()[0]}")
        self.assertIn("agent|sre|/agents/sre/|", lines)
        self.assertIn("agent|backupdr|/agents/backupdr/|", lines)
        self.assertIn("api|backupdr|/agents/backupdr/api/|", lines)
        self.assertIn("api|devops|/agents/devops/api/stream/|", lines)
        self.assertFalse(any("msp-embed" in line or "index.html" in line for line in lines))

    def test_command_line_entry_point(self) -> None:
        out = self.ws.dir / "cli-out"
        run = subprocess.run(
            [sys.executable, "-I", str(INFRA / "render.py"), "--manifests-dir", str(self.ws.agents), "--agent-list", str(FIXTURES / "agents.txt"), "--shell-file", str(self.ws.shell_file), "--out-dir", str(out), "--quiet"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual((out / "template.json").read_bytes(), (self.ws.out / "template.json").read_bytes())


class TestRouterFunction(WorkspaceCase):
    """viewer-request: the generated code, executed by Node the way CloudFront runs it."""

    def setUp(self) -> None:
        super().setUp()
        self.render_ok()
        self.code = (self.ws.out / "router.js").read_text()

    def route(self, uris: List[str]) -> List[Any]:
        events = [{"request": {"method": "GET", "uri": uri, "headers": {"host": {"value": "msp.aivar.app"}}, "querystring": {}}} for uri in uris]
        return run_function(self.code, events)

    def test_uri_table(self) -> None:
        table = [
            # the dashboard: one page, every route without a file extension is index.html
            ("/", "/index.html"), ("/index.html", "/index.html"), ("/overview", "/index.html"), ("/a/b/c", "/index.html"), ("/a/b/", "/index.html"),
            ("/favicon.ico", "/favicon.ico"), ("/_next/static/chunks/main-123.js", "/_next/static/chunks/main-123.js"), ("/brand/logo.svg", "/brand/logo.svg"),
            ("/missing.js", "/missing.js"), ("/index.txt", "/index.txt"),
            # /agents and /agents/ name no agent: the dashboard
            ("/agents", "/index.html"), ("/agents/", "/index.html"),
            # under /agents/<id>/ everything but the API is a static file: the path goes to S3 as it is, no index.html, no rewrite
            ("/agents/sre/", "/agents/sre/"), ("/agents/sre", "/agents/sre"), ("/agents/sre/console", "/agents/sre/console"), ("/agents/sre/console/", "/agents/sre/console/"),
            ("/agents/devops/images/logo.png", "/agents/devops/images/logo.png"), ("/agents/secops/samples/findings.csv", "/agents/secops/samples/findings.csv"),
            ("/agents/sre/v1.2/readme", "/agents/sre/v1.2/readme"), ("/agents/sre/index.html", "/agents/sre/index.html"),
            ("/agents/wafr/profiles/abc", "/agents/wafr/profiles/abc"), ("/agents/devops/runs/123", "/agents/devops/runs/123"),
            ("/agents/nope/a.png", "/agents/nope/a.png"), ("/agents/backupdr/", "/agents/backupdr/"), ("/agents/backupdr/vaults/abc", "/agents/backupdr/vaults/abc"),
            # a name that is only almost the API prefix is a static path, not the API
            ("/agents/secops/api", "/agents/secops/api"), ("/agents/secops/apix/y", "/agents/secops/apix/y"), ("/agents/secops/x/api/y", "/agents/secops/x/api/y"),
            # API: prefix swapped for originPath, longest prefix wins
            ("/agents/secops/api/runs/1", "/api/runs/1"), ("/agents/secops/api/", "/api/"), ("/agents/secops/api/a.b/c", "/api/a.b/c"),
            ("/agents/devops/api/x", "/prod/x"), ("/agents/devops/api/stream/events", "/events"), ("/agents/devops/api/streams", "/prod/streams"),
            ("/agents/onboarding/api/upload", "/v2/upload"), ("/agents/wafr/api/profiles/abc", "/api/profiles/abc"),
            ("/agents/sre/api/a..b", "/api/a..b"), ("/agents/sre/api/v1.2/x", "/api/v1.2/x"),
            # an empty originPath is the origin's root (an API Gateway default stage)
            ("/agents/backupdr/api/vaults/abc", "/vaults/abc"), ("/agents/backupdr/api/", "/"),
        ]
        for (uri, _), result in zip(table, self.route([uri for uri, _ in table])):
            self.assertEqual(result["uri"], dict(table)[uri], uri)

    def test_dot_segments_cannot_leave_the_origin_path(self) -> None:
        for uri in ["/agents/secops/api/../../admin", "/agents/secops/api/%2e%2e/x", "/agents/secops/api/a/./b", "/agents/secops/api/a/%2E%2e/b", "/agents/secops/api/.."]:
            result = self.route([uri])[0]
            self.assertEqual(result.get("statusCode"), 400, uri)
            self.assertNotIn("uri", result)

    def test_the_rest_of_the_request_is_left_alone(self) -> None:
        result = self.route(["/agents/secops/api/x"])[0]
        self.assertEqual(result["method"], "GET")
        self.assertEqual(result["headers"]["host"]["value"], "msp.aivar.app")


class TestHeadersFunction(WorkspaceCase):
    """viewer-response: the one CSP, only on HTML."""

    def setUp(self) -> None:
        super().setUp()
        self.render_ok()
        self.code = (self.ws.out / "headers.js").read_text()

    def respond(self, uri: str, content_type: Any = "text/html", extra: Dict[str, Any] = None) -> Dict[str, Any]:
        headers: Dict[str, Any] = dict(extra or {})
        if content_type is not None:
            headers["content-type"] = {"value": content_type}
        event = {"request": {"method": "GET", "uri": uri, "headers": {}}, "response": {"statusCode": 200, "statusDescription": "OK", "headers": headers}}
        return run_function(self.code, [event])[0]

    def csp(self, uri: str, **kwargs: Any) -> str:
        return self.respond(uri, **kwargs)["headers"]["content-security-policy"]["value"]

    def test_the_whole_site_gets_the_one_policy(self) -> None:
        wanted = fixture_policy()
        for uri in ["/", "/index.html", "/overview", "/agents", "/agents/", "/some/deep/route", "/agents/sre/console/", "/agents/sre/help.html", "/agents/nope/x.html"]:
            self.assertEqual(self.csp(uri), wanted, uri)

    def test_the_policy_is_the_dashboards_hashes_and_the_union_of_every_agents_hosts(self) -> None:
        policy = self.csp("/")
        for declared in shell_hashes():
            self.assertIn(declared, policy)
        for host in ("https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://*.s3.amazonaws.com", "https://onboarding-uploads.s3.us-east-1.amazonaws.com", COGNITO):
            self.assertEqual(policy.count(host), 1, host)

    def test_policy_contents_follow_the_design(self) -> None:
        policy = self.csp("/")
        for part in ("default-src 'self'", f"connect-src 'self' {COGNITO}", "frame-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"):
            self.assertIn(part, policy)
        self.assertNotIn("frame-ancestors 'self'", policy)
        script_src = [part for part in policy.split("; ") if part.startswith("script-src")][0]
        self.assertTrue(all(token == "'self'" or token.startswith("'sha256-") for token in script_src.split()[1:]), script_src)
        for loose in ("unsafe-eval", "script-src 'self' 'unsafe-inline'", " * ", "http:"):
            self.assertNotIn(loose, policy)

    def test_only_html_is_touched(self) -> None:
        for kind in ("application/javascript", "text/css", "application/json", "image/svg+xml", "application/xml", "image/png", None):
            self.assertNotIn("content-security-policy", self.respond("/agents/secops/", content_type=kind)["headers"], kind)

    def test_html_variants_and_other_headers(self) -> None:
        for kind in ("text/html; charset=utf-8", "Text/HTML", "text/html"):
            self.assertIn("content-security-policy", self.respond("/", content_type=kind)["headers"], kind)
        answered = self.respond("/", extra={"content-security-policy": {"value": "default-src *"}, "etag": {"value": "abc"}})
        self.assertEqual(answered["headers"]["content-security-policy"]["value"], fixture_policy(), "an origin policy is replaced")
        self.assertEqual(answered["headers"]["etag"], {"value": "abc"})
        self.assertEqual(answered["statusCode"], 200)


class TestUnionOfExternalHosts(WorkspaceCase):
    """Every agent's screens run on the same pages, so one policy carries every host any agent declared."""

    def policy(self) -> str:
        self.render_ok()
        return run_function((self.ws.out / "headers.js").read_text(), [{"request": {"uri": "/"}, "response": {"headers": {"content-type": {"value": "text/html"}}}}])[0]["headers"]["content-security-policy"]["value"]

    def directive(self, policy: str, name: str) -> List[str]:
        return [part for part in policy.split("; ") if part.startswith(name + " ")][0].split()[1:]

    def test_a_host_declared_by_one_agent_is_allowed_for_the_whole_site(self) -> None:
        self.ws.edit("wafr", lambda d: d["externalHosts"]["img-src"].append("https://images.wafr.example.com"))
        self.assertIn("https://images.wafr.example.com", self.directive(self.policy(), "img-src"))

    def test_hosts_declared_by_several_agents_appear_once_and_sorted(self) -> None:
        self.ws.edit("sre", lambda d: d["externalHosts"]["connect-src"].extend(["https://z.example.com", "https://m.example.com"]))
        self.ws.edit("wafr", lambda d: d["externalHosts"]["connect-src"].extend(["https://m.example.com", "https://a.example.com"]))
        connect = self.directive(self.policy(), "connect-src")
        self.assertEqual(connect, ["'self'", COGNITO, "https://a.example.com", "https://m.example.com", "https://onboarding-uploads.s3.us-east-1.amazonaws.com", "https://z.example.com"])

    def test_the_order_agents_are_listed_in_does_not_change_the_policy(self) -> None:
        first = self.policy()
        ws = self.other_workspace()
        ws.edit("secops", lambda d: d["externalHosts"]["font-src"].append("https://fonts.gstatic.com"))  # a duplicate of sre's
        ws.edit("devops", lambda d: d["externalHosts"]["style-src"].append("https://fonts.googleapis.com"))
        code, err = ws.render()
        self.assertEqual(code, 0, err)
        again = run_function((ws.out / "headers.js").read_text(), [{"request": {"uri": "/"}, "response": {"headers": {"content-type": {"value": "text/html"}}}}])[0]["headers"]["content-security-policy"]["value"]
        self.assertEqual(again, first)

    def test_the_shell_may_declare_hosts_too(self) -> None:
        self.ws.edit_shell(lambda d: d.update(externalHosts={"font-src": ["https://use.typekit.net"], "img-src": [], "connect-src": [], "style-src": ["https://use.typekit.net"]}))
        policy = self.policy()
        self.assertIn("https://use.typekit.net", self.directive(policy, "font-src"))
        self.assertIn("https://use.typekit.net", self.directive(policy, "style-src"))

    def test_no_agent_declaring_anything_leaves_only_the_base(self) -> None:
        for agent_id in AGENT_IDS:
            self.ws.edit(agent_id, lambda d: d.update(externalHosts={"font-src": [], "img-src": [], "connect-src": [], "style-src": []}))
        policy = self.policy()
        self.assertEqual(self.directive(policy, "connect-src"), ["'self'", COGNITO])
        self.assertEqual(self.directive(policy, "img-src"), ["'self'", "data:"])
        self.assertEqual(self.directive(policy, "font-src"), ["'self'", "data:"])
        self.assertEqual(self.directive(policy, "style-src"), ["'self'", "'unsafe-inline'"])


class TestRefusedDeclarations(WorkspaceCase):
    """Anything that does not fit the contract stops the render, names the file and writes nothing."""

    def test_what_the_real_manifests_emit_is_accepted(self) -> None:
        """Seen in the real files: an empty originPath, 'unsafe-inline' and 'self' under style-src, data: images, "rewrites": [], "id" in the shell file."""
        self.ws.edit("secops", lambda d: d["apiProxy"][0].update(originPath=""))
        self.ws.edit("sre", lambda d: d["externalHosts"].update({"style-src": ["'unsafe-inline'", "'self'"], "img-src": ["data:"], "connect-src": [COGNITO]}))
        self.ws.edit("wafr", lambda d: d.update(rewrites=[]))
        self.ws.edit("onboarding", lambda d: d.pop("needsAws"))
        self.render_ok()
        code = (self.ws.out / "router.js").read_text()
        self.assertIn('{"prefix":"/agents/secops/api/","origin":"/"}', code, "an empty originPath is the origin's root")
        ws = self.other_workspace()
        ws.edit_shell(lambda d: d.update(id="other"))
        code, err = ws.render()
        self.assertEqual((code, "must be 'shell' if present" in err), (1, True))

    def test_a_function_close_to_the_limit_warns(self) -> None:
        self.ws.edit_shell(lambda d: d["scriptHashes"].extend(script_source_hash(f"script {i}") for i in range(130)))
        code, err = self.ws.render()
        self.assertEqual(code, 0, err)
        self.assertRegex(err, r"warning: headers\.js is \d+ of 10000 bytes")

    def test_a_function_over_10_kb_is_refused(self) -> None:
        self.ws.edit_shell(lambda d: d["scriptHashes"].extend(script_source_hash(f"script {i}") for i in range(200)))
        self.assert_refused("headers.js is")

    def test_script_hashes_of_the_dashboard_build(self) -> None:
        good = "'sha256-" + "A" * 43 + "='"
        for bad in ["sha256-" + "A" * 43 + "=", "'sha256-short='", "'sha512-" + "A" * 43 + "='", good + " 'unsafe-inline'", "'sha256-" + "A" * 43 + "=' ; script-src *", 5]:
            ws = self.other_workspace()
            ws.edit_shell(lambda d, b=bad: d["scriptHashes"].append(b))
            code, err = ws.render()
            self.assertEqual(code, 1, repr(bad))
            self.assertIn("shell/.msp-build.json.scriptHashes", err)
        self.ws.edit_shell(lambda d: d["scriptHashes"].append(good))
        self.render_ok()

    def test_an_agent_cannot_bring_its_own_script_hashes(self) -> None:
        self.ws.edit("sre", lambda d: d.update(scriptHashes=["'sha256-" + "A" * 43 + "='"]))
        self.assert_refused("agents/sre/manifest.json: scriptHashes does not belong in a manifest")

    def test_origin_domains(self) -> None:
        for bad in ["http://x.example.com", "https://x.example.com", "x.example.com:8443", "x.example.com/api", "X.Example.com", "10.0.0.1", "localhost", "x.example.com.", "x_y.example.com", "", None, "a b.example.com", "x.example.com\n"]:
            ws = self.other_workspace()
            ws.edit("secops", lambda d, b=bad: d["apiProxy"][0].update(originDomain=b))
            code, err = ws.render()
            self.assertEqual(code, 1, repr(bad))
            self.assertIn("agents/secops/manifest.json.apiProxy[0].originDomain", err)

    def test_prefixes_and_origin_paths(self) -> None:
        cases = [
            ("prefix", "/agents/wafr/api/", "must be /agents/secops/api/"),        # another agent's space
            ("prefix", "/api/", "must be /agents/secops/api/"),
            ("prefix", "/agents/secops/", "must be /agents/secops/api/"),          # would swallow the agent's static files
            ("prefix", "/agents/secops/samples/", "must be /agents/secops/api/"),  # only api/ is proxied
            ("prefix", "/agents/secops/apix/", "must be /agents/secops/api/"),
            ("prefix", "/agents/secops/api", "end with /"),
            ("prefix", "/agents/secops/api/../../wafr/", "must be /agents/secops/api/"), ("prefix", "/agents/secops/api/./x/", "must be /agents/secops/api/"),
            ("prefix", "/agents/secops/api/\n", "must be /agents/secops/api/"), ("prefix", "/agents/secops/api/a b/", "must be /agents/secops/api/"),
            ("originPath", "../x/", "originPath"), ("originPath", "api/", "originPath"), ("originPath", "/a//b/", "originPath"), ("originPath", "/a?b=1/", "originPath"),
        ]
        for key, value, message in cases:
            ws = self.other_workspace()
            ws.edit("secops", lambda d, k=key, v=value: d["apiProxy"][0].update({k: v}))
            code, err = ws.render()
            self.assertEqual(code, 1, f"{key}={value!r}")
            self.assertIn(message, err)

    def test_a_folder_below_api_is_a_valid_prefix(self) -> None:
        self.ws.edit("secops", lambda d: d["apiProxy"].append({"prefix": "/agents/secops/api/events/", "originDomain": "events.example.com", "originPath": "/"}))
        self.render_ok()
        self.assertIn('"prefix":"/agents/secops/api/events/"', (self.ws.out / "router.js").read_text())

    def test_duplicate_prefix(self) -> None:
        self.ws.edit("secops", lambda d: d["apiProxy"].append(copy.deepcopy(d["apiProxy"][0])))
        self.assert_refused("is listed twice")

    def test_origin_path_gets_its_trailing_slash(self) -> None:
        self.ws.edit("secops", lambda d: d["apiProxy"][0].update(originPath="/prod"))
        self.render_ok()
        self.assertIn('"origin":"/prod/"', (self.ws.out / "router.js").read_text())

    def test_an_agent_without_an_api_is_fine(self) -> None:
        self.ws.edit("wafr", lambda d: d.update(apiProxy=[]))
        self.render_ok()
        self.assertNotIn("/agents/wafr/api/", (self.ws.out / "router.js").read_text())
        self.assertNotIn("/agents/wafr/api/*", (self.ws.out / "template.json").read_text())

    def test_rewrites_are_gone(self) -> None:
        """/agents/<id>/ is static files, not an app: a manifest asking for routes to be rewritten is refused."""
        self.ws.edit("devops", lambda d: d.update(rewrites=[{"match": "^/agents/devops/runs/[^/.]+/?$", "to": "/agents/devops/index.html"}]))
        self.assert_refused("agents/devops/manifest.json.rewrites: must be empty or absent")
        ws = self.other_workspace()
        ws.edit("devops", lambda d: d.update(rewrites={}))
        self.assertEqual(ws.render()[0], 1)

    def test_external_hosts_cannot_inject_policy(self) -> None:
        bad_values = ["https://a.example.com; script-src *", "*", "https://*", "https://*.com", "https://com", "http://a.example.com", "'unsafe-inline'", "'self'",
                      "https://a.example.com/path", "https://a.example.com'", "https://a.example.com b.example.com", "https://A.example.com", "data:", "https://a.example.com,",
                      "ftp://a.example.com", "https://a.example.com\nscript-src *", "https://a.example.com\n"]
        for value in bad_values:
            ws = self.other_workspace()
            ws.edit("sre", lambda d, v=value: d["externalHosts"]["connect-src"].append(v))
            code, err = ws.render()
            self.assertEqual(code, 1, repr(value))
            self.assertIn("agents/sre/manifest.json.externalHosts.connect-src[1]", err)

    def test_external_hosts_keys_and_allowed_values(self) -> None:
        self.ws.edit("sre", lambda d: d["externalHosts"].update({"script-src": ["https://cdn.example.com"]}))
        self.assert_refused("unknown key")
        ws = self.other_workspace()
        ws.edit("sre", lambda d: d["externalHosts"]["font-src"].extend(["https://fonts.gstatic.com", "data:", "https://*.typekit.net", "https://x.example.com:8443"]))
        ws.edit("sre", lambda d: d["externalHosts"]["img-src"].extend(["blob:", "wss://x.example.com"]))
        code, err = ws.render()
        self.assertEqual(code, 0, err)
        self.assertIn("https://*.typekit.net", load(ws.out / "template.json")["Resources"]["HeadersFunction"]["Properties"]["FunctionCode"])
        ws2 = self.other_workspace()
        ws2.edit("sre", lambda d: d["externalHosts"]["style-src"].append("blob:"))
        self.assertEqual(ws2.render()[0], 1, "blob: is only allowed for images")

    def test_identity_and_shape(self) -> None:
        ws = self.other_workspace()
        ws.edit("secops", lambda d: d.update(id="wafr"))
        code, err = ws.render()
        self.assertEqual(code, 1)
        self.assertIn("is 'wafr' but the folder is 'secops'", err)
        for key in ("id", "apiProxy", "externalHosts"):
            ws = self.other_workspace()
            ws.edit("secops", lambda d, k=key: d.pop(k))
            code, err = ws.render()
            self.assertEqual(code, 1, key)
            self.assertIn(f"required key {key!r} is missing", err)
        for key, value in (("apiProxy", {}), ("externalHosts", []), ("needsAws", "x"), ("note", 5)):
            ws = self.other_workspace()
            ws.edit("secops", lambda d, k=key, v=value: d.update({k: v}))
            self.assertEqual(ws.render()[0], 1, f"{key}={value!r}")

    def test_old_build_keys_are_ignored_with_a_warning(self) -> None:
        self.ws.edit("sre", lambda d: d.update(entry="/agents/sre/console/", basePath="/agents/sre"))
        code, err = self.ws.render()
        self.assertEqual(code, 0, err)
        self.assertIn("agents/sre/manifest.json: unknown key 'entry' is ignored", err)

    def test_missing_extra_and_unreadable_manifests(self) -> None:
        shutil.rmtree(self.ws.agents / "wafr")
        self.assert_refused("agents/wafr/manifest.json: file not found")
        ws = self.other_workspace()
        shutil.copytree(ws.agents / "sre", ws.agents / "surprise")
        ws.edit("surprise", lambda d: d.update(id="surprise", apiProxy=[]))
        code, err = ws.render()
        self.assertEqual((code, "not in infra/agents.txt" in err), (1, True))
        ws = self.other_workspace()
        (ws.agents / "devops" / "manifest.json").write_text("{not json", encoding="utf-8")
        code, err = ws.render()
        self.assertEqual((code, "not readable JSON" in err), (1, True))
        ws = self.other_workspace()
        (ws.agents / "devops" / "manifest.json").write_text("[]", encoding="utf-8")
        self.assertEqual(ws.render()[0], 1)

    def test_a_folder_without_a_manifest_is_not_an_agent(self) -> None:
        """agents/<id>/embedded/ only (the archived first version) and unrelated folders do not count."""
        (self.ws.agents / "old-thing" / "embedded").mkdir(parents=True)
        self.render_ok()

    def test_the_shell_file(self) -> None:
        self.ws.shell_file.write_text("{}", encoding="utf-8")
        self.assert_refused("required key 'scriptHashes' is missing")
        self.ws.shell_file.write_text(json.dumps({"scriptHashes": [], "apiProxy": []}), encoding="utf-8")
        self.assert_refused("the shell has no apiProxy")
        self.ws.shell_file.write_text(json.dumps({"scriptHashes": ["nope"]}), encoding="utf-8")
        self.assert_refused("shell/.msp-build.json.scriptHashes[0]")
        self.ws.shell_file.unlink()
        self.assert_refused("file not found")

    def test_all_problems_are_reported_together(self) -> None:
        self.ws.edit("secops", lambda d: d["apiProxy"][0].update(originDomain="http://x"))
        self.ws.edit("sre", lambda d: d["externalHosts"]["font-src"].append("bad"))
        self.ws.edit_shell(lambda d: d["scriptHashes"].append("bad"))
        code, err = self.ws.render()
        self.assertEqual(code, 1)
        for where in ("agents/secops/manifest.json", "agents/sre/manifest.json", "shell/.msp-build.json"):
            self.assertIn(where, err)

    def test_check_manifests_only_validates(self) -> None:
        self.ws.shell_file.unlink()  # the dashboard is not built yet at that point
        self.render_ok("--check-manifests")
        self.assertFalse(self.ws.out.exists(), "nothing is written")
        self.ws.edit("sre", lambda d: d["apiProxy"][0].update(originDomain="http://x"))
        code, err = self.ws.render("--check-manifests")
        self.assertEqual((code, "agents/sre/manifest.json.apiProxy[0].originDomain" in err), (1, True))

    def test_missing_node_is_a_tool_error_not_a_declaration_error(self) -> None:
        import msp_render.jsnode as jsnode
        original = jsnode.shutil.which
        jsnode.shutil.which = lambda _name: None
        try:
            code, err = self.ws.render()
        finally:
            jsnode.shutil.which = original
        self.assertEqual(code, 2, err)


class TestSiteCheck(WorkspaceCase):
    """--check-site: the assembled folder against what was declared."""

    def setUp(self) -> None:
        super().setUp()
        self.site = self.ws.dir / "site"
        subprocess.run([sys.executable, "-I", str(FIXTURES / "fake_build.py"), str(self.site)], check=True)
        (self.site / ".msp-build.json").unlink()  # assemble.sh leaves it out of the site

    def page(self, count: int, extra: str = "") -> str:
        scripts = "".join(f"<script>shell inline script {i}</script>" for i in range(count))
        return f"<!doctype html><html><head><title>t</title></head><body>{scripts}<script src=\"/_next/static/a.js\"></script>{extra}</body></html>"

    def write(self, relative: str, text: str) -> None:
        path = self.site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def check(self) -> Tuple[int, str]:
        return self.ws.render("--check-site", str(self.site))

    def test_the_fixture_site_passes_and_fixture_hashes_are_of_those_scripts(self) -> None:
        code, err = self.check()
        self.assertEqual((code, err), (0, ""))
        for index, declared in enumerate(shell_hashes()):
            self.assertEqual(script_source_hash(f"shell inline script {index}"), declared)

    def test_an_agent_with_no_static_files_needs_no_folder(self) -> None:
        self.assertFalse((self.site / "agents" / "wafr").exists())
        self.assertEqual(self.check()[0], 0)

    def test_an_undeclared_inline_script_is_refused(self) -> None:
        self.write("index.html", self.page(9, "<script>window.evil = 1</script>"))
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("index.html: inline script 'sha256-", err)
        self.assertIn("window.evil", err)

    def test_every_html_file_is_held_to_the_dashboards_hashes(self) -> None:
        self.write("agents/sre/help.html", "<script>an agent's own inline script</script>")
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("agents/sre/help.html: inline script", err)
        self.write("agents/sre/help.html", "<script>shell inline script 0</script>")
        self.assertEqual(self.check()[0], 0)

    def test_data_blocks_are_not_scripts_but_importmaps_are(self) -> None:
        self.write("index.html", self.page(9, '<script type="application/json">{"a":1}</script><script type="application/ld+json">{}</script><script></script>'))
        self.assertEqual(self.check()[0], 0)
        self.write("index.html", self.page(9, '<script type="importmap">{"imports":{}}</script>'))
        self.assertEqual(self.check()[0], 1)

    def test_script_text_is_hashed_the_way_a_browser_does(self) -> None:
        self.assertEqual(script_source_hash("a\r\nb\rc"), script_source_hash("a\nb\nc"))
        self.assertEqual(script_source_hash(""), "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='")

    def test_external_scripts_and_inline_handlers(self) -> None:
        self.write("index.html", self.page(9, '<script src="https://cdn.example.com/x.js"></script><button onclick="go()">x</button>'))
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("another host (https://cdn.example.com/x.js)", err)
        self.assertIn("inline event handler attributes (onclick)", err)

    def test_unused_declared_hashes_only_warn(self) -> None:
        self.write("index.html", self.page(8))
        code, err = self.check()
        self.assertEqual(code, 0)
        self.assertIn("warning: shell/.msp-build.json: scriptHashes lists", err)

    def test_leaks_missing_pieces_and_secrets_are_refused(self) -> None:
        cases = [
            (lambda: self.write("agents/sre/.msp-build.json", "{}"), ".msp-build.json: must not be published"),
            (lambda: self.write("NOTES.md", "x"), "NOTES.md: must not be published"),
            (lambda: self.write("_next/static/chunks/a.js.map", "{}"), "a.js.map: must not be published"),
            (lambda: self.write("agents/devops/leak.js", 'k="AKIAABCDEFGHIJKLMNOP"'), "looks like it contains a credential"),
            (lambda: self.write("agents/devops/key.txt", "-----BEGIN RSA PRIVATE KEY-----"), "looks like it contains a credential"),
            (lambda: self.write("agents/stray/x.png", "x"), "site/agents/stray: is not a known agent"),
            (lambda: self.write("agents/stray.png", "x"), "site/agents/stray.png: is not a known agent"),
            (lambda: (self.site / "index.html").unlink(), "index.html is missing at the root"),
            (lambda: self.write("agents/devops/api/sample.json", "{}"), "agents/devops/api/sample.json: is under an API proxy prefix"),
            (lambda: self.write("agents/devops/api/stream/x.json", "{}"), "agents/devops/api/stream/x.json: is under an API proxy prefix"),
        ]
        for damage, message in cases:
            self.setUp()
            damage()
            code, err = self.check()
            self.assertEqual(code, 1, message)
            self.assertIn(message, err)

    def test_a_file_that_only_looks_like_an_api_path_is_fine(self) -> None:
        self.write("agents/devops/apiary/notes.json", "{}")
        self.write("agents/devops/images/api/x.png", "x")
        self.assertEqual(self.check()[0], 0)

    def test_missing_site_folder(self) -> None:
        shutil.rmtree(self.site)
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("run scripts/assemble.sh", err)


class TestAgentList(unittest.TestCase):
    def test_the_fixture_list_matches_the_fixtures(self) -> None:
        from msp_render.buildinfo import read_agent_ids
        self.assertEqual(read_agent_ids(FIXTURES / "agents.txt"), AGENT_IDS)
        self.assertEqual(sorted(p.name for p in (FIXTURES / "agents").iterdir()), sorted(AGENT_IDS))

    def test_an_empty_list_is_allowed(self) -> None:
        from msp_render.buildinfo import read_agent_ids
        self.write_list("# no agent connected yet\n")
        self.assertEqual(read_agent_ids(self.list_file), [])

    def write_list(self, text: str) -> None:
        folder = Path(tempfile.mkdtemp(prefix="mm-agent-list-"))
        self.addCleanup(shutil.rmtree, folder, True)
        self.list_file = folder / "agents.txt"
        self.list_file.write_text(text, encoding="utf-8")

    def test_every_listed_agent_has_a_manifest_and_every_manifest_is_listed(self) -> None:
        from msp_render.buildinfo import read_agent_ids
        listed = read_agent_ids(INFRA / "agents.txt")
        self.assertEqual(sorted(listed), sorted(p.parent.name for p in (ROOT / "agents").glob("*/manifest.json")))

    def test_the_per_agent_build_files_are_gone(self) -> None:
        self.assertEqual(sorted(p.parent.name for p in (ROOT / "agents").glob("*/build.sh")), [])
        self.assertEqual(sorted(p.parent.name for p in (ROOT / "agents").glob("*/.msp-build.json")), [])


class TestRealManifests(unittest.TestCase):
    """The repository's own agents/*/manifest.json (and out/.msp-build.json when there is a build) pass the same checks."""

    def render_real(self, shell_file: Path) -> Tuple[int, str, Path]:
        out = Path(tempfile.mkdtemp(prefix="msp-render-real-"))
        self.addCleanup(shutil.rmtree, out, True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = render.main(["--root", str(ROOT), "--shell-file", str(shell_file), "--out-dir", str(out)])
        return code, err.getvalue(), out

    def test_the_real_manifests_render(self) -> None:
        shell_file = ROOT / "out" / ".msp-build.json"
        if not shell_file.is_file():
            shell_file = FIXTURES / "shell" / ".msp-build.json"
        code, err, out = self.render_real(shell_file)
        self.assertEqual(code, 0, err)
        router = (out / "router.js").read_text()
        from msp_render.buildinfo import read_agent_ids
        listed = read_agent_ids(INFRA / "agents.txt")
        for agent_id in listed:
            self.assertIn(f'"prefix":"/agents/{agent_id}/api/"', router)
        if not listed:
            self.assertIn('"api":[]', router, "with no agent connected the router proxies nothing")
            template = json.loads((out / "template.json").read_text())
            self.assertNotIn("CacheBehaviors", template["Resources"]["Distribution"]["Properties"]["DistributionConfig"])
        policy = run_function((out / "headers.js").read_text(), [{"request": {"uri": "/"}, "response": {"headers": {"content-type": {"value": "text/html"}}}}])[0]["headers"]["content-security-policy"]["value"]
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertLess((out / "headers.js").stat().st_size, 8_000, "the real policy should leave room to grow")


if __name__ == "__main__":
    unittest.main()
