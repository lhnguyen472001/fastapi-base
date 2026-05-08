"""Multi-step mutation helpers for :class:`BaseSQLAlchemyRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import delete

from apps.core.database.types import MISSING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.sql import ColumnElement

    from apps.core.database.filters import StatementFilter
    from apps.core.database.repository.base import BaseSQLAlchemyRepository
    from apps.core.database.types import (
        ExecutableOptions,
        SessionType,
        SQLAlchemyModelT,
    )


async def get_and_update(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
    session: SessionType,
    *filters: StatementFilter | ColumnElement[bool],
    match_fields: list[str] | str | None = None,
    attribute_names: Iterable[str] | None = None,
    with_for_update: bool | None = None,
    execution_options: ExecutableOptions | None = None,
    expunge: bool = True,
    uniquify: bool = True,
    **kwargs: Any,
) -> tuple[SQLAlchemyModelT | None, bool]:
    """Fetch a row under SELECT FOR UPDATE and apply per-field updates.

    Returns ``(instance, was_updated)`` — the second flag tracks whether
    any field actually changed value during this call.
    """
    match_filter = repo._build_match_filter(match_fields, kwargs)

    locked_statement = repo.statement.with_for_update()

    existing_instance = await repo.get_one(
        session,
        *filters,
        **match_filter,
        statement=locked_statement,
        execution_options=execution_options,
        uniquify=uniquify,
        expunge=False,
    )

    if not existing_instance:
        return None, False

    updated = False
    for field_name, new_field_value in kwargs.items():
        field = getattr(existing_instance, field_name, MISSING)
        if field is not MISSING and field != new_field_value:
            updated = True
            setattr(existing_instance, field_name, new_field_value)

    if updated:
        existing_instance = await repo._attach_to_session(session, existing_instance, strategy="merge", load=True)
        await session.refresh(
            existing_instance,
            attribute_names=attribute_names,
            with_for_update=with_for_update,
        )

    if expunge:
        session.expunge(existing_instance)

    return existing_instance, updated


async def get_or_upsert(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
    session: SessionType,
    *filters: StatementFilter | ColumnElement[bool],
    match_fields: list[str] | str | None = None,
    attribute_names: Iterable[str] | None = None,
    upsert: bool = False,
    with_for_update: bool | None = None,
    execution_options: ExecutableOptions | None = None,
    expunge: bool = True,
    uniquify: bool = True,
    **kwargs: Any,
) -> tuple[SQLAlchemyModelT, bool]:
    """Find-or-create. Returns ``(instance, was_created)``.

    On Postgres (without ``upsert=True``) this issues a single
    ``INSERT ... ON CONFLICT DO NOTHING`` followed by a confirmation
    ``SELECT``, so two concurrent callers can never both insert. The
    earlier ``SELECT FOR UPDATE`` path was unsafe because predicate
    locking does not gap-lock empty rows on Postgres.

    On other dialects, or when ``upsert=True``, the legacy
    ``SELECT FOR UPDATE → INSERT`` path is used; that path remains
    race-prone outside Postgres but Postgres is the supported production
    driver per :mod:`apps.settings`.
    """
    match_filter = repo._build_match_filter(match_fields, kwargs)
    dialect = repo._get_dialect(session)

    if not upsert and dialect.name == "postgresql" and match_filter:
        return await _pg_find_or_create(
            repo,
            session,
            *filters,
            match_filter=match_filter,
            insert_values=kwargs,
            execution_options=execution_options,
            uniquify=uniquify,
            expunge=expunge,
        )

    locked_statement = repo.statement.with_for_update()

    existing_instance = await repo.get_one(
        session,
        *filters,
        **match_filter,
        statement=locked_statement,
        execution_options=execution_options,
        expunge=False,
    )

    if not existing_instance:
        return await repo.add(session, data=kwargs, expunge=expunge), True

    if upsert:
        for field_name, new_field_value in kwargs.items():
            field = getattr(existing_instance, field_name, MISSING)
            if field is not MISSING and field != new_field_value:
                setattr(existing_instance, field_name, new_field_value)

        existing_instance = await repo._attach_to_session(session, existing_instance, strategy="merge", load=True)
        await session.refresh(
            existing_instance,
            attribute_names=attribute_names,
            with_for_update=with_for_update,
        )

    if expunge:
        session.expunge(existing_instance)

    return existing_instance, False


async def _pg_find_or_create(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
    session: SessionType,
    *filters: StatementFilter | ColumnElement[bool],
    match_filter: dict[str, Any],
    insert_values: dict[str, Any],
    execution_options: ExecutableOptions | None,
    uniquify: bool,
    expunge: bool,
) -> tuple[SQLAlchemyModelT, bool]:
    """Postgres-specific INSERT ... ON CONFLICT DO NOTHING + SELECT.

    The conflict target is ``match_filter.keys()``; the caller is
    responsible for ensuring those columns form a unique constraint or
    primary key (a precondition for any find-or-create operation).
    """
    conflict_columns = list(match_filter.keys())
    insert_stmt = (
        pg_insert(repo.model_type).values(**insert_values).on_conflict_do_nothing(index_elements=conflict_columns)
    )
    result = await session.execute(insert_stmt)
    created = (result.rowcount or 0) > 0

    instance = await repo.get_one(
        session,
        *filters,
        **match_filter,
        execution_options=execution_options,
        uniquify=uniquify,
        expunge=expunge,
    )
    if instance is None:
        msg = (
            "get_or_upsert: INSERT ... ON CONFLICT executed but no row matches "
            f"{match_filter}; check that match_fields targets a unique constraint."
        )
        raise RuntimeError(msg)
    return instance, created


async def delete_where(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
    session: SessionType,
    *filters: StatementFilter | ColumnElement[bool],
    execution_options: ExecutableOptions | None = None,
    expunge: bool = True,
    uniquify: bool = True,
    sanity_check: bool = True,
    **kwargs: Any,
) -> Sequence[SQLAlchemyModelT] | None:
    """Delete matching rows; return the deleted instances when possible.

    On dialects that support ``DELETE ... RETURNING`` we issue a single
    statement; otherwise we list-and-then-delete and sanity-check that
    the affected row count matches what we returned.
    """
    statement = repo._build_query_statement(
        *filters,
        statement=delete(repo.model_type),
        execution_options=execution_options,
        filter_kwargs=kwargs,
    )

    dialect = repo._get_dialect(session)
    if dialect.delete_executemany_returning:
        instances = await session.scalars(statement.returning(repo.model_type))
    else:
        instances = await repo.list_items(
            session,
            *filters,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
        )

        query_result = await repo._execute(session, statement=statement, uniquify=uniquify)
        row_count = getattr(query_result, "rowcount", 0)

        if sanity_check and row_count > 0 and len(instances) != row_count:
            return None

    return cast("Sequence[SQLAlchemyModelT]", instances)


__all__ = ["delete_where", "get_and_update", "get_or_upsert"]
