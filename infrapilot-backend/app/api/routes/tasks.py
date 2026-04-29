from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
import re
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../'))

from agents.bedrock_graph import build_graph
from app.core.task_status import map_task_status
from app.db.database import get_db
from app.models.task import Task
from app.schemas.task import TaskContinue, TaskCreate, TaskResponse
from tools import CORE_TOOL_INPUT_SPECS, CORE_TOOLS_BY_NAME

router = APIRouter()


@router.post("/task", response_model=TaskResponse)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    new_task = Task(
        user_prompt=task_data.user_prompt,
        status="pending",
        code_payload=None
    )
    db.add(new_task)
    db.commit()

    try:
        graph = build_graph()
        result = graph.invoke({
            "messages": [HumanMessage(content=task_data.user_prompt)],
            "final_payload": {},
            "task_id": new_task.task_id,
            "mode": task_data.mode,
        })
        payload = result["final_payload"]
        if task_data.mode == "discovery":
            payload = _normalize_discovery_payload(payload=payload, prompt=task_data.user_prompt)
        new_task.code_payload = payload
        new_task.status = map_task_status(payload)

    except Exception as e:
        new_task.status = "failed"
        new_task.code_payload = {
            "status": "error",
            "task_id": new_task.task_id,
            "intent": None,
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": str(e),
            "missing_parameters": [],
            "explanation": str(e)
        }

    db.commit()
    db.refresh(new_task)
    return new_task


@router.post("/task/{task_id}/continue", response_model=TaskResponse)
def continue_task(task_id: str, task_data: TaskContinue, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    payload = task.code_payload or {}
    if payload.get("mode") != "discovery":
        raise HTTPException(
            status_code=400,
            detail="Only discovery tasks can be continued.",
        )

    selected_tool = payload.get("selected_tool")
    if not isinstance(selected_tool, str) or selected_tool not in CORE_TOOL_INPUT_SPECS:
        raise HTTPException(status_code=400, detail="Task does not reference a supported tool.")

    spec = CORE_TOOL_INPUT_SPECS[selected_tool]
    provided_inputs = dict(payload.get("provided_inputs") or {})
    new_inputs = {
        key: value
        for key, value in (task_data.provided_inputs or {}).items()
        if _has_value(value)
    }
    if task_data.user_input and not new_inputs:
        first_missing = _first_missing_input(payload)
        if first_missing:
            new_inputs[first_missing] = task_data.user_input.strip()

    provided_inputs.update(new_inputs)
    discovery_state = _evaluate_discovery_state(
        selected_tool=selected_tool,
        spec=spec,
        provided_inputs=provided_inputs,
        required_inputs_override=payload.get("required_inputs"),
        defaults_override=payload.get("defaults"),
    )
    missing_inputs = discovery_state["missing_inputs"]
    explanation = discovery_state["explanation"]

    if missing_inputs:
        task.code_payload = _build_discovery_continuation_payload(
            task_id=task.task_id,
            payload=payload,
            spec=spec,
            provided_inputs=provided_inputs,
            missing_inputs=missing_inputs,
            explanation=explanation,
        )
        task.status = map_task_status(task.code_payload)
        db.commit()
        db.refresh(task)
        return task

    precheck_result = _run_precheck_if_needed(spec=spec, provided_inputs=provided_inputs)
    if precheck_result is not None and precheck_result.get("status") != "success":
        task.code_payload = _build_discovery_blocked_payload(
            task_id=task.task_id,
            payload=payload,
            spec=spec,
            provided_inputs=provided_inputs,
            explanation=str(precheck_result.get("explanation") or "Pre-check failed."),
            error=precheck_result.get("error"),
        )
        task.status = map_task_status(task.code_payload)
        db.commit()
        db.refresh(task)
        return task

    tool = CORE_TOOLS_BY_NAME[selected_tool]
    tool_inputs = _build_tool_inputs(
        spec=spec,
        provided_inputs=provided_inputs,
        defaults=payload.get("defaults") or spec["defaults"],
    )
    tool_result = tool.invoke(tool_inputs)
    tool_result["task_id"] = task.task_id
    task.code_payload = tool_result
    task.status = map_task_status(tool_result)
    db.commit()
    db.refresh(task)
    return task


@router.get("/task/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/task/{task_id}/confirm")
def confirm_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "complete"
    db.commit()
    return {"message": f"Task {task_id} marked as complete"}


def _has_value(value) -> bool:
    return value not in (None, "")


def _first_missing_input(payload: dict) -> str | None:
    missing_inputs = payload.get("missing_inputs")
    if isinstance(missing_inputs, list):
        for item in missing_inputs:
            if isinstance(item, str) and item:
                return item
    return None


def _compute_missing_inputs(
    *,
    required_inputs: list[str],
    provided_inputs: dict,
    defaults: dict,
) -> list[str]:
    missing_inputs: list[str] = []
    for name in required_inputs:
        if _has_value(provided_inputs.get(name)):
            continue
        if _has_value(defaults.get(name)):
            continue
        missing_inputs.append(name)
    return missing_inputs


def _normalize_discovery_payload(*, payload: dict, prompt: str) -> dict:
    """Canonicalize discovery payloads against tool specs and deterministic parsing."""
    selected_tool = _normalize_selected_tool(payload.get("selected_tool"), prompt)
    if not selected_tool:
        return {
            "status": "needs_input",
            "task_id": payload.get("task_id", ""),
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
            "error": None,
            "explanation": (
                "InfraPilot could not match this request to a supported tool yet."
            ),
        }

    spec = CORE_TOOL_INPUT_SPECS[selected_tool]
    ai_inputs = payload.get("provided_inputs") if isinstance(payload.get("provided_inputs"), dict) else {}
    extracted_inputs = _extract_inputs_from_prompt(prompt, selected_tool)
    provided_inputs = {**ai_inputs, **extracted_inputs}
    discovery_state = _evaluate_discovery_state(
        selected_tool=selected_tool,
        spec=spec,
        provided_inputs=provided_inputs,
        prompt=prompt,
        base_explanation=payload.get("explanation"),
    )

    return {
        "status": "success" if discovery_state["ready_to_execute"] else "needs_input",
        "task_id": payload.get("task_id", ""),
        "mode": "discovery",
        "intent": spec["intent"],
        "selected_tool": selected_tool,
        "required_inputs": list(spec["required_inputs"]),
        "recommended_inputs": list(spec["recommended_inputs"]),
        "optional_inputs": list(spec["optional_inputs"]),
        "defaults": dict(spec["defaults"]),
        "provided_inputs": provided_inputs,
        "missing_inputs": discovery_state["missing_inputs"],
        "missing_parameters": discovery_state["missing_inputs"],
        "ready_to_execute": discovery_state["ready_to_execute"],
        "precheck_tool": spec.get("precheck_tool"),
        "files": [],
        "commands": [],
        "notes": discovery_state["notes"],
        "requires_confirmation": False,
        "steps": [],
        "error": None,
        "explanation": discovery_state["explanation"],
    }


def _normalize_selected_tool(selected_tool, prompt: str) -> str | None:
    if isinstance(selected_tool, str) and selected_tool in CORE_TOOL_INPUT_SPECS:
        return selected_tool
    return _infer_selected_tool_from_prompt(prompt)


def _infer_selected_tool_from_prompt(prompt: str) -> str | None:
    normalized = prompt.strip().lower()
    has_region = bool(_extract_region(prompt))
    has_instance_type = bool(_extract_instance_type(prompt))

    if "region" in normalized and any(word in normalized for word in ("list", "available", "which", "what")):
        if has_region and ("valid" in normalized or "is " in normalized):
            return "validate_aws_region"
        return "list_aws_regions"
    if "instance type" in normalized:
        if has_region and has_instance_type:
            return "validate_ec2_instance_type"
        if has_region and any(word in normalized for word in ("list", "available", "which", "what")):
            return "list_ec2_instance_type_offerings"
    if "s3" in normalized or "bucket" in normalized:
        return "generate_s3_terraform"
    if "ec2" in normalized or "instance" in normalized:
        return "generate_ec2_terraform"
    if "vpc" in normalized:
        return "generate_vpc_terraform"
    return None


def _extract_inputs_from_prompt(prompt: str, selected_tool: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    region = _extract_region(prompt)
    instance_type = _extract_instance_type(prompt)
    cidr = _extract_cidr(prompt)
    named_value = _extract_named_value(prompt)
    bucket_name = _extract_bucket_name(prompt)

    if selected_tool in {
        "generate_s3_terraform",
        "check_s3_name_availability",
    } and bucket_name:
        extracted["bucket_name"] = bucket_name
    if selected_tool in {
        "generate_s3_terraform",
        "generate_ec2_terraform",
        "generate_vpc_terraform",
        "validate_aws_region",
        "list_ec2_instance_type_offerings",
        "validate_ec2_instance_type",
    } and region:
        extracted["region"] = region
    if selected_tool in {"generate_ec2_terraform", "validate_ec2_instance_type"} and instance_type:
        extracted["instance_type"] = instance_type
    if selected_tool == "generate_ec2_terraform" and named_value:
        extracted["instance_name"] = named_value
    if selected_tool == "generate_vpc_terraform":
        if named_value:
            extracted["vpc_name"] = named_value
        if cidr:
            extracted["vpc_cidr"] = cidr
    return extracted


def _evaluate_discovery_state(
    *,
    selected_tool: str,
    spec: dict,
    provided_inputs: dict,
    prompt: str | None = None,
    base_explanation: str | None = None,
    required_inputs_override: list[str] | None = None,
    defaults_override: dict | None = None,
) -> dict[str, object]:
    defaults = dict(defaults_override or spec["defaults"])
    required_inputs = list(required_inputs_override or spec["required_inputs"])
    missing_inputs = _compute_missing_inputs(
        required_inputs=required_inputs,
        provided_inputs=provided_inputs,
        defaults=defaults,
    )
    validation = _run_discovery_validations(
        selected_tool=selected_tool,
        spec=spec,
        provided_inputs=provided_inputs,
        defaults=defaults,
    )
    combined_missing = list(dict.fromkeys(missing_inputs + validation["invalid_fields"]))
    ready_to_execute = not combined_missing

    if validation["explanation"]:
        explanation = validation["explanation"]
    elif combined_missing:
        explanation = _build_missing_input_explanation(
            selected_tool=selected_tool,
            missing_inputs=combined_missing,
            prompt=prompt,
        )
    else:
        explanation = _build_ready_to_execute_explanation(
            selected_tool=selected_tool,
            provided_inputs=provided_inputs,
            defaults=defaults,
            base_explanation=base_explanation,
        )

    return {
        "missing_inputs": combined_missing,
        "ready_to_execute": ready_to_execute,
        "explanation": explanation,
        "notes": validation["notes"],
    }


def _run_discovery_validations(
    *,
    selected_tool: str,
    spec: dict,
    provided_inputs: dict,
    defaults: dict,
) -> dict[str, object]:
    invalid_fields: list[str] = []
    notes: list[str] = []
    explanation: str | None = None
    validation_context = {**defaults, **provided_inputs}

    for field_name, validator_name in spec.get("validators", {}).items():
        value = provided_inputs.get(field_name)
        if not _has_value(value):
            continue
        validator = CORE_TOOLS_BY_NAME.get(validator_name)
        if validator is None:
            continue

        validator_inputs = _build_validator_inputs(
            validator_name=validator_name,
            field_name=field_name,
            validation_context=validation_context,
        )
        if validator_inputs is None:
            continue
        result = validator.invoke(validator_inputs)
        notes.extend(str(note) for note in result.get("notes") or [])
        if validator_name == "validate_aws_region" and not result.get("valid", False):
            invalid_fields.append(field_name)
            explanation = (
                f"The region '{value}' does not look valid. "
                "Provide an AWS region like us-east-1."
            )
        if validator_name == "validate_ec2_instance_type":
            if not result.get("valid", False):
                invalid_fields.append(field_name)
                explanation = (
                    f"The instance type '{value}' does not look valid. "
                    "Provide a value like t3.micro."
                )
            elif not result.get("available_in_region", False):
                invalid_fields.append(field_name)
                region = validation_context.get("region", "that region")
                explanation = (
                    f"The instance type '{value}' is not available in {region}. "
                    "Choose another instance type or region."
                )

    return {
        "invalid_fields": invalid_fields,
        "notes": list(dict.fromkeys(notes)),
        "explanation": explanation,
    }


def _build_validator_inputs(
    *,
    validator_name: str,
    field_name: str,
    validation_context: dict,
) -> dict | None:
    if validator_name == "validate_aws_region":
        region = validation_context.get(field_name) or validation_context.get("region")
        if not _has_value(region):
            return None
        return {"region": region}
    if validator_name == "validate_ec2_instance_type":
        instance_type = validation_context.get("instance_type")
        region = validation_context.get("region")
        if not (_has_value(instance_type) and _has_value(region)):
            return None
        return {"instance_type": instance_type, "region": region}
    return None


def _build_missing_input_explanation(
    *,
    selected_tool: str,
    missing_inputs: list[str],
    prompt: str | None,
) -> str:
    missing_list = ", ".join(missing_inputs)
    if prompt:
        return (
            f"The request '{prompt}' is missing: {missing_list}. "
            "Provide those values to continue."
        )
    return f"More input is required before {selected_tool} can continue: {missing_list}."


def _build_ready_to_execute_explanation(
    *,
    selected_tool: str,
    provided_inputs: dict,
    defaults: dict,
    base_explanation: str | None,
) -> str:
    if selected_tool == "generate_vpc_terraform":
        if not provided_inputs:
            return "A VPC plan can be generated now using the default region and CIDR values."
        return "All required values for VPC generation are available."
    if selected_tool == "generate_ec2_terraform":
        return "All required values for EC2 generation are available."
    if selected_tool == "generate_s3_terraform":
        return "All required values for S3 bucket generation are available."
    if isinstance(base_explanation, str) and base_explanation.strip():
        return base_explanation.strip()
    if defaults and not provided_inputs:
        return f"{selected_tool} can continue using default values."
    return f"All required inputs are available for {selected_tool}."


def _build_discovery_continuation_payload(
    *,
    task_id: str,
    payload: dict,
    spec: dict,
    provided_inputs: dict,
    missing_inputs: list[str],
    explanation: str,
) -> dict:
    return {
        "status": "needs_input",
        "task_id": task_id,
        "mode": "discovery",
        "intent": payload.get("intent") or spec["intent"],
        "selected_tool": payload.get("selected_tool"),
        "required_inputs": payload.get("required_inputs") or spec["required_inputs"],
        "recommended_inputs": payload.get("recommended_inputs") or spec["recommended_inputs"],
        "optional_inputs": payload.get("optional_inputs") or spec["optional_inputs"],
        "defaults": payload.get("defaults") or spec["defaults"],
        "provided_inputs": provided_inputs,
        "missing_inputs": missing_inputs,
        "missing_parameters": missing_inputs,
        "ready_to_execute": False,
        "precheck_tool": payload.get("precheck_tool") or spec.get("precheck_tool"),
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "error": None,
        "explanation": explanation,
    }


def _build_discovery_blocked_payload(
    *,
    task_id: str,
    payload: dict,
    spec: dict,
    provided_inputs: dict,
    explanation: str,
    error,
) -> dict:
    return {
        "status": "needs_input",
        "task_id": task_id,
        "mode": "discovery",
        "intent": payload.get("intent") or spec["intent"],
        "selected_tool": payload.get("selected_tool"),
        "required_inputs": payload.get("required_inputs") or spec["required_inputs"],
        "recommended_inputs": payload.get("recommended_inputs") or spec["recommended_inputs"],
        "optional_inputs": payload.get("optional_inputs") or spec["optional_inputs"],
        "defaults": payload.get("defaults") or spec["defaults"],
        "provided_inputs": provided_inputs,
        "missing_inputs": ["bucket_name"] if provided_inputs.get("bucket_name") else [],
        "missing_parameters": ["bucket_name"] if provided_inputs.get("bucket_name") else [],
        "ready_to_execute": False,
        "precheck_tool": payload.get("precheck_tool") or spec.get("precheck_tool"),
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "error": str(error) if error else None,
        "explanation": explanation,
    }


def _build_precheck_inputs(provided_inputs: dict) -> dict:
    if "bucket_name" in provided_inputs:
        return {"bucket_name": provided_inputs["bucket_name"]}
    return provided_inputs


def _build_tool_inputs(*, spec: dict, provided_inputs: dict, defaults: dict) -> dict:
    allowed_inputs = set(
        spec["required_inputs"] + spec["recommended_inputs"] + spec["optional_inputs"]
    )
    merged = {**defaults, **provided_inputs}
    return {key: value for key, value in merged.items() if key in allowed_inputs}


def _run_precheck_if_needed(*, spec: dict, provided_inputs: dict) -> dict | None:
    precheck_tool_name = spec.get("precheck_tool")
    if not isinstance(precheck_tool_name, str):
        return None
    precheck_tool = CORE_TOOLS_BY_NAME.get(precheck_tool_name)
    if precheck_tool is None:
        raise HTTPException(status_code=500, detail="Configured precheck tool is unavailable.")
    return precheck_tool.invoke(_build_precheck_inputs(provided_inputs))


REGION_PATTERN = re.compile(r"\b[a-z]{2}-[a-z]+-\d+\b")
REGION_CANDIDATE_PATTERN = re.compile(r"\b(?:in|region)\s+([a-z0-9-]+)\b", re.IGNORECASE)
INSTANCE_TYPE_PATTERN = re.compile(r"\b[a-z]\d[a-z0-9]*\.[a-z0-9]+\b")
CIDR_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b")


def _extract_region(prompt: str) -> str | None:
    normalized = prompt.lower()
    match = REGION_PATTERN.search(normalized)
    if match:
        return match.group(0)

    candidate = REGION_CANDIDATE_PATTERN.search(normalized)
    if candidate and "-" in candidate.group(1):
        return candidate.group(1)
    return None


def _extract_instance_type(prompt: str) -> str | None:
    match = INSTANCE_TYPE_PATTERN.search(prompt.lower())
    return match.group(0) if match else None


def _extract_cidr(prompt: str) -> str | None:
    match = CIDR_PATTERN.search(prompt)
    return match.group(0) if match else None


def _extract_named_value(prompt: str) -> str | None:
    match = re.search(r"\b(?:named|called)\s+([A-Za-z0-9._-]+)", prompt, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_bucket_name(prompt: str) -> str | None:
    match = re.search(
        r"\bbucket\s+(?:named|called)\s+([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])",
        prompt.lower(),
    )
    return match.group(1) if match else None
