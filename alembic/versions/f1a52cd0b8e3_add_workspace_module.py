"""add workspace module

Revision ID: f1a52cd0b8e3
Revises: e7a91c204f31
Create Date: 2026-04-29 17:30:00.000000

Adds the multi-tenancy primitive (Workspace + WorkspaceMember) consumed by
the upcoming blog feature. Slugs are globally unique; per-workspace
membership rows carry the role enum (``owner`` / ``editor`` / ``viewer`` /
``commenter``) — see :mod:`apps.workspace.enums`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import apps.core.database.types  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "f1a52cd0b8e3"
down_revision: Union[str, Sequence[str], None] = "e7a91c204f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create workspaces and workspace_members tables."""
    op.create_table(
        "workspaces",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("deleted_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=True)
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"], unique=False)
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"], unique=False)

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("invited_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_members_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspace_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_members_invited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_members")),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_members_workspace_user",
        ),
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_members_user_id",
        "workspace_members",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_members_workspace_role",
        "workspace_members",
        ["workspace_id", "role"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema — drop workspace_members and workspaces tables."""
    op.drop_index("ix_workspace_members_workspace_role", table_name="workspace_members")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_index(op.f("ix_workspace_members_workspace_id"), table_name="workspace_members")
    op.drop_table("workspace_members")

    op.drop_index("ix_workspaces_deleted_at", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")
    op.drop_table("workspaces")
