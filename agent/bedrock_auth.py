"""Optional Bedrock API key auth (AWS_BEARER_TOKEN_BEDROCK) for cross-account or IAM-less invoke."""
import json
import os


def configure_bedrock_api_key() -> None:
    """Load a Bedrock API key into AWS_BEARER_TOKEN_BEDROCK from Secrets Manager when configured."""
    arn = (os.environ.get("BEDROCK_API_KEY_SECRET_ARN") or "").strip()
    if not arn:
        return
    # AgentCore may inject a placeholder or stale bearer; always load from Secrets Manager when ARN is set.
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    raw = boto3.client("secretsmanager", region_name=region).get_secret_value(SecretId=arn).get("SecretString") or ""
    key = raw.strip()
    if raw.strip().startswith("{"):
        data = json.loads(raw)
        key = (data.get("apiKey") or data.get("key") or data.get("AWS_BEARER_TOKEN_BEDROCK") or "").strip()
    key = key.strip().strip('"').strip("'")
    if not key:
        return
    if not key.startswith("bedrock-api-key"):
        raise ValueError(
            "Bedrock API key in Secrets Manager must start with 'bedrock-api-key' "
            "(Bedrock console → API keys). Update the secret, then start a new run."
        )
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = key
