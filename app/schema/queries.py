import uuid
from datetime import datetime
from typing import Optional
import strawberry
from graphql import GraphQLError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, func, tuple_

from app.models import Task, TaskStatus as ModelStatus, TaskPriority as ModelPriority
from app.sorting import PRIORITY_RANK, STATUS_RANK, PRIORITY_ORDER, STATUS_ORDER
from app.cursors import encode_cursor, decode_cursor
from app.schema.types import (
    TaskType, TaskConnection, TaskEdge, PageInfo,
    TaskFilter, TaskSort, TaskSortField, SortDirection,
    task_to_type,
)


class PaginationArgs(BaseModel):
    first: int = Field(default=20, ge=1, le=100)


def _sort_column(field: TaskSortField):
    return {
        TaskSortField.CREATED_AT: Task.created_at,
        TaskSortField.PRIORITY: PRIORITY_RANK,
        TaskSortField.STATUS: STATUS_RANK,
    }[field]


def _cursor_value(field: TaskSortField, task: Task):
    if field == TaskSortField.CREATED_AT:
        return task.created_at.isoformat()
    if field == TaskSortField.PRIORITY:
        return PRIORITY_ORDER[task.priority]
    return STATUS_ORDER[task.status]


@strawberry.type
class Query:
    @strawberry.field
    async def task(self, info: strawberry.Info, id: uuid.UUID) -> Optional[TaskType]:
        task = await info.context.session.get(Task, id)
        return task_to_type(task) if task else None

    @strawberry.field
    async def tasks(
        self,
        info: strawberry.Info,
        filter: Optional[TaskFilter] = None,
        sort: Optional[TaskSort] = None,
        first: int = 20,
        after: Optional[str] = None,
    ) -> TaskConnection:
        try:
            args = PaginationArgs(first=first)
        except ValidationError as e:
            raise GraphQLError(
                "Invalid pagination arguments",
                extensions={"code": "BAD_USER_INPUT", "details": e.errors()},
            )

        sort = sort or TaskSort()
        session = info.context.session
        col = _sort_column(sort.field)
        descending = sort.direction == SortDirection.DESC

        stmt = select(Task)
        count_stmt = select(func.count()).select_from(Task)

        if filter:
            if filter.project_id:
                stmt = stmt.where(Task.project_id == filter.project_id)
                count_stmt = count_stmt.where(Task.project_id == filter.project_id)
            if filter.status:
                stmt = stmt.where(Task.status == ModelStatus(filter.status.value))
                count_stmt = count_stmt.where(Task.status == ModelStatus(filter.status.value))
            if filter.priority:
                stmt = stmt.where(Task.priority == ModelPriority(filter.priority.value))
                count_stmt = count_stmt.where(Task.priority == ModelPriority(filter.priority.value))
            if filter.assignee_id:
                stmt = stmt.where(Task.assignee_id == filter.assignee_id)
                count_stmt = count_stmt.where(Task.assignee_id == filter.assignee_id)

        stmt = stmt.order_by(col.desc() if descending else col.asc(),
                              Task.id.desc() if descending else Task.id.asc())

        if after:
            cursor_value, cursor_id = decode_cursor(after)
            if sort.field == TaskSortField.CREATED_AT:
                cursor_value = datetime.fromisoformat(cursor_value)
            row = tuple_(col, Task.id)
            cmp = tuple_(cursor_value, cursor_id)
            stmt = stmt.where(row < cmp if descending else row > cmp)

        stmt = stmt.limit(args.first + 1)  # fetch one extra to know if there's a next page

        result = await session.execute(stmt)
        tasks = list(result.scalars())
        has_next = len(tasks) > args.first
        tasks = tasks[: args.first]

        total_count = (await session.execute(count_stmt)).scalar_one()

        edges = [
            TaskEdge(cursor=encode_cursor(_cursor_value(sort.field, t), t.id), node=task_to_type(t))
            for t in tasks
        ]

        return TaskConnection(
            edges=edges,
            page_info=PageInfo(has_next_page=has_next, end_cursor=edges[-1].cursor if edges else None),
            total_count=total_count,
        )