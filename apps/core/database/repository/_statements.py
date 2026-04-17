"""Pure statement-shape helpers used by :class:`BaseSQLAlchemyRepository`.

Extracted as part of the 3.1 Phase-B split. Every function here is either:

* stateless (takes its inputs and returns a transformed statement), or
* a tiny derived lookup (``get_dialect``, ``get_soft_delete_filter``)

so the helpers can be unit-tested without spinning up a repository or
session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.sql import ColumnElement, func as sql_func, text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.engine import Dialect
    from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

    from apps.core.database.types import ExecutableOptions, StatementTypeT


def build_match_filter(
    match_fields: list[str] | str | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Return the subset of ``kwargs`` used for match-based lookups.

    If ``match_fields`` is ``None``/empty the whole ``kwargs`` dict is
    returned (every kwarg participates in the match). When specified,
    only those fields present in ``kwargs`` with a non-``None`` value
    are kept.
    """
    fields = [match_fields] if isinstance(match_fields, str) else match_fields or []
    if fields:
        return {field_name: kwargs.get(field_name) for field_name in fields if kwargs.get(field_name) is not None}
    return kwargs


def get_soft_delete_filter(model_type: type[Any]) -> ColumnElement[bool] | None:
    """Return ``deleted_at IS NULL`` if the model declares ``deleted_at``.

    Models without the attribute (no soft-delete support) return ``None``
    so callers can cleanly skip adding the filter.
    """
    deleted_at_attr = getattr(model_type, "deleted_at", None)
    if deleted_at_attr is None:
        return None
    return deleted_at_attr.is_(None)


def apply_execution_options(
    statement: StatementTypeT,
    execution_options: ExecutableOptions | None,
) -> StatementTypeT:
    """Attach execution options (e.g. ``populate_existing``) when provided."""
    if not execution_options:
        return statement
    return cast("StatementTypeT", statement.execution_options(**execution_options))


def apply_count_projection(statement: StatementTypeT, *, enable: bool = False) -> StatementTypeT:
    """Rewrite ``statement`` into a ``SELECT COUNT(1)`` form when enabled.

    Strips any ``LIMIT`` / ``OFFSET`` so the count covers the whole result
    set.
    """
    if not enable:
        return statement

    return statement.with_only_columns(sql_func.count(text("1")), maintain_column_froms=True).limit(None).offset(None)


def normalize_filter_kwargs(
    kwargs: dict[Any, Any] | Iterable[tuple[Any, Any]] | None,
) -> dict[Any, Any]:
    """Normalize the ``kwargs`` argument of filter-by helpers to a dict.

    Accepts ``None``, a mapping, or an iterable of ``(key, value)`` tuples.
    """
    if not kwargs:
        return {}
    return dict(kwargs)


def get_dialect(
    session: AsyncSession | async_scoped_session[AsyncSession],
) -> Dialect:
    """Return the dialect of the engine backing ``session``.

    Falls back to ``session.get_bind().dialect`` if the session has no
    directly bound engine (scoped sessions resolve lazily).
    """
    bind = getattr(session, "bind", None)
    if bind is not None:
        return bind.dialect
    return session.get_bind().dialect
