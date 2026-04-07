"""Dependency injection container for the User module."""

from dependency_injector import containers, providers

from apps.user.repositories import UserRepository
from apps.user.services import UserService


class UserContainer(containers.DeclarativeContainer):
    """Wires UserRepository -> UserService and activates @inject in routes."""

    wiring_config = containers.WiringConfiguration(modules=["apps.user.routes"])

    user_repository = providers.Factory(UserRepository)
    user_service = providers.Factory(UserService, repository=user_repository)


# Module-level instance so the wiring runs on import.
user_container = UserContainer()
