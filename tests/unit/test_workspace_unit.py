"""Unit tests for the workspace module — pure logic, no database.

Covers:

* :class:`WorkspaceRole` enum values.
* :meth:`WorkspaceService._validate_slug` — format and reserved-slug rules.
* Pydantic request-schema validation on slug / name length bounds.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from apps.workspace.constants import (
    WORKSPACE_RESERVED_SLUGS,
    WORKSPACE_SLUG_MAX_LENGTH,
    WORKSPACE_SLUG_MIN_LENGTH,
)
from apps.workspace.enums import WorkspaceRole
from apps.workspace.exceptions import (
    WorkspaceSlugInvalidError,
    WorkspaceSlugReservedError,
)
from apps.workspace.schemas import (
    AddMemberRequest,
    CreateWorkspaceRequest,
    UpdateMemberRoleRequest,
)
from apps.workspace.services import WorkspaceService

# ---------------------------------------------------------------------------
# WorkspaceRole enum
# ---------------------------------------------------------------------------


def test_workspace_role_values_are_lowercase_strings() -> None:
    assert WorkspaceRole.OWNER.value == "owner"
    assert WorkspaceRole.EDITOR.value == "editor"
    assert WorkspaceRole.VIEWER.value == "viewer"
    assert WorkspaceRole.COMMENTER.value == "commenter"


def test_workspace_role_membership_matrix_complete() -> None:
    """Sanity guard: changes to the role set must be intentional."""
    assert {role.value for role in WorkspaceRole} == {"owner", "editor", "viewer", "commenter"}


# ---------------------------------------------------------------------------
# WorkspaceService._validate_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "abc",
        "team-1",
        "acme-corp",
        "a1b2c3",
        "x-y-z",
        "0abc",
        "abc0",
    ],
)
def test_validate_slug_accepts_valid_formats(slug: str) -> None:
    """Valid slugs pass without raising."""
    WorkspaceService._validate_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "ab",  # too short — pattern requires >=3 chars
        "-abc",  # leading hyphen
        "abc-",  # trailing hyphen
        "Abc",  # uppercase
        "abc_def",  # underscore not allowed
        "abc def",  # space
        "abc.def",  # dot
        "abc/def",  # slash
        "a" * 81,  # over max length (pattern caps at 80)
    ],
)
def test_validate_slug_rejects_invalid_formats(slug: str) -> None:
    with pytest.raises(WorkspaceSlugInvalidError):
        WorkspaceService._validate_slug(slug)


@pytest.mark.parametrize("slug", sorted(WORKSPACE_RESERVED_SLUGS))
def test_validate_slug_rejects_every_reserved_slug(slug: str) -> None:
    """Every reserved slug must be rejected by the validator."""
    with pytest.raises(WorkspaceSlugReservedError):
        WorkspaceService._validate_slug(slug)


# ---------------------------------------------------------------------------
# Pydantic schema validation
# ---------------------------------------------------------------------------


def test_create_workspace_request_accepts_valid_payload() -> None:
    payload = CreateWorkspaceRequest(slug="acme", name="Acme Corp", description=None)
    assert payload.slug == "acme"
    assert payload.name == "Acme Corp"


def test_create_workspace_request_rejects_short_slug() -> None:
    with pytest.raises(ValidationError):
        CreateWorkspaceRequest(slug="a" * (WORKSPACE_SLUG_MIN_LENGTH - 1), name="x", description=None)


def test_create_workspace_request_rejects_long_slug() -> None:
    with pytest.raises(ValidationError):
        CreateWorkspaceRequest(slug="a" * (WORKSPACE_SLUG_MAX_LENGTH + 1), name="x", description=None)


def test_create_workspace_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        CreateWorkspaceRequest(slug="acme", name="", description=None)


def test_add_member_request_role_must_be_valid_enum_value() -> None:
    """Passing an unknown role string fails Pydantic validation."""
    with pytest.raises(ValidationError):
        AddMemberRequest(user_id=uuid.uuid4(), role="superuser")  # type: ignore[arg-type]


def test_update_member_role_request_accepts_each_role() -> None:
    """Every WorkspaceRole value must round-trip through the schema."""
    for role in WorkspaceRole:
        payload = UpdateMemberRoleRequest(role=role)
        # Schema config sets ``use_enum_values=True`` — value is the str form.
        assert payload.role == role.value
