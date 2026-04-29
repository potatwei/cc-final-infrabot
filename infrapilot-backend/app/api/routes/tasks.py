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
from app.schemas.task import TaskCreate, TaskResponse

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
