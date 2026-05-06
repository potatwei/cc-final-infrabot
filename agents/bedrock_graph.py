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
import re
from typing import Annotated, NotRequired, TypedDict

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import CORE_TOOL_INPUT_SPECS, INFRAPILOT_TOOLS


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
    task_id: NotRequired[str]
    mode: NotRequired[str]


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
  1. Read the user's request and identify which generation tool best matches
     it (generate_s3_terraform, generate_ec2_terraform, generate_vpc_terraform).
     2. Before calling any generation tool, identify all required inputs that
     have no default value. Never invent or guess values.
     - If ANY required input is missing: you MUST call `report_missing_inputs`
       immediately. Pass the intended generation tool name, the list of
       missing parameter names, a short user-facing explanation, AND a
       `provided_inputs` dict containing every parameter the user DID supply
       (e.g. {"bucket_name": "my-bucket"}).
       Do NOT output plain text. Do NOT call any other tool first.
     - Only if ALL required inputs are present: proceed to step 3.
  3. When a validation or pre-check tool is available (e.g. name availability,
     region validation), run it BEFORE the generation tool.
     - For S3 bucket creation specifically: you MUST always call
       `check_s3_name_availability` with the bucket_name BEFORE calling
       `generate_s3_terraform`. Only proceed to generation if the tool
       confirms the name is available. If the name is taken, stop and
       inform the user to choose a different bucket name.
  4. If a pre-check fails, stop and explain the blocker. Do not generate.
  5. If a pre-check succeeds, call the generation tool.
  6. Do not invent tools, arguments, or AWS resources not supported by your
     available tools.
  7. Keep responses aligned to simple resource planning.
  8. After all tool calls finish, respond with a short natural-language summary.
     Do not repeat raw tool output.
  9. If a tool returns status `needs_input`, explain what is missing.
 10. If the user's request is completely unrelated to AWS infrastructure
     (e.g. casual chat), respond with a short plain-text message
     saying you are an AWS infrastructure assistant. Do not call any tools.
"""


def _build_discovery_prompt() -> str:
    """Build the discovery-mode prompt from the current core tool catalog."""
    tool_catalog = json.dumps(CORE_TOOL_INPUT_SPECS, indent=2, sort_keys=True)
    return f"""You are InfraPilot in discovery mode.

Your job is to inspect the user's request and decide which single tool from the
catalog best matches it. Do not call tools. Do not generate Terraform.

Return exactly one JSON object with these keys:
{{
  "selected_tool": string or null,
  "intent": string or null,
  "required_inputs": string[],
  "recommended_inputs": string[],
  "optional_inputs": string[],
  "defaults": object,
  "provided_inputs": object,
  "missing_inputs": string[],
  "ready_to_execute": boolean,
  "precheck_tool": string or null,
  "explanation": string
}}

Rules:
  1. Pick only one tool from the catalog.
  2. Extract only values the user actually provided; do not invent values.
  3. Keep fields out of missing_inputs only when a non-empty default exists in
     the catalog for that field. Fields with no default (e.g. region,
     bucket_name, instance_name, vpc_name) must appear in missing_inputs if
     the user did not provide them.
  4. Set ready_to_execute=true only when all required_inputs are present.
  5. If the request does not match any supported tool, set selected_tool=null,
     ready_to_execute=false, and explain the unsupported gap.

Tool catalog:
{tool_catalog}
"""

# SYSTEM_PROMPT = """You are InfraPilot, an AWS infrastructure assistant.

# Your job is to translate a user's natural-language request into concrete
# Terraform code and CLI commands.
# """


def _build_llm(*, bind_tools: bool = True):
    """Instantiate the Bedrock Nova-Micro model with tools bound."""
    llm = ChatBedrockConverse(
        # model_id="amazon.nova-micro-v1:0",
        model_id ="amazon.nova-lite-v1:0",
        region_name="us-east-1",
        temperature=0,
        max_tokens=5000,
    )
    if bind_tools:
        return llm.bind_tools(INFRAPILOT_TOOLS)
    return llm

## We use aws bedrock to interact with the model
## https://reference.langchain.com/python/langchain-aws/chat_models/bedrock_converse/ChatBedrockConverse


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def _agent_node(state: AgentState) -> dict:
    """Run the LLM over the current message history."""
    mode = state.get("mode", "execution")
    llm = _build_llm(bind_tools=mode != "discovery")
    messages = state["messages"]

    prompt = _build_discovery_prompt() if mode == "discovery" else SYSTEM_PROMPT

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=prompt), *messages]
    else:
        messages = [SystemMessage(content=prompt), *messages[1:]]

    response = llm.invoke(messages)
    return {"messages": [response]}


def _formatter_node(state: AgentState) -> dict:
    """Collapse the conversation into the strict FinalResponse payload."""
    if state.get("mode") == "discovery":
        return {"final_payload": _build_discovery_payload(state)}

    blocking_deploy_needs_infra = False
    blocking_deploy_error: str | None = None
    files: list[dict] = []
    commands: list[dict] = []
    notes: list[str] = []
    steps: list[dict] = []
    missing_parameters: list[str] = []
    provided_inputs: dict = {}
    intent: str | None = None
    selected_tool: str | None = None
    requires_confirmation = False
    error: str | None = None
    final_status = "success"
    tool_explanations: list[str] = []

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

        if _is_blocking_deploy_needs_infrastructure(content):
            blocking_deploy_needs_infra = True
            blocking_deploy_error = (
                str(content["error"]) if isinstance(content.get("error"), str) else None
            )

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
        if "provided_inputs" in content and isinstance(content["provided_inputs"], dict):
            provided_inputs.update(content["provided_inputs"])
        if "intent" in content and isinstance(content["intent"], str):
            intent = content["intent"]
        if "selected_tool" in content and isinstance(content["selected_tool"], str):
            selected_tool = content["selected_tool"]
        elif getattr(msg, "name", None) in _GENERATION_TOOLS:
            selected_tool = msg.name
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
        if "explanation" in content and isinstance(content["explanation"], str):
            tool_explanations.append(content["explanation"])

    last_ai = state["messages"][-1]
    explanation = ""
    if isinstance(last_ai, AIMessage):
        if isinstance(last_ai.content, str):
            explanation = last_ai.content
        elif isinstance(last_ai.content, list):
            explanation = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in last_ai.content
            ).strip()
    explanation = _strip_thinking_tags(explanation)

    if final_status == "success" and not (files or commands or steps) and not intent:
        final_status = "error"

    if blocking_deploy_needs_infra:
        final_status = "needs_input"
        intent = "deploy_service"
        files = []
        commands = []
        notes = []
        steps = []
        requires_confirmation = False
        error = blocking_deploy_error or error
        missing_parameters = ["infrastructure"]

    fallback_explanation = _build_fallback_explanation(
        status=final_status,
        intent=intent,
        missing_parameters=missing_parameters,
        error=error,
        tool_explanations=tool_explanations,
        files=files,
        commands=commands,
    )

    if blocking_deploy_needs_infra or _should_use_fallback_explanation(explanation, final_status):
        explanation = fallback_explanation
    elif final_status == "success" and _should_replace_success_explanation(explanation):
        explanation = _build_fallback_explanation(
            status=final_status,
            intent=intent,
            missing_parameters=missing_parameters,
            error=error,
            tool_explanations=tool_explanations,
            files=files,
            commands=commands,
        )

    final_payload = {
        "status": final_status,
        "task_id": state.get("task_id", ""),
        "intent": intent,
        "selected_tool": selected_tool,
        "provided_inputs": provided_inputs,
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


def _build_discovery_payload(state: AgentState) -> dict:
    """Shape the last discovery response into a structured pre-execution payload."""
    raw_text = _message_text(state["messages"][-1]) if state["messages"] else ""
    content = _parse_json_object(raw_text)

    if not isinstance(content, dict):
        return {
            "status": "error",
            "task_id": state.get("task_id", ""),
            "mode": "discovery",
            "intent": None,
            "selected_tool": None,
            "required_inputs": [],
            "recommended_inputs": [],
            "optional_inputs": [],
            "defaults": {},
            "provided_inputs": {},
            "missing_inputs": [],
            "missing_parameters": [],
            "ready_to_execute": False,
            "precheck_tool": None,
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": "Discovery response was not valid JSON.",
            "explanation": "InfraPilot could not summarize the discovery step.",
        }

    selected_tool = content.get("selected_tool")
    spec = CORE_TOOL_INPUT_SPECS.get(selected_tool) if isinstance(selected_tool, str) else None

    required_inputs = _string_list(content.get("required_inputs")) or (
        list(spec["required_inputs"]) if spec else []
    )
    recommended_inputs = _string_list(content.get("recommended_inputs")) or (
        list(spec["recommended_inputs"]) if spec else []
    )
    optional_inputs = _string_list(content.get("optional_inputs")) or (
        list(spec["optional_inputs"]) if spec else []
    )
    defaults = content.get("defaults") if isinstance(content.get("defaults"), dict) else (
        dict(spec["defaults"]) if spec else {}
    )
    provided_inputs = (
        content.get("provided_inputs") if isinstance(content.get("provided_inputs"), dict) else {}
    )
    missing_inputs = _string_list(content.get("missing_inputs"))
    if not missing_inputs:
        missing_inputs = [
            name for name in required_inputs if name not in provided_inputs or provided_inputs[name] in ("", None)
        ]

    ready_to_execute = bool(content.get("ready_to_execute")) and not missing_inputs
    intent = content.get("intent") if isinstance(content.get("intent"), str) else (
        spec["intent"] if spec else None
    )
    precheck_tool = content.get("precheck_tool") if isinstance(content.get("precheck_tool"), str) else (
        spec["precheck_tool"] if spec else None
    )
    explanation = (
        content.get("explanation")
        if isinstance(content.get("explanation"), str) and content.get("explanation").strip()
        else _build_discovery_explanation(selected_tool, required_inputs, missing_inputs)
    )

    status = "success" if ready_to_execute else "needs_input"
    if selected_tool is None:
        status = "needs_input"

    return {
        "status": status,
        "task_id": state.get("task_id", ""),
        "mode": "discovery",
        "intent": intent,
        "selected_tool": selected_tool,
        "required_inputs": required_inputs,
        "recommended_inputs": recommended_inputs,
        "optional_inputs": optional_inputs,
        "defaults": defaults,
        "provided_inputs": provided_inputs,
        "missing_inputs": missing_inputs,
        "missing_parameters": missing_inputs,
        "ready_to_execute": ready_to_execute,
        "precheck_tool": precheck_tool,
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "error": None,
        "explanation": explanation,
    }


def _message_text(message: BaseMessage) -> str:
    """Collapse a LangChain message content field to plain text."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        ).strip()
    return str(content)


def _parse_json_object(raw_text: str) -> dict | None:
    """Parse a raw JSON object, tolerating markdown fences."""
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _string_list(value: object) -> list[str]:
    """Normalize a JSON array to a list[str]."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _build_discovery_explanation(
    selected_tool: str | None,
    required_inputs: list[str],
    missing_inputs: list[str],
) -> str:
    """Fallback explanation for discovery-mode payloads."""
    if not selected_tool:
        return "InfraPilot could not match the request to a supported tool yet."
    if missing_inputs:
        return (
            f"Selected {selected_tool}, but more input is required before execution: "
            f"{', '.join(missing_inputs)}."
        )
    if required_inputs:
        return f"Selected {selected_tool} and collected all required inputs for execution."
    return f"Selected {selected_tool}; execution can proceed with defaults."


def _strip_thinking_tags(text: str) -> str:
    """Remove <thinking>...</thinking> blocks from AI output before showing to users."""
    stripped = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    return stripped.strip()


_GENERATION_TOOLS = frozenset({
    "generate_s3_terraform",
    "generate_ec2_terraform",
    "generate_vpc_terraform",
})


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


def _should_replace_success_explanation(explanation: str) -> bool:
    """Detect verbose success replies that duplicate structured payload content."""
    normalized = explanation.strip().lower()
    if not normalized:
        return True
    return any(
        marker in normalized
        for marker in (
            "```",
            "### terraform files",
            "### terraform commands",
            "resource \"aws_",
            "terraform {",
        )
    )


def _is_blocking_deploy_needs_infrastructure(content: dict) -> bool:
    """Detect a deploy failure caused by missing infrastructure state."""
    if content.get("intent") != "deploy_service":
        return False
    if content.get("status") != "needs_input":
        return False

    missing_parameters = content.get("missing_parameters")
    if isinstance(missing_parameters, list) and "infrastructure" in missing_parameters:
        return True

    error = content.get("error")
    if not isinstance(error, str):
        return False
    return (
        "project_state.infrastructure keys:" in error
        or "non-empty project_state.infrastructure" in error
    )


def _build_fallback_explanation(
    *,
    status: str,
    intent: str | None,
    missing_parameters: list[str],
    error: str | None,
    tool_explanations: list[str],
    files: list[dict],
    commands: list[dict],
) -> str:
    """Provide deterministic user guidance for structured tool failures."""
    if status == "success":
        concise_tool_explanation = _pick_concise_tool_explanation(tool_explanations)
        if concise_tool_explanation:
            return concise_tool_explanation
        return _build_success_summary(intent=intent, files=files, commands=commands)

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


def _pick_concise_tool_explanation(tool_explanations: list[str]) -> str | None:
    """Prefer the last concise tool explanation when available."""
    for explanation in reversed(tool_explanations):
        stripped = explanation.strip()
        if stripped and not _should_replace_success_explanation(stripped):
            return stripped
    for explanation in reversed(tool_explanations):
        stripped = explanation.strip()
        if stripped:
            return stripped
    return None


def _build_success_summary(
    *,
    intent: str | None,
    files: list[dict],
    commands: list[dict],
) -> str:
    """Generate a short success summary from the structured payload."""
    file_count = len(files)
    command_count = len(commands)
    if intent:
        return (
            f"Prepared a {intent} plan with {file_count} file"
            f"{'' if file_count == 1 else 's'} and {command_count} command"
            f"{'' if command_count == 1 else 's'}."
        )
    return (
        f"Prepared a plan with {file_count} file"
        f"{'' if file_count == 1 else 's'} and {command_count} command"
        f"{'' if command_count == 1 else 's'}."
    )


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


def _route_after_action(state: AgentState) -> str:
    """Stop the loop after structured tool failures; otherwise continue reasoning."""
    last = state["messages"][-1]
    if not isinstance(last, ToolMessage):
        return "agent"

    content = last.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return "agent"
    if not isinstance(content, dict):
        return "agent"

    if content.get("status") in {"needs_input", "error"}:
        return "formatter"
    return "agent"


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
    workflow.add_conditional_edges(
        "action",
        _route_after_action,
        {"agent": "agent", "formatter": "formatter"},
    )
    workflow.add_edge("formatter", END)

    return workflow.compile()
