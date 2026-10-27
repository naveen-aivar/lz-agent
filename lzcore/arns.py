"""IAM role ARN parsing shared by the deploy target (``aws_target_session``) and the Transform
role (``transform_credentials``). Deterministic, stdlib only, no network."""
from __future__ import annotations

import re
from typing import NamedTuple

PARTITIONS = ("aws", "aws-cn", "aws-us-gov")
_ACCOUNT_RE = re.compile(r"^\d{12}$")
# IAM role names: 1-64 of [A-Za-z0-9+=,.@_-]. Path segments use printable ASCII without "/".
_ROLE_NAME_RE = re.compile(r"^[\w+=,.@-]{1,64}$", re.ASCII)
_PATH_SEGMENT_RE = re.compile(r"^[\x21-\x2E\x30-\x7E]+$")


class RoleArn(NamedTuple):
    partition: str
    account_id: str
    resource: str  # "role/<path/>name"
    role_name: str  # name without the IAM path (STS assumed-role ARNs use this)


def parse_role_arn(arn: str, *, label: str) -> RoleArn:
    """Parse ``arn:<partition>:iam::<account>:role/[<path>/]<name>`` or raise ValueError.

    ``label`` names the setting being parsed (for example ``deployTarget.roleArn`` or
    ``TRANSFORM_ROLE_ARN``) so the error tells the caller which value to fix.
    """
    expected = "arn:<partition>:iam::<account>:role/<name>"
    parts = (arn or "").split(":", 5)
    if len(parts) != 6 or parts[0] != "arn":
        raise ValueError(f"{label} {arn!r} is not an ARN (expected {expected})")
    _, partition, service, region, account_id, resource = parts
    if partition not in PARTITIONS:
        raise ValueError(f"{label} partition {partition!r} must be one of {list(PARTITIONS)}")
    if service != "iam" or region != "":
        raise ValueError(f"{label} {arn!r} must be an IAM ARN (service iam, empty region; expected {expected})")
    if not _ACCOUNT_RE.fullmatch(account_id):
        raise ValueError(f"{label} account {account_id!r} must be a 12-digit AWS account id")
    if not resource.startswith("role/"):
        raise ValueError(f"{label} {arn!r} must name an IAM role (resource role/<name>)")
    segments = resource[len("role/"):].split("/")
    role_name = segments[-1]
    if not _ROLE_NAME_RE.fullmatch(role_name):
        raise ValueError(
            f"{label} {arn!r} has an invalid role name {role_name!r} (1-64 characters of A-Z a-z 0-9 +=,.@_-)"
        )
    for segment in segments[:-1]:
        if not _PATH_SEGMENT_RE.fullmatch(segment):
            raise ValueError(f"{label} {arn!r} has an invalid IAM path segment {segment!r}")
    return RoleArn(partition, account_id, resource, role_name)
