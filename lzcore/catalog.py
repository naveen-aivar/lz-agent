"""Closed catalogs. The agent can only choose these control ids and these catalog SCP ids.
A SOW requirement that is an SCP but not in the catalog is authored under scope.customScps (validated,
rendered to custom-scps/, and not attached by the stacks). Anything else goes under scope.unsupported
and is never silently dropped.

UNVERIFIED: control ids and guidance levels were written from memory of the Control Tower catalog and have not been
checked against the current catalog (the AWS Knowledge MCP was not available when this was written).
"""
import json
import re

CT_MANAGED_OUS = ("Security", "Sandbox")  # created by Control Tower itself; referenced as targets only
MAX_CUSTOM_SCPS_PER_TARGET = 3  # AWS allows 5 per target including FullAWSAccess and Control Tower's own
SCP_MAX_CHARS = 5120

GLOBAL_SERVICES_NOT_ACTION = [
    "a4b:*", "account:*", "aws-portal:*", "budgets:*", "ce:*", "cloudfront:*", "cur:*", "globalaccelerator:*",
    "health:*", "iam:*", "organizations:*", "route53:*", "route53domains:*", "shield:*", "sts:*", "support:*",
    "trustedadvisor:*", "waf:*", "wafv2:*",
]
CT_EXEMPT_PRINCIPALS = ["arn:aws:iam::*:role/AWSControlTowerExecution", "arn:aws:iam::*:role/aws-controltower-*"]


def _stmt(sid, actions, resources="*", condition=None):
    s = {"Sid": sid, "Effect": "Deny", "Action": actions, "Resource": resources}
    if condition:
        s["Condition"] = condition
    return s


def _policy(*statements):
    return {"Version": "2012-10-17", "Statement": list(statements)}


def _deny_region(scope):
    return _policy({
        "Sid": "DenyOutsideAllowedRegions", "Effect": "Deny", "NotAction": GLOBAL_SERVICES_NOT_ACTION, "Resource": "*",
        "Condition": {
            "StringNotEquals": {"aws:RequestedRegion": scope["regions"]["allowed"]},
            "ArnNotLike": {"aws:PrincipalARN": CT_EXEMPT_PRINCIPALS},
        },
    })


SCP_CATALOG = {
    "deny-region": {
        "title": "Deny actions outside the allowed regions", "build": _deny_region,
        "note": "Generated automatically when regions.enforceDeny is true. Allowed = governed + extraAllowed.",
    },
    "deny-leave-org": {
        "title": "Prevent member accounts from leaving the organization",
        "build": lambda s: _policy(_stmt("DenyLeaveOrg", ["organizations:LeaveOrganization"])),
    },
    "deny-root-user": {
        "title": "Deny all actions by the root user in member accounts",
        "build": lambda s: _policy(_stmt("DenyRoot", "*", condition={"StringLike": {"aws:PrincipalArn": ["arn:aws:iam::*:root"]}})),
    },
    "deny-iam-users": {
        "title": "Deny creation of IAM users, access keys and login profiles",
        "build": lambda s: _policy(_stmt("DenyIamUsers", ["iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile"],
                                         condition={"ArnNotLike": {"aws:PrincipalARN": CT_EXEMPT_PRINCIPALS}})),
    },
    "protect-audit-trail": {
        "title": "Protect CloudTrail and AWS Config from being stopped or deleted",
        "build": lambda s: _policy(_stmt("ProtectAudit", [
            "cloudtrail:DeleteTrail", "cloudtrail:StopLogging", "cloudtrail:UpdateTrail",
            "config:DeleteConfigurationRecorder", "config:DeleteDeliveryChannel", "config:StopConfigurationRecorder",
        ], condition={"ArnNotLike": {"aws:PrincipalARN": CT_EXEMPT_PRINCIPALS}})),
    },
    "deny-guardduty-disable": {
        "title": "Prevent disabling GuardDuty",
        "build": lambda s: _policy(_stmt("ProtectGuardDuty", [
            "guardduty:DeleteDetector", "guardduty:DisassociateFromMasterAccount", "guardduty:UpdateDetector",
            "guardduty:DeleteMembers", "guardduty:StopMonitoringMembers"])),
    },
    "deny-s3-public-access-change": {
        "title": "Prevent removing account-level S3 Block Public Access",
        "build": lambda s: _policy(_stmt("ProtectS3Bpa", ["s3:PutAccountPublicAccessBlock"],
                                         condition={"ArnNotLike": {"aws:PrincipalARN": CT_EXEMPT_PRINCIPALS}})),
    },
}

# kind: preventive | detective. guidance: strongly_recommended | elective. Mandatory controls are enabled by Control
# Tower itself and are deliberately not listed here.
CONTROL_CATALOG = {
    "AWS-GR_RESTRICT_ROOT_USER": ("preventive", "strongly_recommended", "Disallow actions as a root user"),
    "AWS-GR_RESTRICT_ROOT_USER_ACCESS_KEYS": ("preventive", "strongly_recommended", "Disallow creation of access keys for the root user"),
    "AWS-GR_ROOT_ACCOUNT_MFA_ENABLED": ("detective", "strongly_recommended", "Detect whether MFA is enabled for the root user"),
    "AWS-GR_IAM_USER_MFA_ENABLED": ("detective", "strongly_recommended", "Detect whether MFA is enabled for IAM users"),
    "AWS-GR_ENCRYPTED_VOLUMES": ("detective", "strongly_recommended", "Detect whether EBS volumes are encrypted"),
    "AWS-GR_EBS_SNAPSHOT_PUBLIC_RESTORABLE_CHECK": ("detective", "strongly_recommended", "Detect whether public EBS snapshots exist"),
    "AWS-GR_RDS_INSTANCE_PUBLIC_ACCESS_CHECK": ("detective", "strongly_recommended", "Detect publicly accessible RDS instances"),
    "AWS-GR_RDS_SNAPSHOTS_PUBLIC_PROHIBITED": ("detective", "strongly_recommended", "Detect public RDS snapshots"),
    "AWS-GR_RDS_STORAGE_ENCRYPTED": ("detective", "strongly_recommended", "Detect unencrypted RDS storage"),
    "AWS-GR_S3_BUCKET_PUBLIC_READ_PROHIBITED": ("detective", "strongly_recommended", "Detect public read access to S3 buckets"),
    "AWS-GR_S3_BUCKET_PUBLIC_WRITE_PROHIBITED": ("detective", "strongly_recommended", "Detect public write access to S3 buckets"),
    "AWS-GR_SUBNET_AUTO_ASSIGN_PUBLIC_IP_DISABLED": ("detective", "strongly_recommended", "Detect subnets that auto-assign public IPs"),
    "AWS-GR_RESTRICTED_COMMON_PORTS": ("detective", "strongly_recommended", "Detect open common ports in security groups"),
    "AWS-GR_RESTRICTED_SSH": ("detective", "strongly_recommended", "Detect unrestricted SSH in security groups"),
    "AWS-GR_EBS_OPTIMIZED_INSTANCE": ("detective", "elective", "Detect EBS-optimized instance types without optimization"),
    "AWS-GR_DISALLOW_VPC_INTERNET_ACCESS": ("preventive", "elective", "Disallow internet access for VPC instances"),
    "AWS-GR_RESTRICT_S3_CROSS_REGION_REPLICATION": ("preventive", "elective", "Disallow S3 cross-region replication"),
    "AWS-GR_DISALLOW_CROSS_REGION_NETWORKING": ("preventive", "elective", "Disallow cross-region networking"),
}


def build_scp(scp_id, scope):
    return SCP_CATALOG[scp_id]["build"](scope)


def scp_json(scp_id, scope, pretty=False):
    doc = build_scp(scp_id, scope)
    return json.dumps(doc, indent=2) + "\n" if pretty else json.dumps(doc, separators=(",", ":"))


def cid(*parts):
    """CloudFormation logical id from arbitrary names: 'AWS-GR_RESTRICT_ROOT_USER' -> 'AwsGrRestrictRootUser'."""
    out = []
    for p in parts:
        out.extend(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", p) if w)
    return "".join(out)


def catalog_for_agent():
    return {
        "scps": {k: {"title": v["title"], **({"note": v["note"]} if "note" in v else {})} for k, v in SCP_CATALOG.items()},
        "controls": {k: {"kind": v[0], "guidance": v[1], "title": v[2]} for k, v in CONTROL_CATALOG.items()},
        "controlTowerManagedOus": list(CT_MANAGED_OUS),
        "limits": {"maxCustomScpsPerTarget": MAX_CUSTOM_SCPS_PER_TARGET, "scpMaxChars": SCP_MAX_CHARS},
        "customScpAuthoring": {
            "folder": "custom-scps/",
            "appliedByStacks": False,
            "rules": "When the catalog has no matching SCP, author the policy under customScps: "
                     "id is a lowercase slug not in this catalog, document is an IAM policy "
                     "(Version 2012-10-17) of at most scpMaxChars characters. "
                     "Action and Resource are strings or lists of strings, Sid is alphanumeric, and Principal is not allowed. "
                     "The stacks do not attach these files. They do not count against the per-target attach quota; "
                     "a warning is raised when attaching them as well would exceed it.",
        },
    }
