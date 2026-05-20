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
from apps.blog.services._autosave_service import PostAutosaveService
from apps.blog.services._cache import PostCacheService
from apps.blog.services._content_writer import PostContentWriterService
from apps.blog.services._validation import PostValidationService
from apps.blog.store import AutosaveStore
from apps.core.redis import CacheManager, get_redis_client


class BlogContainer(containers.DeclarativeContainer):
    """Wires blog repositories → services and activates @inject in routes."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "apps.blog.routes.admin",
            "apps.blog.routes.admin._taxonomy",
            "apps.blog.routes.admin._posts",
            "apps.blog.routes.admin._comments",
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

    # Domain cache facade — wraps cache_manager with the per-workspace
    # generation-counter key scheme used by PostService and the autosave
    # service (Phase B.2 — extracted from PostService.__init__).
    post_cache_service = providers.Factory(PostCacheService, cache=cache_manager)

    category_repository = providers.Factory(CategoryRepository)
    tag_repository = providers.Factory(TagRepository)
    post_repository = providers.Factory(PostRepository)
    post_content_repository = providers.Factory(PostContentRepository)
    post_tag_repository = providers.Factory(PostTagRepository)
    post_version_repository = providers.Factory(PostVersionRepository)

    # Workspace-scoped validation guards (slug uniqueness, category /
    # tag existence + count cap). Extracted from PostService in Phase
    # B.3 so the post service no longer takes category_repository or
    # tag_repository directly.
    post_validation_service = providers.Factory(
        PostValidationService,
        category_repository=category_repository,
        tag_repository=tag_repository,
        post_repository=post_repository,
    )

    # Owns every write into post_contents and post_versions (Phase B.4
    # — extracted from PostService.create / .publish / ._apply_content_change
    # and the autosave mixin's flush_one + _write_post_version).
    post_content_writer_service = providers.Factory(
        PostContentWriterService,
        content_repository=post_content_repository,
        post_version_repository=post_version_repository,
    )

    # Standalone autosave flow (Phase B.5 — promoted from the autosave
    # mixin). PostService now injects this as a peer collaborator and
    # surfaces 3 thin facade methods (``autosave`` / ``flush_one`` /
    # ``get_for_admin``) so route call-sites are unchanged.
    post_autosave_service = providers.Factory(
        PostAutosaveService,
        post_repository=post_repository,
        content_writer=post_content_writer_service,
        cache_service=post_cache_service,
        autosave_store=autosave_store,
    )
    # F-MAINT-1: declared as an external dependency so AppContainer wires
    # it from ``UserContainer.user_repository`` — no direct import of
    # ``apps.user.*`` from this module. The runtime payload type is
    # known to AppContainer's composition; mypy cannot infer it without
    # importing the user module here, which the architecture rule forbids.
    user_repository = providers.Dependency()  # type: ignore[var-annotated]

    # Same pattern for the RBAC access service: wired by AppContainer
    # from RBACContainer.access_service so the moderation service can
    # run the post-author OR RBAC dispatch without this module importing
    # apps.rbac directly.
    access_service = providers.Dependency()  # type: ignore[var-annotated]

    category_service = providers.Factory(CategoryService, repository=category_repository)
    tag_service = providers.Factory(TagService, repository=tag_repository)
    post_service = providers.Factory(
        PostService,
        repository=post_repository,
        post_tag_repository=post_tag_repository,
        validation_service=post_validation_service,
        content_writer=post_content_writer_service,
        cache_service=post_cache_service,
        autosave_service=post_autosave_service,
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
        access_service=access_service,
    )
