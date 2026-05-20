"""RBACService facade — composes the three focused write services."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac.models import (
    Group,
    GroupRole,
    ObjectPermission,
    Permission,
    Role,
    RolePermission,
    UserGroup,
    UserRole,
)
from apps.rbac.services._group import GroupService
from apps.rbac.services._object_permission import ObjectPermissionService
from apps.rbac.services._permission import PermissionService
from apps.rbac.services._role import RoleService


class RBACService:
    """Write-side facade that delegates to the focused sub-services.

    The facade exists so existing routes and tests that depend on a single
    ``RBACService`` keep working after the 3.3 / 3.4 splits. New code
    should prefer injecting the relevant sub-service directly
    (:class:`RoleService`, :class:`PermissionService`,
    :class:`GroupService`, :class:`ObjectPermissionService`).
    """

    def __init__(
        self,
        *,
        role_service: RoleService,
        permission_service: PermissionService,
        group_service: GroupService,
        object_permission_service: ObjectPermissionService,
    ) -> None:
        self.role_service = role_service
        self.permission_service = permission_service
        self.group_service = group_service
        self.object_permission_service = object_permission_service

    # ----- Roles (RoleService) ---------------------------------------------

    async def create_role(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        description: str | None = None,
        parent_id: int | None = None,
        level: int = 0,
    ) -> Role:
        """Create a new role.

        Delegates to :meth:`RoleService.create_role`. Raises
        :class:`RBACConflictError` on duplicate ``name``.

        Args:
            session: Active async session.
            name: Unique machine name (e.g. ``editor``).
            display_name: Human-facing label.
            description: Optional long-form description.
            parent_id: Optional parent role id for hierarchical roles.
            level: Hierarchy depth (0 = root).

        Returns:
            The persisted :class:`Role` row.
        """
        return await self.role_service.create_role(
            session,
            name=name,
            display_name=display_name,
            description=description,
            parent_id=parent_id,
            level=level,
        )

    async def assign_role_to_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserRole:
        """Grant ``role_id`` to ``user_id`` and sync the Casbin grouping policy.

        Delegates to :meth:`RoleService.assign_role_to_user`. Follows the
        commit-then-policy-sync pattern: on Casbin failure the relational
        row is compensated in a fresh transaction.

        Args:
            session: Active async session.
            user_id: Target user.
            role_id: Role to grant.
            assigned_by: Optional auditing field (the actor performing the grant).

        Returns:
            The persisted :class:`UserRole` row.
        """
        return await self.role_service.assign_role_to_user(
            session, user_id=user_id, role_id=role_id, assigned_by=assigned_by
        )

    # ----- Permissions (PermissionService) ----------------------------------

    async def create_permission(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        resource: str,
        action: str,
        description: str | None = None,
        category: str | None = None,
    ) -> Permission:
        """Register a permission (``resource``, ``action``) the policy engine can grant.

        Delegates to :meth:`PermissionService.create_permission`.

        Args:
            session: Active async session.
            name: Unique permission key (e.g. ``blog:edit_post``).
            display_name: Human-facing label.
            resource: Resource token (e.g. ``blog``).
            action: Action token (e.g. ``edit_post``).
            description: Optional long-form description.
            category: Optional grouping label for UIs.

        Returns:
            The persisted :class:`Permission` row.
        """
        return await self.permission_service.create_permission(
            session,
            name=name,
            display_name=display_name,
            resource=resource,
            action=action,
            description=description,
            category=category,
        )

    async def grant_permission_to_role(
        self,
        session: AsyncSession,
        *,
        role_id: int,
        permission_id: int,
        granted_by: uuid.UUID | None = None,
    ) -> RolePermission:
        """Attach a permission to a role and write the matching Casbin policy.

        Delegates to :meth:`PermissionService.grant_permission_to_role`.

        Args:
            session: Active async session.
            role_id: Target role.
            permission_id: Permission to grant.
            granted_by: Optional auditing field (the actor performing the grant).

        Returns:
            The persisted :class:`RolePermission` join row.
        """
        return await self.permission_service.grant_permission_to_role(
            session, role_id=role_id, permission_id=permission_id, granted_by=granted_by
        )

    # ----- Groups (GroupService) -------------------------------------------

    async def create_group(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        description: str | None = None,
        parent_id: int | None = None,
        level: int = 0,
    ) -> Group:
        """Create a (hierarchical) group used to fan role grants across users.

        Delegates to :meth:`GroupService.create_group`. Raises
        :class:`RBACConflictError` on duplicate ``name``.

        Args:
            session: Active async session.
            name: Unique machine name.
            display_name: Human-facing label.
            description: Optional long-form description.
            parent_id: Optional parent group id.
            level: Hierarchy depth (0 = root).

        Returns:
            The persisted :class:`Group` row.
        """
        return await self.group_service.create_group(
            session,
            name=name,
            display_name=display_name,
            description=description,
            parent_id=parent_id,
            level=level,
        )

    async def add_user_to_group(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        group_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserGroup:
        """Enroll a user in a group and fan every active group role into Casbin for them.

        Delegates to :meth:`GroupService.add_user_to_group`. On Casbin
        failure the membership row is compensated in a fresh transaction.

        Args:
            session: Active async session.
            user_id: Target user.
            group_id: Target group.
            assigned_by: Optional auditing field (the actor enrolling the user).

        Returns:
            The persisted :class:`UserGroup` membership row.
        """
        return await self.group_service.add_user_to_group(
            session, user_id=user_id, group_id=group_id, assigned_by=assigned_by
        )

    async def assign_role_to_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> GroupRole:
        """Attach a role to a group and fan it out to every active member.

        Delegates to :meth:`GroupService.assign_role_to_group`. Pages
        membership in batches of
        :data:`RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE` so very large groups
        don't allocate the full id list at once.

        Args:
            session: Active async session.
            group_id: Target group.
            role_id: Role to attach.
            assigned_by: Optional auditing field (the actor performing the grant).

        Returns:
            The persisted :class:`GroupRole` link row.
        """
        return await self.group_service.assign_role_to_group(
            session, group_id=group_id, role_id=role_id, assigned_by=assigned_by
        )

    # ----- Object-level grants (ObjectPermissionService) -------------------

    async def grant_object_permission(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
        granted_by: uuid.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> ObjectPermission:
        """Grant a per-instance permission (e.g. "user X can edit post Y").

        Delegates to :meth:`ObjectPermissionService.grant`. Object-level
        grants bypass the role/permission hierarchy and live in the
        ``object_permissions`` table; the access service checks them
        before falling through to the general Casbin path.

        Args:
            session: Active async session.
            user_id: Target user.
            resource: Resource token (e.g. ``blog.post``).
            object_id: Concrete instance id (string form).
            action: Action token (e.g. ``edit``).
            granted_by: Optional auditing field.
            expires_at: Optional grant TTL.

        Returns:
            The persisted :class:`ObjectPermission` row.
        """
        return await self.object_permission_service.grant(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
            granted_by=granted_by,
            expires_at=expires_at,
        )

    async def revoke_object_permission(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
    ) -> bool:
        """Revoke a previously-granted per-instance permission.

        Delegates to :meth:`ObjectPermissionService.revoke`. Idempotent —
        returns ``False`` if no matching grant exists.

        Args:
            session: Active async session.
            user_id: Target user.
            resource: Resource token.
            object_id: Concrete instance id (string form).
            action: Action token.

        Returns:
            ``True`` if a row was deleted, ``False`` otherwise.
        """
        return await self.object_permission_service.revoke(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
