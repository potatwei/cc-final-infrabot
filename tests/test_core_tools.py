"""Checks for the default core tool surface."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from tools import CORE_TOOL_INPUT_SPECS
from tools import INFRAPILOT_TOOLS
from tools.advanced_workflow_registry import ADVANCED_WORKFLOW_TOOLS
from tools.aws_lookup_tools import (
    list_aws_regions,
    list_ec2_instance_type_offerings,
    validate_aws_region,
    validate_ec2_instance_type,
)
from tools.ec2_tools import generate_ec2_terraform
from tools.s3_tools import (
    check_s3_name_availability,
    generate_s3_static_website_terraform,
    generate_s3_terraform,
)
from tools.vpc_tools import generate_vpc_terraform


TERRAFORM_BIN = shutil.which("terraform")


class CoreToolRegistryTests(unittest.TestCase):
    def test_default_registry_exposes_only_core_tools(self) -> None:
        default_names = {tool.name for tool in INFRAPILOT_TOOLS}
        advanced_names = {tool.name for tool in ADVANCED_WORKFLOW_TOOLS}

        self.assertEqual(
            {
                "list_aws_regions",
                "validate_aws_region",
                "list_ec2_instance_type_offerings",
                "validate_ec2_instance_type",
                "check_s3_name_availability",
                "generate_s3_terraform",
                "generate_s3_static_website_terraform",
                "generate_ec2_terraform",
                "generate_vpc_terraform",
                "report_missing_inputs",
            },
            default_names,
        )
        self.assertTrue(advanced_names.isdisjoint(default_names))

    def test_core_tool_specs_cover_default_registry(self) -> None:
        core_spec_names = {
            tool.name for tool in INFRAPILOT_TOOLS if tool.name != "report_missing_inputs"
        }
        self.assertEqual(core_spec_names, set(CORE_TOOL_INPUT_SPECS))

    def test_ec2_and_s3_specs_capture_discovery_requirements(self) -> None:
        ec2_spec = CORE_TOOL_INPUT_SPECS["generate_ec2_terraform"]
        s3_spec = CORE_TOOL_INPUT_SPECS["generate_s3_terraform"]
        s3_site_spec = CORE_TOOL_INPUT_SPECS["generate_s3_static_website_terraform"]
        vpc_spec = CORE_TOOL_INPUT_SPECS["generate_vpc_terraform"]

        self.assertEqual(["instance_type", "region", "instance_name"], ec2_spec["required_inputs"])
        self.assertEqual([], ec2_spec["recommended_inputs"])
        self.assertEqual("10.50.0.0/16", ec2_spec["defaults"]["vpc_cidr"])

        self.assertEqual(["bucket_name", "region"], s3_spec["required_inputs"])
        self.assertEqual("check_s3_name_availability", s3_spec["precheck_tool"])
        self.assertEqual("validate_aws_region", s3_spec["validators"]["region"])

        self.assertEqual(["bucket_name", "region"], s3_site_spec["required_inputs"])
        self.assertEqual("index.html", s3_site_spec["defaults"]["index_document"])
        self.assertEqual("check_s3_name_availability", s3_site_spec["precheck_tool"])

        self.assertEqual(["region", "vpc_name"], vpc_spec["required_inputs"])
        self.assertEqual([], vpc_spec["recommended_inputs"])
        self.assertEqual("validate_aws_region", vpc_spec["validators"]["region"])


class AwsLookupToolTests(unittest.TestCase):
    @patch("tools.aws_lookup_tools.boto3.client")
    def test_list_aws_regions_returns_structured_lookup_payload(
        self,
        mock_client: MagicMock,
    ) -> None:
        client = mock_client.return_value
        client.describe_regions.return_value = {
            "Regions": [
                {"RegionName": "us-west-2"},
                {"RegionName": "us-east-1"},
            ]
        }

        result = list_aws_regions.invoke({})

        self.assertEqual("success", result["status"])
        self.assertEqual("list_aws_regions", result["intent"])
        self.assertEqual(["us-east-1", "us-west-2"], result["regions"])
        self.assertFalse(result["requires_confirmation"])

    @patch("tools.aws_lookup_tools.boto3.client")
    def test_validate_aws_region_marks_invalid_region(
        self,
        mock_client: MagicMock,
    ) -> None:
        client = mock_client.return_value
        client.describe_regions.return_value = {
            "Regions": [{"RegionName": "us-east-1"}, {"RegionName": "us-west-2"}]
        }

        result = validate_aws_region.invoke({"region": "east-1"})

        self.assertEqual("success", result["status"])
        self.assertFalse(result["valid"])
        self.assertIn("not a valid", result["explanation"])
        self.assertIn("us-east-1", result["notes"][0])

    @patch("tools.aws_lookup_tools.boto3.client")
    def test_list_ec2_instance_type_offerings_returns_region_offerings(
        self,
        mock_client: MagicMock,
    ) -> None:
        client = mock_client.return_value
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"InstanceTypeOfferings": [{"InstanceType": "t3.micro"}]},
            {"InstanceTypeOfferings": [{"InstanceType": "t3.small"}]},
        ]
        client.get_paginator.return_value = paginator

        result = list_ec2_instance_type_offerings.invoke({"region": "us-east-1"})

        self.assertEqual("success", result["status"])
        self.assertEqual("list_ec2_instance_type_offerings", result["intent"])
        self.assertEqual(["t3.micro", "t3.small"], result["instance_types"])
        paginator.paginate.assert_called_once()

    @patch("tools.aws_lookup_tools.boto3.client")
    def test_validate_ec2_instance_type_checks_region_availability(
        self,
        mock_client: MagicMock,
    ) -> None:
        client = mock_client.return_value
        client.describe_instance_types.return_value = {
            "InstanceTypes": [{"InstanceType": "t3.micro"}]
        }
        client.describe_instance_type_offerings.return_value = {
            "InstanceTypeOfferings": [{"InstanceType": "t3.micro"}]
        }

        result = validate_ec2_instance_type.invoke(
            {"instance_type": "t3.micro", "region": "us-east-1"}
        )

        self.assertEqual("success", result["status"])
        self.assertTrue(result["valid"])
        self.assertTrue(result["available_in_region"])
        self.assertIn("available in us-east-1", result["explanation"])


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

    def test_generate_s3_static_website_terraform_returns_agent_payload(self) -> None:
        result = generate_s3_static_website_terraform.invoke(
            {
                "bucket_name": "demo-static-site",
                "region": "us-east-1",
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("deploy_s3_static_website", result["intent"])
        self.assertEqual("main.tf", result["files"][0]["path"])
        self.assertIn('resource "aws_s3_bucket_website_configuration" "site"', result["files"][0]["content"])
        self.assertIn('output "website_url"', result["files"][0]["content"])
        self.assertIn("static website", result["explanation"].lower())
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


@unittest.skipIf(TERRAFORM_BIN is None, "terraform is not installed")
class TerraformValidationSmokeTests(unittest.TestCase):
    def _write_payload_files(self, payload: dict[str, object], target_dir: Path) -> None:
        for entry in payload["files"]:
            file_path = target_dir / entry["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(entry["content"], encoding="utf-8")

    def _run_terraform(self, working_dir: Path, *args: str) -> None:
        result = subprocess.run(
            [TERRAFORM_BIN, *args],
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            0,
            result.returncode,
            msg=(
                f"terraform {' '.join(args)} failed in {working_dir}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )

    def _assert_payload_validates(self, payload: dict[str, object]) -> None:
        with tempfile.TemporaryDirectory(prefix="infrapilot-tf-") as temp_dir:
            working_dir = Path(temp_dir)
            self._write_payload_files(payload, working_dir)
            self._run_terraform(working_dir, "fmt", "-check")
            self._run_terraform(
                working_dir,
                "init",
                "-backend=false",
                "-input=false",
                "-no-color",
            )
            self._run_terraform(working_dir, "validate", "-no-color")

    def test_generated_s3_plan_validates(self) -> None:
        payload = generate_s3_terraform.invoke(
            {"bucket_name": "infra-pilot-demo-bucket", "region": "us-east-1"}
        )
        self._assert_payload_validates(payload)

    def test_generated_s3_static_website_plan_validates(self) -> None:
        payload = generate_s3_static_website_terraform.invoke(
            {"bucket_name": "infra-pilot-static-site-demo", "region": "us-east-1"}
        )
        self._assert_payload_validates(payload)

    def test_generated_ec2_plan_validates(self) -> None:
        payload = generate_ec2_terraform.invoke(
            {
                "instance_type": "t3.micro",
                "region": "us-east-1",
                "instance_name": "infra-pilot-validate-ec2",
            }
        )
        self._assert_payload_validates(payload)

    def test_generated_vpc_plan_validates(self) -> None:
        payload = generate_vpc_terraform.invoke(
            {
                "region": "us-east-1",
                "vpc_cidr": "10.77.0.0/16",
                "vpc_name": "infra-pilot-validate-vpc",
            }
        )
        self._assert_payload_validates(payload)
