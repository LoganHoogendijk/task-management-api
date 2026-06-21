from strawberry.dataloader import DataLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Project
import uuid

def make_user_loader(session: AsyncSession) -> DataLoader:
    async def batch_load(ids: list[uuid.UUID]) -> list[User | None]:
        result = await session.execute(select(User).where(User.id.in_(ids)))
        by_id = {u.id: u for u in result.scalars()}
        return [by_id.get(i) for i in ids]
    return DataLoader(load_fn=batch_load)

def make_project_loader(session: AsyncSession) -> DataLoader:
    async def batch_load(ids: list[uuid.UUID]) -> list[Project | None]:
        result = await session.execute(select(Project).where(Project.id.in_(ids)))
        by_id = {p.id: p for p in result.scalars()}
        return [by_id.get(i) for i in ids]
    return DataLoader(load_fn=batch_load)