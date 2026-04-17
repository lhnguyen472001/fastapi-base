"""Result-handling helpers for :class:`BaseSQLAlchemyRepository`.

Extracted in 3.1 Phase-C. These helpers centralise three patterns that
recur across every read method on the base repository:

* Execute a statement and optionally de-duplicate rows
  (:func:`execute_statement`).
* Collect a single-column result into a list, optionally expunging each
  row (:func:`collect_rows`).
* Collect a two-column window-function result — ``(row, count_over_all)``
  — into a list plus the total count
  (:func:`collect_rows_with_window_count`).

Keeping them as free functions (rather than methods on a class) avoids
passing a repository reference around and makes them trivially unit-
testable with a mocked ``AsyncSession`` / ``Result``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.engine import Result

    from apps.core.database.types import SessionType, StatementTypeT


async def execute_statement(
    session: SessionType,
    statement: StatementTypeT,
    *,
    uniquify: bool = True,
) -> Result[Any]:
    """Execute ``statement`` on ``session`` and optionally uniquify.

    ``uniquify`` de-duplicates rows where eager-loaded joins would
    otherwise produce repeats of the same primary entity.
    """
    result = await session.execute(statement)
    if uniquify:
        result = result.unique()
    return result


def collect_rows(
    result: Result[Any],
    *,
    session: SessionType,
    expunge: bool = True,
) -> list[Any]:
    """Collect single-column rows, optionally expunging each from ``session``.

    Each tuple in ``result`` is expected to contain exactly one entity.
    """
    instances: list[Any] = []
    for (instance,) in result:
        if expunge:
            session.expunge(instance)
        instances.append(instance)
    return instances


def collect_rows_with_window_count(
    result: Result[Any],
    *,
    session: SessionType,
    expunge: bool = True,
) -> tuple[list[Any], int]:
    """Collect ``(entity, window_count)`` rows and return ``(rows, count)``.

    The window count is read from the first row (``COUNT(*) OVER ()``
    is the same on every row by definition) and defaults to ``0`` when
    the result set is empty.
    """
    count_value: int = 0
    instances: list[Any] = []
    for i, (instance, row_count) in enumerate(result):
        if expunge:
            session.expunge(instance)
        instances.append(instance)
        if i == 0:
            count_value = row_count
    return instances, count_value
