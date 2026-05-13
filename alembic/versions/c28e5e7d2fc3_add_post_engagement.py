"""add post engagement (likes + comments) tables, triggers, sentinel user

Adds the engagement primitives for specs/003-post-likes-comments:

* ``workspaces.allow_anonymous_comments`` boolean column (default false),
  the per-workspace gate for anonymous comment submissions (FR-010b).
* Sentinel ``users`` row at a fixed UUID — the retarget destination for
  ``post_comments.author_user_id`` rows that survive their authoring
  user being deleted (FR-030).
* ``post_likes`` table — unique per ``(post_id, user_id)``; cascades on
  post / user / workspace delete.
* ``post_comments`` table — two-axis lifecycle (state + soft-delete);
  enforces author-shape XOR via a CHECK constraint; carries the moderator-
  private ``author_email`` / ``author_ip`` columns.
* Two PG trigger functions + four triggers that maintain
  ``posts.like_count`` and ``posts.comment_count`` per the data-model
  §3/§4 transition table.

Revision ID: c28e5e7d2fc3
Revises: 4206aa588d85
Create Date: 2026-05-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import apps.core.database.types
from apps.user.constants import DELETED_USER_SENTINEL_ID

# revision identifiers, used by Alembic.
revision: str = "c28e5e7d2fc3"
down_revision: str | Sequence[str] | None = "4206aa588d85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Counter-trigger SQL (data-model §4)
# ---------------------------------------------------------------------------

POST_LIKES_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_post_likes_count_fn() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        UPDATE posts SET like_count = like_count + 1 WHERE id = NEW.post_id;
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        UPDATE posts SET like_count = GREATEST(like_count - 1, 0) WHERE id = OLD.post_id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END $$ LANGUAGE plpgsql;
"""

POST_COMMENTS_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_post_comments_count_fn() RETURNS trigger AS $$
DECLARE
    old_contributes BOOLEAN := false;
    new_contributes BOOLEAN := false;
    delta INT := 0;
    target_post_id UUID;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_contributes := (OLD.state = 'approved' AND OLD.deleted_at IS NULL);
    END IF;
    IF TG_OP IN ('UPDATE', 'INSERT') THEN
        new_contributes := (NEW.state = 'approved' AND NEW.deleted_at IS NULL);
    END IF;

    delta :=
        (CASE WHEN new_contributes THEN 1 ELSE 0 END)
      - (CASE WHEN old_contributes THEN 1 ELSE 0 END);

    IF delta <> 0 THEN
        target_post_id := COALESCE(NEW.post_id, OLD.post_id);
        UPDATE posts SET comment_count = GREATEST(comment_count + delta, 0)
        WHERE id = target_post_id;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END $$ LANGUAGE plpgsql;
"""

# ---------------------------------------------------------------------------
# Sentinel user row (FR-030 / data-model §6)
# ---------------------------------------------------------------------------

SENTINEL_USER_ID = str(DELETED_USER_SENTINEL_ID)
SENTINEL_USER_EMAIL = "deleted+sentinel@fastapi-base.invalid"
SENTINEL_USER_USERNAME = "__deleted__"
# A non-decodable bcrypt hash placeholder so the row cannot be
# authenticated as. The actual bcrypt format is `$2b$cost$22-char-salt$31-char-hash`;
# leaving a single sentinel char ensures the password check always rejects.
SENTINEL_USER_PASSWORD = "!"


def upgrade() -> None:
    """Upgrade schema for the engagement feature."""

    # 1. Per-workspace flag (FR-010b).
    op.add_column(
        "workspaces",
        sa.Column(
            "allow_anonymous_comments",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. Sentinel user row (FR-030). Idempotent via ON CONFLICT.
    # The user table has no separate display_name column — engagement
    # response builders derive the display label from ``username`` (with
    # a "deleted user" override when the username equals __deleted__).
    op.execute(
        sa.text(
            f"""
            INSERT INTO users (
                id, email, username, hashed_password,
                is_active, is_2fa_enabled, created_at, updated_at
            ) VALUES (
                '{SENTINEL_USER_ID}'::uuid,
                :email, :username, :hashed_password,
                FALSE, FALSE, NOW(), NOW()
            )
            ON CONFLICT (id) DO NOTHING;
            """,  # noqa: S608 — SENTINEL_USER_ID is a module-level constant, never user input.
        ).bindparams(
            email=SENTINEL_USER_EMAIL,
            username=SENTINEL_USER_USERNAME,
            hashed_password=SENTINEL_USER_PASSWORD,
        ),
    )

    # 3. post_likes table.
    op.create_table(
        "post_likes",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_post_likes_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_post_likes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_post_likes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_likes")),
        sa.UniqueConstraint("post_id", "user_id", name="uq_post_likes_post_user"),
    )
    op.create_index(op.f("ix_post_likes_post_id"), "post_likes", ["post_id"], unique=False)
    op.create_index(
        "ix_post_likes_post_id_created_at_desc",
        "post_likes",
        ["post_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index("ix_post_likes_user_id", "post_likes", ["user_id"], unique=False)
    op.create_index("ix_post_likes_workspace_id", "post_likes", ["workspace_id"], unique=False)

    # 4. post_comments table.
    op.create_table(
        "post_comments",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("parent_comment_id", sa.UUID(), nullable=True),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("author_display_name", sa.String(length=80), nullable=True),
        sa.Column("author_email", sa.String(length=254), nullable=True),
        sa.Column("author_ip", postgresql.INET(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("is_tombstoned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("moderation_reason", sa.Text(), nullable=True),
        sa.Column("moderated_by_user_id", sa.UUID(), nullable=True),
        sa.Column("moderated_at", apps.core.database.types.DateTimeUTC(), nullable=True),
        sa.Column("edited_at", apps.core.database.types.DateTimeUTC(), nullable=True),
        sa.Column("deleted_at", apps.core.database.types.DateTimeUTC(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(), nullable=False),
        sa.CheckConstraint(
            "(author_user_id IS NOT NULL) <> (author_display_name IS NOT NULL)",
            name=op.f("ck_post_comments_ck_post_comments_author_xor"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_post_comments_ck_post_comments_state_values"),
        ),
        sa.CheckConstraint(
            "length(trim(body)) > 0",
            name=op.f("ck_post_comments_ck_post_comments_body_nonempty"),
        ),
        sa.CheckConstraint(
            "length(body) <= 4000",
            name=op.f("ck_post_comments_ck_post_comments_body_max"),
        ),
        sa.CheckConstraint(
            "NOT is_tombstoned OR deleted_at IS NOT NULL",
            name=op.f("ck_post_comments_ck_post_comments_tombstone_implies_deleted"),
        ),
        sa.CheckConstraint(
            "parent_comment_id IS NULL OR is_tombstoned = false",
            name=op.f("ck_post_comments_ck_post_comments_parent_no_tombstone"),
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_post_comments_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_post_comments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_comment_id"],
            ["post_comments.id"],
            name=op.f("fk_post_comments_parent_comment_id_post_comments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_post_comments_author_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["moderated_by_user_id"],
            ["users.id"],
            name=op.f("fk_post_comments_moderated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_comments")),
    )
    op.create_index(
        "ix_post_comments_post_top_level_recent",
        "post_comments",
        ["post_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
        postgresql_where="state = 'approved' AND deleted_at IS NULL AND parent_comment_id IS NULL",
    )
    op.create_index(
        "ix_post_comments_parent_replies",
        "post_comments",
        ["parent_comment_id", "created_at"],
        unique=False,
        postgresql_where="state = 'approved' AND deleted_at IS NULL",
    )
    op.create_index(
        "ix_post_comments_workspace_pending",
        "post_comments",
        ["workspace_id", "created_at"],
        unique=False,
        postgresql_where="state = 'pending'",
    )
    op.create_index(
        "ix_post_comments_pending_created_at",
        "post_comments",
        ["created_at"],
        unique=False,
        postgresql_where="state = 'pending'",
    )
    op.create_index(
        "ix_post_comments_post_state",
        "post_comments",
        ["post_id", "state"],
        unique=False,
        postgresql_where="deleted_at IS NULL",
    )
    op.create_index(
        "ix_post_comments_author_user_id",
        "post_comments",
        ["author_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_post_comments_author_email_pending",
        "post_comments",
        ["author_email"],
        unique=False,
        postgresql_where="state = 'pending' AND author_email IS NOT NULL",
    )

    # 5. Counter triggers (data-model §4).
    op.execute(POST_LIKES_TRIGGER_FN)
    op.execute(POST_COMMENTS_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_post_likes_count_ins AFTER INSERT ON post_likes "
        "FOR EACH ROW EXECUTE FUNCTION trg_post_likes_count_fn();",
    )
    op.execute(
        "CREATE TRIGGER trg_post_likes_count_del AFTER DELETE ON post_likes "
        "FOR EACH ROW EXECUTE FUNCTION trg_post_likes_count_fn();",
    )
    op.execute(
        "CREATE TRIGGER trg_post_comments_count_ins AFTER INSERT ON post_comments "
        "FOR EACH ROW EXECUTE FUNCTION trg_post_comments_count_fn();",
    )
    op.execute(
        "CREATE TRIGGER trg_post_comments_count_del AFTER DELETE ON post_comments "
        "FOR EACH ROW EXECUTE FUNCTION trg_post_comments_count_fn();",
    )
    op.execute(
        "CREATE TRIGGER trg_post_comments_count_upd AFTER UPDATE OF state, deleted_at "
        "ON post_comments FOR EACH ROW WHEN ("
        "OLD.state IS DISTINCT FROM NEW.state OR "
        "OLD.deleted_at IS DISTINCT FROM NEW.deleted_at"
        ") EXECUTE FUNCTION trg_post_comments_count_fn();",
    )

    # 6. Seed the Casbin policy for moderation. Idempotent.
    op.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', 'role:workspace_admin', 'blog', 'moderate_comments'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = 'role:workspace_admin'
                  AND v1 = 'blog'
                  AND v2 = 'moderate_comments'
            );
            """,
        ),
    )


def downgrade() -> None:
    """Reverse the upgrade in strict dependency order."""

    # 6. Remove the Casbin policy seed.
    op.execute(
        sa.text(
            """
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:workspace_admin'
              AND v1 = 'blog'
              AND v2 = 'moderate_comments';
            """,
        ),
    )

    # 5. Drop triggers and trigger functions.
    op.execute("DROP TRIGGER IF EXISTS trg_post_comments_count_upd ON post_comments;")
    op.execute("DROP TRIGGER IF EXISTS trg_post_comments_count_del ON post_comments;")
    op.execute("DROP TRIGGER IF EXISTS trg_post_comments_count_ins ON post_comments;")
    op.execute("DROP TRIGGER IF EXISTS trg_post_likes_count_del ON post_likes;")
    op.execute("DROP TRIGGER IF EXISTS trg_post_likes_count_ins ON post_likes;")
    op.execute("DROP FUNCTION IF EXISTS trg_post_comments_count_fn();")
    op.execute("DROP FUNCTION IF EXISTS trg_post_likes_count_fn();")

    # 4. post_comments.
    op.drop_index("ix_post_comments_author_email_pending", table_name="post_comments")
    op.drop_index("ix_post_comments_author_user_id", table_name="post_comments")
    op.drop_index("ix_post_comments_post_state", table_name="post_comments")
    op.drop_index("ix_post_comments_pending_created_at", table_name="post_comments")
    op.drop_index("ix_post_comments_workspace_pending", table_name="post_comments")
    op.drop_index("ix_post_comments_parent_replies", table_name="post_comments")
    op.drop_index("ix_post_comments_post_top_level_recent", table_name="post_comments")
    op.drop_table("post_comments")

    # 3. post_likes.
    op.drop_index("ix_post_likes_workspace_id", table_name="post_likes")
    op.drop_index("ix_post_likes_user_id", table_name="post_likes")
    op.drop_index("ix_post_likes_post_id_created_at_desc", table_name="post_likes")
    op.drop_index(op.f("ix_post_likes_post_id"), table_name="post_likes")
    op.drop_table("post_likes")

    # 2. Sentinel user row.
    op.execute(
        sa.text(f"DELETE FROM users WHERE id = '{SENTINEL_USER_ID}'::uuid;"),  # noqa: S608 — constant, not user input.
    )

    # 1. Workspaces column.
    op.drop_column("workspaces", "allow_anonymous_comments")
