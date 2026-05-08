"""Checks for the lightweight backend CLI helper logic."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from infrapilot_cli import (
    determine_next_step,
    _resolve_lookup_prompt,
    _build_discovery_display_inputs,
    print_response_summary,
    prompt_for_discovery_input,
    run_chat,
)


class CliHelperTests(unittest.TestCase):
    def test_collecting_input_maps_to_prompt_loop(self) -> None:
        response = {
            "status": "collecting_input",
            "code_payload": {
                "status": "needs_input",
                "mode": "discovery",
                "missing_inputs": ["instance_type"],
            },
        }

        self.assertEqual("review", determine_next_step(response))

    def test_ready_to_execute_maps_to_review(self) -> None:
        response = {
            "status": "ready_to_execute",
            "code_payload": {
                "status": "success",
                "mode": "discovery",
                "ready_to_execute": True,
            },
        }

        self.assertEqual("review", determine_next_step(response))

    def test_awaiting_confirmation_maps_to_done(self) -> None:
        response = {
            "status": "awaiting_confirmation",
            "code_payload": {
                "status": "success",
            },
        }

        self.assertEqual("done", determine_next_step(response))

    def test_lookup_summary_prints_regions_and_validity(self) -> None:
        response = {
            "task_id": "task-123",
            "status": "planned",
            "code_payload": {
                "status": "success",
                "intent": "list_aws_regions",
                "valid": True,
                "regions": ["us-east-1", "us-west-2"],
                "explanation": "Available AWS regions include: us-east-1, us-west-2",
            },
        }

        with patch("sys.stdout", new=StringIO()) as stdout:
            print_response_summary(response)

        output = stdout.getvalue()
        self.assertIn("valid: True", output)
        self.assertIn("regions:", output)
        self.assertIn("us-east-1", output)

    def test_discovery_summary_prints_notes(self) -> None:
        response = {
            "task_id": "task-456",
            "status": "collecting_input",
            "code_payload": {
                "status": "needs_input",
                "mode": "discovery",
                "selected_tool": "generate_vpc_terraform",
                "provided_inputs": {"region": "east-1"},
                "missing_inputs": ["region"],
                "notes": ["Try one of: us-east-1, us-west-2"],
                "explanation": "The region 'east-1' does not look valid.",
            },
        }

        with patch("sys.stdout", new=StringIO()) as stdout:
            print_response_summary(response)

        output = stdout.getvalue()
        self.assertIn("notes:", output)
        self.assertIn("Try one of: us-east-1, us-west-2", output)

    def test_discovery_summary_merges_defaults_into_display_inputs(self) -> None:
        response = {
            "task_id": "task-789",
            "status": "collecting_input",
            "code_payload": {
                "status": "needs_input",
                "mode": "discovery",
                "selected_tool": "generate_ec2_terraform",
                "required_inputs": ["instance_type"],
                "recommended_inputs": ["region"],
                "optional_inputs": ["instance_name"],
                "defaults": {
                    "region": "us-east-1",
                    "instance_name": "infrapilot-ec2",
                },
                "provided_inputs": {
                    "instance_type": "bad-type",
                },
                "missing_inputs": ["instance_type"],
                "notes": ["instance_type: provide a value like t3.micro."],
                "explanation": "The instance type 'bad-type' does not look valid.",
            },
        }

        with patch("sys.stdout", new=StringIO()) as stdout:
            print_response_summary(response)

        output = stdout.getvalue()
        self.assertIn("provided_inputs:", output)
        self.assertIn("instance_type: bad-type", output)
        self.assertIn("region: us-east-1", output)
        self.assertIn("instance_name: infrapilot-ec2", output)

    @patch("builtins.input", side_effect=["cancel"])
    def test_prompt_for_discovery_input_allows_cancel_keyword(self, _mock_input) -> None:
        response = {
            "code_payload": {
                "mode": "discovery",
                "missing_inputs": ["bucket_name"],
            }
        }

        with self.assertRaises(KeyboardInterrupt):
            prompt_for_discovery_input(response)

    @patch("builtins.input", side_effect=["confirm"])
    def test_prompt_for_discovery_input_accepts_confirm(self, _mock_input) -> None:
        response = {
            "code_payload": {
                "mode": "discovery",
                "ready_to_execute": True,
            }
        }

        self.assertEqual(("confirm", None), prompt_for_discovery_input(response))

    @patch("builtins.input", side_effect=["exit"])
    def test_chat_mode_exits_cleanly(self, _mock_input) -> None:
        self.assertEqual(0, run_chat(base_url="http://127.0.0.1:8000"))

    def test_resolve_lookup_prompt_uses_active_region(self) -> None:
        active_response = {
            "code_payload": {
                "mode": "discovery",
                "required_inputs": ["instance_type"],
                "recommended_inputs": ["region"],
                "optional_inputs": [],
                "defaults": {"region": "us-east-1"},
                "provided_inputs": {"region": "us-east-2"},
            }
        }

        self.assertEqual(
            "what instance types are available in us-east-2",
            _resolve_lookup_prompt("instance_types", active_response),
        )

    def test_build_discovery_display_inputs_includes_defaults_and_missing(self) -> None:
        payload = {
            "required_inputs": ["instance_type"],
            "recommended_inputs": ["region"],
            "optional_inputs": ["instance_name"],
            "defaults": {"region": "us-east-1"},
            "provided_inputs": {"instance_name": "web-box"},
        }

        self.assertEqual(
            {
                "instance_type": "(missing)",
                "region": "us-east-1",
                "instance_name": "web-box",
            },
            _build_discovery_display_inputs(payload),
        )

    @patch("infrapilot_cli.print_task_table")
    @patch("infrapilot_cli.list_tasks", return_value=[{"task_id": "task-1", "status": "planned", "user_prompt": "build ec2"}])
    @patch("builtins.input", side_effect=["/tasks", "exit"])
    def test_chat_mode_supports_tasks_command(
        self,
        _mock_input,
        mock_list_tasks,
        mock_print_task_table,
    ) -> None:
        result = run_chat(base_url="http://127.0.0.1:8000", auto_confirm=False)

        self.assertEqual(0, result)
        mock_list_tasks.assert_called_once_with(base_url="http://127.0.0.1:8000", limit=10)
        mock_print_task_table.assert_called_once()


if __name__ == "__main__":
    unittest.main()
