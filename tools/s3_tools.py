"""S3-focused business tools exposed to the LangGraph agent."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from langchain_core.tools import tool

from .core_payloads import terraform_payload


@tool
def check_s3_name_availability(bucket_name: str) -> dict:
    """Check whether an S3 bucket name is globally available on AWS.

    Uses a HEAD request against the bucket. S3 bucket names are a global
    namespace, so a 404 means the name is free, while 403 (or other errors)
    typically indicate that the name is already taken by another account.

    Args:
        bucket_name: The desired S3 bucket name.

    Returns:
        An agent-compatible planning payload describing whether the name is
        available and whether generation may proceed.
    """
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        return {
            "status": "needs_input",
            "intent": "check_s3_name_availability",
            "files": [],
            "commands": [],
            "notes": [
                f"S3 bucket name {bucket_name} is already in use by the current account."
            ],
            "requires_confirmation": False,
            "steps": [],
            "error": "Bucket name is unavailable.",
            "missing_parameters": [],
            "bucket_name": bucket_name,
            "available": False,
            "explanation": (
                "The requested S3 bucket name is already owned or accessible by the "
                "current AWS account. Choose a different bucket name."
            ),
        }
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")

        if status == 404 or code in {"404", "NoSuchBucket"}:
            return {
                "status": "success",
                "intent": "check_s3_name_availability",
                "files": [],
                "commands": [],
                "notes": [f"S3 bucket name {bucket_name} appears available."],
                "requires_confirmation": False,
                "steps": [],
                "error": None,
                "missing_parameters": [],
                "bucket_name": bucket_name,
                "available": True,
                "explanation": (
                    "The requested S3 bucket name appears available. Generation can proceed."
                ),
            }

        # 403 = exists in another account; anything else we treat as occupied/unknown.
        return {
            "status": "needs_input",
            "intent": "check_s3_name_availability",
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": f"Name is unavailable (HTTP {status}, code={code}).",
            "missing_parameters": [],
            "bucket_name": bucket_name,
            "available": False,
            "explanation": (
                f"The requested S3 bucket name is unavailable (HTTP {status}, code={code})."
            ),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "status": "error",
            "intent": "check_s3_name_availability",
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": f"Unexpected error while checking bucket: {exc!s}",
            "missing_parameters": [],
            "bucket_name": bucket_name,
            "available": False,
            "explanation": f"Unexpected error while checking bucket: {exc!s}",
        }


@tool
def generate_s3_terraform(bucket_name: str, region: str = "us-east-1") -> dict:
    """Generate Terraform HCL and CLI commands for a minimal AWS S3 bucket.

    This is a pure string-template tool; it performs no network calls.

    Args:
        bucket_name: Name to assign to the S3 bucket resource.
        region: AWS region to lock both provider configuration and execution to.

    Returns:
        An agent-compatible planning payload with Terraform files and commands.
    """
    hcl = f'''terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{region}"
}}

resource "aws_s3_bucket" "b" {{
  bucket = "{bucket_name}"

  tags = {{
    Name      = "InfraPilot-Storage"
    ManagedBy = "InfraPilot"
  }}
}}
'''

    return terraform_payload(
        intent="deploy_s3_bucket",
        content=hcl,
        notes=[
            f"Generates a minimal private S3 bucket configuration locked to {region}."
        ],
        explanation=(
            f"Prepared Terraform to create the S3 bucket {bucket_name} in {region}. "
            "The bucket will be private by default."
        ),
    )
