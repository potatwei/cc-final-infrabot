from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse

router = APIRouter()

STUB_PAYLOAD = {
    "status": "success",
    "task_id": "stub",
    "metadata": {
        "intent": "deploy_s3_storage",
        "provider": "aws",
        "region": "us-east-1",
        "requires_confirmation": True,
        "estimated_risk": "low"
    },
    "infrastructure": {
        "files": [
            {
                "path": "main.tf",
                "content": "resource \"aws_s3_bucket\" \"b\" {\n  bucket = \"my-data-bucket\"\n}",
                "type": "terraform"
            }
        ],
        "commands": [
            {
                "step": 1,
                "label": "Initializing Terraform",
                "binary": "terraform",
                "args": ["init"],
                "critical": True
            },
            {
                "step": 2,
                "label": "Deploying S3 Bucket",
                "binary": "terraform",
                "args": ["apply", "-auto-approve"],
                "critical": True
            }
        ]
    },
    "explanation": "Terraform configuration to create a private S3 bucket in us-east-1."
}


@router.post("/task", response_model=TaskResponse)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    new_task = Task(
        user_prompt=task_data.user_prompt,
        status="pending",
        code_payload=STUB_PAYLOAD
    )
    db.add(new_task)
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