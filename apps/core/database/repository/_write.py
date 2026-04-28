"""Write-side methods of :class:`BaseSQLAlchemyRepository`.

Composed into the public class via multiple inheritance. Like the read
mixin, this mixin assumes its host provides identity attributes and the
private statement/session helpers declared on
:class:`BaseSQLAlchemyRepository`. Methods that need to read first
(``update``, ``delete``, ``get_or_upsert``) call the read-side methods
inherited via the host class.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any, Generic, cast

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import ForUpdateParameter

from apps.core.database.filters import StatementFilter
from apps.core.database.repository import _mutations
from apps.core.database.types import (
    ExecutableOptions,
    SessionType,
    SQLAlchemyModelT,
)


class _WriteRepositoryMixin(Generic[SQLAlchemyModelT]):
    """Write methods extracted from BaseSQLAlchemyRepository."""

    async def add(
        self,
        session: SessionType,
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        expunge: bool = True,
    ) -> SQLAlchemyModelT:
        """Add a model instance to the database."""
        model = self.model_type(**data) if isinstance(data, dict) else data  # type: ignore[attr-defined]
        await self._attach_to_session(session, model, strategy="insert", load=False)  # type: ignore[attr-defined]

        await session.flush()
        if expunge:
            session.expunge(model)

        return model

    async def add_many(
        self,
        session: SessionType,
        data: Sequence[SQLAlchemyModelT | dict[str, Any]],
        *,
        expunge: bool = True,
    ) -> Sequence[SQLAlchemyModelT]:
        """Add multiple model instances to the database."""
        data = [self.model_type(**item) if isinstance(item, dict) else item for item in data]  # type: ignore[attr-defined]
        session.add_all(data)

        if expunge:
            await session.flush()
            for model in data:
                session.expunge(model)

        return cast("Sequence[SQLAlchemyModelT]", data)

    async def update(
        self,
        session: SessionType,
        item_id: str | uuid.UUID | InstrumentedAttribute[Any],
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        attribute_names: Iterable[str] | None = None,
        with_for_update: ForUpdateParameter = None,
        expunge: bool | None = None,
        execution_options: ExecutableOptions | None = None,
    ) -> SQLAlchemyModelT | None:
        """Update a record based on the provided data.

        Returns the updated model instance, or ``None`` if not found.
        """
        update_data = data if isinstance(data, dict) else None

        if isinstance(data, dict):
            data = self.model_type(**data)  # type: ignore[attr-defined]

        existing_instance = await self.get_one_by_id(  # type: ignore[attr-defined]
            session,
            item_id=item_id,
            execution_options=execution_options,
            expunge=False,
        )

        if not existing_instance:
            return None

        if update_data is not None:
            for field_name, new_value in update_data.items():
                if hasattr(existing_instance, field_name):
                    setattr(existing_instance, field_name, new_value)
        else:
            for column in self.model_type.__table__.columns:  # type: ignore[attr-defined]
                field_name = column.name
                if hasattr(data, field_name):
                    setattr(existing_instance, field_name, getattr(data, field_name))

        existing_instance = await self._attach_to_session(  # type: ignore[attr-defined]
            session,
            existing_instance,
            strategy="merge",
            load=True,
        )

        await session.flush()
        if expunge:
            session.expunge(existing_instance)

        return existing_instance

    async def delete(
        self,
        session: SessionType,
        item_id: Any,
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        expunge: bool | None = None,
        execution_options: ExecutableOptions | None = None,
    ) -> SQLAlchemyModelT | None:
        """Delete the row whose ``id_attribute`` equals ``item_id``; return it, or ``None`` if missing."""
        existing_instance = await self.get_one_by_id(  # type: ignore[attr-defined]
            session,
            item_id=item_id,
            id_attribute=id_attribute,
            execution_options=execution_options,
        )

        if not existing_instance:
            return None

        await session.delete(existing_instance)

        if expunge:
            session.expunge(existing_instance)

        return existing_instance

    async def delete_where(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        sanity_check: bool = True,
        **kwargs: Any,
    ) -> Sequence[SQLAlchemyModelT] | None:
        """Delete matching rows; return the deleted instances when possible."""
        return await _mutations.delete_where(
            self,
            session,
            *filters,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            sanity_check=sanity_check,
            **kwargs,
        )

    async def get_and_update(
        self,
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

        Returns ``(instance, was_updated)``.
        """
        return await _mutations.get_and_update(
            self,
            session,
            *filters,
            match_fields=match_fields,
            attribute_names=attribute_names,
            with_for_update=with_for_update,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            **kwargs,
        )

    async def get_or_upsert(
        self,
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
        """Find-or-create. Returns ``(instance, was_created)``."""
        return await _mutations.get_or_upsert(
            self,
            session,
            *filters,
            match_fields=match_fields,
            attribute_names=attribute_names,
            upsert=upsert,
            with_for_update=with_for_update,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            **kwargs,
        )
