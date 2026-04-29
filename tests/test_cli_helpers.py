"""Checks for the lightweight backend CLI helper logic."""

from __future__ import annotations

import unittest

from infrapilot_cli import determine_next_step


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


if __name__ == "__main__":
    unittest.main()
