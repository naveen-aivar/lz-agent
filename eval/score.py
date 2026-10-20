"""Score a proposed scope, its session, and the delivered bundle.

Gold cases must be clean: validation, quote grounding, derived regions, custom SCPs only in
custom-scps/, a complete session, and scan reports inside both zips. Trap cases must be caught.
"""
import json

from lzcore import render
from lzcore.regions import ALL_REGIONS
from lzcore.scope import paginate, validate
from lzcore.session import complete as session_complete

from .cases import cases as default_cases


def _fidelity(normalized, gold):
    problems = []
    if not gold:
        return problems
    if "status" in gold and normalized["status"] != gold["status"]:
        problems.append(f"status {normalized['status']} != {gold['status']}")
    if "governed" in gold and normalized["regions"]["governed"] != gold["governed"]:
        problems.append("governed regions mismatch")
    if normalized["regions"]["home"] not in normalized["regions"]["governed"]:
        problems.append("home region not governed")
    allowed = set(normalized["regions"]["allowed"])
    if set(normalized["regions"]["denied"]) != set(ALL_REGIONS) - allowed:
        problems.append("denied regions were not derived")
    if "ou_names" in gold and [o["name"] for o in normalized["ous"]] != gold["ou_names"]:
        problems.append("ou names mismatch")
    if "catalog_ids" in gold and [p["id"] for p in normalized["scps"]] != gold["catalog_ids"]:
        problems.append("catalog scp ids mismatch")
    if "custom_ids" in gold and [p["id"] for p in normalized["customScps"]] != gold["custom_ids"]:
        problems.append("custom scp ids mismatch")
    if "control_ids" in gold and [c["id"] for c in normalized["controls"]] != gold["control_ids"]:
        problems.append("control ids mismatch")
    return problems


def _isolation(scope, session):
    """Custom SCPs stay in custom-scps/. The stacks attach only catalog policies. The session is in the zip."""
    problems = []
    tf = render.render_terraform(scope, session)
    cfn = render.render_cloudformation(scope, session)
    if "session/history.json" not in tf or "session/history.json" not in cfn:
        problems.append("session history missing from the bundle")
    elif session and json.loads(tf["session/history.json"]).get("runId") != session.get("runId"):
        problems.append("session history not packaged")
    for p in scope.get("customScps", []):
        path = f"custom-scps/{p['id']}.json"
        if path not in tf or path not in cfn:
            problems.append(f"custom scp {p['id']} missing from custom-scps/")
        if f"policies/{p['id']}.json" in tf or f'"{p["id"]}"' in tf["terraform.tfvars"]:
            problems.append(f"custom scp {p['id']} attached by the stack")
        if p["id"] in cfn["02-governance.yaml"]:
            problems.append(f"custom scp {p['id']} attached by the stack")
    return problems


def _scans_missing(scope, session, scans):
    missing = []
    for fmt, files in render.render_all(scope, session).items():
        merged = render.with_scans(files, scans)
        if "scans/summary.json" not in merged:
            missing.append(fmt)
            continue
        for check in json.loads(merged["scans/summary.json"]).get("checks", []):
            if check.get("log") not in merged:
                missing.append(f"{fmt}:{check.get('log')}")
    return missing


def analyze(case):
    """Objective problems in this artifact. Empty means a gold extraction packaged correctly."""
    sow, proposed = case["sow"], case["scope"]
    normalized, errors = validate(proposed, sow)
    problems = list(errors)
    if not errors:
        problems.extend(_fidelity(normalized, case.get("gold")))
        problems.extend(_isolation(normalized, case.get("session")))
        if case.get("scans") is not None and _scans_missing(normalized, case.get("session"), case["scans"]):
            problems.append("scans not packaged")
    pages = paginate(sow)
    if case.get("session") is not None and not session_complete(case["session"], len(pages), pages):
        problems.append("session incomplete")
    return problems


def score_run(sow_text, scope, session, scans=None):
    """Score one saved agent run. No gold scope: quotes, session text, isolation, and derived regions only.

    `scans` is a dict of file name -> text, as uploaded under scans/. Omit it when the run has no reports yet.
    """
    normalized, errors = validate(scope, sow_text)
    problems = list(errors)
    pages = paginate(sow_text)
    if not session_complete(session, len(pages), pages):
        problems.append("session incomplete")
    if not errors:
        allowed = set(normalized["regions"]["allowed"])
        if set(normalized["regions"]["denied"]) != set(ALL_REGIONS) - allowed:
            problems.append("denied regions were not derived")
        problems.extend(_isolation(normalized, session))
        if scans is not None and _scans_missing(normalized, session, scans):
            problems.append("scans not packaged")
    return {"passed": not problems, "score": 1.0 if not problems else 0.0, "problems": problems}


def run_case(case):
    problems = analyze(case)
    if case.get("kind") == "trap":
        blob = "\n".join(problems)
        passed = all(needle in blob for needle in case.get("detect", []))
    else:
        passed = not problems
    return {"id": case["id"], "kind": case.get("kind", "gold"), "passed": passed,
            "score": 1.0 if passed else 0.0, "problems": problems}


def run_suite(cases=None):
    cases = default_cases() if cases is None else cases
    rows = [run_case(c) for c in cases]
    dims = {}
    for case, row in zip(cases, rows):
        for name in case.get("dimensions", []):
            dims.setdefault(name, []).append(row["passed"])
    score = sum(r["score"] for r in rows) / len(rows) if rows else 0.0
    return {
        "passed": all(r["passed"] for r in rows) if rows else False,
        "score": score,
        "count": len(rows),
        "passed_count": sum(1 for r in rows if r["passed"]),
        "dimensions": {name: sum(vals) / len(vals) for name, vals in dims.items()},
        "cases": rows,
    }


def format_report(report):
    lines = [f"{'case':<24} {'kind':<6} {'score':>5}  result"]
    for row in report["cases"]:
        lines.append(f"{row['id']:<24} {row['kind']:<6} {row['score']:5.2f}  {'PASS' if row['passed'] else 'FAIL'}")
        if not row["passed"]:
            for problem in row["problems"][:8]:
                lines.append(f"    {problem}")
    dims = "  ".join(f"{name} {value:.2f}" for name, value in report["dimensions"].items())
    lines.append(f"{'overall':<24} {'':<6} {report['score']:5.2f}  "
                 f"{'PASS' if report['passed'] else 'FAIL'}  ({report['passed_count']}/{report['count']})")
    if dims:
        lines.append(f"dimensions  {dims}")
    return "\n".join(lines)
