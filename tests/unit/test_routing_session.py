"""Unit tests for ``RoutingSession`` (read/write engine routing)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.sql import delete, insert, select, update

from apps.core.database.engine import SQLAlchemyEngineTypes
from apps.core.database.session import RoutingSession

# Standalone table for DML clauses — not registered against any model
# registry, so it cannot collide with project models.
_TEST_TABLE = Table(
    "_routing_test_table",
    MetaData(),
    Column("id", Integer, primary_key=True),
)


def _stub_engines() -> tuple[MagicMock, MagicMock]:
    reader = MagicMock(name="reader_engine")
    reader.sync_engine = MagicMock(name="reader_sync")
    writer = MagicMock(name="writer_engine")
    writer.sync_engine = MagicMock(name="writer_sync")
    return reader, writer


def _routing_session() -> RoutingSession:
    """Build a ``RoutingSession`` without binding to a real engine.

    The class only needs an instance to call ``get_bind`` on; we avoid
    invoking ``Session.__init__`` because that would require a real bind.
    """
    session = RoutingSession.__new__(RoutingSession)
    session._wrote = False  # what __init__ would set
    return session


def _patched_factory(reader: Any, writer: Any) -> Any:
    def picker(engine_type: SQLAlchemyEngineTypes) -> Any:
        return reader if engine_type == SQLAlchemyEngineTypes.READER else writer

    return patch("apps.core.database.session.engine_factory", side_effect=picker)


def test_select_routes_to_reader_before_any_write() -> None:
    reader, writer = _stub_engines()
    session = _routing_session()

    with _patched_factory(reader, writer):
        bind = session.get_bind(clause=select(1))

    assert bind is reader.sync_engine
    assert session._wrote is False


def test_insert_routes_to_writer_and_sticks() -> None:
    reader, writer = _stub_engines()
    session = _routing_session()
    with _patched_factory(reader, writer):
        write_bind = session.get_bind(clause=insert(_TEST_TABLE))
        # Subsequent SELECT in the same session should also hit writer.
        post_write_select = session.get_bind(clause=select(1))

    assert write_bind is writer.sync_engine
    assert post_write_select is writer.sync_engine
    assert session._wrote is True


def test_update_and_delete_route_to_writer() -> None:
    reader, writer = _stub_engines()
    with _patched_factory(reader, writer):
        s1 = _routing_session()
        assert s1.get_bind(clause=update(_TEST_TABLE)) is writer.sync_engine
        s2 = _routing_session()
        assert s2.get_bind(clause=delete(_TEST_TABLE)) is writer.sync_engine


def test_select_for_update_routes_to_writer() -> None:
    reader, writer = _stub_engines()
    session = _routing_session()

    with _patched_factory(reader, writer):
        bind = session.get_bind(clause=select(1).with_for_update())

    assert bind is writer.sync_engine
    assert session._wrote is True


def test_pre_write_reads_keep_routing_to_reader() -> None:
    """Multiple SELECTs before any write must all hit the reader.

    Regression: the previous implementation used ``in_transaction()`` plus
    ``_flushing`` and silently routed the second-and-later SELECTs to the
    writer because ``Session.execute`` autobegins a transaction.
    """
    reader, writer = _stub_engines()
    session = _routing_session()

    with _patched_factory(reader, writer):
        first = session.get_bind(clause=select(1))
        second = session.get_bind(clause=select(2))
        third = session.get_bind(clause=select(3))

    assert first is reader.sync_engine
    assert second is reader.sync_engine
    assert third is reader.sync_engine
    assert session._wrote is False
