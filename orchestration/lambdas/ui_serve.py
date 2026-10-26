"""Serve static UI files from the UI S3 bucket when CloudFront is unavailable (HTTPS via API Gateway)."""
import os

import boto3

s3 = boto3.client("s3")
UI_BUCKET = os.environ["UI_BUCKET"]
CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "config.json": "application/json; charset=utf-8",
}


def handler(event, _context):
    path = (event.get("rawPath") or "/").split("?")[0]
    key = "index.html" if path in ("", "/") else path.lstrip("/")
    if key not in CONTENT_TYPES:
        return {"statusCode": 404, "headers": {"content-type": "text/plain"}, "body": "Not found"}
    obj = s3.get_object(Bucket=UI_BUCKET, Key=key)
    body = obj["Body"].read().decode("utf-8")
    return {
        "statusCode": 200,
        "headers": {"content-type": CONTENT_TYPES[key], "cache-control": "no-cache"},
        "body": body,
    }
