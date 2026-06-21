import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
import strawberry
from app.models import Task

@strawberry.enum
class TaskStatus(Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"

@strawberry.enum
class TaskPriority(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"

@strawberry.enum
class TaskSortField(Enum):
    CREATED_AT = "CREATED_AT"
    PRIORITY = "PRIORITY"
    STATUS = "STATUS"

@strawberry.enum
class SortDirection(Enum):
    ASC = "ASC"
    DESC = "DESC"

@strawberry.type
class UserType:
    id: uuid.UUID
    name: str
    email: str

@strawberry.type
class ProjectType:
    id: uuid.UUID
    name: str
    description: Optional[str]

@strawberry.type
class TaskType:
    id: uuid.UUID
    title: str
    description: Optional[str]
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime
    updated_at: datetime
    version: int

    # not exposed as GraphQL fields, just carried on the Python object
    # so the resolvers below can use them
    project_id: strawberry.Private[uuid.UUID]
    assignee_id: strawberry.Private[Optional[uuid.UUID]]

    @strawberry.field
    async def project(self, info: strawberry.Info) -> ProjectType:
        p = await info.context.project_loader.load(self.project_id)
        return ProjectType(id=p.id, name=p.name, description=p.description)

    @strawberry.field
    async def assignee(self, info: strawberry.Info) -> Optional[UserType]:
        if self.assignee_id is None:
            return None
        u = await info.context.user_loader.load(self.assignee_id)
        return UserType(id=u.id, name=u.name, email=u.email)


def task_to_type(task: Task) -> TaskType:
    return TaskType(
        id=task.id,
        title=task.title,
        description=task.description,
        status=TaskStatus(task.status.value),
        priority=TaskPriority(task.priority.value),
        created_at=task.created_at,
        updated_at=task.updated_at,
        version=task.version,
        project_id=task.project_id,
        assignee_id=task.assignee_id,
    )


@strawberry.input
class TaskFilter:
    project_id: Optional[uuid.UUID] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[uuid.UUID] = None

@strawberry.input
class TaskSort:
    field: TaskSortField = TaskSortField.CREATED_AT
    direction: SortDirection = SortDirection.DESC

@strawberry.type
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str]

@strawberry.type
class TaskEdge:
    cursor: str
    node: TaskType

@strawberry.type
class TaskConnection:
    edges: list[TaskEdge]
    page_info: PageInfo
    total_count: int

@strawberry.input
class CreateTaskGQLInput:
    title: str
    project_id: uuid.UUID
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[uuid.UUID] = None

@strawberry.input
class UpdateTaskGQLInput:
    title: Optional[str] = strawberry.UNSET
    description: Optional[str] = strawberry.UNSET
    priority: Optional[TaskPriority] = strawberry.UNSET

@strawberry.type
class BulkTaskFailure:
    id: uuid.UUID
    code: str
    message: str

@strawberry.type
class BulkTaskMutationResult:
    succeeded: list[TaskType]
    failed: list[BulkTaskFailure]