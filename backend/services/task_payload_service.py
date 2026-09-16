"""Offload large Celery payloads from the message broker.

Local storage is appropriate for the current single-EC2 deployment. Configure
S3_BUCKET before adding workers on other hosts so every worker can resolve a
payload reference.
"""
import base64
import json
import os
import time
import uuid
from pathlib import Path

PAYLOAD_DIR = Path(os.environ.get("TASK_PAYLOAD_DIR", "/tmp/openvision-task-payloads"))
PAYLOAD_TTL_SECONDS = int(os.environ.get("TASK_PAYLOAD_TTL_SECONDS", "3600"))


def offload_enabled():
    return os.environ.get("TASK_PAYLOAD_OFFLOAD", "false").strip().lower() in {"1", "true", "yes"}


def _split_image(value):
    header, encoded = value.split(",", 1) if "," in value else ("", value)
    return header, base64.b64decode(encoded, validate=True)


def _cleanup_expired_local():
    cutoff = time.time() - PAYLOAD_TTL_SECONDS
    if not PAYLOAD_DIR.exists():
        return
    for path in PAYLOAD_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def store_image_payload(value):
    if not isinstance(value, str):
        raise TypeError("Image task payload must be a base64 string")
    if not offload_enabled():
        return value
    header, raw = _split_image(value)
    payload_id = uuid.uuid4().hex
    document = json.dumps({
        "header": header,
        "image_b64": base64.b64encode(raw).decode("ascii"),
        "created_at": int(time.time()),
    }).encode("utf-8")

    try:
        from storage import S3_BUCKET, get_s3
        s3 = get_s3()
    except Exception:
        S3_BUCKET, s3 = None, None
    if s3 and S3_BUCKET:
        key = f"task-payloads/{payload_id}.json"
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=document, ContentType="application/json")
        return {"payload_ref": f"s3://{S3_BUCKET}/{key}"}

    PAYLOAD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    _cleanup_expired_local()
    path = PAYLOAD_DIR / f"{payload_id}.json"
    path.write_bytes(document)
    path.chmod(0o600)
    return {"payload_ref": f"local://{payload_id}"}


def resolve_image_payload(value):
    if not isinstance(value, dict) or not value.get("payload_ref"):
        return value, None
    ref = str(value["payload_ref"])
    cleanup = None
    if ref.startswith("local://"):
        payload_id = ref.removeprefix("local://")
        if not payload_id.isalnum():
            raise ValueError("Invalid local task payload reference")
        path = PAYLOAD_DIR / f"{payload_id}.json"
        document = json.loads(path.read_text("utf-8"))
        cleanup = lambda: path.unlink(missing_ok=True)
    elif ref.startswith("s3://"):
        bucket_key = ref.removeprefix("s3://")
        bucket, separator, key = bucket_key.partition("/")
        if not separator or not key.startswith("task-payloads/"):
            raise ValueError("Invalid S3 task payload reference")
        from storage import get_s3
        s3 = get_s3()
        if not s3:
            raise RuntimeError("S3 task payload storage is unavailable")
        from storage import S3_BUCKET
        if bucket != S3_BUCKET:
            raise ValueError("Task payload bucket does not match configured storage")
        document = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        cleanup = lambda: s3.delete_object(Bucket=bucket, Key=key)
    else:
        raise ValueError("Unsupported task payload reference")
    prefix = f"{document.get('header')}," if document.get("header") else ""
    return prefix + document["image_b64"], cleanup
