"""Tool registry for the InfraPilot agent.

The default agent surface should stay small and demo-friendly. Core tools
support one-shot resource planning that aligns with the current product
report, while advanced workflow tools remain available for later integration
without driving the default agent behavior.
"""

from __future__ import annotations

from typing import TypedDict

from .ec2_tools import generate_ec2_terraform
from .s3_tools import check_s3_name_availability, generate_s3_terraform
from .vpc_tools import generate_vpc_terraform


class ToolInputSpec(TypedDict):
    """Structured input requirements for discovery-mode planning."""

    intent: str
    required_inputs: list[str]
    recommended_inputs: list[str]
    optional_inputs: list[str]
    defaults: dict[str, object]
    precheck_tool: str | None

S3_TOOLS = [
    check_s3_name_availability,
    generate_s3_terraform,
]

EC2_TOOLS = [
    generate_ec2_terraform,
]

VPC_TOOLS = [
    generate_vpc_terraform,
]

CORE_TOOLS = [
    *S3_TOOLS,
    *EC2_TOOLS,
    *VPC_TOOLS,
]

CORE_TOOL_INPUT_SPECS: dict[str, ToolInputSpec] = {
    "check_s3_name_availability": {
        "intent": "check_s3_name_availability",
        "required_inputs": ["bucket_name"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": None,
    },
    "generate_s3_terraform": {
        "intent": "deploy_s3_bucket",
        "required_inputs": ["bucket_name"],
        "recommended_inputs": ["region"],
        "optional_inputs": [],
        "defaults": {"region": "us-east-1"},
        "precheck_tool": "check_s3_name_availability",
    },
    "generate_ec2_terraform": {
        "intent": "deploy_ec2_instance",
        "required_inputs": ["instance_type"],
        "recommended_inputs": ["region"],
        "optional_inputs": ["instance_name", "vpc_cidr", "public_subnet_cidr"],
        "defaults": {
            "region": "us-east-1",
            "instance_name": "infrapilot-ec2",
            "vpc_cidr": "10.50.0.0/16",
            "public_subnet_cidr": "10.50.1.0/24",
        },
        "precheck_tool": None,
    },
    "generate_vpc_terraform": {
        "intent": "deploy_vpc_network",
        "required_inputs": [],
        "recommended_inputs": ["region"],
        "optional_inputs": ["vpc_name", "vpc_cidr"],
        "defaults": {
            "region": "us-east-1",
            "vpc_name": "infrapilot-vpc",
            "vpc_cidr": "10.0.0.0/16",
        },
        "precheck_tool": None,
    },
}

INFRAPILOT_TOOLS = [*CORE_TOOLS]

__all__ = [
    "INFRAPILOT_TOOLS",
    "CORE_TOOLS",
    "CORE_TOOL_INPUT_SPECS",
    "ToolInputSpec",
    "S3_TOOLS",
    "EC2_TOOLS",
    "VPC_TOOLS",
    "check_s3_name_availability",
    "generate_s3_terraform",
    "generate_ec2_terraform",
    "generate_vpc_terraform",
]
