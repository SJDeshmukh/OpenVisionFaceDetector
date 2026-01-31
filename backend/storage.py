import os
import base64
try:
    import boto3
    from botocore.client import Config
except Exception:
    boto3 = None
    Config = None
from datetime import timedelta

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET")
OBJECT_STORAGE_ENABLED = bool(S3_BUCKET and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and boto3)

def get_s3():
    if not OBJECT_STORAGE_ENABLED:
        return None
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4") if Config else None
    )

def upload_base64_image(name, b64_data):
    s3 = get_s3()
    if not s3:
        return None
    key = f"faces/{name}.jpg"
    data = b64_data.split(",")[-1] if "," in b64_data else b64_data
    body = base64.b64decode(data)
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType="image/jpeg", ACL="private")
    return f"s3://{S3_BUCKET}/{key}"

def presigned_url_for_key(s3_url, expires_seconds=3600):
    s3 = get_s3()
    if not s3 or not s3_url or not s3_url.startswith("s3://"):
        return None
    _, _, rest = s3_url.partition("s3://")
    bucket, _, key = rest.partition("/")
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
