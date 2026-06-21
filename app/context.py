import dataclasses
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader
from app.loaders import make_user_loader, make_project_loader

@dataclasses.dataclass
class Context:
    session: AsyncSession
    user_loader: DataLoader
    project_loader: DataLoader
    current_user_id: uuid.UUID | None  # who's making this request

async def get_context(session: AsyncSession, current_user_id: uuid.UUID | None) -> Context:
    return Context(
        session=session,
        user_loader=make_user_loader(session),
        project_loader=make_project_loader(session),
        current_user_id=current_user_id,
    )