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
from sqlalchemy.sql import ColumnElement, update
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
        """Add a model instance to the database.

        Always flushes so server-defaulted columns (``id``, ``created_at``)
        are populated before the call returns. The audit's H2 suggestion
        to skip the flush when ``expunge=False`` is unsafe in this
        codebase: many service flows do ``repo.add(parent)`` then
        ``repo.add(child(parent.id))`` and expect the parent's
        server-generated ``id`` to be available immediately. Removing the
        flush would require refactoring every such call site to use ORM
        relationships (which trigger SA unit-of-work dependency-ordered
        inserts) before the optimisation is safe.
        """
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
        """Update a record by id.

        ``data`` may be a partial-update ``dict`` (fast-path: a single
        ``UPDATE ... RETURNING`` round-trip) or a full model instance
        (slow path: load → mutate → merge for full-replace semantics).
        Returns the updated model, or ``None`` when the row does not exist
        (or is soft-deleted).

        ``attribute_names`` and ``with_for_update`` are honoured only on
        the slow path; on the fast path they are ignored because the
        single statement obviates the second SELECT they used to drive.
        """
        if isinstance(data, dict):
            return await self._fast_update_by_id(
                session,
                item_id=item_id,
                update_dict=data,
                execution_options=execution_options,
                expunge=expunge,
            )

        update_dict = self._coerce_update_payload(data)

        existing_instance = await self.get_one_by_id(  # type: ignore[attr-defined]
            session,
            item_id=item_id,
            execution_options=execution_options,
            expunge=False,
        )
        if not existing_instance:
            return None

        for field_name, new_value in update_dict.items():
            setattr(existing_instance, field_name, new_value)

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

    async def _fast_update_by_id(
        self,
        session: SessionType,
        *,
        item_id: Any,
        update_dict: dict[str, Any],
        execution_options: ExecutableOptions | None,
        expunge: bool | None,
    ) -> SQLAlchemyModelT | None:
        """Single-statement ``UPDATE ... RETURNING`` for dict-shaped updates.

        Replaces the legacy load-mutate-merge path (2-3 round-trips) with
        one round-trip. Soft-deleted rows are excluded via the same
        ``HasSoftDeletedMixin`` filter that ``get_one_by_id`` honours, so
        callers see identical "row not found" behaviour for tombstoned
        rows.
        """
        id_attribute = self.id_attribute  # type: ignore[attr-defined]
        if isinstance(id_attribute, InstrumentedAttribute):
            id_col = id_attribute
        else:
            id_col = getattr(self.model_type, id_attribute)  # type: ignore[attr-defined]

        statement = (
            update(self.model_type)  # type: ignore[attr-defined]
            .where(id_col == item_id)
            .values(**update_dict)
            .returning(self.model_type)  # type: ignore[attr-defined]
        )

        soft_delete_filter = self._get_soft_delete_filter()  # type: ignore[attr-defined]
        if soft_delete_filter is not None:
            statement = statement.where(soft_delete_filter)

        if execution_options:
            statement = statement.execution_options(**execution_options)

        result = await session.scalars(statement, execution_options={"synchronize_session": "fetch"})
        instance = result.one_or_none()
        if instance is None:
            return None

        if expunge:
            session.expunge(instance)

        return instance

    def _coerce_update_payload(
        self,
        data: SQLAlchemyModelT | dict[str, Any],
    ) -> dict[str, Any]:
        """Normalise ``update`` input to a plain ``{column: value}`` dict.

        Dict input is returned untouched (partial-update semantics). Model-
        instance input is projected to a full ``{column: value}`` dict
        across every mapped column on the model — preserving the historical
        full-replace behaviour without the redundant
        ``self.model_type(**data)`` round-trip.
        """
        if isinstance(data, dict):
            return data
        return {
            column.name: getattr(data, column.name)
            for column in self.model_type.__table__.columns  # type: ignore[attr-defined]
            if hasattr(data, column.name)
        }

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
