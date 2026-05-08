"""Lambda B — SQS-triggered handler for the InfraPilot agent.

Flow:
    SQS message  →  this handler  →  build_graph().invoke()  →  POST result
                                                                 to Lambda A callback

Expected SQS message body (JSON):
    {
        "task_id": "<uuid>",
        "user_prompt": "Create an S3 bucket named my-bucket in us-east-1",
        "mode": "execution"   // optional, defaults to "execution"
    }

Environment variables:
    CALLBACK_BASE_URL   Base URL of Lambda A's API, e.g.
                        https://io0k4qu4sj.execute-api.us-east-1.amazonaws.com
                        (no trailing slash)

AWS Lambda configuration:
    Handler : lambda_handler.handler
    Runtime : python3.12
    Timeout : 300 s  (agent may call Bedrock several times)
    Memory  : 512 MB
    Trigger : SQS — batch size 1, report-batch-item-failures enabled
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from langchain_core.messages import HumanMessage

from agents.bedrock_graph import build_graph

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CALLBACK_BASE_URL = os.environ.get(
    "CALLBACK_BASE_URL",
    "https://io0k4qu4sj.execute-api.us-east-1.amazonaws.com",
).rstrip("/")


def _run_agent(task_id: str, user_prompt: str, mode: str = "execution") -> dict:
    """Build and invoke the LangGraph workflow; return final_payload."""
    graph = build_graph()
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=f"User request: {user_prompt}")],
            "final_payload": {},
            "task_id": task_id,
            "mode": mode,
        }
    )
    payload = result.get("final_payload")
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Graph returned no final_payload for task_id={task_id!r}. "
            f"Raw result keys: {list(result.keys())}"
        )
    return payload


def _post_result(task_id: str, payload: dict) -> None:
    """POST the agent result back to Lambda A's callback endpoint."""
    url = f"{CALLBACK_BASE_URL}/api/task/{task_id}/result"
    logger.info("Posting result for task %s to %s", task_id, url)

    response = httpx.post(url, json=payload, timeout=30)
    response.raise_for_status()
    logger.info("Callback for task %s returned HTTP %s", task_id, response.status_code)


def handler(event: dict, context) -> dict:  # noqa: ANN001
    """Lambda entry point — processes one SQS batch."""
    batch_item_failures: list[dict] = []

    for record in event.get("Records", []):
        task_id: str | None = None
        try:
            body = json.loads(record["body"])
            task_id = body["task_id"]
            user_prompt: str = body["user_prompt"]
            mode: str = body.get("mode", "execution")

            logger.info(
                "Processing task_id=%s mode=%s prompt=%r",
                task_id, mode, user_prompt[:120],
            )

            payload = _run_agent(task_id, user_prompt, mode)

            # Use the authoritative task_id from Lambda A, not the agent's internal one.
            payload["task_id"] = task_id

            logger.info("=== FINAL PAYLOAD for task %s ===", task_id)
            logger.info("status        : %s", payload.get("status"))
            logger.info("intent        : %s", payload.get("intent"))
            logger.info("selected_tool : %s", payload.get("selected_tool"))
            logger.info("files         : %d file(s)", len(payload.get("files") or []))
            logger.info("commands      : %d command(s)", len(payload.get("commands") or []))
            logger.info("steps         : %d step(s)", len(payload.get("steps") or []))
            logger.info("notes         : %s", payload.get("notes"))
            logger.info("explanation   : %s", payload.get("explanation"))
            logger.info("error         : %s", payload.get("error"))
            logger.info("missing_params: %s", payload.get("missing_parameters"))
            logger.info("full payload  : %s", json.dumps(payload, indent=2))

            _post_result(task_id, payload)

        except Exception:  # noqa: BLE001
            logger.exception("Failed to process SQS record (task_id=%s)", task_id)
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}
