from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
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
    missing_inputs = _compute_missing_inputs(
        required_inputs=payload.get("required_inputs") or spec["required_inputs"],
        provided_inputs=provided_inputs,
        defaults=payload.get("defaults") or spec["defaults"],
    )

    if missing_inputs:
        task.code_payload = _build_discovery_continuation_payload(
            task_id=task.task_id,
            payload=payload,
            spec=spec,
            provided_inputs=provided_inputs,
            missing_inputs=missing_inputs,
        )
        task.status = map_task_status(task.code_payload)
        db.commit()
        db.refresh(task)
        return task

    precheck_tool_name = payload.get("precheck_tool") or spec.get("precheck_tool")
    if isinstance(precheck_tool_name, str):
        precheck_tool = CORE_TOOLS_BY_NAME.get(precheck_tool_name)
        if precheck_tool is None:
            raise HTTPException(status_code=500, detail="Configured precheck tool is unavailable.")
        precheck_result = precheck_tool.invoke(_build_precheck_inputs(provided_inputs))
        if precheck_result.get("status") != "success":
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


def _build_discovery_continuation_payload(
    *,
    task_id: str,
    payload: dict,
    spec: dict,
    provided_inputs: dict,
    missing_inputs: list[str],
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
        "explanation": (
            "More input is required before execution can continue: "
            f"{', '.join(missing_inputs)}."
        ),
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
