"""Throwaway models used by integration tests against a real Postgres."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database.model import HasSoftDeletedMixin
from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.repository.base import BaseSQLAlchemyRepository


class Widget(UUIDAuditBase):
    """Plain UUID-keyed model with timestamps."""

    __tablename__ = "_test_widgets"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    is_featured: Mapped[bool] = mapped_column(default=False, nullable=False)


class SoftWidget(UUIDAuditBase, HasSoftDeletedMixin):
    """Same as Widget but with soft-delete mixin."""

    __tablename__ = "_test_soft_widgets"

    name: Mapped[str] = mapped_column(String(100), nullable=False)


class WidgetRepository(BaseSQLAlchemyRepository[Widget]):
    model_type = Widget


class SoftWidgetRepository(BaseSQLAlchemyRepository[SoftWidget]):
    model_type = SoftWidget
