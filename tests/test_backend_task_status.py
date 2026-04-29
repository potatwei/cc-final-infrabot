"""Tests for backend task lifecycle status mapping."""

from __future__ import annotations

import os
import sys
import unittest


BACKEND_ROOT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "infrapilot-backend",
)
if BACKEND_ROOT not in sys.path:
    sys.path.append(BACKEND_ROOT)

from app.core.task_status import map_task_status


class BackendTaskStatusTests(unittest.TestCase):
    def test_success_with_confirmation_maps_to_awaiting_confirmation(self) -> None:
        payload = {"status": "success", "requires_confirmation": True}

        self.assertEqual("awaiting_confirmation", map_task_status(payload))

    def test_success_without_confirmation_maps_to_planned(self) -> None:
        payload = {"status": "success", "requires_confirmation": False}

        self.assertEqual("planned", map_task_status(payload))

    def test_needs_input_maps_to_needs_input(self) -> None:
        payload = {"status": "needs_input", "requires_confirmation": False}

        self.assertEqual("needs_input", map_task_status(payload))

    def test_error_maps_to_failed(self) -> None:
        payload = {"status": "error", "requires_confirmation": False}

        self.assertEqual("failed", map_task_status(payload))
