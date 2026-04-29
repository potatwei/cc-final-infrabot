"""Advanced ECS/Fargate workflow tool registry.

This module is intentionally separate from the default ``tools`` package
surface so the core agent can run without importing workflow-core.
"""

from .workflow_tools import (
    plan_deploy_service,
    plan_scale_service,
    plan_setup_infra,
    plan_stop_service,
    plan_teardown_infra,
    plan_teardown_service,
)

ADVANCED_WORKFLOW_TOOLS = [
    plan_setup_infra,
    plan_deploy_service,
    plan_scale_service,
    plan_stop_service,
    plan_teardown_service,
    plan_teardown_infra,
]

WORKFLOW_TOOLS = ADVANCED_WORKFLOW_TOOLS

__all__ = [
    "ADVANCED_WORKFLOW_TOOLS",
    "WORKFLOW_TOOLS",
    "plan_setup_infra",
    "plan_deploy_service",
    "plan_scale_service",
    "plan_stop_service",
    "plan_teardown_service",
    "plan_teardown_infra",
]
