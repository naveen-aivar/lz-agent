"""Labeled cases. A gold case is a correct extraction and must produce no findings.
A trap is a bad extraction and passes only when the findings name the problem."""
import json

from lzcore.scope import paginate
from lzcore.session import document

SOW = ("The customer, Acme Corp, requires a Control Tower landing zone in eu-west-1 and eu-central-1 only. "
       "Logs must be retained for 7 years. Workloads and Shared OUs are required. Block root user usage. "
       "Deny AWS Marketplace subscriptions.")

DOC = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "DenyMarketplace",
        "Effect": "Deny",
        "Action": ["aws-marketplace:Subscribe"],
        "Resource": "*",
    }],
}


def _scope(**over):
    base = {
        "schemaVersion": "1",
        "customer": {"orgName": "Acme Corp"},
        "regions": {"home": "eu-west-1", "governed": ["eu-west-1", "eu-central-1"], "extraAllowed": [],
                    "explicitDeny": [], "enforceDeny": True, "denied": ["us-east-1"]},
        "logging": {"retentionDays": 2555, "accessLogRetentionDays": 365,
                    "logArchiveAccountId": "111111111111", "auditAccountId": "222222222222"},
        "evidence": {
            "regions.home": {"basis": "explicit", "source": "landing zone in eu-west-1 and eu-central-1 only"},
            "regions.governed": {"basis": "explicit", "source": "eu-west-1 and eu-central-1 only"},
            "logging.retentionDays": {"basis": "explicit", "source": "retained for 7 years"},
        },
        "ous": [{"name": "Workloads", "basis": "explicit", "source": "Workloads and Shared OUs are required"},
                {"name": "Shared", "basis": "explicit", "source": "Workloads and Shared OUs are required"}],
        "scps": [{"id": "deny-root-user", "targets": ["Workloads"], "basis": "explicit", "source": "Block root user usage"}],
        "customScps": [{
            "id": "deny-marketplace", "title": "Deny AWS Marketplace subscriptions", "targets": ["Workloads"],
            "document": DOC, "basis": "explicit", "source": "Deny AWS Marketplace subscriptions",
        }],
        "controls": [{"id": "AWS-GR_RESTRICT_ROOT_USER", "targets": ["Workloads"], "basis": "explicit",
                      "source": "Block root user usage"}],
        "unsupported": [], "assumptions": [], "openQuestions": [],
    }
    base.update(over)
    return base


def _session(sow, complete=True):
    pages = paginate(sow)
    n = len(pages)
    if not complete:
        return document("eval-run", n, [], [], [], "")
    events = [{"tool": "read_sow_page", "args": {"page": i}, "result": pages[i - 1]} for i in range(1, n + 1)]
    events.append({"tool": "save_scope", "args": {}, "result": "saved. summary={}"})
    return document("eval-run", n, range(1, n + 1), events, [{"role": "assistant", "text": pages[0][:500]}], "saved")


def _scans():
    summary = {"overall": "pass", "checks": [
        {"name": "tf-fmt", "result": "pass", "log": "scans/tf-fmt.log"},
        {"name": "cfn-lint", "result": "pass", "log": "scans/cfn-lint.log"},
    ]}
    return {"summary.json": json.dumps(summary), "tf-fmt.log": "ok\n", "cfn-lint.log": "ok\n"}


def cases():
    gold = {
        "status": "complete",
        "governed": ["eu-central-1", "eu-west-1"],
        "ou_names": ["Shared", "Workloads"],
        "catalog_ids": ["deny-region", "deny-root-user"],
        "custom_ids": ["deny-marketplace"],
        "control_ids": ["AWS-GR_RESTRICT_ROOT_USER"],
    }
    delivered = {"session": _session(SOW), "scans": _scans()}
    needs = _scope()
    needs["logging"] = dict(needs["logging"], auditAccountId="")
    needs["customScps"] = []
    bad_doc = _scope()
    bad_doc["customScps"] = [dict(bad_doc["customScps"][0], document={"Version": "2012-10-17", "Statement": [{"Effect": "Sometimes", "Action": "*", "Resource": "*"}]})]
    huge = _scope()
    huge["customScps"] = [dict(huge["customScps"][0], document={
        "Version": "2012-10-17",
        "Statement": [{"Sid": "x" * 5200, "Effect": "Deny", "Action": ["s3:GetObject"], "Resource": "*"}],
    })]
    quoted = _scope()
    quoted["ous"] = [dict(quoted["ous"][0], source="the customer demands a Quarantine OU")]
    catalog_as_custom = _scope()
    catalog_as_custom["customScps"] = [dict(catalog_as_custom["customScps"][0], id="deny-root-user")]
    return [
        {"id": "acme-custom-scp", "kind": "gold", "sow": SOW, "scope": _scope(), "gold": gold, **delivered,
         "dimensions": ["grounding", "regions", "isolation", "custom_scp", "session", "scans"]},
        {"id": "needs-input", "kind": "gold", "sow": SOW, "scope": needs,
         "gold": {"status": "needs-input", "custom_ids": [], "governed": ["eu-central-1", "eu-west-1"]}, **delivered,
         "dimensions": ["grounding", "regions", "session", "scans"]},
        {"id": "hallucinated-quote", "kind": "trap", "sow": SOW, "scope": quoted, "detect": ["quote not found"],
         "dimensions": ["grounding"]},
        {"id": "catalog-id-as-custom", "kind": "trap", "sow": SOW, "scope": catalog_as_custom, "detect": ["catalog SCP"],
         "dimensions": ["custom_scp"]},
        {"id": "bad-scp-document", "kind": "trap", "sow": SOW, "scope": bad_doc, "detect": ["Effect must be Allow or Deny"],
         "dimensions": ["custom_scp"]},
        {"id": "oversized-scp", "kind": "trap", "sow": SOW, "scope": huge, "detect": ["exceeds 5120"],
         "dimensions": ["custom_scp"]},
        {"id": "session-incomplete", "kind": "trap", "sow": SOW, "scope": _scope(), "session": _session(SOW, complete=False),
         "detect": ["session incomplete"], "dimensions": ["session"]},
    ]
