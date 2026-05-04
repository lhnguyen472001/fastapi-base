"""Workspace module services — business logic and orchestration.

Two services live here:

* :class:`WorkspaceService` — workspace CRUD plus slug validation and the
  bootstrap-owner contract (the caller is auto-added with role ``owner``
  in the same transaction as the workspace insert).
* :class:`WorkspaceMemberService` — membership lifecycle: add, change-role,
  remove. Enforces the "every workspace must keep at least one owner"
  invariant.
"""

from __future__ import annotations

import datetime
import uuid

from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.services.base import BaseSQLAlchemyService
from apps.workspace.constants import (
    WORKSPACE_MAX_MEMBERS,
    WORKSPACE_RESERVED_SLUGS,
    WORKSPACE_SLUG_PATTERN,
)
from apps.workspace.enums import WorkspaceRole
from apps.workspace.exceptions import (
    WorkspaceLastOwnerError,
    WorkspaceMemberAlreadyExistsError,
    WorkspaceMemberLimitExceededError,
    WorkspaceMemberNotFoundError,
    WorkspaceNotFoundError,
    WorkspaceSlugConflictError,
    WorkspaceSlugInvalidError,
    WorkspaceSlugReservedError,
)
from apps.workspace.models import Workspace, WorkspaceMember
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import (
    AddMemberRequest,
    CreateWorkspaceRequest,
    ListMembersRequest,
    ListWorkspacesRequest,
    UpdateMemberRoleRequest,
    UpdateWorkspaceRequest,
)

# ---------------------------------------------------------------------------
# WorkspaceService
# ---------------------------------------------------------------------------


class WorkspaceService(BaseSQLAlchemyService[Workspace]):
    """Business logic for workspaces."""

    repository: WorkspaceRepository

    def __init__(
        self,
        repository: WorkspaceRepository,
        member_repository: WorkspaceMemberRepository,
    ) -> None:
        super().__init__(repository)
        self.member_repository = member_repository

    @transactional
    async def create(
        self,
        session: SessionType,
        *,
        owner_user_id: uuid.UUID,
        data: CreateWorkspaceRequest,
    ) -> Workspace:
        """Create a workspace and seat the caller as its bootstrap owner."""
        slug = data.slug.lower().strip()
        self._validate_slug(slug)
        await self._ensure_slug_available(session, slug=slug)

        workspace = Workspace(
            slug=slug,
            name=data.name,
            description=data.description,
            owner_user_id=owner_user_id,
        )
        workspace = await self.repository.add(session, workspace, expunge=False)

        bootstrap_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner_user_id,
            role=WorkspaceRole.OWNER.value,
            invited_by_user_id=None,
        )
        await self.member_repository.add(session, bootstrap_membership, expunge=False)
        return workspace

    async def find_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
    ) -> Workspace:
        """Fetch a workspace by ID or raise :class:`WorkspaceNotFoundError`."""
        workspace = await self.repository.find_by_id(session, workspace_id=workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(message=f"Workspace with id '{workspace_id}' not found.")
        return workspace

    async def get_by_slug(
        self,
        session: SessionType,
        *,
        slug: str,
    ) -> Workspace:
        """Fetch a non-deleted workspace by slug or raise :class:`WorkspaceNotFoundError`."""
        workspace = await self.repository.find_by_slug(session, slug=slug)
        if workspace is None:
            raise WorkspaceNotFoundError(message=f"Workspace with slug '{slug}' not found.")
        return workspace

    async def list_for_user(
        self,
        session: SessionType,
        *,
        user_id: uuid.UUID,
        params: ListWorkspacesRequest,
    ) -> tuple[list[Workspace], int]:
        """List the workspaces the user belongs to, paginated."""
        return await self.member_repository.list_for_user(
            session,
            user_id=user_id,
            role=params.role,
            limit=params.limit,
            offset=params.offset,
        )

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        data: UpdateWorkspaceRequest,
    ) -> Workspace:
        """Partially update a workspace."""
        await self.find_or_raise(session, workspace_id=workspace_id)

        payload = data.model_dump(exclude_unset=True)
        updated = await self.repository.update(session, item_id=workspace_id, data=payload)
        if updated is None:
            raise WorkspaceNotFoundError(message=f"Workspace with id '{workspace_id}' not found.")
        return updated

    @transactional
    async def soft_delete(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
    ) -> Workspace:
        """Soft-delete a workspace."""
        await self.find_or_raise(session, workspace_id=workspace_id)
        deleted = await self.repository.update(
            session,
            item_id=workspace_id,
            data={"deleted_at": datetime.datetime.now(datetime.UTC)},
        )
        if deleted is None:
            raise WorkspaceNotFoundError(message=f"Workspace with id '{workspace_id}' not found.")
        return deleted

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_slug(slug: str) -> None:
        """Validate slug format and reject reserved values."""
        if WORKSPACE_SLUG_PATTERN.fullmatch(slug) is None:
            raise WorkspaceSlugInvalidError(
                message=(
                    "Workspace slug must be lowercase alphanumeric with hyphens, "
                    "starting and ending with an alphanumeric character."
                ),
            )
        if slug in WORKSPACE_RESERVED_SLUGS:
            raise WorkspaceSlugReservedError(message=f"Workspace slug '{slug}' is reserved.")

    async def _ensure_slug_available(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self.repository.find_by_slug(session, slug=slug, exclude_id=exclude_id)
        if existing is not None:
            raise WorkspaceSlugConflictError(message=f"Workspace with slug '{slug}' already exists.")


# ---------------------------------------------------------------------------
# WorkspaceMemberService
# ---------------------------------------------------------------------------


class WorkspaceMemberService(BaseSQLAlchemyService[WorkspaceMember]):
    """Business logic for workspace memberships."""

    repository: WorkspaceMemberRepository

    def __init__(
        self,
        repository: WorkspaceMemberRepository,
        workspace_repository: WorkspaceRepository,
    ) -> None:
        super().__init__(repository)
        self.workspace_repository = workspace_repository

    async def list_members(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        params: ListMembersRequest,
    ) -> tuple[list[WorkspaceMember], int]:
        """List members of a workspace with pagination."""
        await self._ensure_workspace_exists(session, workspace_id=workspace_id)
        return await self.repository.list_members(
            session,
            workspace_id=workspace_id,
            role=params.role,
            limit=params.limit,
            offset=params.offset,
        )

    @transactional
    async def add_member(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        invited_by_user_id: uuid.UUID,
        data: AddMemberRequest,
    ) -> WorkspaceMember:
        """Add a member to a workspace."""
        await self._ensure_workspace_exists(session, workspace_id=workspace_id)

        existing = await self.repository.find_membership(
            session,
            workspace_id=workspace_id,
            user_id=data.user_id,
        )
        if existing is not None:
            raise WorkspaceMemberAlreadyExistsError(
                message=f"User '{data.user_id}' is already a member of workspace '{workspace_id}'.",
            )

        current_count = await self.repository.count_members(session, workspace_id=workspace_id)
        if current_count >= WORKSPACE_MAX_MEMBERS:
            raise WorkspaceMemberLimitExceededError(
                message=f"Workspace already has the maximum of {WORKSPACE_MAX_MEMBERS} members.",
            )

        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=data.user_id,
            role=data.role,
            invited_by_user_id=invited_by_user_id,
        )
        return await self.repository.add(session, member, expunge=False)

    @transactional
    async def change_role(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        data: UpdateMemberRoleRequest,
    ) -> WorkspaceMember:
        """Change a member's role; refuses to demote the last owner."""
        member = await self._find_membership_or_raise(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )

        new_role = data.role
        if member.role == new_role:
            return member

        if member.role == WorkspaceRole.OWNER.value and new_role != WorkspaceRole.OWNER.value:
            owner_count = await self.repository.count_owners(session, workspace_id=workspace_id)
            if owner_count <= 1:
                raise WorkspaceLastOwnerError(
                    message="Cannot demote the last owner of the workspace.",
                )

        updated = await self.repository.update(session, item_id=member.id, data={"role": new_role})
        if updated is None:
            raise WorkspaceMemberNotFoundError(
                message=f"User '{user_id}' is not a member of workspace '{workspace_id}'.",
            )
        return updated

    @transactional
    async def remove_member(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkspaceMember:
        """Hard-delete a membership row; refuses to remove the last owner."""
        member = await self._find_membership_or_raise(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )

        if member.role == WorkspaceRole.OWNER.value:
            owner_count = await self.repository.count_owners(session, workspace_id=workspace_id)
            if owner_count <= 1:
                raise WorkspaceLastOwnerError(
                    message="Cannot remove the last owner of the workspace.",
                )

        deleted = await self.repository.delete(session, item_id=member.id)
        if deleted is None:
            raise WorkspaceMemberNotFoundError(
                message=f"User '{user_id}' is not a member of workspace '{workspace_id}'.",
            )
        return deleted

    async def find_membership(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkspaceMember | None:
        """Look up a membership row, returning None when absent."""
        return await self.repository.find_membership(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _ensure_workspace_exists(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
    ) -> None:
        workspace = await self.workspace_repository.find_by_id(session, workspace_id=workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(message=f"Workspace with id '{workspace_id}' not found.")

    async def _find_membership_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkspaceMember:
        member = await self.repository.find_membership(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if member is None:
            raise WorkspaceMemberNotFoundError(
                message=f"User '{user_id}' is not a member of workspace '{workspace_id}'.",
            )
        return member
