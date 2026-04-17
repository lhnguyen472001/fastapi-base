---
description: Database and persistence rules for FastAPI Base — SQLAlchemy 2.x async, N+1 prevention, transactions. Apply to ALL database tasks.
---

# Database & Persistence (SQLAlchemy 2.x Async)

## N+1 Prevention — CRITICAL

```python
# FATAL: N+1 query pattern
for item in items:
    related = await session.get(Related, item.related_id)  # N queries!

# Batch query + dict lookup
ids = [item.related_id for item in items]
stmt = select(Related).where(Related.id.in_(ids))
result = await session.execute(stmt)
related_map = {r.id: r for r in result.scalars().all()}  # 1 query
for item in items:
    related = related_map.get(item.related_id)
```

**Rules:**

- Use `.in_()` clause for batch loading related entities
- Use `dict` for O(1) lookup after batch query
- Filter at DB level with `where()`, not in Python after loading all
- Use `selectinload()` or `joinedload()` for relationship eager loading
- Early return for empty lists before querying
- Use `exists()` subquery instead of `JOIN + DISTINCT`

## Relationship Loading Strategies

```python
from sqlalchemy.orm import selectinload, joinedload

# One-to-Many: use selectinload (2 queries, avoids cartesian product)
stmt = select(User).options(selectinload(User.orders))

# Many-to-One / One-to-One: use joinedload (1 query with JOIN)
stmt = select(Order).options(joinedload(Order.user))

# NEVER use lazy loading in async context — it raises errors
```

## Session Management

- Use `session_factory()` async generator as FastAPI dependency
- `RoutingSession` auto-routes reads to READER engine, writes to WRITER engine
- Session is scoped per request via `SQLAlchemySessionMiddleware`
- NEVER create sessions manually — always use the factory

```python
@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
) -> APIResponse[UserResponse]:
    result = await user_service.get_by_id(session, item_id=user_id)
    ...
```

## Transaction Rules

- Use `@Transactional` decorator in Services for write operations
- ALWAYS wrap multi-statement writes in a transaction
- Session auto-rolls back on exception (handled by `session_factory`)
- NEVER manually call `session.commit()` in repository methods — let the service/decorator handle it

```python
from apps.core.database.transactional import Transactional


class UserService(SQLAlchemyService[User]):
    @Transactional()
    async def create_with_profile(self, session, *, user_data, profile_data):
        user = await self.repository.add(session, data=user_data)
        await self.profile_repository.add(session, data={**profile_data, "user_id": user.id})
        return user
```

## Query Building with Filters

- Use `StatementFilter` subclasses for composable query filtering
- NEVER build raw SQL strings — use SQLAlchemy Core/ORM expressions
- Use `text()` only for complex raw SQL that cannot be expressed with ORM

```python
from apps.core.database.filters import (
    SearchFilter,
    LimitOffsetFilter,
    OrderByFilter,
)

filters = [
    SearchFilter(field_name="username", value="john"),
    LimitOffsetFilter(limit=20, offset=0),
    OrderByFilter(field_name="created_at", sort_order="desc"),
]
results, total = await repository.list_and_count(session, statement_filters=filters)
```

## Model Design

- Use `Mapped[type]` annotations for all columns (SQLAlchemy 2.x style)
- Inherit from `UUIDAuditBase` for UUID PK + timestamps (default choice)
- Use `BigIntAuditBase` only when integer PKs are required
- Soft delete via `SoftDeleteMixin` for important data
- `SlugMixin` for URL-friendly identifiers

```python
from sqlalchemy.orm import Mapped, mapped_column
from apps.core.database.model.base import UUIDAuditBase


class User(UUIDAuditBase):
    username: Mapped[str] = mapped_column(unique=True, index=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
```

## Database Design

- Index columns used in `WHERE`, `JOIN`, or `ORDER BY` clauses
- Soft delete (`is_deleted` / `deleted_at`) for important data
- `created_at`, `updated_at` via `HasTimestampMixin` (auto in `*AuditBase`)
- Use Alembic for all schema migrations — naming: `{revision}_{description}.py`
