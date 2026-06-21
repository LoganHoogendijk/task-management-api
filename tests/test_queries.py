import pytest
from app.main import schema
from app.models import Task, TaskStatus, TaskPriority
from tests.conftest import make_context

LIST_TASKS = """
query($projectId: UUID!, $status: TaskStatus, $after: String) {
  tasks(filter: { projectId: $projectId, status: $status }, first: 2, after: $after) {
    edges { cursor node { id title status } }
    pageInfo { hasNextPage endCursor }
    totalCount
  }
}
"""

LIST_WITH_NESTED = """
query($projectId: UUID!) {
  tasks(filter: { projectId: $projectId }) {
    edges { node { title project { name } assignee { name } } }
  }
}
"""


async def _make_tasks(session, project, creator, assignee, n, status=TaskStatus.TODO):
    tasks = [
        Task(title=f"Task {i}", project_id=project.id, assignee_id=assignee.id,
             created_by_id=creator.id, status=status, priority=TaskPriority.MEDIUM)
        for i in range(n)
    ]
    session.add_all(tasks)
    await session.commit()
    return tasks


@pytest.mark.asyncio
async def test_pagination_walks_full_list_without_duplicates(session, users, project):
    alice, bob = users
    await _make_tasks(session, project, alice, bob, n=5)
    ctx = make_context(session)

    seen_ids = set()
    after = None
    pages = 0
    while True:
        result = await schema.execute(
            LIST_TASKS, variable_values={"projectId": str(project.id), "after": after}, context_value=ctx
        )
        assert result.errors is None
        page = result.data["tasks"]
        for edge in page["edges"]:
            assert edge["node"]["id"] not in seen_ids
            seen_ids.add(edge["node"]["id"])
        pages += 1
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
        assert pages < 10  # safety net against an infinite loop bug

    assert len(seen_ids) == 5
    assert pages == 3  # 2 + 2 + 1


@pytest.mark.asyncio
async def test_filter_by_status(session, users, project):
    alice, bob = users
    await _make_tasks(session, project, alice, bob, n=2, status=TaskStatus.TODO)
    await _make_tasks(session, project, alice, bob, n=3, status=TaskStatus.DONE)
    ctx = make_context(session)

    result = await schema.execute(
        LIST_TASKS, variable_values={"projectId": str(project.id), "status": "DONE"}, context_value=ctx
    )
    assert result.errors is None
    assert result.data["tasks"]["totalCount"] == 3


@pytest.mark.asyncio
async def test_nested_resolution_does_not_n_plus_one(session, users, project, query_log):
    alice, bob = users
    await _make_tasks(session, project, alice, bob, n=10)
    ctx = make_context(session)

    query_log.clear()
    result = await schema.execute(
        LIST_WITH_NESTED, variable_values={"projectId": str(project.id)}, context_value=ctx
    )
    assert result.errors is None
    assert len(result.data["tasks"]["edges"]) == 10

    # 1 tasks select + 1 count select + 1 batched project select + 1 batched user select.
    # Without DataLoader batching this would be 1 + 1 + 10 + 10 = 22.
    select_statements = [s for s in query_log if s.strip().upper().startswith("SELECT")]
    assert len(select_statements) <= 4