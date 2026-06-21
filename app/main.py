import uuid
import strawberry
from strawberry.asgi import GraphQL
from strawberry.extensions import SchemaExtension, MaskErrors
from starlette.requests import Request
from app.database import async_session
from app.context import get_context
from app.schema.queries import Query
from app.schema.mutations import Mutation


class CloseSessionExtension(SchemaExtension):
    async def on_operation(self):
        yield
        await self.execution_context.context.session.close()


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        CloseSessionExtension,
        MaskErrors(should_mask_error=lambda error: not (error.extensions and "code" in error.extensions)),
    ],
)

class TaskAPI(GraphQL):
    async def get_context(self, request: Request, response=None):
        session = async_session()
        user_header = request.headers.get("x-user-id")
        try:
            current_user_id = uuid.UUID(user_header) if user_header else None
        except ValueError:
            current_user_id = None
        return await get_context(session, current_user_id)

app = TaskAPI(schema, graphql_ide="graphiql")