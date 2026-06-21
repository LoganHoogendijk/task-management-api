import os
import uuid
import pytest
import pytest_asyncio
import asyncio
from sqlalchemy.pool import NullPool
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
from app.models import User, Project
from app.context import Context
from app.loaders import make_user_loader, make_project_loader

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://taskmanager_user:devpassword@localhost:5433/taskmanager_test",
)

test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def session():
    async with TestSessionLocal() as s:
        yield s


@pytest_asyncio.fixture
async def users(session):
    alice = User(id=uuid.uuid4(), name="Alice", email=f"alice-{uuid.uuid4()}@example.com")
    bob = User(id=uuid.uuid4(), name="Bob", email=f"bob-{uuid.uuid4()}@example.com")
    session.add_all([alice, bob])
    await session.commit()
    return alice, bob


@pytest_asyncio.fixture
async def project(session):
    p = Project(id=uuid.uuid4(), name="Test Project")
    session.add(p)
    await session.commit()
    return p


@pytest.fixture
def query_log():
    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    yield statements
    event.remove(test_engine.sync_engine, "before_cursor_execute", before_cursor_execute)


def make_context(session, current_user_id=None) -> Context:
    return Context(
        session=session,
        user_loader=make_user_loader(session),
        project_loader=make_project_loader(session),
        current_user_id=current_user_id,
    )