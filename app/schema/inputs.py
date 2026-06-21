from typing import Optional
import uuid
from pydantic import BaseModel, field_validator
from app.models import TaskPriority

def _validate_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("title must not be blank")
    if len(v) > 300:
        raise ValueError("title must be at most 300 characters")
    return v

class CreateTaskInput(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: uuid.UUID
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[uuid.UUID] = None

    @field_validator("title")
    @classmethod
    def check_title(cls, v):
        return _validate_title(v)

class UpdateTaskInput(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None

    @field_validator("title")
    @classmethod
    def check_title(cls, v):
        return _validate_title(v) if v is not None else v