"""Core shared by the agent (validation, deploy sequencing) and the Lambdas (render, attest, deploy status).

Not stdlib-only. ``transform_credentials`` imports boto3/botocore at module import, so do
``transform_ops`` and ``deploy_transform`` (which import it); ``transform_ops`` also needs
awslabs.aws-transform-mcp-server for any Transform call. ``aws_target_session``,
``deploy_target_api`` and ``discovery`` import boto3 inside the functions that build sessions.
The remaining modules are deterministic and stdlib-only.
"""
