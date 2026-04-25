"""S3-focused business tools exposed to the LangGraph agent."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from langchain_core.tools import tool


@tool
def check_s3_name_availability(bucket_name: str) -> dict:
    """Check whether an S3 bucket name is globally available on AWS.

    Uses a HEAD request against the bucket. S3 bucket names are a global
    namespace, so a 404 means the name is free, while 403 (or other errors)
    typically indicate that the name is already taken by another account.

    Args:
        bucket_name: The desired S3 bucket name.

    Returns:
        A dict with keys ``bucket_name``, ``available`` (bool) and ``reason``.
    """
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        return {
            "bucket_name": bucket_name,
            "available": False,
            "reason": "Bucket exists and is owned/accessible by the current account.",
        }
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")

        if status == 404 or code in {"404", "NoSuchBucket"}:
            return {
                "bucket_name": bucket_name,
                "available": True,
                "reason": "No bucket with this name was found (HTTP 404).",
            }

        # 403 = exists in another account; anything else we treat as occupied/unknown.
        return {
            "bucket_name": bucket_name,
            "available": False,
            "reason": f"Name is unavailable (HTTP {status}, code={code}).",
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "bucket_name": bucket_name,
            "available": False,
            "reason": f"Unexpected error while checking bucket: {exc!s}",
        }


@tool
def generate_s3_terraform(bucket_name: str) -> dict:
    """Generate Terraform HCL and CLI commands for a minimal AWS S3 bucket.

    This is a pure string-template tool; it performs no network calls.

    Args:
        bucket_name: Name to assign to the S3 bucket resource.

    Returns:
        A dict with ``intent``, ``files`` (list of {path, content}), and
        ``commands`` (list of {step, binary, args}).
    """
    hcl = f'''resource "aws_s3_bucket" "b" {{
  bucket = "{bucket_name}"

  tags = {{
    Name      = "InfraPilot-Storage"
    ManagedBy = "InfraPilot"
  }}
}}
'''

    return {
        "intent": "deploy_s3_bucket",
        "files": [
            {"path": "main.tf", "content": hcl},
        ],
        "commands": [
            {"step": 1, "binary": "terraform", "args": ["init"]},
            {"step": 2, "binary": "terraform", "args": ["apply", "-auto-approve"]},
        ],
    }
