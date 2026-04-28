"""Dependency injection container for the RBAC module."""

from dependency_injector import containers, providers

from apps.rbac.enforcer import create_enforcer
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
    RBACService,
    RolePermissionService,
)
from apps.settings import app_settings


class RBACContainer(containers.DeclarativeContainer):
    """Wires repositories, enforcer, and services for the RBAC module."""

    wiring_config = containers.WiringConfiguration(modules=["apps.rbac.routes", "apps.rbac.dependencies"])

    # Async resource — must be initialized via ``container.init_resources()``
    # in the FastAPI lifespan handler.
    enforcer = providers.Resource(
        create_enforcer,
        database_uri=app_settings.db.database_uri.render_as_string(hide_password=False),
        watcher_redis_url=app_settings.rbac.watcher_redis_url,
    )

    role_repository = providers.Factory(RoleRepository)
    permission_repository = providers.Factory(PermissionRepository)
    group_repository = providers.Factory(GroupRepository)
    role_permission_repository = providers.Factory(RolePermissionRepository)
    user_role_repository = providers.Factory(UserRoleRepository)
    user_group_repository = providers.Factory(UserGroupRepository)
    group_role_repository = providers.Factory(GroupRoleRepository)
    object_permission_repository = providers.Factory(ObjectPermissionRepository)

    # Focused write services — each is wired with only the repositories it
    # actually depends on (ISP). The legacy ``RBACRepositories`` bundle was
    # removed in Phase 1 #10.
    role_permission_service = providers.Factory(
        RolePermissionService,
        role_repository=role_repository,
        permission_repository=permission_repository,
        role_permission_repository=role_permission_repository,
        user_role_repository=user_role_repository,
        enforcer=enforcer,
    )
    group_service = providers.Factory(
        GroupService,
        group_repository=group_repository,
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
        role_permission_service=role_permission_service,
        group_service=group_service,
        object_permission_service=object_permission_service,
    )

    access_service = providers.Factory(AccessService, enforcer=enforcer)


rbac_container = RBACContainer()
