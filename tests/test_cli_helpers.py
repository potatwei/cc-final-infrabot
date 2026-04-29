"""Checks for the lightweight backend CLI helper logic."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from infrapilot_cli import determine_next_step, print_response_summary, run_chat


class CliHelperTests(unittest.TestCase):
    def test_collecting_input_maps_to_prompt_loop(self) -> None:
        response = {
            "status": "collecting_input",
            "code_payload": {
                "status": "needs_input",
                "missing_inputs": ["instance_type"],
            },
        }

        self.assertEqual("collect_input", determine_next_step(response))

    def test_ready_to_execute_maps_to_execute(self) -> None:
        response = {
            "status": "ready_to_execute",
            "code_payload": {
                "status": "success",
                "ready_to_execute": True,
            },
        }

        self.assertEqual("execute", determine_next_step(response))

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

    @patch("infrapilot_cli.run_deploy", return_value=0)
    @patch("builtins.input", side_effect=["Create a VPC in us-east-1", "exit"])
    def test_chat_mode_dispatches_requests_to_run_deploy(
        self,
        _mock_input,
        mock_run_deploy,
    ) -> None:
        result = run_chat(base_url="http://127.0.0.1:8000", auto_confirm=False)

        self.assertEqual(0, result)
        mock_run_deploy.assert_called_once_with(
            "Create a VPC in us-east-1",
            base_url="http://127.0.0.1:8000",
            auto_confirm=False,
        )

    @patch("builtins.input", side_effect=["exit"])
    def test_chat_mode_exits_cleanly(self, _mock_input) -> None:
        self.assertEqual(0, run_chat(base_url="http://127.0.0.1:8000"))


if __name__ == "__main__":
    unittest.main()
