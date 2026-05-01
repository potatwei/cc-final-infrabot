"""Tool registry for the InfraPilot agent.

The default agent surface should stay small and demo-friendly. Core tools
support one-shot resource planning that aligns with the current product
report, while advanced workflow tools remain available for later integration
without driving the default agent behavior.
"""

from __future__ import annotations

from typing import TypedDict

from .aws_lookup_tools import (
    list_aws_regions,
    list_ec2_instance_type_offerings,
    validate_aws_region,
    validate_ec2_instance_type,
)
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
    validators: dict[str, str]

AWS_LOOKUP_TOOLS = [
    list_aws_regions,
    validate_aws_region,
    list_ec2_instance_type_offerings,
    validate_ec2_instance_type,
]

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
    *AWS_LOOKUP_TOOLS,
    *S3_TOOLS,
    *EC2_TOOLS,
    *VPC_TOOLS,
]

CORE_TOOLS_BY_NAME = {tool.name: tool for tool in CORE_TOOLS}

CORE_TOOL_INPUT_SPECS: dict[str, ToolInputSpec] = {
    "check_s3_name_availability": {
        "intent": "check_s3_name_availability",
        "required_inputs": ["bucket_name"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": None,
        "validators": {},
    },
    "list_aws_regions": {
        "intent": "list_aws_regions",
        "required_inputs": [],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": None,
        "validators": {},
    },
    "validate_aws_region": {
        "intent": "validate_aws_region",
        "required_inputs": ["region"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": None,
        "validators": {},
    },
    "list_ec2_instance_type_offerings": {
        "intent": "list_ec2_instance_type_offerings",
        "required_inputs": ["region"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": "validate_aws_region",
        "validators": {"region": "validate_aws_region"},
    },
    "validate_ec2_instance_type": {
        "intent": "validate_ec2_instance_type",
        "required_inputs": ["instance_type", "region"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": "validate_aws_region",
        "validators": {"region": "validate_aws_region"},
    },
    "generate_s3_terraform": {
        "intent": "deploy_s3_bucket",
        "required_inputs": ["bucket_name", "region"],
        "recommended_inputs": [],
        "optional_inputs": [],
        "defaults": {},
        "precheck_tool": "check_s3_name_availability",
        "validators": {"region": "validate_aws_region"},
    },
    "generate_ec2_terraform": {
        "intent": "deploy_ec2_instance",
        "required_inputs": ["instance_type", "region", "instance_name"],
        "recommended_inputs": [],
        "optional_inputs": ["vpc_cidr", "public_subnet_cidr"],
        "defaults": {
            "vpc_cidr": "10.50.0.0/16",
            "public_subnet_cidr": "10.50.1.0/24",
        },
        "precheck_tool": None,
        "validators": {
            "region": "validate_aws_region",
            "instance_type": "validate_ec2_instance_type",
        },
    },
    "generate_vpc_terraform": {
        "intent": "deploy_vpc_network",
        "required_inputs": ["region", "vpc_name"],
        "recommended_inputs": [],
        "optional_inputs": ["vpc_cidr"],
        "defaults": {
            "vpc_cidr": "10.0.0.0/16",
        },
        "precheck_tool": None,
        "validators": {"region": "validate_aws_region"},
    },
}

INFRAPILOT_TOOLS = [*CORE_TOOLS]

__all__ = [
    "INFRAPILOT_TOOLS",
    "CORE_TOOLS",
    "CORE_TOOLS_BY_NAME",
    "CORE_TOOL_INPUT_SPECS",
    "ToolInputSpec",
    "AWS_LOOKUP_TOOLS",
    "S3_TOOLS",
    "EC2_TOOLS",
    "VPC_TOOLS",
    "list_aws_regions",
    "validate_aws_region",
    "list_ec2_instance_type_offerings",
    "validate_ec2_instance_type",
    "check_s3_name_availability",
    "generate_s3_terraform",
    "generate_ec2_terraform",
    "generate_vpc_terraform",
]
