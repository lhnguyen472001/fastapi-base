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
    RBACPolicySyncError,
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

    Membership operations follow the *commit-then-policy-sync* pattern: the
    relational row commits first, then Casbin grouping policies are bulk-
    inserted. On Casbin failure the relational row is compensated in a
    fresh transaction. See :mod:`apps.rbac.services` module docstring for
    the full rationale.
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

    async def add_user_to_group(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        group_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserGroup:
        membership, rules = await self._db_add_user_to_group(
            session,
            user_id=user_id,
            group_id=group_id,
            assigned_by=assigned_by,
        )

        if rules:
            try:
                await self.enforcer.add_grouping_policies(rules)
            except Exception as sync_exc:
                await self._compensate_user_group_drift(
                    session,
                    membership_id=membership.id,
                    rules=rules,
                    operation="add_user_to_group",
                    sync_exc=sync_exc,
                )

        logger.info("GroupService - add_user_to_group - user={} group={}", user_id, group_id)
        return membership

    async def assign_role_to_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> GroupRole:
        link, rules = await self._db_assign_role_to_group(
            session,
            group_id=group_id,
            role_id=role_id,
            assigned_by=assigned_by,
        )

        if rules:
            try:
                await self.enforcer.add_grouping_policies(rules)
            except Exception as sync_exc:
                await self._compensate_group_role_drift(
                    session,
                    link_id=link.id,
                    rules=rules,
                    operation="assign_role_to_group",
                    sync_exc=sync_exc,
                )

        logger.info(
            "GroupService - assign_role_to_group - group={} role={}",
            group_id,
            role_id,
        )
        return link

    @transactional
    async def _db_add_user_to_group(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        group_id: int,
        assigned_by: uuid.UUID | None,
    ) -> tuple[UserGroup, list[list[str]]]:
        """Commit the membership row; return (membership, casbin_rules_to_apply)."""
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

        group_roles = await self.group_role_repository.list_for_group(session, group_id=group_id)
        rules = [[user_sub(user_id), role_sub(gr.role_id)] for gr in group_roles]
        return membership, rules

    @transactional
    async def _db_assign_role_to_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        role_id: int,
        assigned_by: uuid.UUID | None,
    ) -> tuple[GroupRole, list[list[str]]]:
        """Commit the group-role link; return (link, casbin_rules_to_apply)."""
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

        member_ids = await self.user_group_repository.list_active_user_ids(session, group_id=group_id)
        rules = [[user_sub(member_id), role_sub(role_id)] for member_id in member_ids]
        return link, rules

    async def _compensate_user_group_drift(
        self,
        session: AsyncSession,
        *,
        membership_id: int,
        rules: list[list[str]],
        operation: str,
        sync_exc: BaseException,
    ) -> None:
        """Best-effort compensation for a committed UserGroup whose Casbin sync failed."""
        await self._best_effort_remove_grouping_policies(operation, rules, sync_exc)
        drift = await self._best_effort_delete_user_group(membership_id, operation, session)
        msg = (
            f"DRIFT: UserGroup {membership_id} committed but Casbin sync and compensation both failed: {sync_exc}"
            if drift
            else f"Casbin sync failed (UserGroup {membership_id} compensated): {sync_exc}"
        )
        raise RBACPolicySyncError(message=msg) from sync_exc

    async def _compensate_group_role_drift(
        self,
        session: AsyncSession,
        *,
        link_id: int,
        rules: list[list[str]],
        operation: str,
        sync_exc: BaseException,
    ) -> None:
        """Best-effort compensation for a committed GroupRole whose Casbin sync failed."""
        await self._best_effort_remove_grouping_policies(operation, rules, sync_exc)
        drift = await self._best_effort_delete_group_role(link_id, operation, session)
        msg = (
            f"DRIFT: GroupRole {link_id} committed but Casbin sync and compensation both failed: {sync_exc}"
            if drift
            else f"Casbin sync failed (GroupRole {link_id} compensated): {sync_exc}"
        )
        raise RBACPolicySyncError(message=msg) from sync_exc

    async def _best_effort_remove_grouping_policies(
        self,
        operation: str,
        rules: list[list[str]],
        sync_exc: BaseException,
    ) -> None:
        """Try to remove every rule that might have been partially written.

        ``remove_grouping_policy`` is idempotent — it returns ``False`` for
        rules that do not exist, so calling it for every rule is safe.
        """
        logger.error(
            "GroupService - {} - Casbin sync failed; rolling back partial grouping policies: {!r}",
            operation,
            sync_exc,
        )
        for rule in rules:
            try:
                await self.enforcer.remove_grouping_policy(*rule)
            except Exception as cleanup_exc:
                logger.error(
                    "GroupService - {} - DRIFT: failed to remove partial grouping policy {}: {!r}",
                    operation,
                    rule,
                    cleanup_exc,
                )

    async def _best_effort_delete_user_group(
        self,
        membership_id: int,
        operation: str,
        session: AsyncSession,
    ) -> bool:
        """Return ``True`` when compensation failed (drift), ``False`` otherwise."""
        try:
            await self._delete_user_group(session, membership_id=membership_id)
        except Exception as comp_exc:
            logger.error(
                "GroupService - {} - DRIFT: compensation failed UserGroup={}: {!r}",
                operation,
                membership_id,
                comp_exc,
            )
            return True
        return False

    async def _best_effort_delete_group_role(
        self,
        link_id: int,
        operation: str,
        session: AsyncSession,
    ) -> bool:
        """Return ``True`` when compensation failed (drift), ``False`` otherwise."""
        try:
            await self._delete_group_role(session, link_id=link_id)
        except Exception as comp_exc:
            logger.error(
                "GroupService - {} - DRIFT: compensation failed GroupRole={}: {!r}",
                operation,
                link_id,
                comp_exc,
            )
            return True
        return False

    @transactional
    async def _delete_user_group(self, session: AsyncSession, *, membership_id: int) -> None:
        await self.user_group_repository.delete(session, item_id=membership_id)

    @transactional
    async def _delete_group_role(self, session: AsyncSession, *, link_id: int) -> None:
        await self.group_role_repository.delete(session, item_id=link_id)
