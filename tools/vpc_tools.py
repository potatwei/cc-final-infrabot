"""VPC-focused business tools exposed to the LangGraph agent."""

from __future__ import annotations

from langchain_core.tools import tool


def _command_entry(
    *,
    step_name: str,
    description: str,
    binary: str,
    args: list[str],
) -> dict[str, object]:
    return {
        "step_name": step_name,
        "description": description,
        "critical": True,
        "command": {
            "binary": binary,
            "args": args,
        },
    }


@tool
def generate_vpc_terraform(
    region: str = "us-east-1",
    vpc_cidr: str = "10.0.0.0/16",
    vpc_name: str = "infrapilot-vpc",
) -> dict[str, object]:
    """Generate Terraform HCL and CLI commands for a basic AWS VPC."""
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

data "aws_availability_zones" "available" {{
  state = "available"
}}

resource "aws_vpc" "main" {{
  cidr_block           = "{vpc_cidr}"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {{
    Name      = "{vpc_name}"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_internet_gateway" "main" {{
  vpc_id = aws_vpc.main.id

  tags = {{
    Name      = "{vpc_name}-igw"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_subnet" "public" {{
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {{
    Name      = "{vpc_name}-public-${{count.index + 1}}"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_route_table" "public" {{
  vpc_id = aws_vpc.main.id

  route {{
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }}

  tags = {{
    Name      = "{vpc_name}-public-rt"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_route_table_association" "public" {{
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}}

output "vpc_id" {{
  value = aws_vpc.main.id
}}

output "public_subnet_ids" {{
  value = aws_subnet.public[*].id
}}
'''

    return {
        "status": "success",
        "intent": "deploy_vpc_network",
        "files": [
            {
                "path": "main.tf",
                "content": hcl,
                "type": "terraform",
            }
        ],
        "commands": [
            _command_entry(
                step_name="terraform_init",
                description="Initialize Terraform in the generated workspace.",
                binary="terraform",
                args=["init"],
            ),
            _command_entry(
                step_name="terraform_apply",
                description="Apply the VPC Terraform plan.",
                binary="terraform",
                args=["apply", "-auto-approve"],
            ),
        ],
        "notes": [
            "Creates a basic public VPC layout with two subnets and an internet gateway."
        ],
        "requires_confirmation": True,
        "steps": [],
        "error": None,
        "missing_parameters": [],
        "explanation": (
            f"Prepared Terraform to create a basic VPC named {vpc_name} in {region} "
            f"with CIDR {vpc_cidr}."
        ),
    }
