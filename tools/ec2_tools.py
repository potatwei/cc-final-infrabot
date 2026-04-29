"""EC2-focused business tools exposed to the LangGraph agent."""

from __future__ import annotations

from langchain_core.tools import tool

from .core_payloads import terraform_payload


@tool
def generate_ec2_terraform(
    instance_type: str,
    region: str = "us-east-1",
    instance_name: str = "infrapilot-ec2",
) -> dict[str, object]:
    """Generate Terraform HCL and CLI commands for a minimal EC2 instance."""
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

data "aws_ami" "amazon_linux" {{
  most_recent = true
  owners      = ["amazon"]

  filter {{
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }}
}}

resource "aws_instance" "main" {{
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "{instance_type}"

  tags = {{
    Name      = "{instance_name}"
    ManagedBy = "InfraPilot"
  }}
}}

output "instance_id" {{
  value = aws_instance.main.id
}}

output "public_ip" {{
  value = aws_instance.main.public_ip
}}
'''

    return terraform_payload(
        intent="deploy_ec2_instance",
        content=hcl,
        notes=[
            "Uses the latest Amazon Linux 2023 AMI published by Amazon in the selected region."
        ],
        explanation=(
            f"Prepared Terraform to create a {instance_type} EC2 instance in {region} "
            f"with the name {instance_name}."
        ),
    )
