"""Serve the React app from the UI S3 bucket when CloudFront is unavailable (HTTPS via API Gateway)."""
import os
import re
import boto3
s3 = boto3.client("s3")
UI_BUCKET = os.environ["UI_BUCKET"]
ASSET = re.compile(r"^assets/[A-Za-z0-9._-]+\.(js|css)$")
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "json": "application/json; charset=utf-8",
}
def _key(path):
    key = "index.html" if path in ("", "/") else path.lstrip("/")
    if key in ("index.html", "config.json") or ASSET.match(key):
        return key
    return None
def handler(event, _context):
    key = _key((event.get("rawPath") or "/").split("?")[0])
    if key is None:
        return {"statusCode": 404, "headers": {"content-type": "text/plain"}, "body": "Not found"}
    obj = s3.get_object(Bucket=UI_BUCKET, Key=key)
    return {
        "statusCode": 200,
        "headers": {"content-type": CONTENT_TYPES[key.rsplit(".", 1)[1]], "cache-control": "no-cache"},
        "body": obj["Body"].read().decode("utf-8"),
    }
