"""add blog module

Revision ID: c2bf7e91d4a0
Revises: f1a52cd0b8e3
Create Date: 2026-04-29 18:00:00.000000

Creates the workspace-scoped blog domain: categories, tags, posts (hot
metadata), post_contents (cold Tiptap body, 1:1), and the post_tags
many-to-many join. Adds a tsvector trigger over title + excerpt +
content_text for FTS.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import apps.core.database.types  # noqa: F401

revision: str = "c2bf7e91d4a0"
down_revision: Union[str, Sequence[str], None] = "f1a52cd0b8e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create blog tables, indexes, and FTS trigger."""

    # -----------------------------------------------------------------
    # categories
    # -----------------------------------------------------------------
    op.create_table(
        "categories",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("deleted_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_categories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_categories_workspace_slug"),
    )
    op.create_index("ix_categories_workspace_id", "categories", ["workspace_id"], unique=False)
    op.create_index("ix_categories_deleted_at", "categories", ["deleted_at"], unique=False)

    # -----------------------------------------------------------------
    # tags
    # -----------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=90), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tags_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_tags_workspace_slug"),
    )
    op.create_index("ix_tags_workspace_id", "tags", ["workspace_id"], unique=False)

    # -----------------------------------------------------------------
    # posts
    # -----------------------------------------------------------------
    op.create_table(
        "posts",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=280), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("cover_image_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=True),
        sa.Column("reading_minutes", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("hero_quote", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta_title", sa.String(length=200), nullable=True),
        sa.Column("meta_description", sa.String(length=320), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embed_content_hash", sa.String(length=64), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("deleted_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_posts_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_posts_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_posts_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_posts_published_implies_published_at",
        ),
        sa.CheckConstraint(
            "view_count >= 0 AND like_count >= 0 AND comment_count >= 0",
            name="ck_posts_counters_non_negative",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_posts_workspace_slug"),
    )
    op.create_index("ix_posts_workspace_id", "posts", ["workspace_id"], unique=False)
    op.create_index("ix_posts_author_id", "posts", ["author_id"], unique=False)
    op.create_index("ix_posts_category_id", "posts", ["category_id"], unique=False)
    op.create_index(
        "ix_posts_workspace_status_published_at",
        "posts",
        ["workspace_id", "status", "published_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_posts_search_vector",
        "posts",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    # -----------------------------------------------------------------
    # post_contents (1:1 with posts)
    # -----------------------------------------------------------------
    op.create_table(
        "post_contents",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column(
            "content_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'{"type":"doc","content":[]}'::jsonb"""),
        ),
        sa.Column("content_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_post_contents_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_contents")),
        sa.UniqueConstraint("post_id", name="uq_post_contents_post_id"),
    )

    # -----------------------------------------------------------------
    # post_tags (M2M)
    # -----------------------------------------------------------------
    op.create_table(
        "post_tags",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", apps.core.database.types.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_post_tags_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name=op.f("fk_post_tags_tag_id_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_tags")),
        sa.UniqueConstraint("post_id", "tag_id", name="uq_post_tags_post_tag"),
    )
    op.create_index("ix_post_tags_post_id", "post_tags", ["post_id"], unique=False)
    op.create_index("ix_post_tags_tag_id", "post_tags", ["tag_id"], unique=False)

    # -----------------------------------------------------------------
    # FTS trigger — keeps posts.search_vector in sync with title +
    # excerpt (on posts updates) and content_text (on post_contents updates).
    # ``simple`` config — language-agnostic; pluggable later if needed.
    # -----------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION posts_refresh_search_vector(p_post_id UUID) RETURNS void AS $$
        BEGIN
          UPDATE posts SET search_vector =
              setweight(to_tsvector('simple', coalesce(posts.title, '')),    'A')
            || setweight(to_tsvector('simple', coalesce(posts.excerpt, '')), 'B')
            || setweight(
                  to_tsvector('simple',
                    coalesce((SELECT pc.content_text FROM post_contents pc WHERE pc.post_id = posts.id), '')
                  ),
                  'C')
          WHERE posts.id = p_post_id;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION posts_search_vector_trigger() RETURNS trigger AS $$
        BEGIN
          PERFORM posts_refresh_search_vector(NEW.id);
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_posts_search_vector
        AFTER INSERT OR UPDATE OF title, excerpt ON posts
        FOR EACH ROW EXECUTE FUNCTION posts_search_vector_trigger();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION post_contents_search_vector_trigger() RETURNS trigger AS $$
        BEGIN
          PERFORM posts_refresh_search_vector(NEW.post_id);
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_post_contents_search_vector
        AFTER INSERT OR UPDATE OF content_text ON post_contents
        FOR EACH ROW EXECUTE FUNCTION post_contents_search_vector_trigger();
        """
    )


def downgrade() -> None:
    """Downgrade schema — drop trigger functions, indexes, and tables."""
    op.execute("DROP TRIGGER IF EXISTS trg_post_contents_search_vector ON post_contents;")
    op.execute("DROP FUNCTION IF EXISTS post_contents_search_vector_trigger();")
    op.execute("DROP TRIGGER IF EXISTS trg_posts_search_vector ON posts;")
    op.execute("DROP FUNCTION IF EXISTS posts_search_vector_trigger();")
    op.execute("DROP FUNCTION IF EXISTS posts_refresh_search_vector(UUID);")

    op.drop_index("ix_post_tags_tag_id", table_name="post_tags")
    op.drop_index("ix_post_tags_post_id", table_name="post_tags")
    op.drop_table("post_tags")

    op.drop_table("post_contents")

    op.drop_index("ix_posts_search_vector", table_name="posts", postgresql_using="gin")
    op.drop_index(
        "ix_posts_workspace_status_published_at",
        table_name="posts",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_posts_category_id", table_name="posts")
    op.drop_index("ix_posts_author_id", table_name="posts")
    op.drop_index("ix_posts_workspace_id", table_name="posts")
    op.drop_table("posts")

    op.drop_index("ix_tags_workspace_id", table_name="tags")
    op.drop_table("tags")

    op.drop_index("ix_categories_deleted_at", table_name="categories")
    op.drop_index("ix_categories_workspace_id", table_name="categories")
    op.drop_table("categories")
