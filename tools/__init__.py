"""Tool registry for the InfraPilot agent.

The default agent surface should stay small and demo-friendly. Core tools
support one-shot resource planning that aligns with the current product
report, while advanced workflow tools remain available for later integration
without driving the default agent behavior.
"""

from .ec2_tools import generate_ec2_terraform
from .s3_tools import check_s3_name_availability, generate_s3_terraform
from .workflow_tools import (
    plan_deploy_service,
    plan_scale_service,
    plan_setup_infra,
    plan_stop_service,
    plan_teardown_infra,
    plan_teardown_service,
)

S3_TOOLS = [
    check_s3_name_availability,
    generate_s3_terraform,
]

EC2_TOOLS = [
    generate_ec2_terraform,
]

CORE_TOOLS = [
    *S3_TOOLS,
    *EC2_TOOLS,
]

ADVANCED_WORKFLOW_TOOLS = [
    plan_setup_infra,
    plan_deploy_service,
    plan_scale_service,
    plan_stop_service,
    plan_teardown_service,
    plan_teardown_infra,
]

WORKFLOW_TOOLS = ADVANCED_WORKFLOW_TOOLS

INFRAPILOT_TOOLS = [*CORE_TOOLS]

__all__ = [
    "INFRAPILOT_TOOLS",
    "CORE_TOOLS",
    "S3_TOOLS",
    "EC2_TOOLS",
    "ADVANCED_WORKFLOW_TOOLS",
    "WORKFLOW_TOOLS",
    "check_s3_name_availability",
    "generate_s3_terraform",
    "generate_ec2_terraform",
    "plan_setup_infra",
    "plan_deploy_service",
    "plan_scale_service",
    "plan_stop_service",
    "plan_teardown_service",
    "plan_teardown_infra",
]
