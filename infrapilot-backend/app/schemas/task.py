from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class FileItem(BaseModel):
    path: str
    content: str
    type: Optional[str] = None
    source_step: Optional[str] = None


class CommandItem(BaseModel):
    step_name: Optional[str] = None
    description: Optional[str] = None
    command: Optional[str] = None
    critical: Optional[bool] = None


class CodePayload(BaseModel):
    status: str
    task_id: str
    intent: Optional[str] = None
    files: List[FileItem] = []
    commands: List[dict] = []
    notes: List[str] = []
    requires_confirmation: bool = False
    steps: List[dict] = []
    error: Optional[str] = None
    missing_parameters: List[str] = []
    explanation: str


class TaskCreate(BaseModel):
    user_prompt: str


class TaskResponse(BaseModel):
    task_id: str
    status: str
    user_prompt: str
    code_payload: Optional[CodePayload] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True