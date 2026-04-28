"""Group creation + user/role membership management."""

import uuid

import casbin
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.transactional import transactional
from apps.rbac.exceptions import (
    GroupNotFoundError,
    RBACConflictError,
    RoleNotFoundError,
)
from apps.rbac.models import Group, GroupRole, UserGroup
from apps.rbac.services._helpers import role_sub, user_sub
from apps.rbac.services._repositories import RBACRepositories


class GroupService:
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
        repositories: RBACRepositories,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        self.group_repository = repositories.group
        self.role_repository = repositories.role
        self.user_group_repository = repositories.user_group
        self.group_role_repository = repositories.group_role
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
            group = await self.group_repository.add(
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
        group = await self.group_repository.get_one_by_id(session, item_id=group_id)
        if group is None:
            raise GroupNotFoundError(message=f"Group {group_id} not found.")

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
        group = await self.group_repository.get_one_by_id(session, item_id=group_id)
        if group is None:
            raise GroupNotFoundError(message=f"Group {group_id} not found.")
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
