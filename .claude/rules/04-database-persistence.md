# Database & Persistence (SQLAlchemy 2.x Async)

## N+1 Prevention — CRITICAL

```python
# FATAL: N+1 query
for item in items:
    user = await session.get(User, item.user_id)  # N queries!

# Batch query + dict lookup
user_ids = list({item.user_id for item in items})
stmt = select(User).where(User.id.in_(user_ids))
result = await session.execute(stmt)
user_map = {u.id: u for u in result.scalars().all()}  # 1 query
users = [user_map[item.user_id] for item in items]
```

**Rules:**
- Use `.in_()` for batch loading — NEVER loop queries
- Use `dict` comprehension for O(1) lookup
- Filter at DB level with `.where()` — NOT Python list comprehensions after loading all
- Use `select(func.count()).select_from(...)` instead of loading all then `len()`
- Use `selectin` or `joinedload` for relationship eager loading to prevent N+1
- Early return for empty collections before querying

## Relationship Loading

```python
# selectin for one-to-many (preferred for async)
class User(UUIDAuditBase):
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", lazy="selectin"
    )

# joinedload for many-to-one
stmt = select(Order).options(joinedload(Order.user))
```

## Concurrency — Locking

```python
# Default: Optimistic via version column (custom mixin if needed)

# Pessimistic: SELECT FOR UPDATE for financial/critical ops
stmt = select(User).where(User.id == user_id).with_for_update()
result = await session.execute(stmt)
user = result.scalar_one_or_none()

# Repository support
statement = self.statement.with_for_update()  # BaseSQLAlchemyRepository
```

## Database Design

- Index columns used in `WHERE`, `JOIN`, or `ORDER BY`
- Soft delete via `HasSoftDeletedMixin` (`deleted_at` column) for important data
- Audit fields via `UUIDAuditBase` / `BigIntAuditBase` (`created_at`, `updated_at`)
- Use `mapped_column()` with explicit `nullable`, `index`, `unique` — NEVER rely on defaults

## Transaction Rules

- Session lifecycle managed by `session_factory()` FastAPI dependency
- `session.flush()` to persist within transaction; `session.commit()` handled by middleware
- For multi-step operations: session auto-rollback on exception via `session_factory()` context
- NEVER call `session.commit()` inside service/repository — let middleware handle it

```python
# session_factory handles commit/rollback lifecycle
async def session_factory() -> AsyncGenerator[AsyncSession, None]:
    session = scoped_session()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
```

## Read/Write Splitting

- `RoutingSession` auto-routes: writes → writer engine, reads → reader engine
- INSERT/UPDATE/DELETE and flushes route to writer
- Pure SELECT routes to reader
- No manual engine selection needed

## Query Patterns

```python
# Use SQLAlchemy 2.x select() style — NEVER legacy Query API
stmt = select(User).where(User.email == email)
result = await session.execute(stmt)
user = result.scalar_one_or_none()

# Use repository filter helpers
stmt = self.filter_select_by_kwargs(self.statement, {"id": user_id})
stmt = self.apply_filter(stmt, User.deleted_at.is_(None))

# Pagination via filters
stmt = self.apply_filter(stmt, LimitOffsetPaginationFilter(limit=20, offset=0))

# NEVER string concatenation in queries
# NEVER raw SQL unless absolutely necessary (and document why)
```
