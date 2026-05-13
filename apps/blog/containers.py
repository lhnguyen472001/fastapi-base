"""Dependency-injection container for the Blog module."""

from __future__ import annotations

from dependency_injector import containers, providers

from apps.blog.repositories import (
    CategoryRepository,
    PostCommentModerationRepository,
    PostCommentRepository,
    PostContentRepository,
    PostLikeRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.services import (
    CategoryService,
    PostCommentModerationService,
    PostCommentService,
    PostLikeService,
    PostService,
    PostVersionService,
    TagService,
)
from apps.blog.store import AutosaveStore
from apps.core.redis import CacheManager, get_redis_client


class BlogContainer(containers.DeclarativeContainer):
    """Wires blog repositories → services and activates @inject in routes."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "apps.blog.routes.admin",
            "apps.blog.routes.public",
        ],
    )

    # Cache + autosave infrastructure. The Singleton wrappers cache the
    # CacheManager / AutosaveStore instances; ``providers.Callable``
    # resolves to the lazily-built RedisClient singleton each time.
    cache_manager = providers.Singleton(
        CacheManager,
        redis_client=providers.Callable(get_redis_client),
    )
    autosave_store = providers.Singleton(
        AutosaveStore,
        redis_client=providers.Callable(get_redis_client),
    )

    category_repository = providers.Factory(CategoryRepository)
    tag_repository = providers.Factory(TagRepository)
    post_repository = providers.Factory(PostRepository)
    post_content_repository = providers.Factory(PostContentRepository)
    post_tag_repository = providers.Factory(PostTagRepository)
    post_version_repository = providers.Factory(PostVersionRepository)
    # F-MAINT-1: declared as an external dependency so AppContainer wires
    # it from ``UserContainer.user_repository`` — no direct import of
    # ``apps.user.*`` from this module. The runtime payload type is
    # known to AppContainer's composition; mypy cannot infer it without
    # importing the user module here, which the architecture rule forbids.
    user_repository = providers.Dependency()  # type: ignore[var-annotated]

    category_service = providers.Factory(CategoryService, repository=category_repository)
    tag_service = providers.Factory(TagService, repository=tag_repository)
    post_service = providers.Factory(
        PostService,
        repository=post_repository,
        tag_repository=tag_repository,
        content_repository=post_content_repository,
        post_tag_repository=post_tag_repository,
        category_repository=category_repository,
        post_version_repository=post_version_repository,
        cache=cache_manager,
        autosave_store=autosave_store,
    )
    post_version_service = providers.Factory(
        PostVersionService,
        repository=post_version_repository,
        post_repository=post_repository,
        post_content_repository=post_content_repository,
        user_repository=user_repository,
    )

    # Engagement — likes + comments + moderation. Phase 2 wires empty
    # service skeletons (see apps/blog/services/_likes.py etc.); method
    # bodies land in Phases 3-7 of specs/003-post-likes-comments.
    post_like_repository = providers.Factory(PostLikeRepository)
    post_comment_repository = providers.Factory(PostCommentRepository)
    post_comment_moderation_repository = providers.Factory(PostCommentModerationRepository)

    post_like_service = providers.Factory(
        PostLikeService,
        repository=post_like_repository,
        post_repository=post_repository,
    )
    post_comment_service = providers.Factory(
        PostCommentService,
        repository=post_comment_repository,
        post_repository=post_repository,
    )
    post_comment_moderation_service = providers.Factory(
        PostCommentModerationService,
        repository=post_comment_moderation_repository,
        post_repository=post_repository,
    )
