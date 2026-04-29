"""Checks for the default core tool surface."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from tools import INFRAPILOT_TOOLS
from tools.advanced_workflow_registry import ADVANCED_WORKFLOW_TOOLS
from tools.ec2_tools import generate_ec2_terraform
from tools.s3_tools import check_s3_name_availability, generate_s3_terraform
from tools.vpc_tools import generate_vpc_terraform


class CoreToolRegistryTests(unittest.TestCase):
    def test_default_registry_exposes_only_core_tools(self) -> None:
        default_names = {tool.name for tool in INFRAPILOT_TOOLS}
        advanced_names = {tool.name for tool in ADVANCED_WORKFLOW_TOOLS}

        self.assertEqual(
            {
                "check_s3_name_availability",
                "generate_s3_terraform",
                "generate_ec2_terraform",
                "generate_vpc_terraform",
            },
            default_names,
        )
        self.assertTrue(advanced_names.isdisjoint(default_names))


class S3ToolTests(unittest.TestCase):
    def test_generate_s3_terraform_returns_agent_payload(self) -> None:
        result = generate_s3_terraform.invoke(
            {"bucket_name": "demo-bucket", "region": "us-west-2"}
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("deploy_s3_bucket", result["intent"])
        self.assertEqual("main.tf", result["files"][0]["path"])
        self.assertEqual("terraform", result["files"][0]["type"])
        self.assertIn('region = "us-west-2"', result["files"][0]["content"])
        self.assertEqual("terraform", result["commands"][0]["command"]["binary"])
        self.assertTrue(result["requires_confirmation"])

    @patch("tools.s3_tools.boto3.client")
    def test_check_s3_name_availability_returns_success_when_name_is_free(
        self,
        mock_client: MagicMock,
    ) -> None:
        client = mock_client.return_value
        client.head_bucket.side_effect = ClientError(
            {
                "Error": {"Code": "NoSuchBucket"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            },
            "HeadBucket",
        )

        result = check_s3_name_availability.invoke({"bucket_name": "demo-bucket"})

        self.assertEqual("success", result["status"])
        self.assertEqual("check_s3_name_availability", result["intent"])
        self.assertTrue(result["available"])


class EC2ToolTests(unittest.TestCase):
    def test_generate_ec2_terraform_returns_agent_payload(self) -> None:
        result = generate_ec2_terraform.invoke(
            {
                "instance_type": "t3.micro",
                "region": "us-east-1",
                "instance_name": "demo-ec2",
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("deploy_ec2_instance", result["intent"])
        self.assertEqual("main.tf", result["files"][0]["path"])
        self.assertIn('instance_type          = "t3.micro"', result["files"][0]["content"])
        self.assertIn('resource "aws_vpc" "main"', result["files"][0]["content"])
        self.assertEqual("terraform", result["commands"][1]["command"]["binary"])
        self.assertTrue(result["requires_confirmation"])


class VPCToolTests(unittest.TestCase):
    def test_generate_vpc_terraform_returns_agent_payload(self) -> None:
        result = generate_vpc_terraform.invoke(
            {
                "region": "us-east-1",
                "vpc_cidr": "10.42.0.0/16",
                "vpc_name": "demo-vpc",
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("deploy_vpc_network", result["intent"])
        self.assertEqual("main.tf", result["files"][0]["path"])
        self.assertIn('cidr_block           = "10.42.0.0/16"', result["files"][0]["content"])
        self.assertEqual("terraform", result["commands"][0]["command"]["binary"])
        self.assertTrue(result["requires_confirmation"])
