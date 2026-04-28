"""Real backend client (Part 2).

Talks to Person A's FastAPI backend:

    POST /api/task                 -> {task_id, status: "pending", code_payload: null}
    GET  /api/task/{id}            -> poll until code_payload is non-null
    POST /api/task/{id}/confirm    -> {message: "..."}
"""

from __future__ import annotations

import time

import httpx


class HttpClient:
    def __init__(self, api_url: str, api_key: str,
                 poll_interval: float = 2.0, poll_timeout: float = 60.0) -> None:
        self._client = httpx.Client(
            base_url=api_url.rstrip("/") + "/api",
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=30.0,
        )
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def submit(self, user_prompt: str) -> dict:
        r = self._client.post("/task", json={"user_prompt": user_prompt})
        r.raise_for_status()
        task = r.json()
        task_id = task["task_id"]

        if task.get("code_payload") is None:
            print("Waiting for backend...", flush=True)
        deadline = time.monotonic() + self._poll_timeout
        while task.get("code_payload") is None:
            r = self._client.get(f"/task/{task_id}")
            r.raise_for_status()
            task = r.json()
            if task.get("code_payload") is not None:
                break
            if time.monotonic() > deadline:
                return {"status": "error", "task_id": task_id,
                        "message": f"Backend did not return a payload within "
                                   f"{self._poll_timeout:.0f}s."}
            time.sleep(self._poll_interval)

        payload = dict(task["code_payload"])
        payload["task_id"] = task_id
        payload.setdefault("status", "success")
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
