"""EC2-focused business tools exposed to the LangGraph agent."""

from __future__ import annotations

from langchain_core.tools import tool

from .core_payloads import terraform_payload


@tool
def generate_ec2_terraform(
    instance_type: str,
    region: str = "us-east-1",
    instance_name: str = "infrapilot-ec2",
    vpc_cidr: str = "10.50.0.0/16",
    public_subnet_cidr: str = "10.50.1.0/24",
) -> dict[str, object]:
    """Generate Terraform HCL and CLI commands for a self-contained EC2 instance."""
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

data "aws_availability_zones" "available" {{
  state = "available"
}}

resource "aws_vpc" "main" {{
  cidr_block           = "{vpc_cidr}"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {{
    Name      = "{instance_name}-vpc"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_internet_gateway" "main" {{
  vpc_id = aws_vpc.main.id

  tags = {{
    Name      = "{instance_name}-igw"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_subnet" "public" {{
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "{public_subnet_cidr}"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {{
    Name      = "{instance_name}-public-1"
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
    Name      = "{instance_name}-public-rt"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_route_table_association" "public" {{
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}}

resource "aws_security_group" "instance" {{
  name        = "{instance_name}-sg"
  description = "Allow SSH access to the EC2 instance."
  vpc_id      = aws_vpc.main.id

  ingress {{
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name      = "{instance_name}-sg"
    ManagedBy = "InfraPilot"
  }}
}}

resource "aws_instance" "main" {{
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "{instance_type}"
  subnet_id     = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.instance.id]

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

output "vpc_id" {{
  value = aws_vpc.main.id
}}
'''

    return terraform_payload(
        intent="deploy_ec2_instance",
        content=hcl,
        notes=[
            (
                "Uses the latest Amazon Linux 2023 AMI and creates a minimal public VPC, "
                "subnet, route table, and security group so the plan does not depend on a "
                "default VPC."
            )
        ],
        explanation=(
            f"Prepared Terraform to create a {instance_type} EC2 instance in {region} "
            f"with the name {instance_name} inside a minimal dedicated VPC."
        ),
    )
