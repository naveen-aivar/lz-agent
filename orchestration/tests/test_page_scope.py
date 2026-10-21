import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore.page_scope import accept_custom_policies, accept_page, run_intake, scope_from_findings  # noqa: E402
from lzcore.scope import validate  # noqa: E402

PAGE_A = "The customer, Acme Corp, requires a landing zone in eu-west-1 and eu-central-1 only. Logs must be retained for 7 years. "
PAGE_B = "Workloads and Shared OUs are required. Block root user usage."
SOW = PAGE_A + PAGE_B


def cited(page, quote, **fields):
    start = page.index(quote)
    return {**fields, "basis": "explicit", "source": quote, "start": start, "end": start + len(quote)}


def _page_a():
    raw = {
        "scalars": {
            "customer.orgName": cited(PAGE_A, "Acme Corp", value="Acme Corp"),
            "regions.home": cited(PAGE_A, "eu-west-1 and eu-central-1", value="eu-west-1"),
            "regions.governed": cited(PAGE_A, "eu-west-1 and eu-central-1", value=["eu-west-1", "eu-central-1"]),
            "logging.retentionDays": cited(PAGE_A, "retained for 7 years", value=2555),
        }
    }
    finding, errors = accept_page(raw, PAGE_A)
    assert not errors, errors
    return finding


def _page_b():
    raw = {
        "ous": [cited(PAGE_B, "Workloads and Shared", name="Workloads"),
                cited(PAGE_B, "Workloads and Shared", name="Shared")],
        "scps": [cited(PAGE_B, "Block root user usage", id="deny-root-user", targets=["Workloads"])],
        "controls": [cited(PAGE_B, "Block root user usage", id="AWS-GR_RESTRICT_ROOT_USER", targets=["Workloads"])],
    }
    finding, errors = accept_page(raw, PAGE_B)
    assert not errors, errors
    return finding


class PageScopeTests(unittest.TestCase):
    def test_wrong_offsets_accepted_when_source_is_verbatim_on_page(self):
        page = "Block root user usage in production accounts today."
        quote = "Block root user usage"
        raw = {"scps": [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit",
                         "source": quote, "start": page.index("production"), "end": page.index("production") + 10}]}
        _, errors = accept_page(raw, page)
        self.assertEqual(errors, [])

    def test_hallucinated_source_rejected(self):
        page = "Block root user usage in production accounts today."
        raw = {"scps": [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit",
                         "source": "Block root user usage in staging", "start": 0, "end": 33}]}
        _, errors = accept_page(raw, page)
        self.assertTrue(errors)

    def test_dot_leader_quote_rejected(self):
        page = "Contents .......... section one .......... page 3"
        dots = ".......... section"
        start = page.index(dots)
        raw = {"scalars": {"regions.home": {"value": "us-east-1", "basis": "explicit",
                                            "source": dots, "start": start, "end": start + len(dots)}}}
        _, errors = accept_page(raw, page)
        self.assertTrue(any("table-of-contents" in e for e in errors))

    def test_default_basis_and_page_policy_json_are_rejected(self):
        page = "Block root user usage."
        start = page.index("Block root")
        raw = {"scps": [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "default",
                         "source": "Block root user usage", "start": start, "end": start + len("Block root user usage")}]}
        _, errors = accept_page(raw, page)
        self.assertTrue(any("explicit" in e for e in errors))
        raw = {"customScpRequests": [{"id": "protect-kms-keys", "title": "Keys", "requirement": "protect keys",
                                      "targets": ["Workloads"], "policy": {"Version": "2012-10-17"},
                                      "basis": "explicit", "source": "Block root user usage",
                                      "start": start, "end": start + len("Block root user usage")}]}
        _, errors = accept_page(raw, page)
        self.assertTrue(any("policy JSON" in e for e in errors))

    def test_pages_merge_into_a_scope_the_validator_accepts(self):
        scope, errors = scope_from_findings([{**_page_a(), "page": 1}, {**_page_b(), "page": 2}])
        self.assertEqual(errors, [])
        normalized, verrs = validate(scope, SOW)
        self.assertEqual(verrs, [])
        self.assertEqual(normalized["customer"]["orgName"], "Acme Corp")
        self.assertEqual(normalized["regions"]["governed"], ["eu-central-1", "eu-west-1"])
        self.assertIn("deny-root-user", [p["id"] for p in normalized["scps"]])
        self.assertIn("deny-region", [p["id"] for p in normalized["scps"]])

    def test_conflicting_regions_are_not_silently_picked(self):
        first = _page_a()
        second = json.loads(json.dumps(first))
        second["scalars"]["regions.home"]["value"] = "us-east-1"
        second["page"] = 2
        first["page"] = 1
        _, errors = scope_from_findings([first, second])
        self.assertTrue(any("regions.home conflicts" in e for e in errors))

    def test_a_saved_page_is_not_sent_to_the_model_again(self):
        calls = []

        def ask_page(number, page_text, errors):
            calls.append(number)
            return "raw", {}

        saved = {1: _page_a()}
        scope, errors = run_intake([PAGE_A, PAGE_B], lambda n: saved.get(n), lambda n, f: saved.__setitem__(n, f),
                                   ask_page, SOW)
        self.assertEqual(calls, [2])
        self.assertEqual(errors, [])
        self.assertEqual(scope["customer"]["orgName"], "Acme Corp")

    def test_custom_policy_keeps_the_page_quote(self):
        page = "Deny scheduling deletion of customer managed keys."
        quote = "deletion of customer managed keys"
        raw = {"scalars": _page_a()["scalars"], "customScpRequests": [
            cited(page, quote, id="protect-kms-keys", title="Protect keys", requirement="deny key deletion", targets=["Workloads"])]}
        # The quote has to be on the page accept_page checks. Rebuild the request against `page`.
        finding, errors = accept_page({"customScpRequests": raw["customScpRequests"]}, page)
        self.assertEqual(errors, [])
        request = finding["customScpRequests"][0]
        policies, errors = accept_custom_policies({
            "customScps": [{"id": "protect-kms-keys", "source": "invented quote that is not the page",
                            "targets": ["Sandbox"], "policy": {"Version": "2012-10-17", "Statement": []}, "inputs": []}]
        }, [request])
        self.assertEqual(errors, [])
        self.assertEqual(policies[0]["source"], quote)
        self.assertEqual(policies[0]["targets"], ["Workloads"])


if __name__ == "__main__":
    unittest.main()
