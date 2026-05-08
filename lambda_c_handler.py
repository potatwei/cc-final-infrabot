import json
import httpx
from tools import generate_ec2_terraform, generate_s3_terraform, generate_vpc_terraform, check_s3_name_availability, generate_s3_static_website_terraform

LAMBDA_A_URL = "https://io0k4qu4sj.execute-api.us-east-1.amazonaws.com"

# Map tool names to functions and their allowed inputs
TOOLS = {
    "generate_ec2_terraform": {
        "fn": generate_ec2_terraform,
        "inputs": ["instance_type", "region", "instance_name", "vpc_cidr", "public_subnet_cidr"]
    },
    "generate_s3_terraform": {
        "fn": generate_s3_terraform,
        "inputs": ["bucket_name", "region"]
    },
    "generate_s3_static_website_terraform": {
        "fn": generate_s3_static_website_terraform,
        "inputs": ["bucket_name", "region"]
    },
    "generate_vpc_terraform": {
        "fn": generate_vpc_terraform,
        "inputs": ["region", "vpc_cidr", "vpc_name"]
    },
    "check_s3_name_availability": {
        "fn": check_s3_name_availability,
        "inputs": ["bucket_name"]
    },
}

DEFAULTS = {
    "generate_ec2_terraform": {
        "region": "us-east-1",
        "instance_name": "infrapilot-ec2",
        "vpc_cidr": "10.50.0.0/16",
        "public_subnet_cidr": "10.50.1.0/24"
    },
    "generate_s3_terraform": {
        "region": "us-east-1"
    },
    "generate_s3_static_website_terraform": {
        "region": "us-east-1"
    },
    "generate_vpc_terraform": {
        "region": "us-east-1",
        "vpc_cidr": "10.0.0.0/16",
        "vpc_name": "infrapilot-vpc"
    },
    "check_s3_name_availability": {}
}


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        task_id = body["task_id"]
        selected_tool = body.get("selected_tool")
        provided_inputs = body.get("provided_inputs", {})

        try:
            if not selected_tool or selected_tool not in TOOLS:
                raise ValueError(f"Unknown or missing tool: {selected_tool}")

            tool_config = TOOLS[selected_tool]
            tool_fn = tool_config["fn"]
            allowed_inputs = tool_config["inputs"]

            # Merge defaults with provided inputs
            defaults = DEFAULTS.get(selected_tool, {})
            existing_inputs = body.get("existing_payload", {}).get("provided_inputs", {})

            merged_inputs = {**defaults, **existing_inputs, **provided_inputs}

            # Filter to only allowed inputs
            tool_inputs = {
                k: v for k, v in merged_inputs.items()
                if k in allowed_inputs
            }

            # Run the tool
            result = tool_fn.invoke(tool_inputs)
            result["task_id"] = task_id
            result["mode"] = "execution"

        except Exception as e:
            result = {
                "status": "error",
                "task_id": task_id,
                "mode": "execution",
                "intent": None,
                "files": [],
                "commands": [],
                "notes": [],
                "requires_confirmation": False,
                "steps": [],
                "error": str(e),
                "missing_parameters": [],
                "explanation": str(e)
            }

        # Send result back to Lambda A
        try:
            httpx.post(
                f"{LAMBDA_A_URL}/api/task/{task_id}/result",
                json=result,
                timeout=30
            )
        except Exception as e:
            print(f"Failed to send result for task {task_id}: {e}")