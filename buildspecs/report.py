"""Turns the raw scan output of validate.sh into the validation report and the report bundles.

Usage: python3 report.py <reports_dir> <results.tsv> <src_dir> <out_dir> <run_id> <files.txt>
  reports_dir  raw tool output written by validate.sh (checkov-*.json, cfn-lint.json, tflint.json, terraform-validate.json, *.log)
  results.tsv  "<check>\\t<pass|fail>" per check
  src_dir      the rendered bundle (terraform/, cloudformation/)
  files.txt    the bundle's files as rendered (taken before any tool ran, so tool caches such as .terraform/ never enter a zip)
  out_dir      receives validation-report.json, validation-reports.zip and, only when every check passed, terraform.zip and
               cloudformation.zip rebuilt with a reports/ folder

Security scans (checkov) are report-only: findings are counted and shown but do not fail the build.
"""
import datetime
import json
import os
import sys
import zipfile

STACK_REPORTS = {
    "terraform": ("checkov-terraform.json", "tflint.json", "terraform-validate.json", "terraform-fmt.log"),
    "cloudformation": ("checkov-cloudformation.json", "cfn-lint.json"),
}


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def checkov_summary(doc):
    """checkov -o json: a dict per framework, or a list when it ran several."""
    if isinstance(doc, list):
        parts = [p for p in (checkov_summary(d) for d in doc) if p]
        if not parts:
            return None
        merged = {k: sum(p[k] for p in parts) for k in ("passed", "failed", "skipped", "parsingErrors", "resources")}
        return {"tool": "checkov", "version": parts[0]["version"], **merged, "failedChecks": [c for p in parts for c in p["failedChecks"]]}
    if not isinstance(doc, dict) or "summary" not in doc:
        return None
    sm, res = doc["summary"], doc.get("results", {})
    failed = [{"id": c.get("check_id"), "name": c.get("check_name"), "resource": c.get("resource"), "file": c.get("file_path"),
               "severity": c.get("severity")} for c in res.get("failed_checks", [])]
    return {"tool": "checkov", "version": sm.get("checkov_version"), "passed": sm.get("passed", 0), "failed": sm.get("failed", 0),
            "skipped": sm.get("skipped", 0), "parsingErrors": sm.get("parsing_errors", 0), "resources": sm.get("resource_count", 0),
            "failedChecks": failed}


def build_report(reports, results, run_id):
    checks = [{"name": n, "result": r} for n, r in results]
    sec = {fmt: checkov_summary(load(os.path.join(reports, f"checkov-{fmt}.json"))) for fmt in ("terraform", "cloudformation")}
    totals = {k: sum((sec[f] or {}).get(k, 0) for f in sec) for k in ("passed", "failed", "skipped", "parsingErrors")}
    totals["scanned"] = totals["passed"] + totals["failed"] + totals["skipped"]

    tfv = load(os.path.join(reports, "terraform-validate.json")) or {}
    tfl = load(os.path.join(reports, "tflint.json")) or {}
    cfl = load(os.path.join(reports, "cfn-lint.json"))
    cfl = cfl if isinstance(cfl, list) else []
    levels = {lv: sum(1 for m in cfl if m.get("Level") == lv) for lv in ("Error", "Warning", "Informational")}
    lint = {
        "terraformValidate": {"valid": tfv.get("valid"), "errors": tfv.get("error_count"), "warnings": tfv.get("warning_count")},
        "tflint": {"issues": len(tfl.get("issues", [])), "errors": len(tfl.get("errors", []))},
        "cfnLint": {"templates": 3, "errors": levels["Error"], "warnings": levels["Warning"], "informational": levels["Informational"]},
    }
    return {
        "runId": run_id,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "overall": "pass" if checks and all(c["result"] == "pass" for c in checks) else "fail",
        "securityPolicy": "report-only: checkov findings are counted and listed but do not fail the build",
        "checks": checks,
        "security": {"totals": totals, **sec},
        "lint": lint,
    }


def summary_md(rep):
    t = rep["security"]["totals"]
    L = [f"# Validation report ({rep['overall'].upper()})", "", f"Run `{rep['runId']}` at {rep['generatedAt']}", "",
         "## Security scan (checkov, report-only)", "", "| Stack | Checks scanned | Passed | Failed | Skipped |", "|---|---|---|---|---|"]
    for fmt, label in (("terraform", "Terraform"), ("cloudformation", "CloudFormation")):
        s = rep["security"][fmt]
        L.append(f"| {label} | {s['passed'] + s['failed'] + s['skipped']} | {s['passed']} | {s['failed']} | {s['skipped']} |" if s
                 else f"| {label} | scan produced no report | | | |")
    L += [f"| **Total** | **{t['scanned']}** | **{t['passed']}** | **{t['failed']}** | **{t['skipped']}** |", ""]
    failed = [(fmt, c) for fmt in ("terraform", "cloudformation") if rep["security"][fmt] for c in rep["security"][fmt]["failedChecks"]]
    if failed:
        L += ["### Failed security checks", "", "| Stack | Check | Resource | File |", "|---|---|---|---|"]
        L += [f"| {fmt} | {c['id']} {c['name']} | {c['resource']} | {c['file']} |" for fmt, c in failed]
        L.append("")
    lt = rep["lint"]
    L += ["## Validation and lint", "", "| Check | Result |", "|---|---|"]
    L += [f"| {c['name']} | {c['result']} |" for c in rep["checks"]]
    L += ["", f"- terraform validate: valid={lt['terraformValidate']['valid']}, errors={lt['terraformValidate']['errors']}, warnings={lt['terraformValidate']['warnings']}",
          f"- tflint: {lt['tflint']['issues']} issue(s)",
          f"- cfn-lint ({lt['cfnLint']['templates']} templates): {lt['cfnLint']['errors']} error(s), {lt['cfnLint']['warnings']} warning(s), "
          f"{lt['cfnLint']['informational']} informational", ""]
    return "\n".join(L)


def _zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def main(reports, results_tsv, src, out, run_id, files_txt):
    os.makedirs(out, exist_ok=True)
    rendered = [line.rstrip("\n") for line in open(files_txt) if line.strip()]
    results = [tuple(line.rstrip("\n").split("\t")) for line in open(results_tsv) if line.strip()]
    rep = build_report(reports, results, run_id)
    md = summary_md(rep)
    rep_json = json.dumps(rep, indent=2) + "\n"
    open(os.path.join(out, "validation-report.json"), "w").write(rep_json)
    raw = {f: _read(os.path.join(reports, f)) for f in sorted(os.listdir(reports))}
    _zip(os.path.join(out, "validation-reports.zip"), {**{f"reports/{k}": v for k, v in raw.items()},
                                                       "reports/SUMMARY.md": md.encode(), "reports/validation-report.json": rep_json.encode()})
    if rep["overall"] == "pass":  # rebuild the stack bundles with their own scan reports inside
        for fmt, names in STACK_REPORTS.items():
            entries = {}
            for rel in rendered:
                if rel.startswith(fmt + "/"):
                    entries[rel] = _read(os.path.join(src, rel))
            for n in names:
                if n in raw:
                    entries[f"{fmt}/reports/{n}"] = raw[n]
            entries[f"{fmt}/reports/SUMMARY.md"] = md.encode()
            entries[f"{fmt}/reports/validation-report.json"] = rep_json.encode()
            _zip(os.path.join(out, f"{fmt}.zip"), entries)
    t = rep["security"]["totals"]
    print(f"VALIDATION {rep['overall'].upper()} | security scan: {t['scanned']} checks, {t['passed']} passed, {t['failed']} failed, "
          f"{t['skipped']} skipped (report-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:7]))
