#!/usr/bin/env python3
"""Create or update the dashboard's AWS resources DIRECTLY (S3 + CloudFront API calls), without CloudFormation.

This is for an AWS login that may create buckets and CloudFront resources but may not use CloudFormation (the doc-ex SSO role). It reads
the SAME rendered template (.build/template.json) that `scripts/deploy.sh` would give to CloudFormation, so the two ways stay one
definition: every resource below is the template's, resolved (Ref / Fn::GetAtt / Fn::Sub / Fn::If) and translated into the shape the API
wants (CloudFormation leaves out the `Quantity` fields and spells a few keys differently).

    direct.py status   [--root R]      prints NONE (nothing created yet) or EXISTS
    direct.py plan     [--root R]      read-only: for every resource, whether it exists and whether apply would create or update it
    direct.py outputs  [--root R]      prints {"bucket", "distributionId", "distributionDomain"} of what exists (exit 1 when nothing does)
    direct.py apply    [--root R]      creates what is missing, updates what differs, waits until the distribution is deployed

Environment: AWS_PROFILE / AWS_DEFAULT_REGION as for the aws CLI; DOMAIN_NAME and CERTIFICATE_ARN (as in deploy.sh; an empty DOMAIN_NAME means no alias).
Nothing is ever deleted. Resources are found by their names, so running apply again is safe and repeats the same steps.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import key_gates

REGION = "us-east-1"
ACCOUNT = "455162169375"
NOVALUE = object()  # AWS::NoValue: the key is left out


class DirectError(Exception):
    pass


# ---- the AWS CLI ---------------------------------------------------------------------------------------------------
def aws(*args: str, ok_errors: tuple[str, ...] = ()) -> dict | list | str | None:
    """Runs `aws ... --output json`. An error whose text contains one of ok_errors returns None; any other error stops with its text."""
    proc = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, env={**os.environ, "AWS_PAGER": ""})
    if proc.returncode != 0:
        if any(text in proc.stderr for text in ok_errors):
            return None
        raise DirectError(f"aws {' '.join(args[:3])} failed: {proc.stderr.strip()[:500]}")
    out = proc.stdout.strip()
    return json.loads(out) if out else None


def with_file(data: object | str | bytes, fn):
    """Writes data to a temp file and calls fn(path)."""
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as handle:
        if isinstance(data, bytes):
            handle.write(data)
        else:
            handle.write((data if isinstance(data, str) else json.dumps(data)).encode())
        path = handle.name
    try:
        return fn(path)
    finally:
        os.unlink(path)


# ---- the template, resolved ---------------------------------------------------------------------------------------
def resolve(node, ctx: dict):
    """Resolves the CloudFormation functions the template uses. ctx maps names to values:
    parameters and resources ("DomainName", "SiteBucket") and attributes ("SiteBucket.Arn"), plus "AWS::AccountId" etc."""
    if isinstance(node, list):
        out = [resolve(item, ctx) for item in node]
        return [item for item in out if item is not NOVALUE]
    if not isinstance(node, dict):
        return node
    if len(node) == 1:
        (key, value), = node.items()
        if key == "Ref":
            if value == "AWS::NoValue":
                return NOVALUE
            return ctx[value]
        if key == "Fn::GetAtt":
            return ctx[".".join(value) if isinstance(value, list) else value]
        if key == "Fn::Sub":
            text = value
            for name, replacement in sorted(ctx.items(), key=lambda kv: -len(kv[0])):
                text = text.replace("${" + name + "}", str(replacement))
            if "${" in text:
                raise DirectError(f"unresolved name in Fn::Sub: {text}")
            return text
        if key == "Fn::If":
            condition, yes, no = value
            return resolve(yes if ctx["__conditions__"][condition] else no, ctx)
    out = {k: resolve(v, ctx) for k, v in node.items()}
    return {k: v for k, v in out.items() if v is not NOVALUE}


def listing(quantity_items: list) -> dict:
    return {"Quantity": len(quantity_items), "Items": quantity_items} if quantity_items else {"Quantity": 0}


def behavior_to_api(behavior: dict) -> dict:
    """A cache behavior as CloudFormation writes it -> as the CloudFront API wants it.

    A behavior the distribution does not already have is sent as it is (nothing to lay it over), and UpdateDistribution
    rejects that call when these flags are absent. They are CloudFront's own defaults: smooth streaming off, no trusted
    signers, no field encryption, no Lambda association, gRPC off.
    """
    out = dict(behavior)
    methods, cached = out.pop("AllowedMethods"), out.pop("CachedMethods", None)
    out["AllowedMethods"] = {**listing(methods), **({"CachedMethods": listing(cached)} if cached else {})}
    if "FunctionAssociations" in out:
        out["FunctionAssociations"] = listing(out["FunctionAssociations"])
    out.setdefault("SmoothStreaming", False)
    out.setdefault("FieldLevelEncryptionId", "")
    out.setdefault("TrustedSigners", {"Enabled": False, "Quantity": 0})
    out.setdefault("TrustedKeyGroups", {"Enabled": False, "Quantity": 0})
    out.setdefault("LambdaFunctionAssociations", {"Quantity": 0})
    out.setdefault("GrpcConfig", {"Enabled": False})
    return out


def origin_to_api(origin: dict) -> dict:
    out = dict(origin)
    custom = out.get("CustomOriginConfig")
    if custom:
        custom = dict(custom)
        custom.setdefault("HTTPPort", 80)
        custom["OriginSslProtocols"] = listing(custom.pop("OriginSSLProtocols", ["TLSv1.2"]))
        out["CustomOriginConfig"] = custom
    out.setdefault("OriginPath", "")
    out.setdefault("CustomHeaders", {"Quantity": 0})
    # Same reason as the behavior flags: a new origin is not laid over an existing one, and the update call requires these.
    out.setdefault("ConnectionAttempts", 3)
    out.setdefault("ConnectionTimeout", 10)
    out.setdefault("OriginShield", {"Enabled": False})
    out.setdefault("OriginAccessControlId", "")
    return out


def distribution_to_api(config: dict, caller_reference: str) -> dict:
    """The template's DistributionConfig (resolved) -> the API's."""
    out = {k: v for k, v in config.items() if k not in ("Origins", "CacheBehaviors", "DefaultCacheBehavior", "Aliases", "ViewerCertificate", "IPV6Enabled")}
    out["CallerReference"] = caller_reference
    out["Origins"] = listing([origin_to_api(o) for o in config["Origins"]])
    out["DefaultCacheBehavior"] = behavior_to_api(config["DefaultCacheBehavior"])
    out["CacheBehaviors"] = listing([behavior_to_api(b) for b in config.get("CacheBehaviors", [])])
    out["Aliases"] = listing(config.get("Aliases", []))
    out["IsIPV6Enabled"] = config.get("IPV6Enabled", True)
    cert = config.get("ViewerCertificate", {})
    if "AcmCertificateArn" in cert:
        out["ViewerCertificate"] = {"ACMCertificateArn": cert["AcmCertificateArn"], "SSLSupportMethod": cert["SslSupportMethod"],
                                    "MinimumProtocolVersion": cert["MinimumProtocolVersion"]}
    else:
        out["ViewerCertificate"] = cert
    return out


def headers_policy_to_api(config: dict) -> dict:
    out = dict(config)
    custom = dict(out.get("CustomHeadersConfig") or {})
    if "Items" in custom:
        out["CustomHeadersConfig"] = listing(custom["Items"])
    return out


def origin_request_policy_to_api(config: dict) -> dict:
    out = dict(config)
    headers = dict(out["HeadersConfig"])
    if "Headers" in headers:
        headers["Headers"] = listing(headers["Headers"])
    out["HeadersConfig"] = headers
    return out


IDENTITY_KEYS = ("Id", "PathPattern", "EventType")


def identity(item):
    """What names a list item in CloudFront's configuration: an origin by Id, a behavior by PathPattern, a function association by EventType."""
    if isinstance(item, dict):
        for key in IDENTITY_KEYS:
            if key in item:
                return (key, item[key])
    return None


def counterpart(current: list, wanted, index: int):
    """The item of `current` that `wanted` is about: the one with the same name (CloudFront returns its lists in an order of its own), else the one
    at the same position."""
    name = identity(wanted)
    if name is not None:
        return next((item for item in current if identity(item) == name), None)
    return current[index] if index < len(current) else None


def contains(current, desired) -> bool:
    """True when `current` holds everything `desired` says (the API adds defaults of its own, which are not differences, and returns lists in an
    order of its own)."""
    if isinstance(desired, dict):
        return isinstance(current, dict) and all(k in current and contains(current[k], v) for k, v in desired.items())
    if isinstance(desired, list):
        if not isinstance(current, list) or len(current) != len(desired):
            return False
        if all(not isinstance(item, (dict, list)) for item in desired):
            return sorted(map(str, current)) == sorted(map(str, desired))
        return all((match := counterpart(current, want, i)) is not None and contains(match, want) for i, want in enumerate(desired))
    return current == desired


def merged(current, desired):
    """`current` with everything in `desired` laid over it. CloudFront's update call needs the WHOLE configuration (logging, restrictions, each
    origin's own defaults and the rest too), so what is already there is kept and only what the template says is replaced. A list takes the template's
    items in the template's order, each laid over the item of the same name that is already there."""
    if isinstance(current, dict) and isinstance(desired, dict):
        out = dict(current)
        for key, value in desired.items():
            out[key] = merged(current[key], value) if key in current else value
        return out
    if isinstance(current, list) and isinstance(desired, list) and desired and any(isinstance(item, dict) for item in desired):
        return [merged(match, want) if (match := counterpart(current, want, i)) is not None else want for i, want in enumerate(desired)]
    return desired


def distribution_update(current: dict, desired: dict) -> dict:
    """The configuration to send to UpdateDistribution.

    ViewerCertificate is a choice of one certificate. Merging its fields would leave CloudFrontDefaultCertificate beside
    ACMCertificateArn, and CloudFront rejects that. The template's certificate replaces the one that is there."""
    out = merged(current, desired)
    if "ViewerCertificate" in desired:
        out["ViewerCertificate"] = desired["ViewerCertificate"]
    return out


# ---- the plan ------------------------------------------------------------------------------------------------------
class Stack:
    def __init__(self, root: Path, domain: str, certificate: str):
        self.template = json.loads((root / ".build" / "template.json").read_text())
        self.domain, self.certificate = domain, certificate
        r = self.template["Resources"]
        ctx = {"AWS::AccountId": ACCOUNT, "AWS::Region": REGION, "AWS::Partition": "aws", "DomainName": domain, "CertificateArn": certificate,
               "__conditions__": {"HasAlias": bool(domain)}}
        self.bucket = resolve(r["SiteBucket"]["Properties"]["BucketName"], ctx)
        ctx.update({"SiteBucket": self.bucket, "SiteBucket.Arn": f"arn:aws:s3:::{self.bucket}", "SiteBucket.RegionalDomainName": f"{self.bucket}.s3.{REGION}.amazonaws.com"})
        self.ctx = ctx
        self.res = r
        # The template has no API origin request policy while no agent is connected (nothing is proxied, so nothing would use it).
        self.has_api = "ApiOriginRequestPolicy" in r
        self.names = {
            "oac": r["OriginAccessControl"]["Properties"]["OriginAccessControlConfig"]["Name"],
            "headers_policy": r["SecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"]["Name"],
            "request_policy": r["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"]["Name"] if self.has_api else "",
            "router": r["RouterFunction"]["Properties"]["Name"],
            "headers_fn": r["HeadersFunction"]["Properties"]["Name"],
            "comment": r["Distribution"]["Properties"]["DistributionConfig"]["Comment"],
        }

    # -- finders (read-only) --
    def find_bucket(self) -> bool:
        # head-bucket prints nothing on success, so the answer is the exit code
        return subprocess.run(["aws", "s3api", "head-bucket", "--bucket", self.bucket], capture_output=True, text=True).returncode == 0

    def find_oac(self) -> str | None:
        data = aws("cloudfront", "list-origin-access-controls") or {}
        for item in (data.get("OriginAccessControlList") or {}).get("Items", []) or []:
            if item["Name"] == self.names["oac"]:
                return item["Id"]
        return None

    def find_function(self, name: str) -> dict | None:
        found = aws("cloudfront", "describe-function", "--name", name, ok_errors=("NoSuchFunctionExists",))
        return found

    def find_policy(self, kind: str, name: str) -> str | None:
        data = aws("cloudfront", f"list-{kind}", "--type", "custom") or {}
        listkey = "ResponseHeadersPolicyList" if kind == "response-headers-policies" else "OriginRequestPolicyList"
        itemkey = "ResponseHeadersPolicy" if kind == "response-headers-policies" else "OriginRequestPolicy"
        cfgkey = itemkey + "Config"
        for item in (data.get(listkey) or {}).get("Items", []) or []:
            policy = item[itemkey]
            if policy[cfgkey]["Name"] == name:
                return policy["Id"]
        return None

    def find_distribution(self) -> dict | None:
        data = aws("cloudfront", "list-distributions") or {}
        for item in (data.get("DistributionList") or {}).get("Items", []) or []:
            if item.get("Comment") == self.names["comment"]:
                return item
        return None

    def status(self) -> str:
        return "EXISTS" if (self.find_distribution() or self.find_bucket()) else "NONE"

    # -- apply --
    def ensure_bucket(self) -> None:
        props = self.res["SiteBucket"]["Properties"]
        if not self.find_bucket():
            aws("s3api", "create-bucket", "--bucket", self.bucket)
            log(f"created bucket {self.bucket}")
        aws("s3api", "put-public-access-block", "--bucket", self.bucket, "--public-access-block-configuration", json.dumps(props["PublicAccessBlockConfiguration"]))
        rules = [{"ApplyServerSideEncryptionByDefault": r["ServerSideEncryptionByDefault"], "BucketKeyEnabled": r.get("BucketKeyEnabled", False)}
                 for r in props["BucketEncryption"]["ServerSideEncryptionConfiguration"]]
        aws("s3api", "put-bucket-encryption", "--bucket", self.bucket, "--server-side-encryption-configuration", json.dumps({"Rules": rules}))
        aws("s3api", "put-bucket-ownership-controls", "--bucket", self.bucket, "--ownership-controls", json.dumps(props["OwnershipControls"]))
        lifecycle = [{"ID": r["Id"], "Status": r["Status"], "Filter": {"Prefix": ""}, "AbortIncompleteMultipartUpload": r["AbortIncompleteMultipartUpload"]}
                     for r in props["LifecycleConfiguration"]["Rules"]]
        aws("s3api", "put-bucket-lifecycle-configuration", "--bucket", self.bucket, "--lifecycle-configuration", json.dumps({"Rules": lifecycle}))
        aws("s3api", "put-bucket-tagging", "--bucket", self.bucket, "--tagging", json.dumps({"TagSet": props["Tags"]}))

    def ensure_oac(self) -> str:
        found = self.find_oac()
        if found:
            return found
        config = self.res["OriginAccessControl"]["Properties"]["OriginAccessControlConfig"]
        made = aws("cloudfront", "create-origin-access-control", "--origin-access-control-config", json.dumps(config))
        log(f"created origin access control {self.names['oac']}")
        return made["OriginAccessControl"]["Id"]

    def ensure_function(self, resource: str) -> str:
        props = self.res[resource]["Properties"]
        name, code = props["Name"], props["FunctionCode"].encode()
        config = json.dumps({"Comment": props["FunctionConfig"]["Comment"], "Runtime": props["FunctionConfig"]["Runtime"]})
        existing = self.find_function(name)
        if existing is None:
            created = with_file(code, lambda p: aws("cloudfront", "create-function", "--name", name, "--function-config", config, "--function-code", f"fileb://{p}"))
            published = aws("cloudfront", "publish-function", "--name", name, "--if-match", created["ETag"])
            log(f"created and published function {name}")
            return published["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]
        live_code = self._live_code(name)
        arn = existing["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]
        if live_code == code:
            return arn
        dev = aws("cloudfront", "describe-function", "--name", name, "--stage", "DEVELOPMENT")
        updated = with_file(code, lambda p: aws("cloudfront", "update-function", "--name", name, "--if-match", dev["ETag"], "--function-config", config, "--function-code", f"fileb://{p}"))
        aws("cloudfront", "publish-function", "--name", name, "--if-match", updated["ETag"])
        log(f"updated and published function {name}")
        return arn

    def _live_code(self, name: str) -> bytes:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            proc = subprocess.run(["aws", "cloudfront", "get-function", "--name", name, "--stage", "LIVE", path], capture_output=True, text=True)
            return Path(path).read_bytes() if proc.returncode == 0 else b""
        finally:
            os.unlink(path)

    def ensure_headers_policy(self) -> str:
        config = headers_policy_to_api(resolve(self.res["SecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"], self.ctx))
        found = self.find_policy("response-headers-policies", self.names["headers_policy"])
        if not found:
            made = aws("cloudfront", "create-response-headers-policy", "--response-headers-policy-config", json.dumps(config))
            log(f"created response headers policy {self.names['headers_policy']}")
            return made["ResponseHeadersPolicy"]["Id"]
        current = aws("cloudfront", "get-response-headers-policy", "--id", found)
        if not contains(current["ResponseHeadersPolicy"]["ResponseHeadersPolicyConfig"], config):
            aws("cloudfront", "update-response-headers-policy", "--id", found, "--if-match", current["ETag"], "--response-headers-policy-config", json.dumps(config))
            log("updated the response headers policy")
        return found

    def ensure_request_policy(self) -> str:
        config = origin_request_policy_to_api(resolve(self.res["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"], self.ctx))
        found = self.find_policy("origin-request-policies", self.names["request_policy"])
        if not found:
            made = aws("cloudfront", "create-origin-request-policy", "--origin-request-policy-config", json.dumps(config))
            log(f"created origin request policy {self.names['request_policy']}")
            return made["OriginRequestPolicy"]["Id"]
        current = aws("cloudfront", "get-origin-request-policy", "--id", found)
        if not contains(current["OriginRequestPolicy"]["OriginRequestPolicyConfig"], config):
            aws("cloudfront", "update-origin-request-policy", "--id", found, "--if-match", current["ETag"], "--origin-request-policy-config", json.dumps(config))
            log("updated the origin request policy")
        return found

    def resolved_distribution(self, ids: dict) -> dict:
        """The template's DistributionConfig with the ids and ARNs of the resources it refers to filled in."""
        ctx = {**self.ctx, "OriginAccessControl.Id": ids["oac"], "RouterFunction.FunctionARN": ids["router"], "HeadersFunction.FunctionARN": ids["headers_fn"],
               "SecurityHeadersPolicy": ids["headers_policy"]}
        if self.has_api:
            ctx["ApiOriginRequestPolicy"] = ids["request_policy"]
        return resolve(self.res["Distribution"]["Properties"]["DistributionConfig"], ctx)

    def ensure_distribution(self, ids: dict) -> dict:
        resolved = self.resolved_distribution(ids)
        for gate in key_gates.GATES:
            if ids.get(f"gate:{gate.agent}"):
                key_gates.point_at_gate(resolved, gate, ids[f"gate:{gate.agent}"])
        existing = self.find_distribution()
        tags = {"Items": [{"Key": t["Key"], "Value": t["Value"]} for t in self.res["Distribution"]["Properties"].get("Tags", [])]}
        if not existing:
            config = distribution_to_api(resolved, "ingram-mm-dashboard-1")
            made = with_file({"DistributionConfig": config, "Tags": tags}, lambda p: aws("cloudfront", "create-distribution-with-tags", "--distribution-config-with-tags", f"file://{p}"))
            log(f"created distribution {made['Distribution']['Id']}")
            return {"id": made["Distribution"]["Id"], "domain": made["Distribution"]["DomainName"]}
        current = aws("cloudfront", "get-distribution-config", "--id", existing["Id"])
        config = distribution_to_api(resolved, current["DistributionConfig"]["CallerReference"])
        if not contains(current["DistributionConfig"], config):
            whole = distribution_update(current["DistributionConfig"], config)
            with_file(whole, lambda p: aws("cloudfront", "update-distribution", "--id", existing["Id"], "--if-match", current["ETag"], "--distribution-config", f"file://{p}"))
            log(f"updated distribution {existing['Id']}")
        return {"id": existing["Id"], "domain": existing["DomainName"]}

    def put_bucket_policy(self, distribution_id: str) -> None:
        ctx = {**self.ctx, "Distribution": distribution_id}
        document = resolve(self.res["SiteBucketPolicy"]["Properties"]["PolicyDocument"], ctx)
        aws("s3api", "put-bucket-policy", "--bucket", self.bucket, "--policy", json.dumps(document))

    def apply(self) -> dict:
        self.ensure_bucket()
        ids = {"oac": self.ensure_oac(), "router": self.ensure_function("RouterFunction"), "headers_fn": self.ensure_function("HeadersFunction"),
               "headers_policy": self.ensure_headers_policy()}
        if self.has_api:
            ids["request_policy"] = self.ensure_request_policy()
        base = self.resolved_distribution(ids)
        for gate in key_gates.GATES:
            if key_gates.wanted(base, gate):
                ids[f"gate:{gate.agent}"] = key_gates.ensure_gate(gate)
                log(f"{gate.label} key gate {ids[f'gate:{gate.agent}']}")
        dist = self.ensure_distribution(ids)
        self.put_bucket_policy(dist["id"])
        log("waiting for the distribution to be deployed (a few minutes the first time) ...")
        subprocess.run(["aws", "cloudfront", "wait", "distribution-deployed", "--id", dist["id"]], check=True)
        return {"bucket": self.bucket, "distributionId": dist["id"], "distributionDomain": dist["domain"]}

    def outputs(self) -> dict | None:
        dist = self.find_distribution()
        if not dist or not self.find_bucket():
            return None
        return {"bucket": self.bucket, "distributionId": dist["Id"], "distributionDomain": dist["DomainName"]}

    def plan(self) -> list[str]:
        """Read-only: for every resource, whether it exists and whether apply would change it (a function whose live code differs from the
        rendered one, a policy or the distribution whose settings differ). Nothing here writes."""
        def line(status: str, label: str) -> str:
            return f"  {status:<12}  {label}"

        def differs(status_if_same: str, same: bool) -> str:
            return status_if_same if same else "would update"

        lines = [line("exists" if self.find_bucket() else "would create", f"S3 bucket {self.bucket} (private, encrypted, policy for CloudFront only)")]
        oac = self.find_oac()
        lines.append(line("exists" if oac else "would create", f"origin access control {self.names['oac']}"))
        arns: dict[str, str] = {}
        for key, resource in (("router", "RouterFunction"), ("headers_fn", "HeadersFunction")):
            name = self.names[key]
            found = self.find_function(name)
            if found is None:
                status = "would create"
            else:
                arns[key] = found["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]
                status = differs("up to date", self._live_code(name) == self.res[resource]["Properties"]["FunctionCode"].encode())
            lines.append(line(status, f"CloudFront function {name}"))
        policy_ids: dict[str, str] = {}
        policies = [
            ("headers_policy", "response-headers-policies", "SecurityHeadersPolicy", "ResponseHeadersPolicyConfig", "get-response-headers-policy", "ResponseHeadersPolicy"),
            ("request_policy", "origin-request-policies", "ApiOriginRequestPolicy", "OriginRequestPolicyConfig", "get-origin-request-policy", "OriginRequestPolicy"),
        ]
        if not self.has_api:
            policies = policies[:1]
        for key, kind, resource, config_key, getter, item in policies:
            found = self.find_policy(kind, self.names[key])
            if not found:
                status = "would create"
            else:
                policy_ids[key] = found
                wanted = resolve(self.res[resource]["Properties"][config_key], self.ctx)
                wanted = headers_policy_to_api(wanted) if key == "headers_policy" else origin_request_policy_to_api(wanted)
                current = aws("cloudfront", getter, "--id", found)
                status = differs("up to date", contains(current[item][config_key], wanted))
            lines.append(line(status, f"{'response headers' if key == 'headers_policy' else 'origin request'} policy {self.names[key]}"))
        template = self.res["Distribution"]["Properties"]["DistributionConfig"]
        gates: dict = {}  # the key gates this distribution needs, with their function URL host once they exist
        for gate in key_gates.GATES:
            if not key_gates.wanted(template, gate):
                continue
            gates[gate] = key_gates.find_gate_host(gate)
            if gates[gate]:
                lines.append(line("exists", f"{gate.label} key gate (signed-in calls only; the access key stays in Secrets Manager)"))
            elif key_gates.secret_exists(gate):
                lines.append(line("would create", f"{gate.label} key gate (signed-in calls only; the access key stays in Secrets Manager)"))
            else:
                lines.append(line("BLOCKED", f"{gate.label} key gate: secret {gate.secret_id} is missing in this account (infra/README.md: Key gates)"))
        dist = self.find_distribution()
        if not dist:
            status = "would create"
        elif oac and len(arns) == 2 and len(policy_ids) == len(policies):
            ids = {"oac": oac, "router": arns["router"], "headers_fn": arns["headers_fn"], **policy_ids}
            current = aws("cloudfront", "get-distribution-config", "--id", dist["Id"])
            resolved = self.resolved_distribution(ids)
            for gate, host in gates.items():
                if host:
                    key_gates.point_at_gate(resolved, gate, host)
            wanted = distribution_to_api(resolved, current["DistributionConfig"]["CallerReference"])
            status = differs("up to date", contains(current["DistributionConfig"], wanted))
        else:
            status = "would update"  # something it refers to has to be created first
        lines.append(line(status, f"CloudFront distribution ({self.names['comment']})"))
        return lines


def log(message: str) -> None:
    print(f"[direct] {message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["status", "plan", "outputs", "apply"])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    domain = os.environ.get("DOMAIN_NAME", "")
    certificate = os.environ.get("CERTIFICATE_ARN", "arn:aws:acm:us-east-1:455162169375:certificate/df4a2cb0-96be-4c56-9639-fad4dd000d8d")
    try:
        stack = Stack(Path(args.root), domain, certificate)
        if args.command == "status":
            print(stack.status())
        elif args.command == "plan":
            print("\n".join(stack.plan()))
        elif args.command == "outputs":
            out = stack.outputs()
            if out is None:
                return 1
            print(json.dumps(out))
        else:
            print(json.dumps(stack.apply()))
    except DirectError as error:
        print(f"[direct] ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
