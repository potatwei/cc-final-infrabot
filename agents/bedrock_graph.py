"""LangGraph workflow definition for the InfraPilot agent.

The graph implements a classic ReAct loop:

    agent  --tool_calls-->  action  --> agent  ...  --no tool_calls-->  formatter  -->  END

* ``agent``     reasons over the conversation and either asks for a tool or
                produces a final natural-language answer.
* ``action``    executes the requested tool(s) via ``ToolNode``.
* ``formatter`` collects the last tool result(s) plus the agent's final
                message and shapes them into a strict ``FinalResponse`` dict.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, TypedDict

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import INFRAPILOT_TOOLS


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
# AgentState is the state of the agent. It contains the messages and the final payload.
# The messages are the messages in the conversation.
# The final payload is the final payload of the agent.

class AgentState(TypedDict):
    """Shared state passed between graph nodes."""

    messages: Annotated[list[BaseMessage], add_messages]
    final_payload: dict


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are InfraPilot, an AWS infrastructure assistant.

Your job is to translate a user's natural-language request into concrete
Terraform code and CLI commands by orchestrating the tools that have been
made available to you. The set of tools may grow over time; rely on each
tool's name and description (provided to you alongside this prompt) to
decide which one to call.

General policy:
  1. Read the user's request and pick the tools whose descriptions best
     match the requested AWS resources or actions.
  2. When a tool is available to validate or pre-check something (for
     example, name availability, quota, permissions), prefer running it
     BEFORE any tool that generates or mutates artifacts.
  3. If a pre-check indicates the request cannot proceed, stop, do not
     call generation tools, and explain the blocker to the user.
  4. Otherwise, call the appropriate generation tool(s) to produce
     Terraform files and CLI commands. You may chain multiple tools when
     a request spans several resources.
  5. Do not invent tools, arguments, or AWS resources that are not
     supported by the tools you have been given.
  6. After all tool calls finish, respond with a short, natural-language
     summary of what was produced. Do not repeat the raw tool output.
  7. If a tool returns status `needs_input`, do not treat it as an internal
     crash. Explain what is missing and what the user should provide next.
  8. If deploy_service is blocked by missing infrastructure, tell the user
     that shared infrastructure must be planned or provided first.
  9. If stop_service or teardown_service is blocked by a missing service_name,
     ask for the explicit service name instead of guessing.
"""

# SYSTEM_PROMPT = """You are InfraPilot, an AWS infrastructure assistant.

# Your job is to translate a user's natural-language request into concrete
# Terraform code and CLI commands.
# """


def _build_llm():
    """Instantiate the Bedrock Nova-Micro model with tools bound."""
    llm = ChatBedrockConverse(
        model_id="amazon.nova-micro-v1:0",
        region_name="us-east-1",
        temperature=0,
        max_tokens=2000,
    )
    return llm.bind_tools(INFRAPILOT_TOOLS)

## We use aws bedrock to interact with the model
## https://reference.langchain.com/python/langchain-aws/chat_models/bedrock_converse/ChatBedrockConverse


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def _agent_node(state: AgentState) -> dict:
    """Run the LLM over the current message history."""
    llm = _build_llm()
    messages = state["messages"]

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

    response = llm.invoke(messages)
    return {"messages": [response]}


def _formatter_node(state: AgentState) -> dict:
    """Collapse the conversation into the strict FinalResponse payload."""
    files: list[dict] = []
    commands: list[dict] = []
    notes: list[str] = []
    steps: list[dict] = []
    missing_parameters: list[str] = []
    intent: str | None = None
    requires_confirmation = False
    error: str | None = None
    final_status = "success"

    for msg in state["messages"]:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, dict):
            continue

        if "files" in content and isinstance(content["files"], list):
            files.extend(content["files"])
        if "commands" in content and isinstance(content["commands"], list):
            commands.extend(content["commands"])
        if "notes" in content and isinstance(content["notes"], list):
            notes.extend(str(note) for note in content["notes"])
        if "steps" in content and isinstance(content["steps"], list):
            steps.extend(step for step in content["steps"] if isinstance(step, dict))
        if "missing_parameters" in content and isinstance(content["missing_parameters"], list):
            missing_parameters.extend(
                str(item) for item in content["missing_parameters"] if isinstance(item, str)
            )
        if "intent" in content and isinstance(content["intent"], str):
            intent = content["intent"]
        if "requires_confirmation" in content:
            requires_confirmation = (
                requires_confirmation or bool(content["requires_confirmation"])
            )
        if content.get("status") == "error":
            final_status = "error"
        elif content.get("status") == "needs_input" and final_status != "error":
            final_status = "needs_input"
        if "error" in content and isinstance(content["error"], str):
            error = content["error"]

    last_ai = state["messages"][-1]
    explanation = ""
    if hasattr(last_ai, "content"):
        if isinstance(last_ai.content, str):
            explanation = last_ai.content
        elif isinstance(last_ai.content, list):
            explanation = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in last_ai.content
            ).strip()

    if final_status == "success" and not (files or commands or steps or intent):
        final_status = "error"

    if _should_use_fallback_explanation(explanation, final_status):
        explanation = _build_fallback_explanation(
            status=final_status,
            intent=intent,
            missing_parameters=missing_parameters,
            error=error,
        )

    final_payload = {
        "status": final_status,
        "task_id": str(uuid.uuid4()),
        "intent": intent,
        "files": files,
        "commands": commands,
        "notes": notes,
        "requires_confirmation": requires_confirmation,
        "steps": steps,
        "error": error,
        "missing_parameters": list(dict.fromkeys(missing_parameters)),
        "explanation": explanation or "InfraPilot finished processing your request.",
    }
    return {"final_payload": final_payload}


def _should_use_fallback_explanation(explanation: str, status: str) -> bool:
    """Decide when formatter should replace unhelpful non-success text."""
    if status == "success":
        return not explanation

    normalized = explanation.strip().lower()
    return normalized in {
        "",
        "planning failed.",
        "planning failed internally.",
        "infrapilot finished processing your request.",
    }


def _build_fallback_explanation(
    *,
    status: str,
    intent: str | None,
    missing_parameters: list[str],
    error: str | None,
) -> str:
    """Provide deterministic user guidance for structured tool failures."""
    if status == "needs_input":
        missing = list(dict.fromkeys(missing_parameters))
        if intent == "deploy_service" and "infrastructure" in missing:
            return (
                "Shared infrastructure is missing for deploy_service. "
                "Plan setup_infra first, or provide the required infrastructure "
                "state before retrying deploy_service."
            )
        if intent in {"stop_service", "teardown_service"} and "service_name" in missing:
            return (
                f"{intent} requires an explicit service_name. "
                "Provide the target service name and retry the request."
            )
        if missing:
            missing_list = ", ".join(missing)
            return (
                f"More input is required before {intent or 'planning'} can continue: "
                f"{missing_list}."
            )
        if error:
            return error
        return "More input is required before planning can continue."

    if status == "error":
        return error or "Internal workflow planning failure."

    return "InfraPilot finished processing your request."


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
#Define if the last message is a tool call or not.
#If it is a tool call, go to the action node, otherwise go to the formatter node.
def _route_after_agent(state: AgentState) -> str:
    """Go to `action` if the last AI message requested tools, else `formatter`."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        return "action"
    return "formatter"


# --------------------------------------------------------------------------- #
# Graph builder
# --------------------------------------------------------------------------- #
# The agent is built using the StateGraph class and compiled using the compile method.
def build_graph():
    """Compile and return the InfraPilot LangGraph application."""
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", _agent_node)
    workflow.add_node("action", ToolNode(INFRAPILOT_TOOLS))
    workflow.add_node("formatter", _formatter_node)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"action": "action", "formatter": "formatter"},
    )
    workflow.add_edge("action", "agent")
    workflow.add_edge("formatter", END)

    return workflow.compile()
