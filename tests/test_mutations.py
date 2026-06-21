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

BULK_CHANGE_STATUS = """
mutation($ids: [UUID!]!, $status: TaskStatus!) {
  bulkChangeTaskStatus(ids: $ids, status: $status) {
    succeeded { id status version }
    failed { id code message }
  }
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


@pytest.mark.asyncio
async def test_bulk_change_task_status_success(session, users, project):
    alice, bob = users
    task_a = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))
    task_b = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))

    bob_ctx = make_context(session, current_user_id=bob.id)
    result = await schema.execute(
        BULK_CHANGE_STATUS,
        variable_values={"ids": [task_a["id"], task_b["id"]], "status": "DONE"},
        context_value=bob_ctx,
    )
    assert result.errors is None
    payload = result.data["bulkChangeTaskStatus"]
    assert payload["failed"] == []
    succeeded_ids = {t["id"] for t in payload["succeeded"]}
    assert succeeded_ids == {task_a["id"], task_b["id"]}
    assert all(t["status"] == "DONE" for t in payload["succeeded"])
    assert all(t["version"] == 2 for t in payload["succeeded"])  # bumped from 1 -> 2


@pytest.mark.asyncio
async def test_bulk_change_task_status_partial_failure(session, users, project):
    import uuid
    alice, bob = users
    # bob is the assignee — should succeed
    allowed_task = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))
    # alice is the assignee, not bob — should be rejected
    forbidden_task = await _create_task(session, alice.id, project.id, assigneeId=str(alice.id))
    missing_id = str(uuid.uuid4())

    bob_ctx = make_context(session, current_user_id=bob.id)
    result = await schema.execute(
        BULK_CHANGE_STATUS,
        variable_values={"ids": [allowed_task["id"], forbidden_task["id"], missing_id], "status": "DONE"},
        context_value=bob_ctx,
    )
    assert result.errors is None
    payload = result.data["bulkChangeTaskStatus"]

    assert [t["id"] for t in payload["succeeded"]] == [allowed_task["id"]]

    failures_by_id = {f["id"]: f["code"] for f in payload["failed"]}
    assert failures_by_id[forbidden_task["id"]] == "PERMISSION_DENIED"
    assert failures_by_id[missing_id] == "TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_bulk_change_task_status_requires_auth(session, users, project):
    alice, bob = users
    task = await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))

    anon_ctx = make_context(session, current_user_id=None)
    result = await schema.execute(
        BULK_CHANGE_STATUS,
        variable_values={"ids": [task["id"]], "status": "DONE"},
        context_value=anon_ctx,
    )
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_bulk_change_task_status_is_batched(session, users, project, query_log):
    alice, bob = users
    tasks = [
        await _create_task(session, alice.id, project.id, assigneeId=str(bob.id))
        for _ in range(5)
    ]
    bob_ctx = make_context(session, current_user_id=bob.id)

    query_log.clear()
    result = await schema.execute(
        BULK_CHANGE_STATUS,
        variable_values={"ids": [t["id"] for t in tasks], "status": "DONE"},
        context_value=bob_ctx,
    )
    assert result.errors is None
    assert len(result.data["bulkChangeTaskStatus"]["succeeded"]) == 5

    # 1 SELECT to fetch all candidate tasks + 1 UPDATE...RETURNING for the
    # allowed set, regardless of how many ids are in the batch — not 5 of each.
    select_statements = [s for s in query_log if s.strip().upper().startswith("SELECT")]
    update_statements = [s for s in query_log if s.strip().upper().startswith("UPDATE")]
    assert len(select_statements) <= 1
    assert len(update_statements) <= 1