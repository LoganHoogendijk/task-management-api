import pytest
from app.main import schema
from tests.conftest import make_context

CREATE_TASK = """
mutation($input: CreateTaskGQLInput!) {
  createTask(input: $input) { id title status version }
}
"""

DELETE_TASK = """
mutation($id: UUID!) { deleteTask(id: $id) }
"""

CHANGE_STATUS = """
mutation($id: UUID!, $version: Int!, $status: TaskStatus!) {
  changeTaskStatus(id: $id, version: $version, status: $status) { status version }
}
"""

ASSIGN_TASK = """
mutation($id: UUID!, $version: Int!, $assigneeId: UUID!) {
  assignTask(id: $id, version: $version, assigneeId: $assigneeId) { id }
}
"""


async def _create_task(session, creator_id, project_id, **overrides):
    ctx = make_context(session, current_user_id=creator_id)
    variables = {"input": {"title": "A task", "projectId": str(project_id), **overrides}}
    result = await schema.execute(CREATE_TASK, variable_values=variables, context_value=ctx)
    assert result.errors is None, result.errors
    return result.data["createTask"]


@pytest.mark.asyncio
async def test_create_task_success(session, users, project):
    alice, _ = users
    task = await _create_task(session, alice.id, project.id)
    assert task["status"] == "TODO"
    assert task["version"] == 1


@pytest.mark.asyncio
async def test_create_task_blank_title_rejected(session, users, project):
    alice, _ = users
    ctx = make_context(session, current_user_id=alice.id)
    variables = {"input": {"title": "   ", "projectId": str(project.id)}}
    result = await schema.execute(CREATE_TASK, variable_values=variables, context_value=ctx)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "BAD_USER_INPUT"


@pytest.mark.asyncio
async def test_create_task_unknown_project_rejected(session, users):
    import uuid
    alice, _ = users
    ctx = make_context(session, current_user_id=alice.id)
    variables = {"input": {"title": "Valid title", "projectId": str(uuid.uuid4())}}
    result = await schema.execute(CREATE_TASK, variable_values=variables, context_value=ctx)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_task_requires_auth(session, project):
    ctx = make_context(session, current_user_id=None)
    variables = {"input": {"title": "Valid title", "projectId": str(project.id)}}
    result = await schema.execute(CREATE_TASK, variable_values=variables, context_value=ctx)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_only_creator_can_delete(session, users, project):
    alice, bob = users
    task = await _create_task(session, alice.id, project.id)

    bob_ctx = make_context(session, current_user_id=bob.id)
    result = await schema.execute(DELETE_TASK, variable_values={"id": task["id"]}, context_value=bob_ctx)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "PERMISSION_DENIED"

    alice_ctx = make_context(session, current_user_id=alice.id)
    result = await schema.execute(DELETE_TASK, variable_values={"id": task["id"]}, context_value=alice_ctx)
    assert result.errors is None
    assert result.data["deleteTask"] is True


@pytest.mark.asyncio
async def test_only_assignee_can_change_status(session, users, project):
    alice, bob = users
    task = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))

    alice_ctx = make_context(session, current_user_id=alice.id)
    result = await schema.execute(
        CHANGE_STATUS,
        variable_values={"id": task["id"], "version": task["version"], "status": "IN_PROGRESS"},
        context_value=alice_ctx,
    )
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "PERMISSION_DENIED"

    bob_ctx = make_context(session, current_user_id=bob.id)
    result = await schema.execute(
        CHANGE_STATUS,
        variable_values={"id": task["id"], "version": task["version"], "status": "IN_PROGRESS"},
        context_value=bob_ctx,
    )
    assert result.errors is None
    assert result.data["changeTaskStatus"]["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_version_conflict_on_stale_update(session, users, project):
    alice, bob = users
    task = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))

    bob_ctx = make_context(session, current_user_id=bob.id)
    # First update succeeds and bumps the version under the hood
    await schema.execute(
        CHANGE_STATUS,
        variable_values={"id": task["id"], "version": task["version"], "status": "IN_PROGRESS"},
        context_value=bob_ctx,
    )

    # Retry with the now-stale version, simulating a second client that read before the first update
    stale_result = await schema.execute(
        CHANGE_STATUS,
        variable_values={"id": task["id"], "version": task["version"], "status": "DONE"},
        context_value=bob_ctx,
    )
    assert stale_result.errors is not None
    assert stale_result.errors[0].extensions["code"] == "VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_only_creator_can_reassign(session, users, project):
    alice, bob = users
    task = await _create_task(session, alice.id, project.id)

    bob_ctx = make_context(session, current_user_id=bob.id)
    result = await schema.execute(
        ASSIGN_TASK,
        variable_values={"id": task["id"], "version": task["version"], "assigneeId": str(bob.id)},
        context_value=bob_ctx,
    )
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "PERMISSION_DENIED"