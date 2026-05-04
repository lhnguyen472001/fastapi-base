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


class BlogContainer(containers.DeclarativeContainer):
    """Wires blog repositories → services and activates @inject in routes."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "apps.blog.routes.admin",
            "apps.blog.routes.public",
        ],
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
        content_repository=post_content_repository,
        post_tag_repository=post_tag_repository,
        category_repository=category_repository,
        tag_repository=tag_repository,
    )
