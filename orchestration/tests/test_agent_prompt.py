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
    def test_prompt_formats_and_placeholders_reach_the_agent_intact(self):
        text = _prompts().INTAKE_PROMPT.format(run_id="abc")  # a stray single brace would raise KeyError here
        self.assertIn("{{ADMIN_ROLE_NAME}}", text)  # custom SCP placeholders use double braces in the policy text
        self.assertIn('"customScps"', text)
        self.assertIn('"accounts"', text)

    def test_example_json_in_prompt_parses(self):
        text = _prompts().INTAKE_PROMPT.format(run_id="abc")
        example = text[text.index('{\n "schemaVersion"'):text.index("\n\nWhen save_scope")]
        doc = json.loads(example.replace("{...}", "{}").replace("<quote>", "q"))
        for key in ("ous", "accounts", "scps", "customScps", "controls", "unsupported"):
            self.assertIn(key, doc)
        self.assertEqual(doc["ous"][1]["parent"], "Workloads")

    def test_prompt_routes_scp_requirements_to_custom_scps_not_unsupported(self):
        text = _prompts().INTAKE_PROMPT
        self.assertIn("Catalog first, then custom", text)
        self.assertIn('never goes under `unsupported` just because the catalog lacks it', text)
        self.assertIn("search the get_catalog control titles", text)
        self.assertIn("REVIEW items", text)
        self.assertIn("customScps", _prompts().SYSTEM)  # the one thing the agent may author

    def test_prompt_never_asks_the_agent_for_emails(self):
        text = _prompts().INTAKE_PROMPT
        self.assertIn("Never put an email address in the scope", text)


if __name__ == "__main__":
    unittest.main()
