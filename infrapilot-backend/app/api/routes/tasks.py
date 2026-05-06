from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskContinue, TaskResponse
from app.core.task_status import map_task_status
import boto3
import json

router = APIRouter()

SQS_AGENT_QUEUE = "https://sqs.us-east-1.amazonaws.com/969084115150/infrapilot-tasks"
SQS_TOOLS_QUEUE = "https://sqs.us-east-1.amazonaws.com/969084115150/infrapilot-tools"

sqs = boto3.client("sqs", region_name="us-east-1")


@router.post("/task", response_model=TaskResponse)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    # 1. Save task to DB with status pending
    new_task = Task(
        user_prompt=task_data.user_prompt,
        status="pending",
        code_payload=None
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    # 2. Publish to SQS1 for Lambda B (agent + Bedrock)
    sqs.send_message(
        QueueUrl=SQS_AGENT_QUEUE,
        MessageBody=json.dumps({
            "task_id": new_task.task_id,
            "user_prompt": task_data.user_prompt,
            "mode": task_data.mode
        })
    )

    # 3. Return instantly
    return new_task


@router.post("/task/{task_id}/continue", response_model=TaskResponse)
def continue_task(task_id: str, task_data: TaskContinue, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Set back to pending while Lambda C processes
    task.status = "pending"
    db.commit()

    # Publish to SQS2 for Lambda C (Person C's tools)
    sqs.send_message(
        QueueUrl=SQS_TOOLS_QUEUE,
        MessageBody=json.dumps({
            "task_id": task_id,
            "selected_tool": task.code_payload.get("selected_tool") if task.code_payload else None,
            "provided_inputs": task_data.provided_inputs,
            "user_input": task_data.user_input,
            "execute": task_data.execute,
            "existing_payload": task.code_payload
        })
    )

    db.refresh(task)
    return task


@router.post("/task/{task_id}/result")
def receive_result(task_id: str, payload: dict, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.code_payload = payload
    task.status = map_task_status(payload)
    db.commit()
    return {"message": "Result received"}


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