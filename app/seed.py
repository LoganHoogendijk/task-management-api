import asyncio
import uuid
from app.database import async_session
from app.models import User, Project, Task, TaskStatus, TaskPriority

ALICE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


async def seed():
    async with async_session() as session:
        alice = User(id=ALICE_ID, name="Alice", email="alice@example.com")
        bob = User(id=BOB_ID, name="Bob", email="bob@example.com")
        project = Project(id=PROJECT_ID, name="Demo Project", description="Seed data for manual testing")

        session.add_all([alice, bob, project])
        await session.flush()  # so FKs below are valid before commit

        session.add(Task(
            title="Set up CI pipeline",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            project_id=project.id,
            assignee_id=bob.id,
            created_by_id=alice.id,
        ))

        await session.commit()
        print(f"Seeded. Alice={ALICE_ID}  Bob={BOB_ID}  Project={PROJECT_ID}")


if __name__ == "__main__":
    asyncio.run(seed())