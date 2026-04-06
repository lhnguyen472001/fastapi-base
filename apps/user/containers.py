from dependency_injector import containers, providers

from apps.user.repositories import UserRepository
from apps.user.services import UserService


class UserContainer(containers.DeclarativeContainer):
    """Dependency injection container for the User module."""

    user_repository = providers.Factory(UserRepository)
    user_service = providers.Factory(UserService, repository=user_repository)
