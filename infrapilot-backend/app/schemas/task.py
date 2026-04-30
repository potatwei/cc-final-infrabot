from pydantic import BaseModel, Field
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
    mode: Optional[str] = None
    intent: Optional[str] = None
    selected_tool: Optional[str] = None
    required_inputs: List[str] = []
    recommended_inputs: List[str] = []
    optional_inputs: List[str] = []
    defaults: dict = {}
    provided_inputs: dict = {}
    missing_inputs: List[str] = []
    ready_to_execute: Optional[bool] = None
    precheck_tool: Optional[str] = None
    files: List[FileItem] = []
    commands: List[dict] = []
    notes: List[str] = []
    requires_confirmation: bool = False
    steps: List[dict] = []
    error: Optional[str] = None
    missing_parameters: List[str] = []
    explanation: str

    class Config:
        extra = "allow"


class TaskCreate(BaseModel):
    user_prompt: str
    mode: str = "execution"


class TaskContinue(BaseModel):
    user_input: Optional[str] = None
    provided_inputs: dict = Field(default_factory=dict)
    execute: bool = False


class TaskResponse(BaseModel):
    task_id: str
    status: str
    user_prompt: str
    code_payload: Optional[CodePayload] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True