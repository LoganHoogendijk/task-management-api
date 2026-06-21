import uuid
import strawberry
from graphql import GraphQLError
from pydantic import ValidationError
from sqlalchemy import select, update as sa_update

from app.models import Task, Project, User, TaskStatus as ModelStatus, TaskPriority as ModelPriority
from app.errors import (
    DomainError, TaskNotFoundError, ProjectNotFoundError, UserNotFoundError,
    PermissionDeniedError, VersionConflictError, UnauthenticatedError,
)
from app.schema.types import (
    TaskType, TaskStatus, TaskPriority, task_to_type,
    CreateTaskGQLInput, UpdateTaskGQLInput,
    BulkTaskFailure, BulkTaskMutationResult,
)
from app.schema.inputs import CreateTaskInput, UpdateTaskInput

MAX_BULK_IDS = 100


def _require_auth(info) -> uuid.UUID:
    if info.context.current_user_id is None:
        raise GraphQLError(str(UnauthenticatedError()), extensions={"code": "UNAUTHENTICATED"})
    return info.context.current_user_id


def _domain_error(e: DomainError) -> GraphQLError:
    return GraphQLError(str(e), extensions={"code": e.code})


def _validation_error(e: ValidationError) -> GraphQLError:
    return GraphQLError("Invalid input", extensions={"code": "BAD_USER_INPUT", "details": e.errors()})


async def _apply_optimistic_update(session, task_id: uuid.UUID, expected_version: int, values: dict) -> Task:
    stmt = (
        sa_update(Task)
        .where(Task.id == task_id, Task.version == expected_version)
        .values(**values, version=Task.version + 1)
        .returning(Task)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        existing = await session.get(Task, task_id)
        if existing is None:
            raise TaskNotFoundError(task_id)
        raise VersionConflictError()
    await session.commit()
    return row


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_task(self, info: strawberry.Info, input: CreateTaskGQLInput) -> TaskType:
        session = info.context.session
        creator_id = _require_auth(info)

        try:
            data = CreateTaskInput(
                title=input.title,
                description=input.description,
                project_id=input.project_id,
                priority=ModelPriority(input.priority.value),
                assignee_id=input.assignee_id,
            )
        except ValidationError as e:
            raise _validation_error(e)

        if await session.get(Project, data.project_id) is None:
            raise _domain_error(ProjectNotFoundError(data.project_id))

        if data.assignee_id and await session.get(User, data.assignee_id) is None:
            raise _domain_error(UserNotFoundError(data.assignee_id))

        task = Task(
            title=data.title,
            description=data.description,
            project_id=data.project_id,
            priority=data.priority,
            assignee_id=data.assignee_id,
            status=ModelStatus.TODO,
            created_by_id=creator_id,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task_to_type(task)

    @strawberry.mutation
    async def update_task(
        self, info: strawberry.Info, id: uuid.UUID, version: int, input: UpdateTaskGQLInput
    ) -> TaskType:
        session = info.context.session
        actor_id = _require_auth(info)

        task = await session.get(Task, id)
        if task is None:
            raise _domain_error(TaskNotFoundError(id))
        if actor_id not in (task.created_by_id, task.assignee_id):
            raise _domain_error(PermissionDeniedError("Only the creator or assignee can edit this task"))

        raw = {}
        if input.title is not strawberry.UNSET:
            raw["title"] = input.title
        if input.description is not strawberry.UNSET:
            raw["description"] = input.description
        if input.priority is not strawberry.UNSET:
            raw["priority"] = ModelPriority(input.priority.value)

        try:
            data = UpdateTaskInput(**raw)
        except ValidationError as e:
            raise _validation_error(e)

        values = data.model_dump(exclude_unset=True)
        if not values:
            return task_to_type(task)

        try:
            updated = await _apply_optimistic_update(session, id, version, values)
        except DomainError as e:
            raise _domain_error(e)
        return task_to_type(updated)

    @strawberry.mutation
    async def change_task_status(
        self, info: strawberry.Info, id: uuid.UUID, version: int, status: TaskStatus
    ) -> TaskType:
        session = info.context.session
        actor_id = _require_auth(info)

        task = await session.get(Task, id)
        if task is None:
            raise _domain_error(TaskNotFoundError(id))
        if task.assignee_id != actor_id:
            raise _domain_error(PermissionDeniedError("Only the assignee can change task status"))

        try:
            updated = await _apply_optimistic_update(session, id, version, {"status": ModelStatus(status.value)})
        except DomainError as e:
            raise _domain_error(e)
        return task_to_type(updated)

    @strawberry.mutation
    async def assign_task(
        self, info: strawberry.Info, id: uuid.UUID, version: int, assignee_id: uuid.UUID
    ) -> TaskType:
        session = info.context.session
        actor_id = _require_auth(info)

        task = await session.get(Task, id)
        if task is None:
            raise _domain_error(TaskNotFoundError(id))
        if task.created_by_id != actor_id:
            raise _domain_error(PermissionDeniedError("Only the creator can reassign this task"))
        if await session.get(User, assignee_id) is None:
            raise _domain_error(UserNotFoundError(assignee_id))

        try:
            updated = await _apply_optimistic_update(session, id, version, {"assignee_id": assignee_id})
        except DomainError as e:
            raise _domain_error(e)
        return task_to_type(updated)

    @strawberry.mutation
    async def unassign_task(self, info: strawberry.Info, id: uuid.UUID, version: int) -> TaskType:
        session = info.context.session
        actor_id = _require_auth(info)

        task = await session.get(Task, id)
        if task is None:
            raise _domain_error(TaskNotFoundError(id))
        if actor_id not in (task.created_by_id, task.assignee_id):
            raise _domain_error(PermissionDeniedError("Only the creator or current assignee can unassign"))

        try:
            updated = await _apply_optimistic_update(session, id, version, {"assignee_id": None})
        except DomainError as e:
            raise _domain_error(e)
        return task_to_type(updated)

    @strawberry.mutation
    async def delete_task(self, info: strawberry.Info, id: uuid.UUID) -> bool:
        session = info.context.session
        actor_id = _require_auth(info)

        task = await session.get(Task, id)
        if task is None:
            raise _domain_error(TaskNotFoundError(id))
        if task.created_by_id != actor_id:
            raise _domain_error(PermissionDeniedError("Only the creator can delete this task"))

        await session.delete(task)
        await session.commit()
        return True

    @strawberry.mutation
    async def bulk_change_task_status(
        self, info: strawberry.Info, ids: list[uuid.UUID], status: TaskStatus
    ) -> BulkTaskMutationResult:
        """Set the same status on many tasks in one round trip.

        Same authorization rule as `changeTaskStatus` (assignee only),
        applied per task rather than failing the whole batch on one bad id.
        Deliberately skips per-item expected `version` (see README) — this
        is a "set state X on these tasks" operation, not a guarded edit of
        one task, so it's naturally idempotent: calling it again with the
        same ids+status is a no-op in effect (status unchanged), even
        though `version` still increments each time.
        """
        session = info.context.session
        actor_id = _require_auth(info)

        if not ids:
            return BulkTaskMutationResult(succeeded=[], failed=[])
        if len(ids) > MAX_BULK_IDS:
            raise GraphQLError(
                f"Cannot operate on more than {MAX_BULK_IDS} tasks at once",
                extensions={"code": "BAD_USER_INPUT"},
            )

        unique_ids = list(dict.fromkeys(ids))  # de-dupe, preserve order

        result = await session.execute(select(Task).where(Task.id.in_(unique_ids)))
        found = {t.id: t for t in result.scalars()}

        failed: list[BulkTaskFailure] = []
        allowed_ids: list[uuid.UUID] = []

        for task_id in unique_ids:
            task = found.get(task_id)
            if task is None:
                err = TaskNotFoundError(task_id)
                failed.append(BulkTaskFailure(id=task_id, code=err.code, message=str(err)))
                continue
            if task.assignee_id != actor_id:
                err = PermissionDeniedError("Only the assignee can change task status")
                failed.append(BulkTaskFailure(id=task_id, code=err.code, message=str(err)))
                continue
            allowed_ids.append(task_id)

        if not allowed_ids:
            return BulkTaskMutationResult(succeeded=[], failed=failed)

        stmt = (
            sa_update(Task)
            .where(Task.id.in_(allowed_ids))
            .values(status=ModelStatus(status.value), version=Task.version + 1)
            .returning(Task)
        )
        result = await session.execute(stmt)
        updated_tasks = result.scalars().all()
        await session.commit()

        succeeded = [task_to_type(t) for t in updated_tasks]
        return BulkTaskMutationResult(succeeded=succeeded, failed=failed)