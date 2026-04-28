from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class FileItem(BaseModel):
    path: str
    content: str
    type: str


class CommandItem(BaseModel):
    step: int
    label: str
    binary: str
    args: List[str]
    critical: bool


class Infrastructure(BaseModel):
    files: List[FileItem]
    commands: List[CommandItem]


class Metadata(BaseModel):
    intent: str
    provider: str
    region: str
    requires_confirmation: bool
    estimated_risk: str


class CodePayload(BaseModel):
    status: str
    task_id: str
    metadata: Metadata
    infrastructure: Infrastructure
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