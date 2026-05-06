"""Real backend client (Part 2).

Talks to Person A's FastAPI backend:

    POST /api/task                  -> task envelope; status starts as "pending"
    GET  /api/task/{id}             -> poll until status leaves "pending"
    POST /api/task/{id}/continue    -> multi-turn (more inputs / execute)
    POST /api/task/{id}/confirm     -> mark task complete
"""

from __future__ import annotations

import time

import httpx


class HttpClient:
    def __init__(self, api_url: str, api_key: str,
                 poll_interval: float = 2.0, poll_timeout: float = 120.0) -> None:
        self._client = httpx.Client(
            base_url=api_url.rstrip("/") + "/api",
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=30.0,
        )
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def submit(self, user_prompt: str) -> dict:
        r = self._client.post(
            "/task",
            json={"user_prompt": user_prompt, "mode": "execution"},
        )
        r.raise_for_status()
        return self._wait_for_payload(r.json())

    def continue_task(self, task_id: str, user_input: str | None = None,
                      provided_inputs: dict | None = None,
                      execute: bool = False) -> dict:
        body = {
            "user_input": user_input,
            "provided_inputs": provided_inputs or {},
            "execute": execute,
        }
        r = self._client.post(f"/task/{task_id}/continue", json=body)
        r.raise_for_status()
        return self._wait_for_payload(r.json())

    def get_task(self, task_id: str) -> dict:
        """Fetch a task envelope by id and return its code_payload (with status)."""
        r = self._client.get(f"/task/{task_id}")
        r.raise_for_status()
        task = r.json()
        payload = dict(task.get("code_payload") or {})
        payload["task_id"] = task_id
        payload["status"] = task.get("status") or payload.get("status") or ""
        return payload

    def confirm(self, task_id: str, approved: bool) -> dict:
        if not approved:
            return {"status": "cancelled", "task_id": task_id,
                    "message": "User declined. Backend was not asked to execute."}
        try:
            r = self._client.post(f"/task/{task_id}/confirm")
            r.raise_for_status()
        except httpx.HTTPError as e:
            return {"status": "error", "task_id": task_id, "message": str(e)}
        body = r.json() if r.content else {}
        return {"status": "executed", "task_id": task_id,
                "message": body.get("message", "Task marked complete.")}

    def _wait_for_payload(self, task: dict) -> dict:
        task_id = task["task_id"]
        if task.get("status") == "pending" or task.get("code_payload") is None:
            print("Waiting for backend...", flush=True)
        deadline = time.monotonic() + self._poll_timeout
        while task.get("status") == "pending" or task.get("code_payload") is None:
            if time.monotonic() > deadline:
                return {"status": "error", "task_id": task_id,
                        "message": f"Backend did not return a payload within "
                                   f"{self._poll_timeout:.0f}s."}
            time.sleep(self._poll_interval)
            r = self._client.get(f"/task/{task_id}")
            r.raise_for_status()
            task = r.json()
        payload = dict(task.get("code_payload") or {})
        payload["task_id"] = task_id
        # Outer envelope status is the lifecycle source of truth
        # ("needs_input" / "awaiting_confirmation" / "planned" / "failed" / "complete").
        payload["status"] = task.get("status") or payload.get("status") or "success"
        return payload
