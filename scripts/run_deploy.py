#!/usr/bin/env python3
"""Start a Landing Zone deploy run for a DELIVERED design run and follow it to the end.

Goes through the same api-runs Lambda the UI calls (POST /deploy-target/verify, then
POST /runs/{designRunId}/deploy), so validation, credential storage and UI visibility are
identical to a UI-started run. The run is owned by the design run's requester, so it shows up
in that user's Runs list. Your IAM identity (sts get-caller-identity) is sent as "invokedBy"
and recorded in the run's META and in the deploy.started / design.deploy_requested audit rows.

Credentials:
  * Platform account: your normal AWS credentials (AWS_PROFILE or env vars). Needs
    lambda:InvokeFunction on <stack>-api-runs, cloudformation:DescribeStacks on the stack
    (for the UI URL), plus DynamoDB/Step Functions read.
  * Target account: --role-arn and --external-id (recommended), or TARGET_ACCESS_KEY_ID /
    TARGET_SECRET_ACCESS_KEY (+ optional TARGET_SESSION_TOKEN) env vars. Prefer a role or
    short-lived session credentials over long-lived AKIA keys. Never pass secrets as
    command-line arguments (they end up in shell history and process listings).

Usage:
  python3 scripts/run_deploy.py --design-run <design-run-id> --account <target-account-id> \\
    --role-arn arn:aws:iam::<target-account-id>:role/IngramLandingZoneDeploy --external-id <external-id>

  TARGET_ACCESS_KEY_ID=... TARGET_SECRET_ACCESS_KEY=... \\
    python3 scripts/run_deploy.py --design-run <design-run-id> --account <target-account-id>

Exit code: 0 when the deploy run SUCCEEDED, 1 on failure/abort/timeout. Ctrl-C stops following
only; the deploy run keeps going in Step Functions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import boto3

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _invoke_api(lam, fn: str, route: str, sub: str, invoked_by: str, body: dict,
                run_id: str | None = None) -> tuple[int, dict]:
    # No requestContext.http: api_runs treats this as a direct (IAM-gated) invoke and requires invokedBy.
    event = {
        "routeKey": route,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": sub}}}},
        "invokedBy": invoked_by,
        "body": json.dumps(body),
    }
    if run_id:
        event["pathParameters"] = {"runId": run_id}
    out = lam.invoke(FunctionName=fn, Payload=json.dumps(event).encode())
    payload = json.loads(out["Payload"].read() or b"{}")
    if out.get("FunctionError"):
        _fail(f"{route} Lambda error: {json.dumps(payload)[:1500]}")
    return int(payload.get("statusCode", 0)), json.loads(payload.get("body") or "{}")


def _target_from_args(args) -> dict:
    if args.role_arn:
        if not args.external_id:
            _fail("--external-id is required with --role-arn (the target role's trust policy must require sts:ExternalId)")
        return {"accountId": args.account, "roleArn": args.role_arn, "externalId": args.external_id}
    ak = os.environ.get("TARGET_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("TARGET_SECRET_ACCESS_KEY", "").strip()
    if not ak or not sk:
        _fail("set TARGET_ACCESS_KEY_ID and TARGET_SECRET_ACCESS_KEY (or pass --role-arn/--external-id) for the target account")
    t = {"accountId": args.account, "accessKeyId": ak, "secretAccessKey": sk}
    tok = os.environ.get("TARGET_SESSION_TOKEN", "").strip()
    if tok:
        t["sessionToken"] = tok
    elif ak.startswith("AKIA"):
        print("WARNING: long-lived access keys (AKIA...). Prefer --role-arn, or session credentials.", file=sys.stderr)
    return t


def _stack_output(cfn, stack: str, key: str) -> str:
    stacks = cfn.describe_stacks(StackName=stack)["Stacks"]
    for o in stacks[0].get("Outputs") or []:
        if o["OutputKey"] == key and o.get("OutputValue"):
            return o["OutputValue"]
    _fail(f"stack {stack} has no {key} output; pass --ui-url explicitly")
    return ""  # unreachable


def _print_new_audit(ddb, table: str, run_id: str, seen: set) -> None:
    kwargs = {
        "TableName": table,
        "KeyConditionExpression": "PK = :p AND begins_with(SK, :s)",
        "ExpressionAttributeValues": {":p": {"S": f"RUN#{run_id}"}, ":s": {"S": "AUDIT#"}},
    }
    items = []
    while True:
        page = ddb.query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    for it in sorted(items, key=lambda i: i["SK"]["S"]):
        sk = it["SK"]["S"]
        if sk in seen:
            continue
        seen.add(sk)
        ts = time.strftime("%H:%M:%S", time.localtime(int(it.get("ts", {}).get("N", "0"))))
        detail = it.get("detail", {}).get("S", "")
        print(f"  {ts}  {it.get('action', {}).get('S', '?'):<42} {detail[:260]}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design-run", required=True, help="DELIVERED design run id")
    ap.add_argument("--account", required=True, help="12-digit target account id")
    ap.add_argument("--role-arn", help="target-account role to assume instead of access keys")
    ap.add_argument("--external-id", help="sts:ExternalId required by the target role (required with --role-arn)")
    ap.add_argument("--stack", default="ingram-landing-zone", help="platform CloudFormation stack name (also the resource name prefix)")
    ap.add_argument("--region", help="platform region (default: AWS_REGION / AWS_DEFAULT_REGION)")
    ap.add_argument("--ui-url", help="UI base URL (default: the stack's UiUrl output)")
    ap.add_argument("--timeout-min", type=int, default=120, help="stop following after N minutes (run keeps going)")
    ap.add_argument("--no-follow", action="store_true", help="start the run and exit")
    args = ap.parse_args()

    region = args.region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        _fail("set --region or AWS_REGION/AWS_DEFAULT_REGION to the platform region")
    session = boto3.Session(region_name=region)
    caller = session.client("sts").get_caller_identity()
    invoked_by = caller["Arn"]
    print(f"Platform caller (recorded as invokedBy): {invoked_by}")
    lam, ddb, sfn = session.client("lambda"), session.client("dynamodb"), session.client("stepfunctions")
    ui_url = (args.ui_url or _stack_output(session.client("cloudformation"), args.stack, "UiUrl")).rstrip("/")
    fn, table = f"{args.stack}-api-runs", f"{args.stack}-state"

    design = ddb.get_item(TableName=table, Key={"PK": {"S": f"RUN#{args.design_run}"}, "SK": {"S": "META"}}).get("Item")
    if not design:
        _fail(f"design run {args.design_run} not found in {table}")
    status = design.get("status", {}).get("S")
    if status != "DELIVERED":
        _fail(f"design run {args.design_run} is {status}, must be DELIVERED")
    sub = design["requester"]["S"]
    print(f"Design run {args.design_run}: DELIVERED ({design.get('customerId', {}).get('S', '')})")

    target = _target_from_args(args)

    # 1. Test connection (same check as the UI button; nothing is stored).
    code, res = _invoke_api(lam, fn, "POST /deploy-target/verify", sub, invoked_by,
                            {"deployTarget": target, "designRunId": args.design_run})
    if code != 200 or not res.get("ok"):
        _fail(f"target connection test failed: {res.get('error') or res}")
    print(f"Target OK: {res.get('message')}")
    org = (res.get("organizations") or {}).get("status")
    if org != "enabled":
        _fail(f"target account Organizations status is {org!r}: {res.get('warnings')}")

    # 2. Start the deploy run.
    code, res = _invoke_api(lam, fn, "POST /runs/{runId}/deploy", sub, invoked_by, {"deployTarget": target},
                            run_id=args.design_run)
    if code not in (200, 201, 202):
        _fail(f"deploy start returned HTTP {code}: {res}")
    run_id = res.get("runId") or res.get("deployRunId")
    if not run_id:
        _fail(f"deploy start response has no run id: {res}")
    print(f"\nDeploy run started: {run_id}\nUI: {ui_url}/#/run/{run_id}\n")
    if args.no_follow:
        return

    # 3. Follow Step Functions + audit log until terminal.
    exec_arn = f"arn:aws:states:{region}:{caller['Account']}:execution:{args.stack}-deploy:{run_id}"
    seen: set = set()
    deadline = time.time() + args.timeout_min * 60
    try:
        while True:
            _print_new_audit(ddb, table, run_id, seen)
            ex = sfn.describe_execution(executionArn=exec_arn)
            if ex["status"] in TERMINAL:
                _print_new_audit(ddb, table, run_id, seen)
                meta = ddb.get_item(TableName=table, Key={"PK": {"S": f"RUN#{run_id}"}, "SK": {"S": "META"}})["Item"]
                print(f"\nExecution {ex['status']}; run status {meta.get('status', {}).get('S')}")
                err = meta.get("error", {}).get("S")
                if err:
                    print(f"Error: {err}")
                cleanup = meta.get("credentialsCleanupError", {}).get("S")
                if cleanup:
                    print(f"Credentials cleanup error: {cleanup}")
                sys.exit(0 if ex["status"] == "SUCCEEDED" else 1)
            if time.time() > deadline:
                print(f"\nStopped following after {args.timeout_min} min; run is still {ex['status']}. UI: {ui_url}/#/run/{run_id}")
                sys.exit(1)
            time.sleep(10)
    except KeyboardInterrupt:
        print(f"\nStopped following; run continues. UI: {ui_url}/#/run/{run_id}")
        sys.exit(1)


if __name__ == "__main__":
    main()
