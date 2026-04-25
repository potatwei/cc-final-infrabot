"""Tool registry for the InfraPilot agent.

Add new resource modules under ``Infrapilot/tools/`` (e.g. ``ec2_tools.py``,
``iam_tools.py``) and append their exported tools to ``INFRAPILOT_TOOLS``
below. The agent graph imports this single list, so both ``bind_tools``
(what the LLM is told about) and ``ToolNode`` (what actually executes)
stay in sync automatically.
"""

from .s3_tools import check_s3_name_availability, generate_s3_terraform

S3_TOOLS = [
    check_s3_name_availability,
    generate_s3_terraform,
]

INFRAPILOT_TOOLS = [
    *S3_TOOLS,
]

__all__ = [
    "INFRAPILOT_TOOLS",
    "S3_TOOLS",
    "check_s3_name_availability",
    "generate_s3_terraform",
]
