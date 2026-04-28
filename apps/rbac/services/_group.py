"""Group creation + user/role membership management."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import casbin
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.transactional import transactional
from apps.core.services.base import SQLAlchemyService
from apps.rbac.exceptions import (
    GroupNotFoundError,
    RBACConflictError,
    RoleNotFoundError,
)
from apps.rbac.models import Group, GroupRole, UserGroup
from apps.rbac.services._helpers import role_sub, user_sub

if TYPE_CHECKING:
    from apps.rbac.repositories import (
        GroupRepository,
        GroupRoleRepository,
        RoleRepository,
        UserGroupRepository,
    )


class GroupService(SQLAlchemyService[Group]):
    """Create groups and manage membership.

    Responsibilities:

    * :meth:`create_group` — CREATE a hierarchical group.
    * :meth:`add_user_to_group` — enroll a user and propagate every active
      group-role grant into Casbin for that user.
    * :meth:`assign_role_to_group` — attach a role to the group and fan it
      out to every active member.

    Both membership operations mirror the relational write into Casbin
    inside the same ``@transactional`` block for atomicity.
    """

    def __init__(
        self,
        *,
        repository: GroupRepository,
        role_repository: RoleRepository,
        user_group_repository: UserGroupRepository,
        group_role_repository: GroupRoleRepository,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        super().__init__(repository=repository)
        self.role_repository = role_repository
        self.user_group_repository = user_group_repository
        self.group_role_repository = group_role_repository
        self.enforcer = enforcer

    @transactional
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
        try:
            group = await self.repository.add(
                session,
                data={
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "parent_id": parent_id,
                    "level": level,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message=f"Group '{name}' already exists.") from exc
        logger.info("GroupService - create_group - Created group {} ({})", group.id, name)
        return group

    @transactional
    async def add_user_to_group(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        group_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserGroup:
        await self._get_or_raise(
            session,
            item_id=group_id,
            error_cls=GroupNotFoundError,
            message=f"Group {group_id} not found.",
        )

        try:
            membership = await self.user_group_repository.add(
                session,
                data={
                    "user_id": user_id,
                    "group_id": group_id,
                    "assigned_by": assigned_by,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message="User already in this group.") from exc

        # Propagate every active role currently attached to the group to this user.
        group_roles = await self.group_role_repository.list_for_group(session, group_id=group_id)
        rules = [[user_sub(user_id), role_sub(gr.role_id)] for gr in group_roles]
        if rules:
            await self.enforcer.add_grouping_policies(rules)
        logger.info("GroupService - add_user_to_group - user={} group={}", user_id, group_id)
        return membership

    @transactional
    async def assign_role_to_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> GroupRole:
        await self._get_or_raise(
            session,
            item_id=group_id,
            error_cls=GroupNotFoundError,
            message=f"Group {group_id} not found.",
        )
        role = await self.role_repository.get_one_by_id(session, item_id=role_id)
        if role is None:
            raise RoleNotFoundError(message=f"Role {role_id} not found.")

        try:
            link = await self.group_role_repository.add(
                session,
                data={
                    "group_id": group_id,
                    "role_id": role_id,
                    "assigned_by": assigned_by,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message="Role already assigned to this group.") from exc

        # Propagate to every current active member of the group.
        member_ids = await self.user_group_repository.list_active_user_ids(session, group_id=group_id)
        rules = [[user_sub(member_id), role_sub(role_id)] for member_id in member_ids]
        if rules:
            await self.enforcer.add_grouping_policies(rules)
        logger.info(
            "GroupService - assign_role_to_group - group={} role={}",
            group_id,
            role_id,
        )
        return link
