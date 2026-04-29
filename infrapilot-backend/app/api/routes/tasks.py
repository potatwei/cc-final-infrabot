from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage
import sys
import os

# This lets your FastAPI app find the agents/ and tools/ folders
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../'))

from agents.bedrock_graph import build_graph
from app.db.database import get_db
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse

router = APIRouter()


@router.post("/task", response_model=TaskResponse)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    # 1. Save task to DB immediately
    new_task = Task(
        user_prompt=task_data.user_prompt,
        status="pending",
        code_payload=None
    )
    db.add(new_task)
    db.commit()

    try:
        # 2. Call Person B's agent
        graph = build_graph()
        result = graph.invoke({
            "messages": [HumanMessage(content=task_data.user_prompt)],
            "final_payload": {}
        })

        # 3. Extract the payload and save it
        payload = result["final_payload"]
        new_task.code_payload = payload
        new_task.status = "complete" if payload.get("status") == "success" else "failed"

    except Exception as e:
        new_task.status = "failed"
        new_task.code_payload = {"status": "error", "explanation": str(e)}

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