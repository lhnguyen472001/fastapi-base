"""Association tables with assignment metadata.

These link users/groups/roles with extra columns (``granted_by``,
``expires_at``, ``conditions``, ``is_active``) so each assignment carries
its own audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database.model.base import BigIntAuditBase
from apps.rbac.models._helpers import utc_now

if TYPE_CHECKING:
    from apps.rbac.models._core import Group, Permission, Role


class RolePermission(BigIntAuditBase):
    """Role↔Permission with assignment metadata."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_rbac_role_permissions"),
        Index("idx_rbac_role_permissions_permission", "permission_id"),
        Index("idx_rbac_role_permissions_role_active", "role_id", "is_active"),
        Index("idx_rbac_role_permissions_active_expires", "is_active", "expires_at"),
        Index("idx_rbac_role_permissions_expires", "expires_at"),
    )

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)

    conditions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    role: Mapped[Role] = relationship("Role", back_populates="permissions", lazy="raise")
    permission: Mapped[Permission] = relationship("Permission", back_populates="roles", lazy="raise")

    def __repr__(self) -> str:
        return f"RolePermission(role_id={self.role_id}, permission_id={self.permission_id})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at


class UserRole(BigIntAuditBase):
    """User↔Role assignment."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_rbac_user_roles"),
        Index("idx_rbac_user_roles_role", "role_id"),
        Index("idx_rbac_user_roles_user_active", "user_id", "is_active"),
        Index("idx_rbac_user_roles_active_expires", "is_active", "expires_at"),
        Index("idx_rbac_user_roles_expires", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    role: Mapped[Role] = relationship("Role", back_populates="users", lazy="raise")

    def __repr__(self) -> str:
        return f"UserRole(user_id={self.user_id}, role_id={self.role_id})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at


class UserGroup(BigIntAuditBase):
    """User↔Group membership."""

    __tablename__ = "user_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_rbac_user_groups"),
        Index("idx_rbac_user_groups_group", "group_id"),
        Index("idx_rbac_user_groups_user_active", "user_id", "is_active"),
        Index("idx_rbac_user_groups_active_expires", "is_active", "expires_at"),
        Index("idx_rbac_user_groups_expires", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    group: Mapped[Group] = relationship("Group", back_populates="users", lazy="raise")

    def __repr__(self) -> str:
        return f"UserGroup(user_id={self.user_id}, group_id={self.group_id})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at


class GroupRole(BigIntAuditBase):
    """Group↔Role assignment for bulk role propagation."""

    __tablename__ = "group_roles"
    __table_args__ = (
        UniqueConstraint("group_id", "role_id", name="uq_rbac_group_roles"),
        Index("idx_rbac_group_roles_role", "role_id"),
        Index("idx_rbac_group_roles_group_active", "group_id", "is_active"),
        Index("idx_rbac_group_roles_active_expires", "is_active", "expires_at"),
        Index("idx_rbac_group_roles_expires", "expires_at"),
    )

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    group: Mapped[Group] = relationship("Group", back_populates="roles", lazy="raise")
    role: Mapped[Role] = relationship("Role", lazy="raise")

    def __repr__(self) -> str:
        return f"GroupRole(group_id={self.group_id}, role_id={self.role_id})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at
