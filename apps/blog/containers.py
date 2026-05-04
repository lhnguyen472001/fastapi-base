"""Dependency-injection container for the Blog module."""

from __future__ import annotations

from dependency_injector import containers, providers

from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    TagRepository,
)
from apps.blog.services import CategoryService, PostService, TagService
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

    category_service = providers.Factory(CategoryService, repository=category_repository)
    tag_service = providers.Factory(TagService, repository=tag_repository)
    post_service = providers.Factory(
        PostService,
        repository=post_repository,
        tag_repository=tag_repository,
        content_repository=post_content_repository,
        post_tag_repository=post_tag_repository,
        category_repository=category_repository,
        cache=cache_manager,
        autosave_store=autosave_store,
    )
