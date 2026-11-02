#!/usr/bin/env python3
"""The S3 and CloudFront half of the AWS CLI test double (infra/fixtures/stubs/aws hands every `s3api ...` and
`cloudfront ...` call it does not answer itself to this file). It exists so infra/test_scripts.sh can run the direct deploy
(infra/direct.py, DEPLOY_MODE=direct) end to end without AWS: it keeps a pretend account in $STUB_STATE/direct.json and
changes nothing anywhere else.

Only the calls infra/direct.py makes are understood; anything else exits 99. Like the real service it
  - answers a lookup of something that does not exist with the CLI's own error text,
  - hands lists back in an order of its own (reversed) and adds fields the template never wrote (what `merged` and `contains` in direct.py exist for).
"""
import json
import os
import sys
from pathlib import Path

STATE_FILE = Path(os.environ["STUB_STATE"]) / "direct.json"
ARN = "arn:aws:cloudfront::455162169375:function/"


def load() -> dict:
    if STATE_FILE.is_file():
        return json.loads(STATE_FILE.read_text())
    return {"buckets": {}, "bucket_config": {}, "oacs": {}, "functions": {}, "headers_policies": {}, "request_policies": {}, "distributions": {}}


def save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1))


def fail(code: str, message: str) -> None:
    print(f"\nAn error occurred ({code}) when calling the operation: {message}", file=sys.stderr)
    sys.exit(254)


def out(data: object) -> None:
    print(json.dumps(data))


def parse(args: list) -> tuple:
    """(flags, positional): `--flag value` pairs and the arguments left over (get-function's output file)."""
    flags, rest, i = {}, [], 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            flags[args[i][2:]] = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    return flags, rest


def value(text: str):
    """A JSON argument: inline, file://path (a config file) or fileb://path (function code)."""
    if text.startswith("file://"):
        return json.loads(Path(text[7:]).read_text())
    return json.loads(text)


def code_of(text: str) -> str:
    return Path(text[len("fileb://"):]).read_text()


def etag(counter_key: str, state: dict) -> str:
    state.setdefault("etags", {})
    state["etags"][counter_key] = state["etags"].get(counter_key, 0) + 1
    return f"E{state['etags'][counter_key]}"


def own_order(config: dict) -> dict:
    """What CloudFront returns: the lists in an order of its own, and fields nobody wrote."""
    config = json.loads(json.dumps(config))
    for key in ("Origins", "CacheBehaviors"):
        items = config.get(key, {}).get("Items")
        if items:
            items.reverse()
    config.setdefault("Logging", {"Enabled": False, "IncludeCookies": False, "Bucket": "", "Prefix": ""})
    config.setdefault("Restrictions", {"GeoRestriction": {"RestrictionType": "none", "Quantity": 0}})
    return config


def main() -> None:
    service, command, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    flags, positional = parse([a for a in rest if a not in ("--output", "json")])
    flags.pop("output", None)
    state = load()

    if service == "s3api":
        bucket = flags.get("bucket")
        if command == "head-bucket":
            sys.exit(0 if bucket in state["buckets"] else 254)
        if command == "create-bucket":
            state["buckets"][bucket] = True
            save(state)
            return out({"Location": f"/{bucket}"})
        if command.startswith("put-bucket-") or command == "put-public-access-block":
            if bucket not in state["buckets"]:
                fail("NoSuchBucket", "The specified bucket does not exist")
            state["bucket_config"][command] = value(next(v for k, v in flags.items() if k != "bucket"))
            return save(state)

    elif service == "cloudfront":
        if command == "list-origin-access-controls":
            return out({"OriginAccessControlList": {"Items": [{"Id": i, "Name": c["Name"]} for i, c in state["oacs"].items()]}})
        if command == "create-origin-access-control":
            state["oacs"]["OAC-STUB"] = value(flags["origin-access-control-config"])
            save(state)
            return out({"OriginAccessControl": {"Id": "OAC-STUB"}})

        if command in ("describe-function", "get-function", "create-function", "update-function", "publish-function"):
            name = flags["name"]
            function = state["functions"].get(name)
            if command == "create-function":
                state["functions"][name] = {"dev": code_of(flags["function-code"]), "live": None, "config": value(flags["function-config"])}
                save(state)
                return out({"ETag": etag(name, state), "FunctionSummary": {"FunctionMetadata": {"FunctionARN": ARN + name}}})
            if function is None:
                fail("NoSuchFunctionExists", "The specified function does not exist.")
            if command == "describe-function":
                return out({"ETag": etag(name, state), "FunctionSummary": {"FunctionMetadata": {"FunctionARN": ARN + name, "Stage": flags.get("stage", "LIVE")}}})
            if command == "get-function":
                code = function["dev"] if flags.get("stage") == "DEVELOPMENT" else function["live"]
                if code is None:
                    fail("NoSuchFunctionExists", "The function has not been published.")
                Path(positional[-1]).write_text(code)
                return out({"ETag": "E1", "ContentType": "application/octet-stream"})
            if command == "update-function":
                function["dev"], function["config"] = code_of(flags["function-code"]), value(flags["function-config"])
                save(state)
                return out({"ETag": etag(name, state), "FunctionSummary": {"FunctionMetadata": {"FunctionARN": ARN + name}}})
            function["live"] = function["dev"]
            save(state)
            return out({"FunctionSummary": {"FunctionMetadata": {"FunctionARN": ARN + name}}})

        for kind, table, listing, item, config_key, prefix in (
            ("response-headers-polic", "headers_policies", "ResponseHeadersPolicyList", "ResponseHeadersPolicy", "ResponseHeadersPolicyConfig", "HP"),
            ("origin-request-polic", "request_policies", "OriginRequestPolicyList", "OriginRequestPolicy", "OriginRequestPolicyConfig", "RP"),
        ):
            plural, single = kind + "ies", kind + "y"
            policies = state[table]
            if command == f"list-{plural}":
                return out({listing: {"Items": [{item: {"Id": i, config_key: {"Name": c["Name"]}, "Type": "custom"}} for i, c in policies.items()]}})
            if command == f"create-{single}":
                policies[f"{prefix}-STUB"] = value(flags[f"{single}-config"])
                save(state)
                return out({item: {"Id": f"{prefix}-STUB"}})
            if command == f"get-{single}":
                return out({"ETag": etag(flags["id"], state), item: {"Id": flags["id"], config_key: policies[flags["id"]]}})
            if command == f"update-{single}":
                policies[flags["id"]] = value(flags[f"{single}-config"])
                save(state)
                return out({"ETag": etag(flags["id"], state)})

        if command == "list-distributions":
            items = [{"Id": i, "Comment": d["config"]["Comment"], "DomainName": d["domain"]} for i, d in state["distributions"].items()]
            return out({"DistributionList": {"Items": items} if items else {"Quantity": 0}})
        if command == "create-distribution-with-tags":
            made = value(flags["distribution-config-with-tags"])
            state["distributions"]["EDIRECT1"] = {"config": made["DistributionConfig"], "tags": made["Tags"], "domain": "ddirect1.cloudfront.net"}
            save(state)
            return out({"Distribution": {"Id": "EDIRECT1", "DomainName": "ddirect1.cloudfront.net"}})
        if command == "get-distribution-config":
            return out({"ETag": etag(flags["id"], state), "DistributionConfig": own_order(state["distributions"][flags["id"]]["config"])})
        if command == "update-distribution":
            state["distributions"][flags["id"]]["config"] = value(flags["distribution-config"])
            save(state)
            return out({"ETag": etag(flags["id"], state)})

    print(f"stub aws: unexpected call: {service} {command} {' '.join(rest)}", file=sys.stderr)
    sys.exit(99)


main()
