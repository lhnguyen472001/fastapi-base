"""Core RBAC entities: Role, Permission, Group.

Relationship targets (RolePermission, UserRole, UserGroup, GroupRole) are
referenced by string so this module can be imported before the
``_assignments`` module is loaded — SQLAlchemy resolves string targets at
mapper-configuration time against the declarative registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from apps.core.database.model.base import BigIntAuditBase
from apps.core.database.model import HasSoftDeletedMixin

if TYPE_CHECKING:
    from apps.rbac.models._assignments import (
        GroupRole,
        RolePermission,
        UserGroup,
        UserRole,
    )


class Role(BigIntAuditBase):
    """Hierarchical role assignable to users and groups."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_rbac_roles_name"),
        Index("idx_rbac_roles_active_level", "is_active", "level"),
        Index("idx_rbac_roles_parent_active", "parent_id", "is_active"),
        Index("idx_rbac_roles_system_active", "is_system", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    level: Mapped[int] = mapped_column(nullable=False, default=0)

    meta: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    permissions: Mapped[list[RolePermission]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="select",
    )

    children: Mapped[list[Role]] = relationship(
        "Role",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="select",
        foreign_keys="[Role.parent_id]",
    )

    parent: Mapped[Role | None] = relationship(
        "Role",
        back_populates="children",
        lazy="select",
        remote_side="[Role.id]",
    )

    users: Mapped[list[UserRole]] = relationship(
        "UserRole",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f'Role(id={self.id}, name="{self.name}", level={self.level})'

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        if not value:
            raise ValueError("Role name cannot be empty")
        if len(value) > 100:
            raise ValueError("Role name cannot exceed 100 characters")
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Role name must be alphanumeric (underscores and hyphens allowed)")
        return value.lower().strip()

    @validates("display_name")
    def validate_display_name(self, _key: str, value: str) -> str:
        if not value:
            raise ValueError("Role display name cannot be empty")
        if len(value) > 200:
            raise ValueError("Role display name cannot exceed 200 characters")
        return value.strip()

    @validates("level")
    def validate_level(self, _key: str, value: int) -> int:
        if value < 0:
            raise ValueError("Role level must be non-negative")
        if value > 10:
            raise ValueError("Role level cannot exceed 10 (max hierarchy depth)")
        return value

    def has_permission(self, resource: str, action: str) -> bool:
        """Check membership against the role's loaded permissions.

        Wildcards: ``("*", "*")``, ``(resource, "*")`` are honored.
        Requires the ``permissions`` relationship to be loaded.
        """
        return any(
            (p.permission.resource == resource and p.permission.action == action)
            or (p.permission.resource == "*" and p.permission.action == "*")
            or (p.permission.resource == resource and p.permission.action == "*")
            for p in self.permissions
            if p.is_active and p.permission.is_active
        )

    def get_all_permissions(self) -> list[Permission]:
        return [rp.permission for rp in self.permissions if rp.is_active and rp.permission.is_active]


class Permission(BigIntAuditBase, HasSoftDeletedMixin):
    """A (resource, action) capability assignable to roles."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("name", name="uq_rbac_permissions_name"),
        Index("idx_rbac_permissions_resource_action", "resource", "action"),
        Index("idx_rbac_permissions_category_active", "category", "is_active"),
        Index("idx_rbac_permissions_deleted", "deleted_at"),
        Index("idx_rbac_permissions_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    conditions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    roles: Mapped[list[RolePermission]] = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f'Permission(id={self.id}, name="{self.name}", resource="{self.resource}", action="{self.action}")'


class Group(BigIntAuditBase):
    """Hierarchical group of users."""

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("name", name="uq_rbac_groups_name"),
        Index("idx_rbac_groups_active_level", "is_active", "level"),
        Index("idx_rbac_groups_parent_active", "parent_id", "is_active"),
        Index("idx_rbac_groups_system_active", "is_system", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    level: Mapped[int] = mapped_column(nullable=False, default=0)

    meta: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    users: Mapped[list[UserGroup]] = relationship(
        "UserGroup",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="select",
    )

    roles: Mapped[list[GroupRole]] = relationship(
        "GroupRole",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="select",
    )

    children: Mapped[list[Group]] = relationship(
        "Group",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="select",
        foreign_keys="[Group.parent_id]",
    )

    parent: Mapped[Group | None] = relationship(
        "Group",
        back_populates="children",
        lazy="select",
        remote_side="[Group.id]",
    )

    def __repr__(self) -> str:
        return f'Group(id={self.id}, name="{self.name}", level={self.level})'
