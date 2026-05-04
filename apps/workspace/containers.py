"""Dependency-injection container for the Workspace module."""

from __future__ import annotations

from dependency_injector import containers, providers

from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.services import WorkspaceMemberService, WorkspaceService


class WorkspaceContainer(containers.DeclarativeContainer):
    """Wires workspace repositories → services and activates @inject in routes/dependencies."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "apps.workspace.routes",
            "apps.workspace.dependencies",
        ],
    )

    workspace_repository = providers.Factory(WorkspaceRepository)
    workspace_member_repository = providers.Factory(WorkspaceMemberRepository)

    workspace_service = providers.Factory(
        WorkspaceService,
        repository=workspace_repository,
        member_repository=workspace_member_repository,
    )
    workspace_member_service = providers.Factory(
        WorkspaceMemberService,
        repository=workspace_member_repository,
        workspace_repository=workspace_repository,
    )
