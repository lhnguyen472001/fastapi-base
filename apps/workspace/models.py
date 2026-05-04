"""Workspace module ORM models: Workspace and WorkspaceMember.

Tenancy primitive: every blog row gains a ``workspace_id`` FK back to
:class:`Workspace`, and authorization on those rows is gated by the
caller's :class:`WorkspaceMember` row (and its :class:`WorkspaceRole`).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.schema import ForeignKey, Index, UniqueConstraint
from sqlalchemy.sql.sqltypes import String, Text

from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.model.mixins import HasSoftDeletedMixin
from apps.workspace.constants import (
    WORKSPACE_NAME_MAX_LENGTH,
    WORKSPACE_SLUG_MAX_LENGTH,
)
from apps.workspace.enums import WorkspaceRole

if TYPE_CHECKING:
    from apps.user.models import User


class Workspace(UUIDAuditBase, HasSoftDeletedMixin):
    """Workspace — the multi-tenancy unit. Auto-pluralized table: ``workspaces``."""

    __table_args__ = (
        Index("ix_workspaces_owner_user_id", "owner_user_id"),
        Index("ix_workspaces_deleted_at", "deleted_at"),
    )

    slug: Mapped[str] = mapped_column(
        String(WORKSPACE_SLUG_MAX_LENGTH),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(WORKSPACE_NAME_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bootstrap-owner pointer. The actual permission grant lives in
    # :class:`WorkspaceMember`; this column just records *which user* spawned
    # the workspace, kept around even if their membership row later changes.
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    members: Mapped[list[WorkspaceMember]] = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class WorkspaceMember(UUIDAuditBase):
    """Workspace ↔ User membership row carrying the per-workspace role.

    Auto-pluralized table: ``workspace_members``. The composite uniqueness
    on ``(workspace_id, user_id)`` is the integrity contract: a user has at
    most one role per workspace.
    """

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_user_id", "user_id"),
        Index("ix_workspace_members_workspace_role", "workspace_id", "role"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkspaceRole.VIEWER.value)

    # Audit trail: who added this member, optional for system / bootstrap rows.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace",
        back_populates="members",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        lazy="raise",
        foreign_keys=[user_id],
    )
