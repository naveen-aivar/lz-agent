"""Deployment phase: build post-deployment (foundation) attestation report vs approved scope."""
import json

from common import ARTIFACT_BUCKET, audit, get_run, record_artifact, s3
from lzcore.attestation import build_deployment_report
from lzcore.deploy_artifacts import deployment_artifact_keys
from lzcore.deploy_workflow import evaluate_deployment_outcome


def handler(event, _ctx):
    run_id = event["runId"]
    run = get_run(run_id)
    if not run or run.get("runKind") != "deploy":
        raise ValueError("not a deploy run")
    design_run_id = run["designRunId"]
    design = get_run(design_run_id)
    intake = (design.get("artifacts") or {}).get("intake")
    if not intake:
        raise ValueError("design run has no scope")

    def _get(key):
        return json.loads(s3().get_object(Bucket=ARTIFACT_BUCKET, Key=key)["Body"].read().decode())

    missing = []
    for key in deployment_artifact_keys(run_id):
        try:
            s3().head_object(Bucket=ARTIFACT_BUCKET, Key=key)
        except Exception:
            missing.append(key)
    if missing:
        raise RuntimeError(f"deploy attestation missing artifacts: {', '.join(missing)}")

    base = f"runs/{run_id}/deployment"
    scope = _get(intake["key"])
    pre_snapshot = _get(f"{base}/foundation.json")
    pre_classification = _get(f"{base}/classification.json")
    pre_gaps = _get(f"{base}/gap-analysis.json")
    post_snapshot = _get(f"{base}/foundation-post.json")
    post_classification = _get(f"{base}/classification-post.json")
    post_gaps = _get(f"{base}/gap-analysis-post.json")

    plan = _get(f"{base}/iac-change-plan.json")

    deploy_poll = _get(f"{base}/transform-poll-deploy.json")
    deploy_status = deploy_poll.get("status")

    overall, reasons = evaluate_deployment_outcome(
        pre_gaps=pre_gaps,
        post_gaps=post_gaps,
        plan=plan,
        transform_deploy_status=deploy_status,
    )
    iac_plan_summary = None
    if plan:
        iac_plan_summary = {
            "strategy": plan.get("strategy"),
            "summary": plan.get("summary"),
            "changeCount": len(plan.get("changes") or []),
            "manualStepCount": len(plan.get("manualSteps") or []),
        }
    transform_block = {
        "workspaceId": run.get("transformWorkspaceId"),
        "analyzeJobId": run.get("transformAnalyzeJobId"),
        "deployJobId": run.get("transformDeployJobId"),
        "deployJobStatus": deploy_status,
    }
    report = build_deployment_report(
        run_id=run_id,
        design_run_id=design_run_id,
        scope=scope,
        pre_snapshot=pre_snapshot,
        pre_classification=pre_classification,
        post_snapshot=post_snapshot,
        post_classification=post_classification,
        pre_gaps=pre_gaps,
        post_gaps=post_gaps,
        overall=overall,
        outcome_reasons=reasons,
        iac_plan=iac_plan_summary,
        transform=transform_block,
    )
    report_key = f"{base}/deployment-report.json"
    s3().put_object(
        Bucket=ARTIFACT_BUCKET,
        Key=report_key,
        Body=json.dumps(report, indent=2, sort_keys=True).encode(),
    )
    record_artifact(run_id, "deployment-report", report_key)
    audit(run_id, "system", "deploy.attested", {"overall": overall, "reasons": reasons})
    if overall == "fail":
        raise RuntimeError("; ".join(reasons) or "Deployment attestation failed")
    return {"runId": run_id, "overall": overall}
