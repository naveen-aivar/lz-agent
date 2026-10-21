"""Closed catalogs. The agent can only choose SCP ids and control ids from these lists.
Catalog SCP JSON is built here. A requirement this SCP list cannot express is a custom SCP (customscp.py):
validated, delivered for review, and not attached by the stacks. Anything else is reported under scope.unsupported.

Verification against the Control Tower controls reference (docs.aws.amazon.com/controltower/latest/controlreference):
  * VERIFIED ids (the reference page shows the identifier): AWS-GR_RESTRICT_ROOT_USER, AWS-GR_RESTRICT_ROOT_USER_ACCESS_KEYS,
    AWS-GR_DISALLOW_CROSS_REGION_NETWORKING, AWS-GR_DISALLOW_VPC_INTERNET_ACCESS, AWS-GR_DISALLOW_VPN_CONNECTIONS,
    AWS-GR_RESTRICT_S3_CROSS_REGION_REPLICATION, AWS-GR_AUDIT_BUCKET_RETENTION_POLICY, AWS-GR_EC2_VOLUME_INUSE_CHECK.
  * The remaining detective ids exist as controls by name on the reference pages, but those pages do not print the
    identifier, so each id below is UNVERIFIED. Run the pre-flight check in the bundle README before applying.
"""
import json
import re

SECURITY_OU = "Security"  # landing zone 4.0: the OU directly under the root that holds the service-integration accounts
SANDBOX_OU = "Sandbox"
STANDARD_OUS = (SECURITY_OU, SANDBOX_OU)  # created by the generated stacks (4.0 no longer creates them); added to the scope when referenced
MAX_CUSTOM_SCPS_PER_TARGET = 3  # AWS allows 5 per target including FullAWSAccess and Control Tower's own
SCP_MAX_CHARS = 5120

# Control Tower region-deny NotAction list. Source: the controls reference, "Deny access to AWS based on the
# requested AWS Region" (primary-region-deny-policy). Global services terminate outside the governed regions.
GLOBAL_SERVICES_NOT_ACTION = [
    "a4b:*", "access-analyzer:*", "account:*", "acm:*", "activate:*", "artifact:*", "aws-marketplace-management:*",
    "aws-marketplace:*", "aws-portal:*", "billing:*", "billingconductor:*", "budgets:*", "ce:*", "chatbot:*", "chime:*",
    "cloudfront:*", "cloudtrail:LookupEvents", "compute-optimizer:*", "config:*", "consoleapp:*", "consolidatedbilling:*",
    "cur:*", "datapipeline:GetAccountLimits", "devicefarm:*", "directconnect:*", "ec2:DescribeRegions",
    "ec2:DescribeTransitGateways", "ec2:DescribeVpnGateways", "ecr-public:*", "fms:*", "freetier:*", "globalaccelerator:*",
    "health:*", "iam:*", "importexport:*", "invoicing:*", "iq:*", "kms:*", "license-manager:ListReceivedLicenses",
    "lightsail:Get*", "mobileanalytics:*", "networkmanager:*", "notifications-contacts:*", "notifications:*",
    "organizations:*", "payments:*", "pricing:*", "quicksight:DescribeAccountSubscription", "resource-explorer-2:*",
    "route53-recovery-cluster:*", "route53-recovery-control-config:*", "route53-recovery-readiness:*", "route53:*",
    "route53domains:*", "s3:CreateMultiRegionAccessPoint", "s3:DeleteMultiRegionAccessPoint",
    "s3:DescribeMultiRegionAccessPointOperation", "s3:GetAccountPublicAccessBlock", "s3:GetBucketLocation",
    "s3:GetBucketPolicyStatus", "s3:GetBucketPublicAccessBlock", "s3:GetMultiRegionAccessPoint",
    "s3:GetMultiRegionAccessPointPolicy", "s3:GetMultiRegionAccessPointPolicyStatus", "s3:GetStorageLensConfiguration",
    "s3:GetStorageLensDashboard", "s3:ListAllMyBuckets", "s3:ListMultiRegionAccessPoints", "s3:ListStorageLensConfigurations",
    "s3:PutAccountPublicAccessBlock", "s3:PutMultiRegionAccessPointPolicy", "savingsplans:*", "shield:*", "sso:*", "sts:*",
    "support:*", "supportapp:*", "supportplans:*", "sustainability:*", "tag:GetResources", "tax:*", "trustedadvisor:*",
    "vendor-insights:ListEntitledSecurityProfiles", "waf-regional:*", "waf:*", "wafv2:*",
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
        "build": lambda s: _policy(_stmt("DenyRoot", "*", condition={"StringLike": {"aws:PrincipalARN": ["arn:aws:iam::*:root"]}})),
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
            "guardduty:DeleteMembers", "guardduty:StopMonitoringMembers"],
            condition={"ArnNotLike": {"aws:PrincipalARN": CT_EXEMPT_PRINCIPALS}})),
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
    "AWS-GR_ENCRYPTED_VOLUMES": ("detective", "strongly_recommended", "Detect whether EBS volumes are encrypted"),
    "AWS-GR_EC2_VOLUME_INUSE_CHECK": ("detective", "strongly_recommended", "Detect EBS volumes that are not attached to instances"),
    "AWS-GR_EBS_OPTIMIZED_INSTANCE": ("detective", "strongly_recommended", "Detect EC2 instances without EBS optimization"),
    "AWS-GR_RDS_INSTANCE_PUBLIC_ACCESS_CHECK": ("detective", "strongly_recommended", "Detect publicly accessible RDS instances"),
    "AWS-GR_RDS_SNAPSHOTS_PUBLIC_PROHIBITED": ("detective", "strongly_recommended", "Detect public RDS snapshots"),
    "AWS-GR_RDS_STORAGE_ENCRYPTED": ("detective", "strongly_recommended", "Detect unencrypted RDS storage"),
    "AWS-GR_S3_BUCKET_PUBLIC_READ_PROHIBITED": ("detective", "strongly_recommended", "Detect public read access to S3 buckets"),
    "AWS-GR_S3_BUCKET_PUBLIC_WRITE_PROHIBITED": ("detective", "strongly_recommended", "Detect public write access to S3 buckets"),
    "AWS-GR_RESTRICTED_COMMON_PORTS": ("detective", "strongly_recommended", "Detect open common ports in security groups"),
    "AWS-GR_RESTRICTED_SSH": ("detective", "strongly_recommended", "Detect unrestricted SSH in security groups"),
    "AWS-GR_IAM_USER_MFA_ENABLED": ("detective", "elective", "Detect whether MFA is enabled for IAM users"),
    "AWS-GR_SUBNET_AUTO_ASSIGN_PUBLIC_IP_DISABLED": ("detective", "elective", "Detect subnets that auto-assign public IPs"),
    "AWS-GR_DISALLOW_VPC_INTERNET_ACCESS": ("preventive", "elective", "Disallow internet access for VPC instances"),
    "AWS-GR_DISALLOW_VPN_CONNECTIONS": ("preventive", "elective", "Disallow VPN connections"),
    "AWS-GR_RESTRICT_S3_CROSS_REGION_REPLICATION": ("preventive", "elective", "Disallow S3 cross-region replication"),
    "AWS-GR_DISALLOW_CROSS_REGION_NETWORKING": ("preventive", "elective", "Disallow cross-region networking"),
    "AWS-GR_AUDIT_BUCKET_RETENTION_POLICY": ("preventive", "elective", "Set a retention policy for the log archive"),
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
        "standardOus": list(STANDARD_OUS),  # Security (required) and Sandbox: list them under "ous" when the SOW uses them
        "accountKinds": ["management", "log-archive", "audit", "workload", "other"],
        "limits": {"maxCustomScpsPerTarget": MAX_CUSTOM_SCPS_PER_TARGET},
    }
