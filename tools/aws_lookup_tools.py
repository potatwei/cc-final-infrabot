"""Read-only AWS lookup and validation tools for discovery flows."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError
from langchain_core.tools import tool


def _lookup_payload(
    *,
    intent: str,
    explanation: str,
    notes: list[str] | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, object]:
    """Build a read-only tool response that fits the current payload contract."""
    status = "error" if error else "success"
    return {
        "status": status,
        "intent": intent,
        "files": [],
        "commands": [],
        "notes": notes or [],
        "requires_confirmation": False,
        "steps": [],
        "error": error,
        "missing_parameters": [],
        "explanation": explanation,
        **extra,
    }


def _suggest_regions(region: str, candidates: list[str]) -> list[str]:
    """Offer a few plausible region suggestions for typo-like inputs."""
    region = region.strip().lower()
    prefix_matches = [candidate for candidate in candidates if candidate.startswith(region[:2])]
    if prefix_matches:
        return prefix_matches[:5]

    parts = [part for part in region.split("-") if part]
    fuzzy_matches = [
        candidate
        for candidate in candidates
        if any(part in candidate for part in parts)
    ]
    return fuzzy_matches[:5]


@tool
def list_aws_regions() -> dict[str, object]:
    """List enabled AWS regions for the caller account."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    try:
        response = ec2.describe_regions(AllRegions=False)
        regions = sorted(region["RegionName"] for region in response.get("Regions", []))
        preview = ", ".join(regions[:10])
        suffix = "" if len(regions) <= 10 else ", ..."
        return _lookup_payload(
            intent="list_aws_regions",
            explanation=f"Available AWS regions include: {preview}{suffix}",
            notes=[f"Found {len(regions)} enabled regions."],
            regions=regions,
        )
    except ClientError as exc:
        return _lookup_payload(
            intent="list_aws_regions",
            explanation="Could not list AWS regions.",
            error=str(exc),
        )


@tool
def validate_aws_region(region: str) -> dict[str, object]:
    """Validate one AWS region name against the account-visible region list."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    try:
        response = ec2.describe_regions(AllRegions=False)
        regions = sorted(region_info["RegionName"] for region_info in response.get("Regions", []))
        valid = region in regions
        explanation = (
            f"{region} is a valid AWS region."
            if valid
            else f"{region} is not a valid enabled AWS region."
        )
        suggestions = _suggest_regions(region, regions)
        return _lookup_payload(
            intent="validate_aws_region",
            explanation=explanation,
            notes=([] if valid else [f"Try one of: {', '.join(suggestions)}"] if suggestions else []),
            region=region,
            valid=valid,
            suggestions=suggestions,
        )
    except ClientError as exc:
        return _lookup_payload(
            intent="validate_aws_region",
            explanation=f"Could not validate region {region}.",
            error=str(exc),
            region=region,
            valid=False,
            suggestions=[],
        )


@tool
def list_ec2_instance_type_offerings(region: str) -> dict[str, object]:
    """List EC2 instance types currently offered in one AWS region."""
    ec2 = boto3.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_instance_type_offerings")
    try:
        instance_types: set[str] = set()
        for page in paginator.paginate(
            LocationType="region",
            Filters=[{"Name": "location", "Values": [region]}],
        ):
            for offering in page.get("InstanceTypeOfferings", []):
                instance_types.add(offering["InstanceType"])

        ordered = sorted(instance_types)
        preview = ", ".join(ordered[:10])
        suffix = "" if len(ordered) <= 10 else ", ..."
        return _lookup_payload(
            intent="list_ec2_instance_type_offerings",
            explanation=f"EC2 instance types in {region} include: {preview}{suffix}",
            notes=[f"Found {len(ordered)} instance type offerings in {region}."],
            region=region,
            instance_types=ordered,
        )
    except ClientError as exc:
        return _lookup_payload(
            intent="list_ec2_instance_type_offerings",
            explanation=f"Could not list EC2 instance types for {region}.",
            error=str(exc),
            region=region,
            instance_types=[],
        )


@tool
def validate_ec2_instance_type(instance_type: str, region: str) -> dict[str, object]:
    """Validate one EC2 instance type globally and within a target region."""
    ec2 = boto3.client("ec2", region_name=region)
    try:
        describe_response = ec2.describe_instance_types(InstanceTypes=[instance_type])
        type_exists = bool(describe_response.get("InstanceTypes"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "InvalidInstanceType":
            return _lookup_payload(
                intent="validate_ec2_instance_type",
                explanation=f"{instance_type} is not a valid EC2 instance type.",
                instance_type=instance_type,
                region=region,
                valid=False,
                available_in_region=False,
            )
        return _lookup_payload(
            intent="validate_ec2_instance_type",
            explanation=f"Could not validate instance type {instance_type}.",
            error=str(exc),
            instance_type=instance_type,
            region=region,
            valid=False,
            available_in_region=False,
        )

    try:
        offerings_response = ec2.describe_instance_type_offerings(
            LocationType="region",
            Filters=[
                {"Name": "location", "Values": [region]},
                {"Name": "instance-type", "Values": [instance_type]},
            ],
        )
        available_in_region = bool(offerings_response.get("InstanceTypeOfferings"))
        explanation = (
            f"{instance_type} is available in {region}."
            if available_in_region
            else f"{instance_type} exists but is not offered in {region}."
        )
        return _lookup_payload(
            intent="validate_ec2_instance_type",
            explanation=explanation,
            instance_type=instance_type,
            region=region,
            valid=type_exists,
            available_in_region=available_in_region,
        )
    except ClientError as exc:
        return _lookup_payload(
            intent="validate_ec2_instance_type",
            explanation=f"Could not validate whether {instance_type} is available in {region}.",
            error=str(exc),
            instance_type=instance_type,
            region=region,
            valid=type_exists,
            available_in_region=False,
        )
