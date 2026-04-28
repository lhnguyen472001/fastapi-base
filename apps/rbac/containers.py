"""Dependency injection container for the RBAC module."""

from dependency_injector import containers, providers

from apps.rbac.enforcer import enforcer_factory
from apps.rbac.repositories import (
    GroupRepository,
    GroupRoleRepository,
    ObjectPermissionRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserGroupRepository,
    UserRoleRepository,
)
from apps.rbac.services import (
    AccessService,
    GroupService,
    ObjectPermissionService,
    PermissionService,
    RBACService,
    RoleService,
)


class RBACContainer(containers.DeclarativeContainer):
    """Wires repositories, enforcer, and services for the RBAC module."""

    wiring_config = containers.WiringConfiguration(modules=["apps.rbac.routes", "apps.rbac.dependencies"])

    # Async resource — must be initialized via ``container.init_resources()``
    # in the FastAPI lifespan handler.
    enforcer = providers.Resource(enforcer_factory)

    role_repository = providers.Factory(RoleRepository)
    permission_repository = providers.Factory(PermissionRepository)
    group_repository = providers.Factory(GroupRepository)
    role_permission_repository = providers.Factory(RolePermissionRepository)
    user_role_repository = providers.Factory(UserRoleRepository)
    user_group_repository = providers.Factory(UserGroupRepository)
    group_role_repository = providers.Factory(GroupRoleRepository)
    object_permission_repository = providers.Factory(ObjectPermissionRepository)

    # Focused write services — each is wired with only the repositories it
    # actually depends on (ISP).
    role_service = providers.Factory(
        RoleService,
        repository=role_repository,
        user_role_repository=user_role_repository,
        enforcer=enforcer,
    )
    permission_service = providers.Factory(
        PermissionService,
        repository=permission_repository,
        role_repository=role_repository,
        role_permission_repository=role_permission_repository,
        enforcer=enforcer,
    )
    group_service = providers.Factory(
        GroupService,
        repository=group_repository,
        role_repository=role_repository,
        user_group_repository=user_group_repository,
        group_role_repository=group_role_repository,
        enforcer=enforcer,
    )
    object_permission_service = providers.Factory(
        ObjectPermissionService,
        repository=object_permission_repository,
        enforcer=enforcer,
    )

    # Facade consumed by routes / tests expecting the pre-split public surface.
    rbac_service = providers.Factory(
        RBACService,
        role_service=role_service,
        permission_service=permission_service,
        group_service=group_service,
        object_permission_service=object_permission_service,
    )

    # AccessService is stateless aside from the shared enforcer Resource —
    # promote to Singleton so every authenticated request reuses one instance
    # instead of paying per-request construction.
    access_service = providers.Singleton(AccessService, enforcer=enforcer)
