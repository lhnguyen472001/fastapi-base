"""Per-object ABAC grants (resource:object_id, action, user)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database.model.base import BigIntAuditBase
from apps.rbac.models._helpers import utc_now


class ObjectPermission(BigIntAuditBase):
    """Per-object ABAC grant.

    Allows granting a specific action on a specific instance of a resource to
    a specific user. The instance is identified by ``(resource, object_id)``
    where ``object_id`` is the stringified primary key of the target row.
    """

    __tablename__ = "object_permissions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "resource",
            "object_id",
            "action",
            name="uq_rbac_object_permissions",
        ),
        Index(
            "idx_rbac_object_permissions_user_resource_object",
            "user_id",
            "resource",
            "object_id",
        ),
        Index("idx_rbac_object_permissions_resource_object", "resource", "object_id"),
        Index("idx_rbac_object_permissions_expires", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"ObjectPermission(user_id={self.user_id}, {self.resource}:{self.object_id}, action={self.action})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at
