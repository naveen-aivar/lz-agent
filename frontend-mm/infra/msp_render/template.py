"""The CloudFormation template: one private S3 bucket (OAC) behind one CloudFront distribution.

Built as plain dictionaries and written as JSON; no CDK, no extra packages. Everything that varies between
runs (the agents' API origins and the two function bodies) comes in as arguments, so the output is deterministic:
the same manifests always produce byte-identical JSON and CloudFormation reports "no changes".
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .buildinfo import Agent

PROJECT = "ingram-mm-dashboard"
DEFAULT_DOMAIN = ""
DEFAULT_CERTIFICATE_ARN = "arn:aws:acm:us-east-1:455162169375:certificate/df4a2cb0-96be-4c56-9639-fad4dd000d8d"
# AWS managed policies (account independent).
CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"
CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
S3_ORIGIN_ID = "site-bucket"
API_READ_TIMEOUT_SECONDS = 60
# CloudFormation takes at most 51,200 bytes of template through --template-body / `aws cloudformation deploy`.
MAX_TEMPLATE_BYTES = 51_200
# CloudFront quotas (default): 75 cache behaviors and 100 origins per distribution.
MAX_BEHAVIORS = 75
MAX_ORIGINS = 100
TAGS = [{"Key": "Project", "Value": PROJECT}]
HTTP_METHODS = ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]


def ref(name: str) -> Dict[str, str]:
    return {"Ref": name}


def get_att(name: str, attribute: str) -> Dict[str, Any]:
    return {"Fn::GetAtt": [name, attribute]}


def api_origins(agents: List[Agent]) -> List[str]:
    """The distinct API origin domains, sorted, one CloudFront origin each."""
    return sorted({proxy.origin_domain for agent in agents for proxy in agent.api_proxy})


def api_behaviors(agents: List[Agent]) -> List[Tuple[str, str]]:
    """(path pattern, origin domain), the most specific pattern first: CloudFront tries behaviors in list order."""
    items = [(proxy.prefix + "*", proxy.origin_domain) for agent in agents for proxy in agent.api_proxy]
    return sorted(items, key=lambda item: (-len(item[0]), item[0]))


def _origin_id(domain: str) -> str:
    return "api-" + domain


def _function_association(event: str, function: str) -> Dict[str, Any]:
    return {"EventType": event, "FunctionARN": get_att(function, "FunctionARN")}


def _bucket_resources() -> Dict[str, Any]:
    bucket_name = {"Fn::Sub": PROJECT + "-${AWS::AccountId}-${AWS::Region}"}
    bucket_arn = get_att("SiteBucket", "Arn")
    distribution_arn = {"Fn::Sub": "arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}"}
    bucket_and_objects = [bucket_arn, {"Fn::Sub": "${SiteBucket.Arn}/*"}]
    via_distribution = {"StringEquals": {"AWS:SourceArn": distribution_arn}}
    return {
        "SiteBucket": {
            "Type": "AWS::S3::Bucket",
            # A non-empty bucket cannot be deleted by CloudFormation: tearing down means emptying it first on purpose.
            "DeletionPolicy": "Delete",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "BucketName": bucket_name,
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"BucketKeyEnabled": True, "ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                },
                "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
                "LifecycleConfiguration": {
                    "Rules": [
                        {
                            "Id": "abort-incomplete-uploads",
                            "Status": "Enabled",
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                        }
                    ]
                },
                "Tags": TAGS,
            },
        },
        "SiteBucketPolicy": {
            "Type": "AWS::S3::BucketPolicy",
            "Properties": {
                "Bucket": ref("SiteBucket"),
                "PolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "DenyInsecureTransport",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": bucket_and_objects,
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        },
                        {
                            "Sid": "CloudFrontReadsObjects",
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudfront.amazonaws.com"},
                            "Action": "s3:GetObject",
                            "Resource": {"Fn::Sub": "${SiteBucket.Arn}/*"},
                            "Condition": via_distribution,
                        },
                        {
                            # With list permission S3 answers a missing key with 404 instead of 403.
                            "Sid": "CloudFrontSeesMissingKeysAs404",
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudfront.amazonaws.com"},
                            "Action": "s3:ListBucket",
                            "Resource": bucket_arn,
                            "Condition": via_distribution,
                        },
                    ],
                },
            },
        },
        "OriginAccessControl": {
            "Type": "AWS::CloudFront::OriginAccessControl",
            "Properties": {
                "OriginAccessControlConfig": {
                    "Name": PROJECT + "-oac",
                    "Description": "Signs the distribution's requests to the private site bucket",
                    "OriginAccessControlOriginType": "s3",
                    "SigningBehavior": "always",
                    "SigningProtocol": "sigv4",
                }
            },
        },
    }


def _policy_resources(has_api: bool) -> Dict[str, Any]:
    resources: Dict[str, Any] = {
        "SecurityHeadersPolicy": {
            "Type": "AWS::CloudFront::ResponseHeadersPolicy",
            "Properties": {
                "ResponseHeadersPolicyConfig": {
                    "Name": PROJECT + "-security-headers",
                    "Comment": "HSTS, nosniff, X-Frame-Options DENY, referrer and permissions headers. The CSP is set by the headers function.",
                    "SecurityHeadersConfig": {
                        "StrictTransportSecurity": {
                            "AccessControlMaxAgeSec": 31536000,
                            "IncludeSubdomains": True,
                            "Preload": False,
                            "Override": True,
                        },
                        "ContentTypeOptions": {"Override": True},
                        "FrameOptions": {"FrameOption": "DENY", "Override": True},
                        "ReferrerPolicy": {"ReferrerPolicy": "strict-origin-when-cross-origin", "Override": True},
                    },
                    "CustomHeadersConfig": {
                        "Items": [
                            {
                                "Header": "Permissions-Policy",
                                "Value": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                                "Override": True,
                            }
                        ]
                    },
                }
            },
        }
    }
    if has_api:
        resources["ApiOriginRequestPolicy"] = {
            "Type": "AWS::CloudFront::OriginRequestPolicy",
            "Properties": {
                "OriginRequestPolicyConfig": {
                    "Name": PROJECT + "-api-origin",
                    "Comment": "Like Managed-AllViewerExceptHostHeader (all headers but Host, all query strings) but sends no cookies",
                    "HeadersConfig": {"HeaderBehavior": "allExcept", "Headers": ["host"]},
                    "CookiesConfig": {"CookieBehavior": "none"},
                    "QueryStringsConfig": {"QueryStringBehavior": "all"},
                }
            },
        }
    return resources


def _function_resource(name: str, comment: str, code: str) -> Dict[str, Any]:
    return {
        "Type": "AWS::CloudFront::Function",
        "Properties": {
            "Name": f"{PROJECT}-{name}",
            "AutoPublish": True,
            "FunctionCode": code,
            "FunctionConfig": {"Comment": comment, "Runtime": "cloudfront-js-2.0"},
        },
    }


def _distribution(agents: List[Agent]) -> Dict[str, Any]:
    origins: List[Dict[str, Any]] = [
        {
            "Id": S3_ORIGIN_ID,
            "DomainName": get_att("SiteBucket", "RegionalDomainName"),
            "OriginAccessControlId": get_att("OriginAccessControl", "Id"),
            "S3OriginConfig": {"OriginAccessIdentity": ""},
        }
    ]
    for domain in api_origins(agents):
        origins.append(
            {
                "Id": _origin_id(domain),
                "DomainName": domain,
                "CustomOriginConfig": {
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "https-only",
                    "OriginSSLProtocols": ["TLSv1.2"],
                    "OriginReadTimeout": API_READ_TIMEOUT_SECONDS,
                    "OriginKeepaliveTimeout": 5,
                },
            }
        )

    behaviors = [
        {
            "PathPattern": pattern,
            "TargetOriginId": _origin_id(domain),
            "ViewerProtocolPolicy": "https-only",
            "AllowedMethods": HTTP_METHODS,
            "CachedMethods": ["GET", "HEAD"],
            "Compress": False,
            "CachePolicyId": CACHING_DISABLED,
            "OriginRequestPolicyId": ref("ApiOriginRequestPolicy"),
            "ResponseHeadersPolicyId": ref("SecurityHeadersPolicy"),
            "FunctionAssociations": [_function_association("viewer-request", "RouterFunction")],
        }
        for pattern, domain in api_behaviors(agents)
    ]

    config: Dict[str, Any] = {
        "Enabled": True,
        # infra/direct.py finds the distribution by this exact text: rewording it would make a direct deploy create a second distribution.
        "Comment": "Ingram Migration and Modernization dashboard: shell, agent UIs and API proxies",
        "Aliases": {"Fn::If": ["HasAlias", [ref("DomainName")], ref("AWS::NoValue")]},
        "DefaultRootObject": "index.html",
        "HttpVersion": "http2and3",
        "IPV6Enabled": True,
        "PriceClass": "PriceClass_100",
        "Origins": origins,
        "DefaultCacheBehavior": {
            "TargetOriginId": S3_ORIGIN_ID,
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": ["GET", "HEAD"],
            "CachedMethods": ["GET", "HEAD"],
            "Compress": True,
            "CachePolicyId": CACHING_OPTIMIZED,
            "ResponseHeadersPolicyId": ref("SecurityHeadersPolicy"),
            "FunctionAssociations": [
                _function_association("viewer-request", "RouterFunction"),
                _function_association("viewer-response", "HeadersFunction"),
            ],
        },
        "ViewerCertificate": {
            "Fn::If": [
                "HasAlias",
                {
                    "AcmCertificateArn": ref("CertificateArn"),
                    "SslSupportMethod": "sni-only",
                    "MinimumProtocolVersion": "TLSv1.2_2021",
                },
                {"CloudFrontDefaultCertificate": True},
            ]
        },
    }
    if behaviors:
        config["CacheBehaviors"] = behaviors
    return {"Type": "AWS::CloudFront::Distribution", "Properties": {"DistributionConfig": config, "Tags": TAGS}}


def build_template(agents: List[Agent], router_code: str, headers_code: str) -> Dict[str, Any]:
    resources: Dict[str, Any] = {}
    resources.update(_bucket_resources())
    resources.update(_policy_resources(has_api=bool(api_behaviors(agents))))
    resources["RouterFunction"] = _function_resource(
        "router", "Viewer request: agent API proxy rewrite; any other path without a file extension is the dashboard page", router_code
    )
    resources["HeadersFunction"] = _function_resource(
        "headers", "Viewer response: the site's one Content-Security-Policy on HTML", headers_code
    )
    resources["Distribution"] = _distribution(agents)

    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Ingram Migration and Modernization dashboard: one private S3 bucket behind one CloudFront distribution (the dashboard with every agent's screens, and the agents' API proxies). Generated by frontend-mm/infra/render.py; do not edit by hand.",
        "Parameters": {
            "DomainName": {
                "Type": "String",
                "Default": DEFAULT_DOMAIN,
                "AllowedPattern": r"^$|^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$",
                "ConstraintDescription": "A lowercase host name such as mm.aivar.app, or empty to serve on the cloudfront.net name only.",
                "Description": "Alternate domain name (CNAME) for the distribution. Leave empty to run without one.",
            },
            "CertificateArn": {
                "Type": "String",
                "Default": DEFAULT_CERTIFICATE_ARN,
                "AllowedPattern": r"^$|^arn:aws:acm:us-east-1:[0-9]{12}:certificate/[0-9a-f-]{36}$",
                "ConstraintDescription": "An ACM certificate ARN in us-east-1 (CloudFront only accepts that region), or empty.",
                "Description": "ACM certificate (us-east-1) covering DomainName. Used only when DomainName is set.",
            },
        },
        "Rules": {
            "AliasNeedsCertificate": {
                "RuleCondition": {"Fn::Not": [{"Fn::Equals": [ref("DomainName"), ""]}]},
                "Assertions": [
                    {
                        "Assert": {"Fn::Not": [{"Fn::Equals": [ref("CertificateArn"), ""]}]},
                        "AssertDescription": "DomainName needs CertificateArn: a custom domain cannot be served without a certificate.",
                    }
                ],
            }
        },
        "Conditions": {"HasAlias": {"Fn::Not": [{"Fn::Equals": [ref("DomainName"), ""]}]}},
        "Resources": resources,
        "Outputs": {
            "SiteBucketName": {"Description": "Private bucket holding the whole site", "Value": ref("SiteBucket")},
            "DistributionId": {"Description": "CloudFront distribution id (for invalidations)", "Value": ref("Distribution")},
            "DistributionDomainName": {
                "Description": "The *.cloudfront.net name; the CNAME for DomainName points here",
                "Value": get_att("Distribution", "DomainName"),
            },
        },
    }


def check_limits(agents: List[Agent], template_json: str) -> List[str]:
    """Returns problems (empty if all fine) with CloudFront and CloudFormation size limits."""
    problems: List[str] = []
    behaviors, origins = len(api_behaviors(agents)), len(api_origins(agents)) + 1
    if behaviors > MAX_BEHAVIORS:
        problems.append(f"{behaviors} cache behaviors; a distribution holds at most {MAX_BEHAVIORS} by default")
    if origins > MAX_ORIGINS:
        problems.append(f"{origins} origins; a distribution holds at most {MAX_ORIGINS} by default")
    size = len(template_json.encode("utf-8"))
    if size > MAX_TEMPLATE_BYTES:
        problems.append(f"the template is {size} bytes; `aws cloudformation deploy` without an S3 bucket takes at most {MAX_TEMPLATE_BYTES}")
    return problems
