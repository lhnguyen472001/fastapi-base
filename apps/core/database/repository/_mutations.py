"""Multi-step mutation helpers for :class:`BaseSQLAlchemyRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

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

    Locks via SELECT FOR UPDATE before checking existence so concurrent
    callers cannot both insert.
    """
    match_filter = repo._build_match_filter(match_fields, kwargs)

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
