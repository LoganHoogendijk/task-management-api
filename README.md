# Task Management API

A GraphQL API for managing tasks within projects, built with Strawberry GraphQL,
SQLAlchemy (async), Alembic, and Postgres.

## Tech Stack

- Python 3.11+
- Strawberry GraphQL (code-first schema)
- Pydantic / pydantic-settings (input validation & config)
- SQLAlchemy 2.0 (async) + asyncpg
- Alembic (migrations)
- PostgreSQL 17
- Uvicorn (ASGI server)
- pytest / pytest-asyncio

## Running It

### Option A - Docker (recommended, no local setup needed)

```bash
docker compose up --build
```

This builds the app image, starts Postgres, waits for it to be healthy, runs
`alembic upgrade head` automatically, then starts the API.

Visit **http://localhost:8000** for the GraphiQL playground.

Seed some demo data (a project, two users, one task) so there's something to query:

```bash
docker compose exec app python -m app.seed
```

To fully reset (wipe the DB volume and start clean):

```bash
docker compose down -v
```

### Option B - Local dev

```bash
python -m venv venv
venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
```

Requires a local Postgres instance. Create the database and grant schema
ownership (Postgres 15+ restricts `public` schema rights by default):

```sql
CREATE DATABASE taskmanager;
CREATE USER taskmanager_user WITH PASSWORD 'devpassword';
GRANT ALL PRIVILEGES ON DATABASE taskmanager TO taskmanager_user;
\c taskmanager
ALTER SCHEMA public OWNER TO taskmanager_user;
```

Set `DATABASE_URL` in `.env`, then:

```bash
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

## Authentication (stubbed)

Every request is treated as made on behalf of a user, identified by an
`X-User-Id: <uuid>` header. There's no real auth (no password/token
verification) - this is a stand-in so permission logic has something
real to check against. See `app/seed.py` for two ready-made user IDs
to test with.

## Authorization model

| Action                            | Who can do it               |
| --------------------------------- | --------------------------- |
| Create task                       | Any authenticated user      |
| Update title/description/priority | Creator or current assignee |
| Change status                     | Current assignee only       |
| Bulk change status                | Current assignee only       |
| Assign / reassign                 | Creator only                |
| Unassign                          | Creator or current assignee |
| Delete                            | Creator only                |

Rationale: the creator owns the task's existence and who's responsible for
it; the assignee owns reporting progress on it. Errors return a typed
`PERMISSION_DENIED` code rather than a generic 403/500.

## Running Tests

### Option A - Docker

```bash
docker compose exec app pytest -v
```

`TEST_DATABASE_URL` is already set on the `app` service, pointing at a
`taskmanager_test` database created automatically alongside the main one
via `db/init-test-db.sql` (Postgres only runs init scripts on first boot
of an empty volume - if you already had a `pgdata` volume from before
this was added, run `docker compose down -v` once and `docker compose up
--build` again to pick it up).

### Option B - Local

Requires a separate test database (same setup as above, named
`taskmanager_test`), referenced via `TEST_DATABASE_URL` in `.env`.

```bash
pytest -v
```

Tests execute real GraphQL operations against the live `strawberry.Schema`
object with a hand-built context - exercising resolvers, DataLoaders, and
Pydantic validation exactly as production does, without going through the
ASGI/HTTP layer. Tables are truncated between tests rather than using
per-test transaction rollback, since the mutations themselves call
`session.commit()` internally, which conflicts with SAVEPOINT-based
rollback strategies - simpler at a small cost of speed.

One test (`test_nested_resolution_does_not_n_plus_one`) asserts directly on
the SQL statement count to prove nested resolution doesn't scale with row
count - not just spot-checked once by eye.

## Key Decisions & Tradeoffs

**Postgres over SQLite.** The assignment asks for concurrency handling and "a
real database." SQLite serializes all writes at the file level, which
would make the optimistic-locking path we built untestable in any
meaningful way - there's no real race to protect against. Docker Compose
solves the runnability concern instead (one command, no manual install),
without giving up a database that actually has the property being tested.

**Cursor (keyset) pagination, not OFFSET.** `OFFSET n` forces Postgres to
scan and discard `n` rows on every page - with "thousands of tasks per
project," that gets worse the deeper you page. Keyset pagination
(`WHERE (sort_col, id) > (last_value, last_id)`) stays roughly constant
cost regardless of page depth, backed by composite indexes on
`(project_id, created_at, id)`, `(project_id, status)`, etc. Cursors are
opaque base64 tokens - clients pass them back, never construct them.

**DataLoaders for nested fields.** `Task.project` and `Task.assignee`
resolvers go through per-request `DataLoader` instances that batch all IDs
requested within a tick into one `WHERE id IN (...)` query. Listing 1,000
tasks costs 1 query for tasks + 1 batched query for projects + 1 batched
query for users - not O(n) extra round trips.

**Optimistic concurrency via a `version` column.** Every mutating
operation is a single atomic `UPDATE ... WHERE id = :id AND version =
:expected_version`. If another request already moved the version on, zero
rows match and the client gets a typed `VERSION_CONFLICT` error telling
them to refetch and retry. This avoids a separate read-then-write race
window - the check and the write happen in the same statement, relying on
Postgres's row-level locking during the `UPDATE`.

**Typed errors, not bare exceptions.** All domain errors (`TASK_NOT_FOUND`,
`PERMISSION_DENIED`, `VERSION_CONFLICT`, `BAD_USER_INPUT`,
`UNAUTHENTICATED`, etc.) surface as `GraphQLError` with a `code` in
`extensions`, so clients can branch on a stable code instead of parsing
message text. Pydantic handles input shape/constraint validation;
domain rules (does the project exist, is the actor allowed) are checked
explicitly in resolvers.

**`strawberry.UNSET` for partial updates.** `updateTask`'s input fields
default to `UNSET` rather than `None`, so the API can distinguish "client
didn't mention this field" from "client explicitly set it to null."

**Total count costs a second query.** `tasks.totalCount` runs a separate
`COUNT(*)` alongside the page query. Cheap with the indexes in place at
realistic scale, but it's a real cost that would need revisiting (caching,
or dropping it) at much larger scale - a conscious tradeoff, not an
oversight.

**`bulkChangeTaskStatus` - batched, partial-success, and idempotent by
construction.** One `SELECT ... WHERE id IN (...)` to find the candidate
tasks, then one `UPDATE ... WHERE id IN (...) RETURNING *` for the ones
the caller is allowed to touch - cost doesn't scale with batch size, just
two statements whether the batch is 2 ids or 100. A bad id (not found,
not yours to touch) doesn't fail the whole batch; it's reported per-item
in `failed` alongside whatever did succeed, which is a better fit for a
"select several rows in the UI, bulk-update them" workflow than an
all-or-nothing transaction would be. It deliberately doesn't take a
per-item expected `version` the way the single-task mutations do - version
checking exists to protect a deliberate edit against a concurrent one,
and that's not the shape of this operation. The tradeoff is that it's not
safe against the "someone already moved this task to a different status
for a reason" race the way `changeTaskStatus` is; it's the right tool for
"close all of these," not for high-contention single-task edits. As a
side effect, it satisfies the "idempotent" framing too: calling it
twice with the same ids and status is a no-op in effect (the resulting
status doesn't change), even though `version` still ticks up each call.

## Deliberately Left Out

- **Real authentication** - stubbed via header, no token verification.
- **Role-based access beyond creator/assignee** (e.g. an admin override).
- **Rate limiting or request-level observability / structured logging** - the other
  bonus category; skipped in favor of `bulkChangeTaskStatus` to keep
  effort concentrated on one bonus done well rather than two done thinly.
- **Soft delete / audit trail** - deletes are hard deletes.
- **Real-time updates (GraphQL subscriptions).**

## With More Time

- Structured request-level logging (correlation ID per request, logged
  alongside the acting user and operation name) - the other bonus
  category, and the natural next addition.
- Extend the bulk pattern to `bulkAssignTask`/`bulkUnassignTask` if a real
  client workflow calls for it - same batched-SELECT-then-batched-UPDATE
  shape would apply directly.
- Expand test coverage: `assignTask`/`unassignTask` happy paths, sorting
  by priority/status, more Pydantic validation edge cases.
- Swap the stub header for real token-based auth.
- Reconsider `totalCount` at large scale - cache it or make it opt-in.

## Project Structure

```
app/
├── main.py             # ASGI app, schema wiring, session lifecycle
├── config.py           # Settings (env-driven)
├── database.py         # Async engine/session, declarative Base
├── models.py           # SQLAlchemy models
├── errors.py           # Domain error types
├── sorting.py          # Sort-field → SQL expression mapping
├── cursors.py          # Opaque cursor encode/decode
├── loaders.py          # DataLoaders (N+1 prevention)
├── context.py          # Per-request GraphQL context
├── seed.py             # Demo data script
└── schema/
    ├── types.py        # GraphQL types, inputs, enums
    ├── inputs.py       # Pydantic validation models
    ├── queries.py      # Query type (task, tasks)
    └── mutations.py    # Mutation type
alembic/                # Migrations
tests/
├── conftest.py         # Fixtures (DB, users, project, context)
├── test_mutations.py
└── test_queries.py
```
