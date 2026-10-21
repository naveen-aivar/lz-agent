import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _report_module():
    spec = importlib.util.spec_from_file_location("buildspec_report", ROOT / "buildspecs" / "report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def checkov(passed, failed, skipped=0, resources=3, version="3.2.0"):
    return {"check_type": "x", "summary": {"passed": passed, "failed": failed, "skipped": skipped, "parsing_errors": 0,
                                           "resource_count": resources, "checkov_version": version},
            "results": {"failed_checks": [{"check_id": f"CKV_{i}", "check_name": f"check {i}", "resource": f"aws_x.r{i}",
                                           "file_path": "/main.tf", "severity": "HIGH"} for i in range(failed)]}}


class ReportTests(unittest.TestCase):
    def _run(self, tf_checkov, cfn_checkov, results, lint_issues=0):
        m = _report_module()
        d = Path(tempfile.mkdtemp())
        reports, src, out = d / "reports", d / "src", d / "out"
        for p in (reports, src / "terraform", src / "cloudformation"):
            p.mkdir(parents=True)
        (src / "terraform" / "main.tf").write_text("x")
        (src / "terraform" / ".terraform").mkdir()
        (src / "terraform" / ".terraform" / "provider.bin").write_text("huge")  # tool cache that must never enter a zip
        (src / "cloudformation" / "00-prerequisites.yaml").write_text("y")
        (reports / "checkov-terraform.json").write_text(json.dumps(tf_checkov))
        (reports / "checkov-cloudformation.json").write_text(json.dumps(cfn_checkov))
        (reports / "terraform-validate.json").write_text(json.dumps({"valid": True, "error_count": 0, "warning_count": 0}))
        (reports / "tflint.json").write_text(json.dumps({"issues": [{}] * lint_issues, "errors": []}))
        (reports / "cfn-lint.json").write_text("[]")
        (reports / "terraform-fmt.log").write_text("")
        (d / "results.tsv").write_text("".join(f"{n}\t{r}\n" for n, r in results))
        (d / "files.txt").write_text("terraform/main.tf\ncloudformation/00-prerequisites.yaml\n")  # taken before the tools ran
        m.main(str(reports), str(d / "results.tsv"), str(src), str(out), "run1", str(d / "files.txt"))
        return json.loads((out / "validation-report.json").read_text()), out

    def test_counts_scanned_passed_failed_for_both_stacks(self):
        rep, _ = self._run(checkov(30, 2, 1), checkov(20, 3), [("tf-fmt", "pass"), ("cfn-lint", "pass")])
        t = rep["security"]["totals"]
        self.assertEqual((t["scanned"], t["passed"], t["failed"], t["skipped"]), (56, 50, 5, 1))
        self.assertEqual(rep["security"]["terraform"]["failed"], 2)
        self.assertEqual(len(rep["security"]["terraform"]["failedChecks"]), 2)
        self.assertEqual(rep["security"]["cloudformation"]["passed"], 20)

    def test_security_findings_are_report_only_but_tool_failures_fail_the_build(self):
        rep, _ = self._run(checkov(1, 9), checkov(1, 9), [("tf-security", "pass"), ("cfn-security", "pass")])
        self.assertEqual(rep["overall"], "pass")  # findings alone do not fail
        rep, _ = self._run(checkov(1, 0), checkov(1, 0), [("tf-lint", "fail"), ("tf-security", "pass")])
        self.assertEqual(rep["overall"], "fail")

    def test_passing_run_rebuilds_stack_zips_with_their_reports_and_no_tool_cache(self):
        _, out = self._run(checkov(5, 0), checkov(5, 0), [("tf-fmt", "pass")])
        tf = set(zipfile.ZipFile(out / "terraform.zip").namelist())
        self.assertIn("terraform/main.tf", tf)
        self.assertIn("terraform/reports/checkov-terraform.json", tf)
        self.assertIn("terraform/reports/SUMMARY.md", tf)
        self.assertFalse(any(".terraform/" in n for n in tf), tf)
        cfn = set(zipfile.ZipFile(out / "cloudformation.zip").namelist())
        self.assertIn("cloudformation/reports/checkov-cloudformation.json", cfn)
        self.assertIn("cloudformation/reports/cfn-lint.json", cfn)
        self.assertNotIn("terraform/reports/tflint.json", cfn)  # each stack carries only its own reports
        allr = set(zipfile.ZipFile(out / "validation-reports.zip").namelist())
        self.assertIn("reports/checkov-terraform.json", allr)
        self.assertIn("reports/checkov-cloudformation.json", allr)

    def test_failing_run_does_not_replace_the_stack_zips_but_still_reports(self):
        _, out = self._run(checkov(5, 0), checkov(5, 0), [("tf-lint", "fail")])
        self.assertFalse((out / "terraform.zip").exists())
        self.assertTrue((out / "validation-reports.zip").exists())
        self.assertTrue((out / "validation-report.json").exists())

    def test_summary_markdown_shows_the_counts(self):
        _, out = self._run(checkov(30, 2), checkov(20, 0), [("tf-fmt", "pass")])
        md = zipfile.ZipFile(out / "validation-reports.zip").read("reports/SUMMARY.md").decode()
        self.assertIn("| Terraform | 32 | 30 | 2 | 0 |", md)
        self.assertIn("| CloudFormation | 20 | 20 | 0 | 0 |", md)
        self.assertIn("Failed security checks", md)

    def test_missing_scan_output_is_reported_not_hidden(self):
        m = _report_module()
        d = Path(tempfile.mkdtemp())
        rep = m.build_report(str(d), [("tf-security", "fail")], "r")
        self.assertIsNone(rep["security"]["terraform"])
        self.assertEqual(rep["overall"], "fail")
        self.assertIn("scan produced no report", m.summary_md(rep))


if __name__ == "__main__":
    unittest.main()
