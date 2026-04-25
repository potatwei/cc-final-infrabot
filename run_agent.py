"""Local smoke test for the InfraPilot agent (no FastAPI).

Builds the LangGraph workflow directly, runs it against a natural-language
query, and prints:

  1. each node's update as it happens (the agent's "thinking trace"), and
  2. the final ``final_payload`` that would be returned to the API client.

Usage (from the Infrapilot/ directory):
    python run_agent.py "create an s3 bucket named infrapilot-demo-001"
    python run_agent.py                # uses DEFAULT_QUERY below

Requires AWS credentials with Bedrock + (optionally) S3 HeadBucket access,
e.g. via `aws configure` or AWS_PROFILE / AWS_ACCESS_KEY_ID env vars.
"""

from __future__ import annotations

import json
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.bedrock_graph import build_graph

# for dynamodb, current tools only support, using this query result from error.
# DEFAULT_QUERY = "Create an dynamodb table named infrapilot-demo-table-001 in us-east-1." 
# for s3 bucket, can successfully return the expercted result..
DEFAULT_QUERY = "Create an S3 bucket named infrapilot-demo-bucket-001 in us-east-1." 


def _format_message(msg) -> str:
    """Render a single LangChain message as a one-liner for the trace."""
    if isinstance(msg, AIMessage):
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines = [f"[AI] {text}".rstrip()] if text else []
        for tc in getattr(msg, "tool_calls", None) or []:
            lines.append(f"  -> tool_call: {tc.get('name')}({tc.get('args')})")
        return "\n".join(lines) or "[AI] (empty)"
    if isinstance(msg, ToolMessage):
        name = getattr(msg, "name", "?")
        content = msg.content
        if isinstance(content, str) and len(content) > 400:
            content = content[:400] + "...<truncated>"
        return f"[TOOL/{name}] {content}"
    return f"[{type(msg).__name__}] {getattr(msg, 'content', msg)!r}"


def run(query: str) -> dict | None:
    graph = build_graph()
    inputs = {"messages": [HumanMessage(content=f"User request: {query}")]}

    print("=" * 72)
    print(f"USER QUERY: {query}")
    print("=" * 72)

    final_payload: dict | None = None

    for step, update in enumerate(graph.stream(inputs, stream_mode="updates"), start=1):
        for node_name, delta in update.items():
            print(f"\n--- step {step}: node = {node_name} ---")

            for msg in delta.get("messages", []) or []:
                print(_format_message(msg))

            if "final_payload" in delta:
                final_payload = delta["final_payload"]
                print("[formatter] final_payload set "
                      f"(status={final_payload.get('status')}, "
                      f"files={len(final_payload.get('files', []))}, "
                      f"commands={len(final_payload.get('commands', []))})")

    print("\n" + "=" * 72)
    print("FINAL PAYLOAD")
    print("=" * 72)
    if final_payload:
        print(json.dumps(final_payload, indent=2))
    else:
        print("(no final_payload was produced)")

    return final_payload


if __name__ == "__main__":
    cli_query = " ".join(sys.argv[1:]).strip()
    run(cli_query or DEFAULT_QUERY)
