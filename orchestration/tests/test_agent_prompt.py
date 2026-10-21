import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _prompts():
    spec = importlib.util.spec_from_file_location("agent_prompts", ROOT / "agent" / "prompts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PromptTests(unittest.TestCase):
    def test_page_prompt_is_one_page_and_does_not_use_the_old_example(self):
        text = _prompts().page_prompt(1, 3, "page body", "{}")
        self.assertIn("Page 1 of 3", text)
        self.assertIn("page body", text)
        self.assertNotIn("eu-west-1", text)
        self.assertNotIn("read_sow_page", text)
        self.assertIn('"accounts"', text)
        self.assertIn("placeholders", text)

    def test_example_json_in_page_prompt_parses(self):
        text = _prompts().page_prompt(1, 1, "body", "{}")
        example = text[text.index('{\n  "scalars"'):text.index("\n\nPage body")]
        doc = json.loads(example)
        self.assertEqual(doc["ous"][1]["parent"], "ParentOu")
        for key in ("ous", "accounts", "scps", "customScpRequests", "controls", "unsupported"):
            self.assertIn(key, doc)

    def test_prompt_routes_scp_requirements_to_custom_requests_not_unsupported(self):
        text = _prompts().page_prompt(1, 1, "body", "{}")
        self.assertIn("Catalog first, then custom", text)
        self.assertIn("never goes under `unsupported` just because the catalog lacks it", text)
        self.assertIn("search the catalog control titles", text)
        self.assertIn("customScps", _prompts().SYSTEM)

    def test_custom_policy_prompt_keeps_placeholders_and_refuses_emails(self):
        text = _prompts().custom_policy_prompt("[]")
        self.assertIn("{{ADMIN_ROLE_NAME}}", text)
        self.assertIn('"customScps"', text)
        self.assertIn("Never put an email address in the scope", text)
        example = text[text.index('{\n  "customScps"'):]
        json.loads(example)


if __name__ == "__main__":
    unittest.main()
